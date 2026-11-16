"""OBS bucket discovery and provisioning via the KooCLI embedded obsutil (hcloud OBS)."""
import os
import re
import uuid
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.service.plans import PlanStore, fingerprint

REGION_TOKEN=re.compile(r'[a-z]{2,4}-[a-z]+-\d+')
BLOCK_PUBLIC_FLAG=('-public-access-block-configuration=BlockPublicAcls=true,'
                   'IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true')
PROBE_NOTE='公共状态仅对前 10 个桶检测；Public 桶有匿名公开风险，尽量不用（优先私有桶）'


class ObsService:
    """OBS bucket discovery and provisioning via the KooCLI embedded obsutil (hcloud OBS):
    the storage_component target for a Supabase application - a private standard-storage
    bucket, multi-AZ by default, public access blocked."""

    def __init__(self,koocli=None,plans=None,ledger=None):
        self.koocli=koocli or KoocliClient()
        self.plans=plans or PlanStore()
        self.ledger=ledger   # None disables resource-ledger recording (tests / embedded use)

    def intent_digest(self,method,path,body):
        """Fingerprint a bucket intent against this KooCLI credential, mirroring Network."""
        return fingerprint({'endpoint':'hcloud:'+self.koocli.region,'credential':self.koocli.token,
                            'method':method,'path':path,'body':body})

    def credential_mode(self):
        """Classify the ambient AK/SK: temporary credentials cannot back storage_component."""
        temporary=bool(getattr(self.koocli,'_security_token',''))
        if temporary:
            detail='当前环境为临时凭证（含 SecurityToken），不能作为应用的持久存储凭据'
            notice=('请用户提供长期 AK/SK（经本地请求文件写入 storage_component，或更新环境变量）后再对接，'
                    '否则凭证过期后应用将无法访问 OBS；可先做一次读测试确认现有凭证的 OBS 权限')
        else:
            detail='环境凭证为长期 AK/SK，可直接复用'
            notice=None
        return {'temporary':temporary,'detail':detail,'notice':notice}

    def bucket_name_for(self,app_name):
        """Derive a DNS-safe bucket name: lowercase, [a-z0-9-] only, supabase- prefix, 3-63 chars."""
        slug=re.sub(r'[^a-z0-9-]+','-',str(app_name).lower())
        slug=re.sub(r'-{2,}','-',slug).strip('-')
        name=('supabase-'+slug)[:56].rstrip('-')
        if len(name)<3:name+='-obs'
        return name

    def new_bucket_spec(self,bucket_name,redundancy='multi_az'):
        """Describe the fixed bucket baseline: private, standard storage, public access blocked."""
        return {'bucket_name':bucket_name,
                'storage_class':'标准存储（standard，固定）',
                'bucket_type':'私有（private，固定）',
                'redundancy':'多AZ存储（multi-az，默认）' if redundancy=='multi_az' else '单AZ存储（single_az）',
                'block_public_access':'开启（默认开启，固定不可修改）',
                'region':self.koocli.region+'（与环境当前项目保持一致，自动推导）',
                'enterprise_project':'default（默认企业项目）',
                'storage_component_hint':{'bucket':bucket_name,'ak_sk':'经本地请求文件提供'}}

    async def list_buckets(self):
        """List buckets via obsutil ls and probe public status for the first ten."""
        try:
            text=await self.koocli.obs('ls')
        except McpToolError as exc:
            error=str(exc.message)[:120]
            return {'data':[],'read_test':{'passed':False,'detail':error},'note':PROBE_NOTE,'error':error}
        buckets=[]
        for line in text.splitlines():
            line=line.strip()
            # Real bucket rows (verified live): "obs://name  CreationDate  Location  BucketType".
            if not line.startswith('obs://'):continue
            tokens=line.split()
            name=tokens[0][len('obs://'):]
            if not name or '/' in name:continue  # object rows carry a key path - not a bucket row
            location=None
            for token in tokens[1:]:
                if REGION_TOKEN.fullmatch(token):
                    location=token
                    break
            buckets.append({'name':name,'location':location})
        if not buckets:
            return {'data':[],'read_test':{'passed':True,'detail':'ls 成功，无桶'}}
        data=[]
        for index,bucket in enumerate(buckets):
            status=await self._public_status(bucket['name'],bucket['location']) if index<10 else '未知'
            data.append({'name':bucket['name'],'location':bucket['location'],'public_status':status,
                         'risk_note':'Public 桶有匿名公开风险，尽量不用' if status=='Public' else None})
        # Private buckets first (security): reuse candidates surface private storage
        # before anything anonymously readable; original order kept within groups.
        order={bucket['name']:index for index,bucket in enumerate(buckets)}
        data.sort(key=lambda row:(row['public_status']=='Public',order.get(row['name'],0)))
        return {'data':data,'read_test':{'passed':True,'detail':'ls 成功，读取到 '+str(len(buckets))+' 个桶（私有桶优先排序）'},
                'note':PROBE_NOTE}

    async def _public_status(self,name,location=None):
        """Probe one bucket's public-status text and classify it Private/Public/未知."""
        try:
            text=await self.koocli.obs('get-bucket-public-status',args=['obs://'+name],region=location)
        except McpToolError:
            return '未知'
        lowered=text.lower()
        if 'ot public' in lowered or 'private' in lowered or '非公共' in lowered:
            return 'Private'
        if 'public' in lowered or '公共' in lowered:
            return 'Public'
        return '未知'

    async def discover_storage(self,app_name=None):
        """Compose the storage decision surface: credential mode, reuse inventory, new-bucket spec."""
        listing=await self.list_buckets()
        name=self.bucket_name_for(app_name or 'supabase-app')
        return {'mode':'storage_options',
                'credential':self.credential_mode(),
                'reuse':{'option':'复用已有桶',
                         'note':'私有桶优先；公共桶提示风险尽量不用；无可复用桶则转新建',
                         'buckets':listing['data'],'read_test':listing['read_test']},
                'new_bucket':{'option':'新建桶（推荐、默认）',
                              'note':'全新私有桶，完全隔离，安全可靠',
                              'spec':self.new_bucket_spec(name,'multi_az')},
                'storage_component_note':('storage_component={enabled:true, bucket:<桶名>, AK/SK 经本地请求文件} '
                                          '随 create_supabase_with_new_instance / create_supabase_link_exist_instance 一次提交（启用存储时创建工具自动确保桶存在并回填最终桶名）。'
                                          '强烈建议业务确认需要文件存储就在创建时当场启用，避免遗漏与流程拉长；'
                                          '创建时未启用的，事后可经 update_supabase_storage 补开对接（首次须全量凭据：桶名+AK+SK），凭据轮换同经该工具')}

    async def ensure_bucket_now(self,bucket_name,redundancy='multi_az'):
        """Idempotent provisioning for the orchestrated creation flow: keep a bucket that
        already exists, otherwise create it per the fixed rules; returns the final bucket
        name (short-uuid suffix on global-name collision) so the request can be backfilled."""
        if not isinstance(bucket_name,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,62}',bucket_name):
            raise McpToolError('MCP_INVALID_ARGS','bucket_name 必须是 3-63 位小写字母/数字/中划线，且以字母或数字开头')
        if redundancy not in ('multi_az','single_az'):
            raise McpToolError('MCP_INVALID_ARGS','redundancy must be multi_az or single_az')
        try:
            await self.koocli.obs('stat',args=['obs://'+bucket_name])
            return {'bucket':bucket_name,'created':False,'note':'桶已存在，直接复用；建议核对归属与访问属性后再提交'}
        except McpToolError as exc:
            message=str(exc.message)
            if 'NoSuchBucket' not in message and '404' not in message:
                raise
        name=bucket_name
        for attempt in range(3):
            flags=['-acl=private','-location='+self.koocli.region,'-sc=standard','-epid=0']
            if redundancy=='multi_az':flags.append('-az=multi-az')
            try:
                await self.koocli.obs('mb',args=['obs://'+name],flags=flags)
            except McpToolError as exc:
                message=str(exc.message)
                if attempt<2 and ('xist' in message.lower() or '已存在' in message or 'conflict' in message.lower()):
                    name=bucket_name+'-'+uuid.uuid4().hex[:4]
                    continue
                raise
            break
        block_note=None
        try:
            await self.koocli.obs('put-public-access-block',args=['obs://'+name],flags=[BLOCK_PUBLIC_FLAG])
        except McpToolError as exc:
            block_note='阻止公共访问设置未成功：'+str(exc.message)[:100]+'——需控制台补设'
        lead='桶已新建（私有/标准/%s/阻止公共访问）'%('多AZ' if redundancy=='multi_az' else '单AZ')
        if block_note:lead+='；'+block_note
        return {'bucket':name,'created':True,'note':lead}

    async def create_bucket(self,app_name,redundancy='multi_az',confirm=False,plan_id=None):
        """Preview or execute the bucket creation behind the plan ledger; block public access after mb."""
        if not isinstance(app_name,str) or not 1<=len(app_name)<=64:
            raise McpToolError('MCP_INVALID_ARGS','app_name must be a string of 1-64 characters')
        if redundancy not in ('multi_az','single_az'):
            raise McpToolError('MCP_INVALID_ARGS','redundancy must be multi_az or single_az')
        name=self.bucket_name_for(app_name)
        spec=self.new_bucket_spec(name,redundancy)
        digest=self.intent_digest('POST','obs://bucket',
                                  {'bucket':name,'redundancy':redundancy,'location':self.koocli.region})
        if not confirm:
            return {'status':'confirmation_required','execution':'not_executed','spec':spec,
                    'warnings':['新桶立即产生少量存储计费',
                                '推荐在创建请求携带 storage_component 时一次挂载成型；未启用的应用事后可经 update_supabase_storage 补开对接（桶名+AK/SK 全量凭据）'],
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        if plan_id:
            self.plans.claim(plan_id,digest)
        try:
            for attempt in range(3):
                flags=['-acl=private','-location='+self.koocli.region,'-sc=standard','-epid=0']
                if redundancy=='multi_az':flags.append('-az=multi-az')
                try:
                    await self.koocli.obs('mb',args=['obs://'+name],flags=flags)
                except McpToolError as exc:
                    message=str(exc.message)
                    if attempt<2 and ('xist' in message.lower() or '已存在' in message or 'conflict' in message.lower()):
                        name=self.bucket_name_for(app_name)+'-'+uuid.uuid4().hex[:4]
                        spec=self.new_bucket_spec(name,redundancy)
                        continue
                    raise
                break
            block_note=None
            try:
                await self.koocli.obs('put-public-access-block',args=['obs://'+name],flags=[BLOCK_PUBLIC_FLAG])
            except McpToolError as exc:
                block_note='阻止公共访问设置未成功：'+str(exc.message)[:100]+'——需控制台补设'
            self.plans.finish(plan_id,'accepted')
            lead='桶已创建（并已设置阻止公共访问）' if block_note is None else '桶已创建；'+block_note
            result={'status':'ok','bucket':spec,
                    'storage_component_hint':{'bucket':name,'ak_sk':'经本地请求文件提供'},
                    'note':lead+'；把 bucket 与持久 AK/SK 经本地请求文件写入 storage_component，'
                                '随 create_supabase_application 提交完成对接'}
            if self.ledger is not None:
                warning=self.ledger.record_safe('obs_bucket',name,auto_created=True,
                                                detail={'provenance':'create_supabase_new_obs',
                                                        'block_public_access':block_note is None})
                if warning:result['record_warning']=warning
            return result
        except BaseException:
            self.plans.finish(plan_id,'unknown')
            raise
