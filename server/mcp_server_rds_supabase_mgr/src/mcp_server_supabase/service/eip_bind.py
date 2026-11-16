"""Bind a public EIP to a Supabase application via the native RDS AttachEip API through KooCLI."""
import ipaddress
import os
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.service.network import identifier
from mcp_server_supabase.service.plans import PlanStore, fingerprint


class EipBindService:
    """Bind an EIP to a Supabase application through the RDS AttachEip API (KooCLI),
    with strict ownership validation: the instance ID must be this environment's
    Supabase application ID (in32 suffix) to prevent mistaken or stray operations."""

    def __init__(self,operations=None,koocli=None,plans=None,ledger=None):
        """Accept injected doubles; fall back to the canonical KooCLI channel and ledger."""
        self.operations=operations
        self.koocli=koocli or KoocliClient()
        self.plans=plans or PlanStore()
        self.ledger=ledger   # None disables resource-ledger recording (tests / embedded use)

    def _ops(self):
        """Resolve the shared application-inventory reader lazily to avoid import cycles."""
        if self.operations is None:
            from mcp_server_supabase.service.operations import Operations
            self.operations=Operations()
        return self.operations

    def intent_digest(self,method,path,body):
        """Fingerprint the credential-scoped intent exactly like the VPC network service."""
        return fingerprint({'endpoint':'hcloud:'+self.koocli.region,'credential':self.koocli.token,
                            'method':method,'path':path,'body':body})

    async def bind_public_ip(self,instance_id,public_ip_id,public_ip,confirm=False,plan_id=None):
        """Validate all arguments locally, verify the application is managed by this
        environment with one read-only inventory call, then preview or - behind the
        write gate and a claimed plan - submit the AttachEip binding through KooCLI."""
        if not isinstance(instance_id,str) or not instance_id.endswith('in32'):
            raise McpToolError('MCP_INVALID_ARGS','instance_id 必须是 Supabase 应用 ID（in32 结尾），当前值不满足——为避免误绑定已拒绝')
        identifier(public_ip_id)
        try:
            if not isinstance(public_ip,str):raise ValueError()
            ipaddress.IPv4Address(public_ip)
        except ValueError:
            raise McpToolError('MCP_INVALID_ARGS','public_ip 必须是合法的 IPv4 地址') from None
        try:
            listing=await self._ops().read('applications',application_id=instance_id)
        except McpToolError:
            # An exact-ID filter that the backend rejects outright is an unknown application,
            # not a stray backend fault: keep the rejection message about ownership.
            raise McpToolError('MCP_NOT_FOUND','instance_id 不是本环境管理的 Supabase 应用——避免滥操作，已拒绝',
                               hint='先用 list_supabase_applications 确认应用列表') from None
        rows=listing.get('data') if isinstance(listing,dict) else None
        if not isinstance(rows,list) or not any(isinstance(row,dict) and row.get('id')==instance_id for row in rows):
            raise McpToolError('MCP_NOT_FOUND','instance_id 不是本环境管理的 Supabase 应用——避免滥操作，已拒绝',
                               hint='先用 list_supabase_applications 确认应用列表')
        body={'instance_id':instance_id,'is_bind':True,'public_ip':public_ip,'public_ip_id':public_ip_id}
        digest=self.intent_digest('PUT','/v3/{project}/instances/%s'%instance_id,body)
        if not confirm:
            return {'status':'confirmation_required','execution':'not_executed','changes':body,
                    'warnings':['绑定后必须同步 api_external_url（update_supabase_auth_config），邮箱链接与 OAuth 回调依赖此地址',
                                '确认 EIP 与应用同区域'],
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        if plan_id:self.plans.claim(plan_id,digest)
        data=await self.koocli.call('RDS','AttachEip',{'instance_id':instance_id,'is_bind':True,
                                                        'public_ip':public_ip,'public_ip_id':public_ip_id})
        result={'status':'ok','job':'eip bind','instance_id':instance_id,
                'eip':{'public_ip':public_ip,'public_ip_id':public_ip_id},
                'post_bind':'立即 update_supabase_auth_config 同步 api_external_url，并探活验证'}
        if self.ledger is not None:
            warning=self.ledger.bind_safe('eip',public_ip_id,instance_id,
                                          detail={'address':public_ip,'provenance':'bind_supabase_eip（复用或既有 EIP）'})
            if warning:result['record_warning']=warning
        return result
