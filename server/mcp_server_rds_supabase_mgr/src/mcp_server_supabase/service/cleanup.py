"""Post-deletion resource cleanup via KooCLI: EIP release, OBS bucket removal and
per-application OBS workspace clearing.

Every destructive operation follows the house two-phase discipline with the plan
ledger. All guards run immediately before the destructive call while the decision
is still fresh: the live-application reference sweep (REST inventory), the EIP
address cross-check, the bucket emptiness gate and the workspace prefix confinement.
The workspace deletion prefix is constructed exclusively from validated components
(canonical bucket name + in32-format application ID); no caller-supplied path
fragment can widen the deletion scope.
"""
import os
import re
from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails import assert_not_protected
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.client.rest import segment, ensure_project
from mcp_server_supabase.client.sdk_core import configured_client
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.contracts import application_query
from mcp_server_supabase.service.network import identifier
from mcp_server_supabase.service.operations import ROOT
from mcp_server_supabase.service.plans import PlanStore, fingerprint

BUCKET_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]{2,62}')
# obsutil rows print "obs://bucket/key  size  date": the key is the first token only,
# so trailing metadata never widens or fakes the prefix scope.
OBJECT_ROW = re.compile(r'^obs://([^/]+)/(\S+)')
COUNT_ROW = re.compile(r'(Succeeded|Failed)\s+(?:number|count)[:\s]*(\d+)', re.I)
ADDRESS_ALIASES = ('public_ip', 'direct_eip', 'public_ip_address', 'eip_address')


def bucket_name(bucket):
    if not isinstance(bucket, str) or not BUCKET_PATTERN.fullmatch(bucket):
        raise McpToolError('MCP_INVALID_ARGS', 'bucket 必须是 3-63 位小写字母/数字/中划线，且以字母或数字开头')
    return bucket


def object_rows(text, bucket, prefix=None):
    """Extract exactly-scoped object keys from obsutil ls/rm output: only rows inside
    the requested bucket and, when given, under the exact application-id prefix."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('obs://'):
            continue
        match = OBJECT_ROW.match(line)
        if not match:
            continue
        row_bucket, key = match.group(1), match.group(2)
        if row_bucket != bucket or not key or key.endswith(':'):
            continue
        if prefix is not None and not key.startswith(prefix):
            continue
        rows.append(key)
    return rows


def deletion_counts(text):
    succeeded = failed = None
    for match in COUNT_ROW.finditer(text):
        value = int(match.group(2))
        if match.group(1).lower() == 'succeeded':
            succeeded = value
        else:
            failed = value
    return succeeded, failed


def bucket_absent(exc):
    message = str(exc.message)
    return 'NoSuchBucket' in message or '404' in message


class CleanupService:
    """EIP and OBS cleanup after Supabase application deletion: the KooCLI channel
    carries the destructive calls, the REST inventory stays the reference authority."""

    def __init__(self, client=None, koocli=None, plans=None):
        self.client = client or configured_client()
        self.koocli = koocli or KoocliClient()
        self.plans = plans or PlanStore()

    def intent_digest(self, method, path, body):
        # Bind both channels: the REST identity that signs the reference sweep and
        # the KooCLI credential that will run the destructive command.
        if not self.client.project:
            self.client.project = ensure_project(self.client.project)
        return fingerprint({'endpoint': self.client.endpoint, 'project': self.client.project,
                            'credential': fingerprint(self.client.token if self.client.token is not None else os.getenv('HUAWEICLOUD_AUTH_TOKEN', '')),
                            'koocli': self.koocli.token,
                            'method': method, 'path': path, 'body': body})

    def _write_gate(self):
        if os.getenv('SUPABASE_ENABLE_WRITES') != 'true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY', 'false').lower() == 'true':
            raise McpToolError('MCP_READ_ONLY', 'Writes are disabled')

    async def _applications(self):
        """Collect the bounded application inventory - the same source the instance
        sharing sweep uses; reference checks never rely on stale local state."""
        rows = []
        seen = 0
        for page in range(5):
            _, listing = await self.client.request('GET', ROOT + '/applications',
                                                   query=application_query(100, page * 100))
            data = listing.get('data') if isinstance(listing, dict) else None
            total = listing.get('total_count') if isinstance(listing, dict) else None
            if not isinstance(data, list) or not isinstance(total, int):
                raise McpToolError('MCP_SDK_ERROR', 'Application inventory unreadable; resource references cannot be verified')
            seen += len(data)
            rows.extend(row for row in data if isinstance(row, dict))
            if seen >= total or not data:
                break
        else:
            raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'Too many applications to verify resource references',
                               hint='Narrow the environment or verify the references manually before retrying.')
        return rows

    async def delete_eip(self, public_ip_id, public_ip=None, confirm=False, plan_id=None):
        """Release one EIP (KooCLI EIP DeletePublicip) after the referencing application
        is gone. Bound EIPs are rejected by the backend itself; this guard layer adds the
        live-application reference sweep and an optional address cross-check."""
        identifier(public_ip_id)
        digest = self.intent_digest('DELETE', 'eip/' + public_ip_id, {'public_ip': public_ip})
        warnings = ['EIP 删除不可逆：地址释放，IP 保有费立即停止。',
                    '已绑定资源的 EIP 会被后端直接拒绝（DeletePublicip 语义）：先解绑（change_supabase_eip 置 is_bind=false，或控制台）再删。',
                    '提交前服务端全量扫描应用清单：仍被任何存活 Supabase 应用公网地址引用的 EIP 会被拦截。']
        notices = {'warnings': warnings, 'completion_verified': False}
        if not confirm:
            return {'status': 'confirmation_required', 'execution': 'not_executed',
                    'public_ip_id': public_ip_id, 'public_ip': public_ip, 'action': 'delete_eip',
                    **notices, **self.plans.issue(digest)}
        self._write_gate()
        data = await self.koocli.call('EIP', 'ShowPublicIp', {'publicip_id': public_ip_id})
        publicip = data.get('publicip') if isinstance(data, dict) else None
        if not isinstance(publicip, dict) or publicip.get('id') != public_ip_id:
            raise McpToolError('MCP_SDK_ERROR', 'EIP identity not verified')
        address = publicip.get('public_ip_address')
        if not isinstance(address, str) or not address:
            raise McpToolError('MCP_SDK_ERROR', 'EIP address not readable; the in-use sweep cannot be verified')
        if public_ip is not None and public_ip != address:
            raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'EIP address mismatch: the caller record does not match the live address',
                               hint='重新读取 EIP（ShowPublicIp）后携带当前地址提交，或省略地址交叉核对参数。')
        assert_not_protected(publicip)
        for row in await self._applications():
            for alias in ADDRESS_ALIASES:
                if row.get(alias) == address:
                    raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'EIP is still referenced by a live Supabase application',
                                       hint=f"应用 {row.get('id')}（{row.get('name')}）仍在使用该地址——先删除该应用，再清理 EIP。")
        self.plans.claim(plan_id, digest)
        try:
            await self.koocli.call('EIP', 'DeletePublicip', {'publicip_id': public_ip_id})
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'EIP deletion result unknown', 'submission_unknown',
                                'Reconcile the EIP state (EIP ListPublicIps / console) before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        return {'status': 'applied', 'public_ip_id': public_ip_id, 'public_ip': address,
                'plan_id': plan_id, **notices,
                'follow_up': '删除为同步调用，无 job_id；用 hcloud EIP ListPublicIps 或控制台复核 EIP 已消失，清理才算完成。'}

    async def delete_bucket(self, bucket, confirm=False, plan_id=None):
        """Delete one OBS bucket (KooCLI embedded obsutil rm) after every referencing
        application is gone. Non-empty buckets are blocked here - the per-application
        workspaces go through clean_supabase_obs_ws first, anything else needs manual
        review - so a shared bucket can never be emptied by accident."""
        bucket_name(bucket)
        digest = self.intent_digest('DELETE', 'obs://' + bucket, {'bucket': bucket})
        warnings = ['删除桶不可逆：桶内残留对象全部销毁。',
                    '非空桶会被本工具拦截（共享桶防误删）：先用 clean_supabase_obs_ws 清理各应用数据目录，其余对象人工核对处置后再删桶。',
                    '提交前服务端全量扫描应用清单：仍被任何存活 Supabase 应用 storage_component 引用的桶会被拦截。']
        notices = {'warnings': warnings, 'completion_verified': False}
        if not confirm:
            return {'status': 'confirmation_required', 'execution': 'not_executed',
                    'bucket': bucket, 'action': 'delete_obs', **notices, **self.plans.issue(digest)}
        self._write_gate()
        try:
            await self.koocli.obs('stat', args=['obs://' + bucket])
        except McpToolError as exc:
            if bucket_absent(exc):
                return {'status': 'already_absent', 'bucket': bucket, 'execution': 'not_executed',
                        'note': '桶不存在，无需清理（计划未消耗，自然过期）', **notices, 'plan_id': plan_id}
            raise
        assert_not_protected({'id': bucket, 'name': bucket})
        for row in await self._applications():
            component = row.get('storage_component')
            if isinstance(component, dict) and component.get('bucket') == bucket:
                raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'Bucket is still referenced by a live Supabase application',
                                   hint=f"应用 {row.get('id')}（{row.get('name')}）的存储对接仍指向该桶——先删除该应用，再清理桶。")
        listing = await self.koocli.obs('ls', args=['obs://' + bucket + '/'], flags=['-limit=1'])
        if object_rows(listing, bucket):
            raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'Bucket is not empty',
                               hint='先用 clean_supabase_obs_ws 清理各应用数据目录；其余对象人工核对处置后再删桶。')
        self.plans.claim(plan_id, digest)
        try:
            await self.koocli.obs('rm', args=['obs://' + bucket], flags=['-f'])
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'Bucket deletion result unknown', 'submission_unknown',
                                'Reconcile with hcloud obs ls before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        return {'status': 'applied', 'bucket': bucket, 'plan_id': plan_id, **notices,
                'follow_up': '删除为同步调用，无 job_id；用 hcloud obs ls 复核桶已消失，清理才算完成。'}

    async def clean_workspace(self, bucket, application_id, confirm=False, plan_id=None):
        """Clear one application's OBS data directory: the bucket-root folder whose
        name is exactly the application ID (obs://<bucket>/<application_id>/). The
        bucket itself and every other directory stay untouched. The deletion prefix
        is built solely from the validated bucket name and the in32-format
        application ID - no caller-supplied path fragment can widen the scope."""
        bucket_name(bucket)
        application_id = segment(application_id)
        prefix = application_id + '/'
        url = 'obs://' + bucket + '/' + prefix
        digest = self.intent_digest('DELETE', url, {'bucket': bucket, 'application_id': application_id})
        safety = {'scope': url,
                  'confinement': '删除前缀仅由通过校验的桶名与应用 ID 构造；应用 ID 强制 in32 规范格式，不含任何调用方路径片段。'}
        warnings = ['仅清理该桶根目录下名称为应用 ID 的数据目录（' + url + '），桶与其他任何目录不受影响。',
                    '清理不可逆：目录内对象（应用上传的文件等）全部删除。',
                    '服务端拒绝仍存活应用的 ID：先删应用（delete_supabase_application）再清目录。']
        notices = {'warnings': warnings, 'completion_verified': False}
        if not confirm:
            return {'status': 'confirmation_required', 'execution': 'not_executed',
                    'bucket': bucket, 'application_id': application_id, 'workspace': url,
                    'action': 'clean_obs_ws', 'safety': safety, **notices, **self.plans.issue(digest)}
        self._write_gate()
        for row in await self._applications():
            if row.get('id') == application_id:
                raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'Application still exists; its workspace stays live data',
                                   hint='先删除该应用（delete_supabase_application），再清理其数据目录。')
        try:
            await self.koocli.obs('stat', args=['obs://' + bucket])
        except McpToolError as exc:
            if bucket_absent(exc):
                return {'status': 'already_absent', 'bucket': bucket, 'application_id': application_id,
                        'workspace': url, 'execution': 'not_executed',
                        'note': '桶不存在，无需清理（计划未消耗，自然过期）', **notices, 'plan_id': plan_id}
            raise
        assert_not_protected({'id': application_id})
        listing = await self.koocli.obs('ls', args=[url])
        objects = object_rows(listing, bucket, prefix)
        if not objects:
            return {'status': 'already_clean', 'bucket': bucket, 'application_id': application_id,
                    'workspace': url, 'objects': 0, 'execution': 'executed',
                    'note': '目录不存在或为空，无需清理（计划未消耗，自然过期）', **notices, 'plan_id': plan_id}
        self.plans.claim(plan_id, digest)
        try:
            result = await self.koocli.obs('rm', args=[url], flags=['-r', '-f'])
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'Workspace cleanup result unknown', 'submission_unknown',
                                'Reconcile with hcloud obs ls on the workspace prefix before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        succeeded, failed = deletion_counts(result)
        payload = {'status': 'applied' if not failed else 'partial', 'bucket': bucket,
                   'application_id': application_id, 'workspace': url,
                   'objects_listed': len(objects), 'deleted': succeeded, 'delete_failed': failed,
                   'plan_id': plan_id, 'safety': safety, **notices,
                   'follow_up': '用 hcloud obs ls ' + url + ' 复核目录已空；删除为同步调用，无 job_id。'}
        if failed:
            payload['warning_extra'] = '部分对象删除失败（failed=' + str(failed) + '）：核对失败对象与权限后重新预览提交。'
        return payload
