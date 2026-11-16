"""Security-group set (SetSecurityGroup, full replacement) across three target
modes: the application itself, the managed instance resolved live from the
binding, and an attachable PG instance (pre-creation preparation), with
parameter cross-validation, state guardrails, two-phase confirmation and
workflowId-based job follow-up."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service import security_group_set
from mcp_server_supabase.service.operations import Operations
from mcp_server_supabase.service.plans import PlanStore

APP_ID = 'ad9079c304464c33a4f2fd516d4a3b16in32'
INSTANCE_ID = 'ee36e15f94ed4432adb3ada163620d82in01'
ATTACH_ID = 'bb45c2d7a10f4f7f9f21e5e6f1a5b7c9in01'
READ_PATH = '/v3/{project}/ai-application/' + APP_ID + '/supabase'
MANAGEABLE_PATH = '/v3/{project}/ai-application/manageable-instances'
SIMPLIFIED_PATH = '/v3/{project}/simplified-instances'
SET_PATH = '/v3/{project}/instances/%s/security-group'
GROUPS = ['8530e414-b559-4c20-9b71-3ebc6e572f3a', '9a2b7c1d-5678-4d01-9abc-52fa57c7cdef']
UPPER_GROUP = '8530E414-B559-4C20-9B71-3EBC6E572F3A'
GROUPS_BODY = {'security_group_id': ','.join(GROUPS)}


def detail(**overrides):
    record = {'id': APP_ID, 'name': 'rds-supabase-liujian-web', 'status': 'normal',
              'current_actions': [], 'port': 8443, 'enable_ssl': False,
              'private_ip': '192.168.0.112', 'created_time': 1794025857392,
              'security_group_id': 'current-app-group-uuid',
              'managed_instance': {'id': INSTANCE_ID, 'name': 'pg-managed',
                                   'security_group_id': 'current-managed-group-uuid'}}
    record.update(overrides)
    return record


def instance_row(instance_id=INSTANCE_ID, **overrides):
    row = {'id': instance_id, 'name': 'pg-managed', 'engine_name': 'PostgreSQL',
           'instance_status': 'normal', 'frozen': False, 'current_actions': []}
    row.update(overrides)
    return row


def manageable_payload(instance_id=ATTACH_ID):
    return {'instances': [{'id': instance_id, 'name': 'pg-attach', 'status': 'ACTIVE',
                           'security_group_id': 'current-attach-group-uuid'}]}


class SecurityGroupSetTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'SUPABASE_ENABLE_WRITES': 'true',
                                           'HUAWEICLOUD_MCP_READ_ONLY': 'false'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.client = AsyncMock()
        self.client.endpoint = 'https://example.invalid'
        self.client.project = 'project'; self.client.token = 'fixture'
        self.ops = Operations(self.client, PlanStore(Path(self.tmp.name) / 'state.db'))


class ArgumentCrossValidationTests(SecurityGroupSetTestCase):
    async def test_invalid_target_rejected_before_any_call(self):
        for target in ('app', 'instance', None, 'APPLICATION'):
            with self.subTest(target=target):
                with self.assertRaises(McpToolError) as ctx:
                    await security_group_set.change(self.ops, target, GROUPS, application_id=APP_ID)
                self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.client.request.assert_not_awaited()

    async def test_application_mode_requires_application_id(self):
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'application', GROUPS)
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertIn('application_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_application_mode_rejects_instance_id(self):
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'application', GROUPS,
                                            application_id=APP_ID, instance_id=ATTACH_ID)
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertIn('instance_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_managed_mode_requires_application_id(self):
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'managed_instance', GROUPS)
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertIn('application_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_managed_mode_rejects_instance_id(self):
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                            application_id=APP_ID, instance_id=ATTACH_ID)
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertIn('instance_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_attachable_mode_requires_instance_id(self):
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'attachable_instance', GROUPS)
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertIn('instance_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_attachable_mode_rejects_application_id(self):
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                            application_id=APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertIn('application_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_both_ids_rejected_for_every_mode(self):
        for target in ('application', 'managed_instance', 'attachable_instance'):
            with self.subTest(target=target):
                with self.assertRaises(McpToolError) as ctx:
                    await security_group_set.change(self.ops, target, GROUPS,
                                                    application_id=APP_ID, instance_id=ATTACH_ID)
                self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
                self.assertIn('application_id', ctx.exception.message)
                self.assertIn('instance_id', ctx.exception.message)
        self.client.request.assert_not_awaited()

    async def test_group_ids_must_be_non_empty_uuids(self):
        cases = ([], 'not-a-list', [''], [GROUPS[0], 'not-a-uuid'],
                 ['8530e414-b559-4c20-9b71-3ebc6e572f3'], [None, GROUPS[0]])
        for groups in cases:
            with self.subTest(groups=groups):
                with self.assertRaises(McpToolError) as ctx:
                    await security_group_set.change(self.ops, 'application', groups,
                                                    application_id=APP_ID)
                self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.client.request.assert_not_awaited()

    async def test_multiple_and_uppercase_uuid_groups_accepted(self):
        self.client.request.side_effect = [(200, detail())]
        preview = await security_group_set.change(self.ops, 'application', GROUPS + [UPPER_GROUP],
                                                  application_id=APP_ID)
        self.assertEqual(preview['security_group_ids'], GROUPS + [UPPER_GROUP])

    async def test_tool_registers_with_dangerous_contract(self):
        from mcp_server_supabase.tools import operations as tools_operations

        class RecordingServer:
            def __init__(self): self.functions = {}
            def tool(self):
                def decorate(func):
                    self.functions[func.__name__] = func
                    return func
                return decorate

        server = RecordingServer()
        with patch.object(tools_operations, 'Operations', lambda **kwargs: self.ops):
            tools_operations.register(server)
        self.assertIn('change_supabase_security_group', server.functions)
        self.client.request.side_effect = [(200, detail())]
        preview = await server.functions['change_supabase_security_group'](
            'application', GROUPS, application_id=APP_ID)
        self.assertEqual(preview['status'], 'confirmation_required')


class ApplicationTargetTests(SecurityGroupSetTestCase):
    async def test_unknown_application_fails_closed(self):
        self.client.request.side_effect = [(200, {'id': 'someone-else', 'status': 'normal'})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'application', GROUPS, application_id=APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')

    async def test_not_normal_application_blocked(self):
        for status in ('shutdown', 'abnormal', 'creating'):
            with self.subTest(status=status):
                self.client.request.side_effect = [(200, detail(status=status))]
                with self.assertRaises(McpToolError) as ctx:
                    await security_group_set.change(self.ops, 'application', GROUPS,
                                                    application_id=APP_ID)
                self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_busy_application_blocked(self):
        self.client.request.side_effect = [(200, detail(current_actions=[{'action': 'resize'}]))]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'application', GROUPS, application_id=APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
        self.assertIn('show_operation_job_status', ctx.exception.hint)

    async def test_preview_contract_for_application(self):
        self.client.request.side_effect = [(200, detail())]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        self.assertEqual(preview['status'], 'confirmation_required')
        self.assertEqual(preview['execution'], 'not_executed')
        self.assertEqual(preview['target'], 'application')
        self.assertEqual(preview['target_id'], APP_ID)
        self.assertEqual(preview['current_security_group_id'], 'current-app-group-uuid')
        self.assertEqual(preview['security_group_ids'], GROUPS)
        self.assertNotIn('current_security_group_note', preview)
        self.assertTrue(preview['plan_id'])
        self.assertNotIn('job_follow_up', preview)
        self.assertEqual(preview['resource_path'], SET_PATH % APP_ID)
        joined = ''.join(preview['impact'])
        self.assertIn('整体替换', joined)
        self.assertIn('8443/5432', joined)
        self.assertIn('创建、数据库升级、变更规格、创建用户、删除用户', joined)
        self.assertIn('短暂中断', joined)
        self.assertIn('失联', joined)
        self.assertEqual(self.client.request.await_count, 1)
        self.assertEqual(self.client.request.call_args_list[0].args, ('GET', READ_PATH))

    async def test_unknown_current_group_degrades_with_note(self):
        record = detail(); record.pop('security_group_id')
        self.client.request.side_effect = [(200, record)]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        self.assertIsNone(preview['current_security_group_id'])
        self.assertIn('未知', preview['current_security_group_note'])

    async def test_confirm_puts_application_path_with_comma_joined_body(self):
        self.client.request.side_effect = [(200, detail()), (200, detail()),
                                           (200, {'workflowId': 'wf-application'})]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        result = await security_group_set.change(self.ops, 'application', GROUPS,
                                                 application_id=APP_ID, confirm=True,
                                                 plan_id=preview['plan_id'])
        self.assertEqual(result['status'], 'accepted')
        self.assertFalse(result['complete'])
        self.assertEqual(result['job_id'], 'wf-application')
        self.assertEqual(result['job_id_source'], 'workflowId')
        self.assertEqual(result['target'], 'application')
        self.assertEqual(result['target_id'], APP_ID)
        self.assertEqual(result['security_group_ids'], GROUPS)
        self.assertIn('show_operation_job_status', result['job_follow_up'])
        self.assertIn('整体替换', ''.join(result['notices']['warnings']))
        self.assertEqual(result['plan_id'], preview['plan_id'])
        calls = self.client.request.call_args_list
        self.assertEqual([c.args[0] for c in calls], ['GET', 'GET', 'PUT'])
        self.assertEqual(calls[2].args, ('PUT', SET_PATH % APP_ID))
        self.assertEqual(calls[2].kwargs.get('body'), GROUPS_BODY)
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'accepted')
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['job_id'], 'wf-application')


class ManagedInstanceTargetTests(SecurityGroupSetTestCase):
    async def test_without_managed_instance_blocked(self):
        for managed in (None, {}, {'name': 'pg-without-id'}):
            with self.subTest(managed=managed):
                self.client.request.side_effect = [(200, detail(managed_instance=managed))]
                with self.assertRaises(McpToolError) as ctx:
                    await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                                    application_id=APP_ID)
                self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
                self.assertIn('托管实例', ctx.exception.hint)

    async def test_instance_not_normal_blocked(self):
        for status in ('creating', 'shutdown', 'abnormal'):
            with self.subTest(status=status):
                self.client.request.side_effect = [
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status)]})]
                with self.assertRaises(McpToolError) as ctx:
                    await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                                    application_id=APP_ID)
                self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
                self.assertIn('创建、数据库升级、变更规格、创建用户、删除用户', ctx.exception.message)

    async def test_busy_instance_blocked(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, {'instances': [instance_row(current_actions=[{'action': 'resize'}])]})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                            application_id=APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
        self.assertIn('show_operation_job_status', ctx.exception.hint)

    async def test_vanished_instance_fails_closed(self):
        self.client.request.side_effect = [(200, detail()), (200, {'instances': []})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                            application_id=APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')

    async def test_preview_resolves_managed_instance(self):
        self.client.request.side_effect = [(200, detail()),
                                           (200, {'instances': [instance_row()]})]
        preview = await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                                  application_id=APP_ID)
        self.assertEqual(preview['status'], 'confirmation_required')
        self.assertEqual(preview['target'], 'managed_instance')
        self.assertEqual(preview['target_id'], INSTANCE_ID)
        self.assertEqual(preview['current_security_group_id'], 'current-managed-group-uuid')
        self.assertEqual(preview['resource_path'], SET_PATH % INSTANCE_ID)
        calls = self.client.request.call_args_list
        self.assertEqual(calls[0].args, ('GET', READ_PATH))
        self.assertEqual(calls[1].args, ('POST', SIMPLIFIED_PATH))
        self.assertEqual(calls[1].kwargs.get('body'), {'instance_ids': [INSTANCE_ID]})

    async def test_confirm_puts_resolved_instance_path(self):
        self.client.request.side_effect = [
            (200, detail()), (200, {'instances': [instance_row()]}),
            (200, detail()), (200, {'instances': [instance_row()]}),
            (200, {'workflowId': 'wf-managed'})]
        preview = await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                                  application_id=APP_ID)
        result = await security_group_set.change(self.ops, 'managed_instance', GROUPS,
                                                 application_id=APP_ID, confirm=True,
                                                 plan_id=preview['plan_id'])
        self.assertEqual(result['job_id'], 'wf-managed')
        self.assertEqual(result['target_id'], INSTANCE_ID)
        calls = self.client.request.call_args_list
        self.assertEqual([c.args[0] for c in calls], ['GET', 'POST', 'GET', 'POST', 'PUT'])
        self.assertEqual(calls[4].args, ('PUT', SET_PATH % INSTANCE_ID))
        self.assertEqual(calls[4].kwargs.get('body'), GROUPS_BODY)
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'accepted')


class AttachableInstanceTargetTests(SecurityGroupSetTestCase):
    async def test_not_in_candidate_list_blocked(self):
        self.client.request.side_effect = [(200, manageable_payload())]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                            instance_id=INSTANCE_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
        self.assertIn('可挂载', ctx.exception.hint)
        self.assertEqual(self.client.request.await_count, 1)

    async def test_in_list_but_not_normal_blocked(self):
        self.client.request.side_effect = [
            (200, manageable_payload()),
            (200, {'instances': [instance_row(ATTACH_ID, instance_status='creating')]})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                            instance_id=ATTACH_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_in_list_but_busy_blocked(self):
        self.client.request.side_effect = [
            (200, manageable_payload()),
            (200, {'instances': [instance_row(ATTACH_ID, current_actions=[{'action': 'resize'}])]})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                            instance_id=ATTACH_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_empty_candidate_list_blocks(self):
        self.client.request.side_effect = [(200, {'total_count': 0})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                            instance_id=ATTACH_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_preview_and_confirm_use_candidate_and_probe(self):
        self.client.request.side_effect = [
            (200, manageable_payload()),
            (200, {'instances': [instance_row(ATTACH_ID)]})]
        preview = await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                                  instance_id=ATTACH_ID)
        self.assertEqual(preview['status'], 'confirmation_required')
        self.assertEqual(preview['target'], 'attachable_instance')
        self.assertEqual(preview['target_id'], ATTACH_ID)
        self.assertEqual(preview['current_security_group_id'], 'current-attach-group-uuid')
        self.assertEqual(preview['resource_path'], SET_PATH % ATTACH_ID)
        calls = self.client.request.call_args_list
        self.assertEqual(calls[0].args, ('GET', MANAGEABLE_PATH))
        self.assertEqual(calls[0].kwargs.get('query'), {'application_type': 'supabase'})
        self.assertEqual(calls[1].args, ('POST', SIMPLIFIED_PATH))
        self.assertEqual(calls[1].kwargs.get('body'), {'instance_ids': [ATTACH_ID]})
        self.client.request.side_effect = [
            (200, manageable_payload()),
            (200, {'instances': [instance_row(ATTACH_ID)]}),
            (200, {'workflowId': 'wf-attach'})]
        result = await security_group_set.change(self.ops, 'attachable_instance', GROUPS,
                                                 instance_id=ATTACH_ID, confirm=True,
                                                 plan_id=preview['plan_id'])
        self.assertEqual(result['job_id'], 'wf-attach')
        self.assertEqual(result['target_id'], ATTACH_ID)
        self.assertEqual(self.client.request.call_args_list[-1].args, ('PUT', SET_PATH % ATTACH_ID))
        self.assertEqual(self.client.request.call_args_list[-1].kwargs.get('body'), GROUPS_BODY)
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'accepted')


class AcceptanceAndFailureTests(SecurityGroupSetTestCase):
    async def test_accepts_both_200_and_202_with_workflow_id(self):
        for http_status in (200, 202):
            with self.subTest(http_status=http_status):
                client = AsyncMock()
                client.endpoint = 'https://example.invalid'
                client.project = 'project'; client.token = 'fixture'
                ops = Operations(client, PlanStore(Path(self.tmp.name) / ('jobs-%d.db' % http_status)))
                client.request.side_effect = [
                    (200, detail()), (200, detail()),
                    (http_status, {'workflowId': 'wf-%d' % http_status})]
                preview = await security_group_set.change(ops, 'application', GROUPS,
                                                         application_id=APP_ID)
                result = await security_group_set.change(ops, 'application', GROUPS,
                                                         application_id=APP_ID, confirm=True,
                                                         plan_id=preview['plan_id'])
                self.assertEqual(result['job_id'], 'wf-%d' % http_status)
                self.assertEqual(result['job_id_source'], 'workflowId')
                self.assertEqual(ops.plans.inspect(preview['plan_id'])['state'], 'accepted')

    async def test_falls_back_to_job_id_key(self):
        self.client.request.side_effect = [(200, detail()), (200, detail()),
                                           (200, {'job_id': 'job-plain'})]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        result = await security_group_set.change(self.ops, 'application', GROUPS,
                                                 application_id=APP_ID, confirm=True,
                                                 plan_id=preview['plan_id'])
        self.assertEqual(result['job_id'], 'job-plain')
        self.assertEqual(result['job_id_source'], 'job_id')

    async def test_response_without_job_marks_unknown(self):
        self.client.request.side_effect = [(200, detail()), (200, detail()), (200, {})]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        with self.assertRaises(McpToolError):
            await security_group_set.change(self.ops, 'application', GROUPS,
                                            application_id=APP_ID, confirm=True,
                                            plan_id=preview['plan_id'])
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'unknown')

    async def test_write_gate_blocks_before_any_call(self):
        self.client.request.side_effect = [(200, detail())]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        self.client.request.reset_mock()
        for environ in ({'HUAWEICLOUD_MCP_READ_ONLY': 'true'}, {'SUPABASE_ENABLE_WRITES': 'false'}):
            with self.subTest(environ=environ):
                with patch.dict(os.environ, environ):
                    with self.assertRaises(McpToolError) as ctx:
                        await security_group_set.change(self.ops, 'application', GROUPS,
                                                        application_id=APP_ID, confirm=True,
                                                        plan_id=preview['plan_id'])
                self.assertEqual(ctx.exception.code, 'MCP_READ_ONLY')
        self.client.request.assert_not_awaited()

    async def test_definite_rejection_marks_plan_failed(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, detail()),
            RecoveryError('MCP_INVALID_ARGS', 'rejected', 'invalid_request', 'fix it')]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        with self.assertRaises(McpToolError):
            await security_group_set.change(self.ops, 'application', GROUPS,
                                            application_id=APP_ID, confirm=True,
                                            plan_id=preview['plan_id'])
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'failed')

    async def test_transport_failure_marks_unknown_and_never_replays(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, detail()),
            RecoveryError('MCP_SDK_ERROR', 'boom', 'service_unavailable', 'retry later')]
        preview = await security_group_set.change(self.ops, 'application', GROUPS,
                                                  application_id=APP_ID)
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'application', GROUPS,
                                            application_id=APP_ID, confirm=True,
                                            plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.recovery['category'], 'submission_unknown')
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'unknown')
        self.client.request.side_effect = [(200, detail()), (200, detail()),
                                           (200, {'workflowId': 'wf-late'})]
        with self.assertRaises(McpToolError) as ctx:
            await security_group_set.change(self.ops, 'application', GROUPS,
                                            application_id=APP_ID, confirm=True,
                                            plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')


class PlanningCapabilitiesTests(unittest.TestCase):
    def test_implemented_operations_cover_security_group_set(self):
        from mcp_server_supabase.service.planning import PlanningService
        operations = PlanningService().capabilities()['implemented_operations']
        self.assertIn('security-group set for application/managed/attachable instance', operations)
        self.assertEqual(len(PlanningService().capabilities()['scenarios']), 6)


if __name__ == '__main__':
    unittest.main()
