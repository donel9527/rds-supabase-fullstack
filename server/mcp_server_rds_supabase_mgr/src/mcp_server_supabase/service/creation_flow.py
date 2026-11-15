"""Scenario-specific creation orchestration: dedicated security groups provisioned and injected, then one submitted creation."""
import ipaddress
import os
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.service.network import Network
from mcp_server_supabase.service.plans import PlanStore, fingerprint

CIDR_CHOICES='public_access_cidr 三选一：auto（探测当前设备出口 IP）/ open（0.0.0.0/0，经 KooCLI）/ 自定义有界 CIDR'
EIP_AUTOMATION=[{'tool':'create_supabase_eip','args':{'prefer_idle':True,'charge_mode':'postPaid','bandwidth_size_mbps':300}},
                {'tool':'bind_supabase_eip','args':{'instance_id':'<application_id（in32 结尾）>','public_ip_id':'<EIP ID>','public_ip':'<EIP 地址>'}},
                {'tool':'update_supabase_auth_config','action':'同步 api_external_url 为公网地址并探活'}]


class CreationFlowService:
    """Scenario-specific application creation executing the arrangement's resource
    preparation end to end: the dedicated security groups are provisioned and wired
    into the request automatically, the creation task is submitted once, and the
    response echoes the application/instance identifiers with tracking and EIP
    automation follow-ups."""

    def __init__(self,operations=None,network=None,koocli=None,plans=None,detector=None,obs=None):
        self.operations=operations
        self.network=network or Network()
        self.koocli=koocli or self.network.koocli
        self.plans=plans or PlanStore()
        self.detector=detector
        self.obs=obs

    def _obs(self):
        """Lazily construct the OBS service on the shared KooCLI channel."""
        if self.obs is None:
            from mcp_server_supabase.service.obs import ObsService
            self.obs=ObsService(koocli=self.koocli)
        return self.obs

    def _obs_target(self,body):
        """The storage_component bucket this flow must ensure before submission, if any."""
        storage=body.get('storage_component') if isinstance(body.get('storage_component'),dict) else {}
        return storage.get('bucket_name') if storage.get('enabled') else None

    def _obs_plan(self,body):
        """Preview-time OBS plan: storage enabled means the flow ensures the bucket
        exists and backfills the final name into storage_component."""
        if not self._obs_target(body):return None
        from mcp_server_supabase.service.obs import ObsService
        credential=ObsService(koocli=self.koocli).credential_mode()
        warnings=[]
        if credential.get('temporary') and credential.get('notice'):
            warnings.append('存储凭据：'+credential['notice'])
        return {'bucket':self._obs_target(body),
                'action':'确保桶存在：已存在则复用，缺失则按固定规则新建（私有/标准/多AZ/阻止公共访问），全局重名自动加短 uuid 并回填最终桶名',
                'credential':credential,'warnings':warnings}

    def _ops(self):
        """Lazily construct the Operations service; orchestrated flows inject their own."""
        if self.operations is None:
            from mcp_server_supabase.service.operations import Operations
            self.operations=Operations()
        return self.operations

    def _digest(self,payload):
        """Fingerprint one orchestrated creation intent; the plan binds it single-use."""
        return fingerprint({'endpoint':'creation_flow','method':'POST',
                            'path':'/v3/{project}/ai-application/supabases','payload':payload})

    async def _resolve_subnet_cidr(self,vpc_id,subnet_id):
        """Read the chosen subnet's CIDR through KooCLI; unresolved placement fails closed."""
        data=await self.koocli.call('VPC','ListSubnets',{'limit':100,'vpc_id':vpc_id})
        subnets=data.get('subnets') if isinstance(data,dict) else None
        for subnet in subnets if isinstance(subnets,list) else []:
            if isinstance(subnet,dict) and subnet.get('id')==subnet_id and subnet.get('cidr'):
                return subnet['cidr']
        raise McpToolError('MCP_NOT_FOUND','无法从 VPC 中解析子网 CIDR',
                           hint='核对 basic_config 的 vpc_id/subnet_id（来源 discover_network_for_create）')

    async def _ingress_cidr(self,public_access_cidr):
        """Resolve the 8443 ingress source: auto detection, explicit open, or a bounded custom CIDR."""
        if not isinstance(public_access_cidr,str) or not public_access_cidr:
            raise McpToolError('MCP_INVALID_ARGS',CIDR_CHOICES)
        if public_access_cidr=='auto':
            detected=self.detector() if self.detector is not None else self._detect_egress()
            if not detected:
                raise McpToolError('MCP_CLI_ERROR','当前设备出口 IP 探测失败',
                                   hint='改传自定义 CIDR 或 open（0.0.0.0/0，经 KooCLI）')
            return detected
        if public_access_cidr=='open':
            return '0.0.0.0/0'
        try:
            network=ipaddress.ip_network(public_access_cidr,strict=True)
        except (ValueError,TypeError):
            raise McpToolError('MCP_INVALID_ARGS',CIDR_CHOICES) from None
        if network.prefixlen==0:
            raise McpToolError('MCP_INVALID_ARGS','全 0 网段请直接传 open（0.0.0.0/0，经 KooCLI）；custom CIDR 必须有界',
                               hint=CIDR_CHOICES)
        return str(network)

    def _detect_egress(self):
        """Default egress probe: the same best-effort public-IP detection as network discovery."""
        from mcp_server_supabase.service.instance_catalog import NetworkDiscovery
        return NetworkDiscovery()._detect_access_cidr()

    async def _create_group_pair(self,scenario,subnet_cidr,ingress_cidr):
        """Provision the dedicated groups and their bounded rules; the /0 ingress is
        issued explicitly through KooCLI because the MCP rule primitive rejects it."""
        app=await self.network.create_group_now('supabase-app-sg','Supabase应用（自动创建）')
        app_id=app['id']
        if ingress_cidr=='0.0.0.0/0':
            await self.koocli.call('VPC','CreateSecurityGroupRule/v3',
                                   {'security_group_rule':{'security_group_id':app_id,'direction':'ingress',
                                                           'ethertype':'IPv4','protocol':'tcp','multiport':'8443',
                                                           'remote_ip_prefix':'0.0.0.0/0','action':'allow','priority':1}})
        else:
            await self.network.add_rule_now(app_id,ingress_cidr,8443)
        await self.network.add_rule_now(app_id,subnet_cidr,5432,'egress')
        rules=[{'group':'app','direction':'ingress','port':8443,'cidr':ingress_cidr},
               {'group':'app','direction':'egress','port':5432,'cidr':subnet_cidr}]
        database_group_id=None
        if scenario=='newly_instance':
            database=await self.network.create_group_now('supabase-db-sg','数据库接入（自动创建）')
            database_group_id=database['id']
            await self.network.add_rule_now(database_group_id,subnet_cidr,5432)
            rules.append({'group':'db','direction':'ingress','port':5432,'cidr':subnet_cidr})
        groups={'application_group_id':app_id,'database_group_id':database_group_id,'rules':rules}
        if scenario!='newly_instance':
            groups['database_group']='不动（保持实例现状）'
        return groups

    def _group_plan(self,scenario,ingress_cidr,subnet_cidr):
        """Preview-time specification of the groups this flow will create and inject."""
        return {'application_group':{'name':'supabase-app-sg','ingress':{'port':8443,'cidr':ingress_cidr}},
                'database_group':{'name':'supabase-db-sg','ingress':{'port':5432,'cidr':subnet_cidr}}
                                 if scenario=='newly_instance' else '不动（保持实例现状）',
                'egress':{'port':5432,'cidr':subnet_cidr},
                'note':'确认后自动创建并注入请求体，无需手填 security_group_id'}

    def _workflow(self,result,scenario):
        """Tracking and post-completion follow-ups echoing the submitted result."""
        if result.get('status')=='order_created':
            track={'tool':'get_supabase_order','args':{'order_id':result.get('order_id')}}
            reminder='预付费订单已创建：须先经 get_supabase_order 核对并 pay_supabase_order 支付后才开始建资源，支付后按返回任务持续查询创建状态'
        else:
            args={'application_id':result.get('application_id'),'application_job_id':result.get('job_id')}
            if scenario=='newly_instance':
                args['instance_job_id']=result.get('instance_job_id')
                args['instance_id']=result.get('instance_id')
            track={'tool':'show_supabase_creation_progress','args':args}
            reminder=('创建任务已下发：请调用方持续查询创建状态（整体约 20-30 分钟；实例先就绪、应用任务才开始；预付费需先支付订单）'
                      if scenario=='newly_instance' else
                      '创建任务已下发：请调用方持续查询创建状态（整体约 20-30 分钟；预付费需先支付订单）')
        return {'track':track,'reminder':reminder,
                'after_completion':{'eip_automation':EIP_AUTOMATION,
                                    'note':'状态到终态且确认公网访问后执行；空闲 EIP 优先复用'}}

    def _response(self,result,groups,scenario,prepared_obs=None):
        """Echo the creation identifiers plus the prepared-resource record and workflow follow-ups."""
        echoed={k:result[k] for k in ('status','job_id','application_id','instance_id','instance_job_id','order_id')
                if k in result}
        response={**echoed,'security_groups':groups,'workflow':self._workflow(result,scenario)}
        if prepared_obs is not None:response['obs']=prepared_obs
        return response

    async def with_new_instance(self,request_ref,public_access_cidr='auto',confirm=False,plan_id=None):
        """Create the application together with its managed PG instance: two dedicated
        security groups are provisioned, wired into the request and submitted once."""
        from mcp_server_supabase.service.creation import validate_creation
        from mcp_server_supabase.service.request_refs import load_request,preview_request
        body=validate_creation(load_request(request_ref))
        if body['manage_type']!='newly_instance':
            raise McpToolError('MCP_INVALID_ARGS','本工具仅服务新建实例场景（对应编排 newly_instance）',
                               hint='已有实例挂载用 create_supabase_link_exist_instance')
        subnet_cidr=await self._resolve_subnet_cidr(body['basic_config']['vpc_id'],body['basic_config']['subnet_id'])
        ingress_cidr=await self._ingress_cidr(public_access_cidr)
        obs_plan=self._obs_plan(body)
        digest=self._digest({'request':body,'security_groups':{'scenario':'newly_instance','ingress_cidr':ingress_cidr,
                                                                'subnet_cidr':subnet_cidr},
                             'obs_bucket':self._obs_target(body)})
        if not confirm:
            return {'status':'confirmation_required','execution':'not_executed','scenario':'newly_instance',
                    'request':preview_request(body),
                    'security_group_plan':self._group_plan('newly_instance',ingress_cidr,subnet_cidr),
                    'obs_plan':obs_plan,
                    'warnings':['确认即创建两个专用安全组（启用存储时确保 OBS 桶）并提交应用创建（计费开始）',
                                '预付费（prePaid）返回订单，须 get/pay_supabase_order 支付后才建资源']
                              +((obs_plan or {}).get('warnings') or []),
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        self.plans.claim(plan_id,digest)
        try:
            groups=await self._create_group_pair('newly_instance',subnet_cidr,ingress_cidr)
            body['security_group_id']=groups['application_group_id']
            body['managed_instance']['security_group_id']=groups['database_group_id']
            prepared_obs=None
            if self._obs_target(body):
                prepared_obs=await self._obs().ensure_bucket_now(self._obs_target(body))
                body['storage_component']['bucket_name']=prepared_obs['bucket']
            body=validate_creation(body)
        except BaseException:
            self.plans.finish(plan_id,'failed');raise
        result=await self._ops().submit_creation(body,plan_id)
        return self._response(result,groups,'newly_instance',prepared_obs)

    async def link_exist_instance(self,request_ref,public_access_cidr='auto',confirm=False,plan_id=None):
        """Attach an existing PG instance: one dedicated application security group is
        provisioned and injected; the instance's own security group stays untouched."""
        from mcp_server_supabase.service.creation import validate_creation
        from mcp_server_supabase.service.instance_catalog import _find_manageable
        from mcp_server_supabase.service.request_refs import load_request,preview_request
        body=validate_creation(load_request(request_ref))
        if body['manage_type']!='existed_instance':
            raise McpToolError('MCP_INVALID_ARGS','本工具仅服务已有实例挂载场景（对应编排 existed_instance）',
                               hint='新建实例用 create_supabase_with_new_instance')
        instance_id=body['existing_instance']['instance_id']
        match=await _find_manageable(self._ops(),instance_id)
        subnet_cidr=await self._resolve_subnet_cidr(match['vpc_id'],match['subnet_id'])
        ingress_cidr=await self._ingress_cidr(public_access_cidr)
        obs_plan=self._obs_plan(body)
        digest=self._digest({'request':body,'security_groups':{'scenario':'existed_instance','ingress_cidr':ingress_cidr,
                                                                'subnet_cidr':subnet_cidr},
                             'obs_bucket':self._obs_target(body)})
        if not confirm:
            return {'status':'confirmation_required','execution':'not_executed','scenario':'existed_instance',
                    'request':preview_request(body),
                    'security_group_plan':self._group_plan('existed_instance',ingress_cidr,subnet_cidr),
                    'obs_plan':obs_plan,
                    'warnings':['确认即创建一个专用安全组（启用存储时确保 OBS 桶）并提交应用创建（计费开始）',
                                '预付费（prePaid）返回订单，须 get/pay_supabase_order 支付后才建资源']
                              +((obs_plan or {}).get('warnings') or []),
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        self.plans.claim(plan_id,digest)
        try:
            groups=await self._create_group_pair('existed_instance',subnet_cidr,ingress_cidr)
            body['security_group_id']=groups['application_group_id']
            prepared_obs=None
            if self._obs_target(body):
                prepared_obs=await self._obs().ensure_bucket_now(self._obs_target(body))
                body['storage_component']['bucket_name']=prepared_obs['bucket']
            body=validate_creation(body)
        except BaseException:
            self.plans.finish(plan_id,'failed');raise
        result=await self._ops().submit_creation(body,plan_id)
        return self._response(result,groups,'existed_instance',prepared_obs)
