"""First-time EIP binding for a Supabase application through the application-level
public-eip endpoint (the same SwitchSupabaseApplicationEipBind contract that
change_supabase_eip submits through).

Fixes #23: the ownership check now reads the authoritative application detail
instead of an ID-filtered inventory query, read failures are never masqueraded as
ownership rejections, and the submission targets the application resource - the
previous KooCLI AttachEip channel was an instance-level API (/v3/{project}/
instances/{instance_id}/public-ip) that no application ID could ever address.
"""
import ipaddress
import os
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.rest import segment
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.network import identifier
from mcp_server_supabase.service.plans import PlanStore
from mcp_server_supabase.service.contracts import accepted_job

_OWNERSHIP_HINT = ('核对源：应用详情接口 GET /v3/{project}/ai-application/<id>/supabase；'
                   '先用 list_supabase_applications 确认应用列表后重试')
# A clean 4xx proves the submission was definitively rejected (never accepted);
# everything else leaves the write result genuinely unknown.
_DEFINITE_REJECTIONS = {"invalid_request", "authentication", "permission", "not_found", "state_conflict"}


class EipBindService:
    """Bind an EIP to a Supabase application through the application-level
    public-eip endpoint, with ownership validated against the application
    detail (the same authoritative source change_supabase_eip uses) and
    scenario separation: only an application without a bound EIP is bindable
    here; swaps and unbinding belong to change_supabase_eip."""

    def __init__(self,operations=None,plans=None,ledger=None):
        """Accept injected doubles; ledger=None disables resource-ledger recording (tests / embedded use)."""
        self.operations=operations
        self.plans=plans or PlanStore()
        self.ledger=ledger

    def _ops(self):
        """Resolve the shared application reader lazily to avoid import cycles."""
        if self.operations is None:
            from mcp_server_supabase.service.operations import Operations
            self.operations=Operations()
        return self.operations

    def _ownership_not_found(self):
        return McpToolError('MCP_NOT_FOUND','instance_id 不是本环境管理的 Supabase 应用——避免滥操作，已拒绝',
                            hint=_OWNERSHIP_HINT)

    async def _read_target(self,application_id):
        """One authoritative detail read. A definitive 404 is an ownership
        rejection; every other read failure propagates unchanged."""
        try:
            _,target=await self._ops().client.request('GET',self._ops().app(application_id))
        except RecoveryError as error:
            if error.recovery.get('category')=='not_found':
                raise self._ownership_not_found() from None
            raise
        if not isinstance(target,dict) or target.get('id')!=application_id:
            raise self._ownership_not_found()
        return target

    def _assert_bindable(self,target):
        """Guards run before the plan claim so a blocked attempt never poisons the plan."""
        if target.get('status')!='normal' or target.get('current_actions'):
            raise McpToolError('MCP_GUARDRAIL_BLOCKED','应用非运行态或存在进行中操作，不可绑定 EIP',
                               hint='仅运行中（normal）且无进行中操作的应用可绑定；先处理进行中任务或启动应用，再重新预览。')
        if target.get('public_ip'):
            raise McpToolError('MCP_GUARDRAIL_BLOCKED','应用已绑定 EIP；本工具仅用于首次绑定',
                               hint='更换 EIP 或解绑请使用 change_supabase_eip。')

    async def bind_public_ip(self,instance_id,public_ip_id,public_ip,confirm=False,plan_id=None):
        """Validate arguments locally, verify ownership and bindability against
        the application detail, then preview or - behind the write gate and a
        claimed plan - submit the binding through the public-eip endpoint."""
        if not isinstance(instance_id,str) or not instance_id.endswith('in32'):
            raise McpToolError('MCP_INVALID_ARGS','instance_id 必须是 Supabase 应用 ID（in32 结尾），当前值不满足——为避免误绑定已拒绝')
        application_id=segment(instance_id)
        identifier(public_ip_id)
        try:
            if not isinstance(public_ip,str):raise ValueError()
            ipaddress.IPv4Address(public_ip)
        except ValueError:
            raise McpToolError('MCP_INVALID_ARGS','public_ip 必须是合法的 IPv4 地址') from None
        ops=self._ops()
        path=ops.app(application_id)+'/public-eip'
        body={'is_bind':True,'public_ip_id':public_ip_id,'public_ip_address':public_ip}
        digest=ops.intent_digest('PUT',path,body)
        warnings=['绑定后必须同步 api_external_url（update_supabase_auth_config），邮箱链接与 OAuth 回调依赖此地址',
                  '确认 EIP 与应用同区域',
                  '本工具仅用于首次绑定；更换或解绑请使用 change_supabase_eip']
        if not confirm:
            target=await self._read_target(application_id)
            self._assert_bindable(target)
            return {'status':'confirmation_required','execution':'not_executed','changes':body,
                    'warnings':warnings,**self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        # Fresh read + guards immediately before submission, still before the claim.
        target=await self._read_target(application_id)
        self._assert_bindable(target)
        self.plans.claim(plan_id,digest)
        unknown=RecoveryError('MCP_SDK_ERROR','Binding result unknown','submission_unknown',
                              'Query the operation task and the application detail directly; do not resubmit - previews and the recorded intent are single-use.',plan_id)
        try:
            status,data=await ops.client.request('PUT',path,body=body)
        except RecoveryError as error:
            if error.recovery.get('category') in _DEFINITE_REJECTIONS:
                self.plans.finish(plan_id,'failed');raise
            self.plans.finish(plan_id,'unknown');raise unknown from None
        except McpToolError:
            self.plans.finish(plan_id,'failed');raise
        except BaseException:
            self.plans.finish(plan_id,'unknown');raise unknown from None
        try:
            result=accepted_job(status,data)
            self.plans.finish(plan_id,'accepted',result['job_id'])
        except BaseException:
            self.plans.finish(plan_id,'unknown');raise unknown from None
        result={**result,'instance_id':application_id,
                'eip':{'public_ip':public_ip,'public_ip_id':public_ip_id},
                'warnings':warnings,
                'post_bind':'立即 update_supabase_auth_config 同步 api_external_url，并探活验证；任务终态后用 show_supabase_application 回查绑定结果',
                'job_follow_up':'任务已受理（异步）：用 show_operation_job_status(job_id) 查询任务状态直至终态；wait_operation_job_complete(job_id) 可有界等待；终态后回查应用确认绑定结果',
                'plan_id':plan_id}
        if self.ledger is not None:
            warning=self.ledger.bind_safe('eip',public_ip_id,application_id,
                                          detail={'address':public_ip,'provenance':'bind_supabase_eip（首次绑定）'})
            if warning:result['record_warning']=warning
        return result
