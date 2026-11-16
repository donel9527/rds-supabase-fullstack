"""Post-deletion resource cleanup via KooCLI: EIP release, OBS bucket removal and
per-application OBS workspace clearing, plus the residual inventory and the
one-click batch cleanup built on the local resource ledger.

Every destructive operation follows the house two-phase discipline with the plan
ledger. Guards run immediately before the destructive call while the decision is
still fresh: the live-application reference sweep (REST inventory), the EIP
address cross-check, the bucket emptiness gate and the workspace prefix
confinement. The workspace deletion prefix is constructed exclusively from
validated components (canonical bucket name + in32-format application ID); no
caller-supplied path fragment can widen the deletion scope.

The single-item tools guard BEFORE claiming their plan, so a blocked guard never
poisons the plan. The batch tool claims once for the whole confirmed set and
tolerates per-item guard rejections - every item reports its own outcome and the
plan always reaches a terminal state.
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
OBJECT_ROW = re.compile(r'^obs://([^/]+)/(\S+)')
COUNT_ROW = re.compile(r'(Succeeded|Failed)\s+(?:number|count)[:\s]*(\d+)', re.I)
ADDRESS_ALIASES = ('public_ip', 'direct_eip', 'public_ip_address', 'eip_address')

RECOMMEND_EIP_AUTO = '建议删除（流程自动创建——删除后立即停止 IP 保有费，避免残留计费）'
RECOMMEND_EIP_REUSED = '用户决策（复用接入的 EIP——确认无其他用途后再删）'
RECOMMEND_BUCKET_AUTO = '建议删除（流程自动创建——删除后停止桶存储计费，避免残留）'
RECOMMEND_BUCKET_REUSED = '用户决策（复用接入的桶——确认无其他数据后再删）'
HIGH_RISK_STORAGE_NOTE = ('高危提醒：桶一旦保留，桶内数据（含该应用目录）持续产生存储费用；'
                          '强烈建议清理应用数据目录（仅 obs://<bucket>/<应用ID>/，不动桶与其他目录），避免残留扣费。')
SG_INSTANCE_RETAINED_NOTE = '实例保留中：数据库安全组仍被实例使用，不可删除（云端也会拒绝）。'


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


def _outcome(error):
    """Classify a per-item failure for the batch report: guard rejections stay
    honest 'blocked', transport/backend faults are 'failed'."""
    if isinstance(error, McpToolError) and error.code in ('MCP_GUARDRAIL_BLOCKED', 'MCP_NOT_FOUND',
                                                         'MCP_INVALID_ARGS', 'MCP_SDK_ERROR'):
        return 'blocked'
    return 'failed'


class CleanupService:
    """EIP and OBS cleanup after Supabase application deletion: the KooCLI channel
    carries the destructive calls, the REST inventory stays the reference authority,
    and the resource ledger scopes the residual inventory and the one-click batch."""

    def __init__(self, client=None, koocli=None, plans=None, ledger=None):
        self.client = client or configured_client()
        self.koocli = koocli or KoocliClient()
        self.plans = plans or PlanStore()
        self.ledger = ledger   # None disables recording (unit tests / embedded use)

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

    def _require_ledger(self):
        if self.ledger is None:
            raise McpToolError('MCP_INVALID_ARGS', '资源记录未启用——残留盘点与一键清理依赖资源记录圈定范围（工具层始终启用）',
                               hint='经 MCP 工具调用本能力，或为服务注入 ResourceLedger。')

    def _mark_cleaned(self, kind, resource_id):
        if self.ledger is None:
            return
        try:
            self.ledger.cleaned(kind, resource_id)
        except Exception:  # noqa: BLE001 - advisory persistence must not fail a finished deletion
            pass

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

    # --------------------------------------------------------------- EIP ----

    async def _verify_eip(self, public_ip_id, public_ip=None):
        """Guards only (read-only): live identity read, address cross-check,
        protection list and the live-application reference sweep."""
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
        return {'address': address}

    async def _run_eip_delete(self, public_ip_id):
        await self.koocli.call('EIP', 'DeletePublicip', {'publicip_id': public_ip_id})

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
        check = await self._verify_eip(public_ip_id, public_ip)
        self.plans.claim(plan_id, digest)
        try:
            await self._run_eip_delete(public_ip_id)
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'EIP deletion result unknown', 'submission_unknown',
                                'Reconcile the EIP state (EIP ListPublicIps / console) before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        self._mark_cleaned('eip', public_ip_id)
        return {'status': 'applied', 'public_ip_id': public_ip_id, 'public_ip': check['address'],
                'plan_id': plan_id, **notices,
                'follow_up': '删除为同步调用，无 job_id；用 hcloud EIP ListPublicIps 或控制台复核 EIP 已消失，清理才算完成。'}

    # ----------------------------------------------------------- OBS bucket ----

    async def _verify_bucket(self, bucket):
        """Guards only (read-only): bucket existence, live-application reference
        sweep and the emptiness gate. Returns {'exists': bool}; absent buckets are
        the caller's decision (single tool: already_absent; batch: skip)."""
        exists = True
        try:
            await self.koocli.obs('stat', args=['obs://' + bucket])
        except McpToolError as exc:
            if not bucket_absent(exc):
                raise
            exists = False
        if not exists:
            return {'exists': False}
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
        return {'exists': True}

    async def _run_bucket_delete(self, bucket):
        await self.koocli.obs('rm', args=['obs://' + bucket], flags=['-f'])

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
        check = await self._verify_bucket(bucket)
        if not check['exists']:
            return {'status': 'already_absent', 'bucket': bucket, 'execution': 'not_executed',
                    'note': '桶不存在，无需清理（计划未消耗，自然过期）', **notices, 'plan_id': plan_id}
        self.plans.claim(plan_id, digest)
        try:
            await self._run_bucket_delete(bucket)
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'Bucket deletion result unknown', 'submission_unknown',
                                'Reconcile with hcloud obs ls before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        self._mark_cleaned('obs_bucket', bucket)
        return {'status': 'applied', 'bucket': bucket, 'plan_id': plan_id, **notices,
                'follow_up': '删除为同步调用，无 job_id；用 hcloud obs ls 复核桶已消失，清理才算完成。'}

    # ----------------------------------------------------------- OBS workspace ----

    async def _verify_workspace(self, bucket, application_id):
        """Guards only (read-only): the live-application block, bucket existence and
        the workspace listing. Returns {'bucket_exists', 'objects'}."""
        for row in await self._applications():
            if row.get('id') == application_id:
                raise McpToolError('MCP_GUARDRAIL_BLOCKED', 'Application still exists; its workspace stays live data',
                                   hint='先删除该应用（delete_supabase_application），再清理其数据目录。')
        bucket_exists = True
        try:
            await self.koocli.obs('stat', args=['obs://' + bucket])
        except McpToolError as exc:
            if not bucket_absent(exc):
                raise
            bucket_exists = False
        objects = []
        if bucket_exists:
            assert_not_protected({'id': application_id})
            listing = await self.koocli.obs('ls', args=['obs://' + bucket + '/' + application_id + '/'])
            objects = object_rows(listing, bucket, application_id + '/')
        return {'bucket_exists': bucket_exists, 'objects': objects}

    async def _run_workspace_delete(self, bucket, application_id):
        """Empty the folder named as the application ID at the bucket root, then
        delete the folder marker itself so the directory disappears entirely."""
        url = 'obs://' + bucket + '/' + application_id + '/'
        result = await self.koocli.obs('rm', args=[url], flags=['-r', '-f'])
        try:
            marker = await self.koocli.obs('rm', args=[url], flags=['-f'])
        except McpToolError as exc:
            # The folder marker may already be gone with the last object; a missing
            # marker is not a failure - the folder is deleted either way.
            marker = 'folder marker: ' + str(exc.message)[:120]
        return result + '\n' + marker

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
        check = await self._verify_workspace(bucket, application_id)
        if not check['bucket_exists']:
            return {'status': 'already_absent', 'bucket': bucket, 'application_id': application_id,
                    'workspace': url, 'execution': 'not_executed',
                    'note': '桶不存在，无需清理（计划未消耗，自然过期）', **notices, 'plan_id': plan_id}
        if not check['objects']:
            return {'status': 'already_clean', 'bucket': bucket, 'application_id': application_id,
                    'workspace': url, 'objects': 0, 'execution': 'executed',
                    'note': '目录不存在或为空，无需清理（计划未消耗，自然过期）', **notices, 'plan_id': plan_id}
        self.plans.claim(plan_id, digest)
        try:
            result = await self._run_workspace_delete(bucket, application_id)
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'Workspace cleanup result unknown', 'submission_unknown',
                                'Reconcile with hcloud obs ls on the workspace prefix before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        succeeded, failed = deletion_counts(result)
        payload = {'status': 'applied' if not failed else 'partial', 'bucket': bucket,
                   'application_id': application_id, 'workspace': url,
                   'objects_listed': len(check['objects']), 'deleted': succeeded, 'delete_failed': failed,
                   'plan_id': plan_id, 'safety': safety, **notices,
                   'follow_up': '用 hcloud obs ls ' + url + ' 复核目录已空；删除为同步调用，无 job_id。'}
        if failed:
            payload['warning_extra'] = '部分对象删除失败（failed=' + str(failed) + '）：核对失败对象与权限后重新预览提交。'
        return payload

    # ------------------------------------------------- residual inventory ----

    async def _eip_live(self, public_ip_id):
        try:
            data = await self.koocli.call('EIP', 'ShowPublicIp', {'publicip_id': public_ip_id})
        except McpToolError as exc:
            text = str(exc.message)
            if 'not found' in text.lower() or '404' in text or 'not exist' in text.lower():
                return {'exists': False}
            return {'exists': None, 'error': text[:160]}
        publicip = data.get('publicip') if isinstance(data, dict) else {}
        return {'exists': True, 'address': (publicip or {}).get('public_ip_address'),
                'status': (publicip or {}).get('status')}

    async def _instance_live(self, instance_id):
        if not instance_id:
            return {'exists': None, 'note': '资源记录无实例 ID（挂载场景记录于应用详情）'}
        try:
            _, listing = await self.client.request('GET', '/v3/{project}/instances', query={'id': instance_id})
        except McpToolError as exc:
            return {'exists': None, 'error': str(exc.message)[:160]}
        rows = listing.get('instances') if isinstance(listing, dict) else None
        if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) and rows[0].get('id') == instance_id:
            return {'exists': True, 'name': rows[0].get('name'), 'status': rows[0].get('status')}
        return {'exists': False}

    async def _residual_inventory(self, application_id):
        """Ledger-scoped, live-verified residual inventory for one application."""
        self._require_ledger()
        app = self.ledger.get('application', application_id)
        if not app:
            raise McpToolError('MCP_NOT_FOUND', '该应用无本地资源记录（可能创建于资源记录机制启用前或非本环境创建）——拒绝猜测清理范围',
                               hint='人工核对残留后使用单项工具：delete_supabase_eip / delete_supabase_obs / clean_supabase_obs_ws / delete_supabase_security_group。')
        deletion = app['detail'].get('deletion') or {}
        managed = app['detail'].get('managed_instance') or {}
        instance_id = managed.get('id')
        instance_live = await self._instance_live(instance_id) if deletion.get('instance_retained') else \
            {'exists': False if deletion.get('instance_cascade') else None,
             'note': '无实例保留记录' if not deletion.get('instance_retained') else ''}
        eip_items = []
        for row in self.ledger.rows(application_id, 'eip'):
            if row['deleted_time']:
                continue
            live = await self._eip_live(row['resource_id'])
            eip_items.append({'resource_id': row['resource_id'], 'name': row['name'],
                             'auto_created': row['auto_created'],
                             'address': row['detail'].get('address'), 'live': live,
                             'recommendation': RECOMMEND_EIP_AUTO if row['auto_created'] else RECOMMEND_EIP_REUSED,
                             'action_tool': 'delete_supabase_eip'})
        bucket_items = []
        workspace_items = []
        for row in self.ledger.rows(application_id, 'obs_bucket'):
            if row['deleted_time']:
                continue
            try:
                await self.koocli.obs('stat', args=['obs://' + row['resource_id']])
                bucket_live = True
            except McpToolError as exc:
                if not bucket_absent(exc):
                    raise
                bucket_live = False
            recommendation = RECOMMEND_BUCKET_AUTO if row['auto_created'] else RECOMMEND_BUCKET_REUSED
            if not bucket_live:
                recommendation = '桶已不存在——无需处理'
            bucket_items.append({'resource_id': row['resource_id'], 'auto_created': row['auto_created'],
                                 'live': bucket_live, 'recommendation': recommendation,
                                 'action_tool': 'delete_supabase_obs'})
            if bucket_live:
                try:
                    listing = await self.koocli.obs('ls',
                                                   args=['obs://%s/%s/' % (row['resource_id'], application_id)])
                    objects = object_rows(listing, row['resource_id'], application_id + '/')
                except McpToolError as exc:
                    objects = None
                    workspace_items.append({'bucket': row['resource_id'], 'workspace':
                                           'obs://%s/%s/' % (row['resource_id'], application_id),
                                           'objects': None, 'live': False,
                                           'error': str(exc.message)[:160]})
                    continue
                workspace_items.append({'bucket': row['resource_id'],
                                        'workspace': 'obs://%s/%s/' % (row['resource_id'], application_id),
                                        'objects': len(objects), 'live': bool(objects),
                                        'high_risk_billing_note': HIGH_RISK_STORAGE_NOTE if objects else None,
                                        'action_tool': 'clean_supabase_obs_ws'})
        group_items = []
        for row in self.ledger.rows(application_id, 'security_group'):
            if row['deleted_time']:
                continue
            role = row['detail'].get('role')
            blocked = None
            if role == 'database' and instance_live.get('exists'):
                blocked = SG_INSTANCE_RETAINED_NOTE
            group_items.append({'resource_id': row['resource_id'], 'name': row['name'],
                                'role': role, 'auto_created': row['auto_created'],
                                'blocked': blocked,
                                'recommendation': blocked or
                                                  ('建议删除（流程自动创建，避免残留）' if row['auto_created']
                                                   else '用户决策（非流程创建的安全组）'),
                                'action_tool': 'delete_supabase_security_group'})
        return {'application': {'application_id': application_id, 'name': app['name'],
                                 'deleted': app['deleted_time'] is not None, 'deletion': deletion,
                                 'managed_instance': managed, 'instance_live': instance_live},
                'eip': eip_items, 'obs_buckets': bucket_items, 'obs_workspaces': workspace_items,
                'security_groups': group_items}

    async def residuals(self, application_id):
        """READ tool: the ledger-scoped, live-verified residual inventory with
        per-category recommendations, the one-click option and the high-risk
        storage-billing reminder when the bucket is retained."""
        application_id = segment(application_id)
        inventory = await self._residual_inventory(application_id)
        categories = {name: len(items) for name, items in
                     (('eip', inventory['eip']), ('obs_buckets', inventory['obs_buckets']),
                      ('obs_workspaces', inventory['obs_workspaces']),
                      ('security_groups', inventory['security_groups'])) if items}
        return {**inventory,
                'categories': categories,
                'one_click': {'tool': 'cleanup_supabase_residuals',
                              'description': '一键清理所选类别的全部关联资源：单次确认、逐项守卫复检、'
                                             '被拦项跳过并如实报告、资源记录回写；选择否则按类别逐项使用单项工具。'},
                'notes': ['资源记录圈定范围、云端实时核对；资源记录无记录的资源不在本清单内（人工核对）。',
                          'EIP 与桶必须经用户明确确认后才删除；流程自动创建的建议删除避免残留。',
                          '保留桶时必须提醒：桶内数据持续计费，强烈建议清理应用数据目录。']}

    # ------------------------------------------------------ one-click batch ----

    async def _network(self):
        from mcp_server_supabase.service.network import Network
        return Network(koocli=self.koocli, ledger=self.ledger)

    async def _batch_item(self, kind, resource_id, verify, run, mark_id=None):
        """One batch item: guard re-check tolerated as 'blocked', cloud faults as
        'failed'; the batch keeps going and reports every outcome."""
        try:
            await verify()
            await run()
        except McpToolError as error:
            return {'resource_id': resource_id, 'outcome': _outcome(error), 'reason': str(error.message)[:200]}
        except RecoveryError:
            raise
        except BaseException as error:  # noqa: BLE001 - batch must survive item faults
            return {'resource_id': resource_id, 'outcome': 'failed', 'reason': str(error)[:200]}
        if kind is not None:
            self._mark_cleaned(kind, mark_id or resource_id)
        return {'resource_id': resource_id, 'outcome': 'deleted'}

    async def cleanup_all(self, application_id, cleanup_eip, cleanup_obs_bucket,
                          cleanup_obs_workspace, cleanup_security_groups,
                          confirm=False, plan_id=None):
        """One-click residual cleanup for one application, scoped by the resource
        ledger and re-guarded per item. The four category choices are mandatory
        booleans - all True is the full cleanup the inventory recommended."""
        application_id = segment(application_id)
        for value in (cleanup_eip, cleanup_obs_bucket, cleanup_obs_workspace, cleanup_security_groups):
            if type(value) is not bool:
                raise McpToolError('MCP_INVALID_ARGS',
                                   'cleanup_eip / cleanup_obs_bucket / cleanup_obs_workspace / cleanup_security_groups 四项均为必选布尔：True 清理该类、False 保留该类',
                                   hint='问用户要清理哪些类别；一键全清则四项全 True；部分清理使用单项工具更合适。')
        self._require_ledger()
        flags = {'eip': cleanup_eip, 'obs_bucket': cleanup_obs_bucket,
                 'obs_workspace': cleanup_obs_workspace, 'security_groups': cleanup_security_groups}
        digest = self.intent_digest('DELETE', 'cleanup/' + application_id, flags)
        inventory = await self._residual_inventory(application_id)
        if not confirm:
            warnings = []
            if cleanup_eip:
                warnings.append('EIP 删除必须经你明确确认：流程自动创建的建议删除（停止 IP 保有费，避免残留）。')
            if cleanup_obs_bucket:
                warnings.append('OBS 桶删除必须经你明确确认：流程自动创建的建议删除（停止桶存储计费，避免残留）；桶内残留对象会随桶全部销毁。')
            if cleanup_obs_workspace:
                warnings.append(HIGH_RISK_STORAGE_NOTE)
            if cleanup_security_groups:
                warnings.append('安全组清理：流程自动创建的建议删除（避免残留）；实例保留时数据库安全组不可删（自动跳过并说明）。')
            return {'status': 'confirmation_required', 'execution': 'not_executed',
                    'application_id': application_id, 'flags': flags,
                    'inventory': {'eip': inventory['eip'], 'obs_buckets': inventory['obs_buckets'],
                                  'obs_workspaces': inventory['obs_workspaces'],
                                  'security_groups': inventory['security_groups'],
                                  'instance_live': inventory['application']['instance_live']},
                    'warnings': warnings,
                    'one_click': '确认后按清单一次清理全部所选类别：逐项守卫复检，被拦项跳过并如实报告，资源记录回写。',
                    **self.plans.issue(digest)}
        self._write_gate()
        self.plans.claim(plan_id, digest)
        results = {}
        try:
            if cleanup_eip:
                results['eip'] = [await self._batch_item('eip', item['resource_id'],
                                                          lambda row=item: self._verify_eip(row['resource_id']),
                                                          lambda row=item: self._run_eip_delete(row['resource_id']))
                                  for item in inventory['eip'] if item['live'].get('exists')]
            if cleanup_obs_workspace:
                results['obs_workspace'] = []
                for item in inventory['obs_workspaces']:
                    bucket = item['bucket']
                    outcome = await self._batch_item(
                        None, application_id,   # workspace cleaning marks no ledger resource
                        lambda: self._verify_workspace(bucket, application_id),
                        lambda: self._run_workspace_delete(bucket, application_id))
                    outcome['bucket'] = bucket
                    results['obs_workspace'].append(outcome)
            if cleanup_obs_bucket:
                results['obs_bucket'] = [await self._batch_item('obs_bucket', item['resource_id'],
                                                                lambda row=item: self._verify_bucket(row['resource_id']),
                                                                lambda row=item: self._run_bucket_delete(row['resource_id']))
                                         for item in inventory['obs_buckets'] if item['live']]
            if cleanup_security_groups:
                network = await self._network()
                results['security_groups'] = []
                for item in inventory['security_groups']:
                    if item.get('blocked'):
                        results['security_groups'].append({'resource_id': item['resource_id'],
                                                            'role': item.get('role'),
                                                            'outcome': 'blocked', 'reason': item['blocked']})
                        continue
                    outcome = await self._batch_item('security_group', item['resource_id'],
                                                     lambda row=item: network.verify_group_deletable(row['resource_id']),
                                                     lambda row=item: network.delete_group_now(row['resource_id']))
                    outcome['role'] = item.get('role')
                    results['security_groups'].append(outcome)
        except BaseException:
            self.plans.finish(plan_id, 'unknown')
            raise RecoveryError('MCP_SDK_ERROR', 'Batch cleanup result unknown', 'submission_unknown',
                                'Some items may already be deleted - reconcile with show_supabase_residuals '
                                'before any retry; previews and the recorded intent are single-use.', plan_id) from None
        self.plans.finish(plan_id, 'accepted')
        items = [row for rows in results.values() for row in rows]
        problematic = [row for row in items if row.get('outcome') not in ('deleted',)]
        return {'status': 'applied' if not problematic else 'partial',
                'application_id': application_id, 'flags': flags, 'results': results,
                'plan_id': plan_id,
                'follow_up': '重跑 show_supabase_residuals 复核残留清单（资源记录已按结果回写）；'
                             '被拦与失败项按 reason 核对处置后可使用单项工具。'}
