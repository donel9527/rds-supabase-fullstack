"""Managed-instance lifecycle (stop/start/restart) and simplified detail query:
the target always resolves from the application's managed_instance binding,
with state guardrails, two-phase confirmation and job follow-up."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service import instance_lifecycle
from mcp_server_supabase.service.operations import Operations
from mcp_server_supabase.service.plans import PlanStore

APP_ID = 'ad9079c304464c33a4f2fd516d4a3b16in32'
INSTANCE_ID = 'ee36e15f94ed4432adb3ada163620d82in03'
READ_PATH = '/v3/{project}/ai-application/' + APP_ID + '/supabase'
SIMPLIFIED_PATH = '/v3/{project}/simplified-instances'
INSTANCE_BASE = '/v3/{project}/instances/' + INSTANCE_ID
ACTION_SUFFIXES = {'stop': '/action/shutdown', 'start': '/action/startup', 'restart': '/action'}
ACTION_BODIES = {'stop': {}, 'start': {}, 'restart': {'restart': {}}}


def detail(**overrides):
    record = {'id': APP_ID, 'name': 'rds-supabase-liujian-web', 'status': 'normal',
              'current_actions': [], 'port': 8443, 'enable_ssl': False,
              'private_ip': '192.168.0.112', 'created_time': 1794025857392,
              'managed_instance': {'id': INSTANCE_ID, 'name': 'pg-managed'}}
    record.update(overrides)
    return record


def instance_row(**overrides):
    row = {'id': INSTANCE_ID, 'name': 'pg-managed', 'engine_name': 'PostgreSQL',
           'engine_version': '17.2', 'instance_status': 'normal', 'frozen': False,
           'type': 'Single', 'pay_model': '0', 'spec_code': 'rds.pg.pg17.xlarge.2.ha',
           'availability_zone_ids': ['cn-north-4a'], 'read_only_instances': [],
           'current_actions': [], 'volume_type': 'ULTRAHIGH', 'volume_size': 40,
           'enterprise_project_id': '0', 'secret_marker': 'must-not-leak'}
    row.update(overrides)
    return row


class InstanceLifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'SUPABASE_ENABLE_WRITES': 'true',
                                           'HUAWEICLOUD_MCP_READ_ONLY': 'false'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.client = AsyncMock()
        self.client.endpoint = 'https://example.invalid'
        self.client.project = 'project'; self.client.token = 'fixture'
        self.ops = Operations(self.client, PlanStore(Path(self.tmp.name) / 'state.db'))


class ManagedInstanceResolutionTests(InstanceLifecycleTestCase):
    async def test_invalid_action_rejected_before_any_call(self):
        for action in ('bounce', 'pause', None, 'STOP'):
            with self.subTest(action=action):
                with self.assertRaises(McpToolError) as ctx:
                    await instance_lifecycle.lifecycle(self.ops, APP_ID, action)
                self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.client.request.assert_not_awaited()

    async def test_unknown_application_fails_closed(self):
        for action in ('stop', 'start', 'restart'):
            with self.subTest(action=action):
                self.client.request.side_effect = [(200, {'id': 'someone-else', 'status': 'normal'})]
                with self.assertRaises(McpToolError) as ctx:
                    await instance_lifecycle.lifecycle(self.ops, APP_ID, action)
                self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')
        self.client.request.side_effect = [(200, {'id': 'someone-else', 'status': 'normal'})]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.show(self.ops, APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')

    async def test_application_without_managed_instance_is_blocked(self):
        for managed in (None, {}, {'name': 'pg-without-id'}):
            with self.subTest(managed=managed):
                self.client.request.side_effect = [(200, detail(managed_instance=managed))]
                with self.assertRaises(McpToolError) as ctx:
                    await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
                self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
                self.assertIn('托管实例', ctx.exception.hint)
                self.assertIn('独立数据库实例', ctx.exception.hint)
        self.client.request.side_effect = [(200, detail(managed_instance=None))]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.show(self.ops, APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_vanished_instance_fails_closed(self):
        for action in ('stop', 'start', 'restart'):
            with self.subTest(action=action):
                self.client.request.side_effect = [(200, detail()), (200, {'instances': []})]
                with self.assertRaises(McpToolError) as ctx:
                    await instance_lifecycle.lifecycle(self.ops, APP_ID, action)
                self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')
        self.client.request.side_effect = [(200, detail()), (200, {'instances': []})]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.show(self.ops, APP_ID)
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')

    async def test_instance_identity_mismatch_fails_closed(self):
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row(id='other-instance-in03')]})]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')


class ManagedInstanceShowTests(InstanceLifecycleTestCase):
    async def test_show_whitelists_fields_and_maps_status(self):
        for status, note in (('normal', '正常'), ('shutdown', '已停止（关机）'),
                             ('abnormal', '异常'), ('creating', '创建中'),
                             ('createfail', '创建失败'), ('data_disk_full', '磁盘满'),
                             ('deleted', '已删除')):
            with self.subTest(status=status):
                self.client.request.side_effect = [
                    (200, detail(status='shutdown' if status == 'shutdown' else 'normal')),
                    (200, {'instances': [instance_row(instance_status=status)]}),
                ]
                result = await instance_lifecycle.show(self.ops, APP_ID)
                self.assertEqual(result['application_id'], APP_ID)
                self.assertEqual(result['application_status'], 'shutdown' if status == 'shutdown' else 'normal')
                self.assertEqual(result['status_note'], note)
                self.assertEqual(set(result['instance']), set(instance_lifecycle._SIMPLIFIED_FIELDS))
                self.assertEqual(result['instance']['id'], INSTANCE_ID)
                self.assertEqual(result['instance']['instance_status'], status)
                self.assertNotIn('secret_marker', result['instance'])
                self.assertIn('十五天', result['note'])
                self.assertIn('托管数据库实例', result['note'])
                calls = self.client.request.call_args_list
                self.assertEqual(calls[0].args, ('GET', READ_PATH))
                self.assertEqual(calls[1].args, ('POST', SIMPLIFIED_PATH))
                self.assertEqual(calls[1].kwargs.get('body'), {'instance_ids': [INSTANCE_ID]})

    async def test_unknown_status_note_degrades(self):
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row(instance_status='weird')]})]
        result = await instance_lifecycle.show(self.ops, APP_ID)
        self.assertEqual(result['status_note'], '未知状态')

    async def test_show_tool_registers_and_attaches_visual(self):
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
        for name in ('show_supabase_managed_instance', 'stop_supabase_managed_instance',
                     'start_supabase_managed_instance', 'restart_supabase_managed_instance'):
            self.assertIn(name, server.functions)
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row()]})]
        result = await server.functions['show_supabase_managed_instance'](APP_ID)
        self.assertIn('托管实例详情', result['visual'])
        self.assertIn(INSTANCE_ID, result['visual'])
        self.assertIn('pg-managed', result['visual'])
        self.assertIn('PostgreSQL 17.2', result['visual'])
        self.assertIn('正常', result['visual'])
        self.assertIn('ULTRAHIGH 40GB', result['visual'])
        self.assertIn('cn-north-4a', result['visual'])
        self.assertIn('实例 ID', result['visual'])
        self.assertIn('进行中动作', result['visual'])


class ManagedInstanceGuardrailTests(InstanceLifecycleTestCase):
    async def test_stop_guardrail_matrix(self):
        cases = [('normal', [], True), ('shutdown', [], False),
                 ('normal', [{'action': 'resize'}], False),
                 ('abnormal', [], False), ('creating', [], False), ('createfail', [], False)]
        for status, actions, allowed in cases:
            with self.subTest(status=status, actions=actions):
                self.client.request.side_effect = [
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status, current_actions=actions)]}),
                ]
                if allowed:
                    preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
                    self.assertEqual(preview['status'], 'confirmation_required')
                else:
                    with self.assertRaises(McpToolError) as ctx:
                        await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
                    self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_start_guardrail_matrix(self):
        cases = [('shutdown', False, True), ('normal', False, False),
                 ('shutdown', True, False), ('normal', True, False),
                 ('abnormal', False, False), ('creating', False, False)]
        for status, frozen, allowed in cases:
            with self.subTest(status=status, frozen=frozen):
                self.client.request.side_effect = [
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status, frozen=frozen)]}),
                ]
                if allowed:
                    preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'start')
                    self.assertEqual(preview['status'], 'confirmation_required')
                else:
                    with self.assertRaises(McpToolError) as ctx:
                        await instance_lifecycle.lifecycle(self.ops, APP_ID, 'start')
                    self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_restart_guardrail_matrix(self):
        cases = [('normal', [], False, True), ('shutdown', [], False, False),
                 ('normal', [], True, False), ('shutdown', [], True, False),
                 ('normal', [{'action': 'backup'}], False, False),
                 ('abnormal', [], False, False), ('data_disk_full', [], False, False)]
        for status, actions, frozen, allowed in cases:
            with self.subTest(status=status, actions=actions, frozen=frozen):
                self.client.request.side_effect = [
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status, current_actions=actions, frozen=frozen)]}),
                ]
                if allowed:
                    preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'restart')
                    self.assertEqual(preview['status'], 'confirmation_required')
                else:
                    with self.assertRaises(McpToolError) as ctx:
                        await instance_lifecycle.lifecycle(self.ops, APP_ID, 'restart')
                    self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')
                    if status == 'shutdown' and not frozen:
                        self.assertIn('先启动', ctx.exception.hint)

    async def test_stop_on_shutdown_hints_start_tool(self):
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row(instance_status='shutdown')]})]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        self.assertIn('start_supabase_managed_instance', ctx.exception.hint)

    async def test_busy_instance_message_mentions_follow_up(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, {'instances': [instance_row(current_actions=[{'action': 'resize'}])]})]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        self.assertIn('show_operation_job_status', ctx.exception.hint)


class ManagedInstanceExecutionTests(InstanceLifecycleTestCase):
    async def test_preview_returns_status_impact_and_plan(self):
        for action, status in (('stop', 'normal'), ('start', 'shutdown'), ('restart', 'normal')):
            with self.subTest(action=action):
                self.client.request.reset_mock()
                self.client.request.side_effect = [
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status)]}),
                ]
                preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, action)
                self.assertEqual(preview['status'], 'confirmation_required')
                self.assertEqual(preview['execution'], 'not_executed')
                self.assertEqual(preview['application_id'], APP_ID)
                self.assertEqual(preview['instance_id'], INSTANCE_ID)
                self.assertEqual(preview['instance_status'], status)
                self.assertTrue(preview['impact'])
                self.assertTrue(preview['plan_id'])
                self.assertNotIn('job_follow_up', preview)
                self.assertEqual(preview['resource_path'], INSTANCE_BASE + ACTION_SUFFIXES[action])
                self.assertEqual(self.client.request.await_count, 2)
                self.assertEqual(self.client.request.call_args_list[0].args, ('GET', READ_PATH))
                self.assertEqual(self.client.request.call_args_list[1].args, ('POST', SIMPLIFIED_PATH))

    async def test_confirm_posts_native_instance_paths(self):
        for action, status in (('stop', 'normal'), ('start', 'shutdown'), ('restart', 'normal')):
            with self.subTest(action=action):
                self.client.request.reset_mock()
                self.client.request.side_effect = [
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status)]}),
                    (200, detail()),
                    (200, {'instances': [instance_row(instance_status=status)]}),
                    (200, {'job_id': 'job-' + action}),
                ]
                preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, action)
                result = await instance_lifecycle.lifecycle(self.ops, APP_ID, action, True, preview['plan_id'])
                self.assertEqual(result['status'], 'accepted')
                self.assertFalse(result['complete'])
                self.assertEqual(result['job_id'], 'job-' + action)
                self.assertEqual(result['application_id'], APP_ID)
                self.assertEqual(result['instance_id'], INSTANCE_ID)
                self.assertEqual(result['action'], action)
                self.assertTrue(result['notices']['warnings'])
                self.assertIn('show_operation_job_status', result['job_follow_up'])
                self.assertIn('wait_operation_job_complete', result['job_follow_up'])
                self.assertEqual(result['plan_id'], preview['plan_id'])
                calls = self.client.request.call_args_list
                self.assertEqual([c.args[0] for c in calls], ['GET', 'POST', 'GET', 'POST', 'POST'])
                self.assertEqual(calls[0].args, ('GET', READ_PATH))
                self.assertEqual(calls[1].args, ('POST', SIMPLIFIED_PATH))
                self.assertEqual(calls[2].args, ('GET', READ_PATH))
                self.assertEqual(calls[3].args, ('POST', SIMPLIFIED_PATH))
                self.assertEqual(calls[4].args, ('POST', INSTANCE_BASE + ACTION_SUFFIXES[action]))
                self.assertEqual(calls[4].kwargs.get('body'), ACTION_BODIES[action])
                self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'accepted')
                self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['job_id'], 'job-' + action)

    async def test_stop_impact_carries_billing_and_auto_start_constraints(self):
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row()]})]
        preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        joined = ''.join(preview['impact'])
        self.assertIn('EIP、存储、备份', joined)
        self.assertIn('十五天', joined)
        self.assertIn('回收站', joined)
        self.assertIn('按需', joined)

    async def test_accepts_both_200_and_202_with_valid_job_id(self):
        for http_status in (200, 202):
            with self.subTest(http_status=http_status):
                client = AsyncMock()
                client.endpoint = 'https://example.invalid'
                client.project = 'project'; client.token = 'fixture'
                ops = Operations(client, PlanStore(Path(self.tmp.name) / ('jobs-%d.db' % http_status)))
                client.request.side_effect = [
                    (200, detail()), (200, {'instances': [instance_row()]}),
                    (200, detail()), (200, {'instances': [instance_row()]}),
                    (http_status, {'job_id': 'job-%d' % http_status}),
                ]
                preview = await instance_lifecycle.lifecycle(ops, APP_ID, 'stop')
                result = await instance_lifecycle.lifecycle(ops, APP_ID, 'stop', True, preview['plan_id'])
                self.assertEqual(result['job_id'], 'job-%d' % http_status)
                self.assertEqual(ops.plans.inspect(preview['plan_id'])['state'], 'accepted')

    async def test_write_gate_blocks_before_any_call(self):
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row()]})]
        preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        self.client.request.reset_mock()
        for environ in ({'HUAWEICLOUD_MCP_READ_ONLY': 'true'}, {'SUPABASE_ENABLE_WRITES': 'false'}):
            with self.subTest(environ=environ):
                with patch.dict(os.environ, environ):
                    with self.assertRaises(McpToolError) as ctx:
                        await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop', True, preview['plan_id'])
                self.assertEqual(ctx.exception.code, 'MCP_READ_ONLY')
        self.client.request.assert_not_awaited()

    async def test_definite_rejection_marks_plan_failed(self):
        self.client.request.side_effect = [
            (200, detail()), (200, {'instances': [instance_row()]}),
            (200, detail()), (200, {'instances': [instance_row()]}),
            RecoveryError('MCP_INVALID_ARGS', 'rejected', 'invalid_request', 'fix it'),
        ]
        preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'restart')
        with self.assertRaises(McpToolError):
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'restart', True, preview['plan_id'])
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'failed')

    async def test_transport_failure_marks_unknown_and_never_replays(self):
        self.client.request.side_effect = [
            (200, detail()), (200, {'instances': [instance_row()]}),
            (200, detail()), (200, {'instances': [instance_row()]}),
            RecoveryError('MCP_SDK_ERROR', 'boom', 'service_unavailable', 'retry later'),
        ]
        preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop', True, preview['plan_id'])
        self.assertEqual(ctx.exception.recovery['category'], 'submission_unknown')
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'unknown')
        self.client.request.side_effect = [(200, detail()), (200, {'instances': [instance_row()]})]
        with self.assertRaises(McpToolError) as ctx:
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop', True, preview['plan_id'])
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_response_without_job_marks_unknown(self):
        self.client.request.side_effect = [
            (200, detail()), (200, {'instances': [instance_row()]}),
            (200, detail()), (200, {'instances': [instance_row()]}),
            (200, {}),
        ]
        preview = await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop')
        with self.assertRaises(McpToolError):
            await instance_lifecycle.lifecycle(self.ops, APP_ID, 'stop', True, preview['plan_id'])
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'unknown')


class PlanningCapabilitiesTests(unittest.TestCase):
    def test_implemented_operations_cover_instance_lifecycle(self):
        from mcp_server_supabase.service.planning import PlanningService
        operations = PlanningService().capabilities()['implemented_operations']
        self.assertIn('application lifecycle (start/stop/restart)', operations)
        self.assertIn('managed-instance lifecycle (stop/start/restart) and simplified detail query', operations)
        self.assertEqual(len(PlanningService().capabilities()['scenarios']), 6)


if __name__ == '__main__':
    unittest.main()
