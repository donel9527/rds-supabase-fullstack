"""Application lifecycle (start/stop/restart): dedicated paths without the
/supabase segment, state guardrails, two-phase confirmation, job follow-up."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.operations import Operations
from mcp_server_supabase.service.plans import PlanStore

APP_ID = 'ad9079c304464c33a4f2fd516d4a3b16in32'
INSTANCE_ID = 'ee36e15f94ed4432adb3ada163620d82in03'
APP_PATH = '/v3/{project}/ai-application/' + APP_ID
READ_PATH = APP_PATH + '/supabase'


def detail(**overrides):
    record = {'id': APP_ID, 'name': 'rds-supabase-liujian-web', 'status': 'normal',
              'current_actions': [], 'port': 8443, 'enable_ssl': False,
              'private_ip': '192.168.0.112', 'created_time': 1794025857392}
    record.update(overrides)
    return record


class LifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'SUPABASE_ENABLE_WRITES': 'true',
                                           'HUAWEICLOUD_MCP_READ_ONLY': 'false'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.client = AsyncMock()
        self.client.endpoint = 'https://example.invalid'
        self.client.project = 'project'; self.client.token = 'fixture'
        self.ops = Operations(self.client, PlanStore(Path(self.tmp.name) / 'state.db'))


class LifecycleGuardrailTests(LifecycleTestCase):
    async def test_invalid_action_and_identifier_rejected_before_any_call(self):
        for application_id, action in ((APP_ID, 'bounce'), ('../bad', 'start'), (APP_ID, 'pause')):
            with self.subTest(action=action):
                with self.assertRaises(McpToolError) as ctx:
                    await self.ops.lifecycle(application_id, action)
                self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.client.request.assert_not_awaited()

    async def test_preview_reads_state_and_returns_plan_and_impact(self):
        for action, status in (('stop', 'normal'), ('restart', 'normal'), ('start', 'shutdown')):
            with self.subTest(action=action):
                self.client.request.reset_mock()
                self.client.request.side_effect = [(200, detail(status=status))]
                preview = await self.ops.lifecycle(APP_ID, action)
                self.assertEqual(preview['status'], 'confirmation_required')
                self.assertEqual(preview['execution'], 'not_executed')
                self.assertEqual(preview['application_id'], APP_ID)
                self.assertEqual(preview['action'], action)
                self.assertEqual(preview['current_status'], status)
                self.assertTrue(preview['impact'])
                self.assertTrue(preview['plan_id'])
                self.assertEqual(preview['resource_path'], APP_PATH + '/' + action)
                self.assertNotIn('job_follow_up', preview)
                self.assertEqual(self.client.request.call_args.args, ('GET', READ_PATH))
                self.assertEqual(self.client.request.await_count, 1)

    async def test_stop_and_restart_blocked_when_not_normal(self):
        for action in ('stop', 'restart'):
            with self.subTest(action=action):
                self.client.request.side_effect = [(200, detail(status='shutdown'))]
                with self.assertRaises(McpToolError) as ctx:
                    await self.ops.lifecycle(APP_ID, action)
                self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_start_blocked_when_already_running(self):
        self.client.request.side_effect = [(200, detail(status='normal'))]
        with self.assertRaises(McpToolError) as ctx:
            await self.ops.lifecycle(APP_ID, 'start')
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_start_allowed_from_stopped_state(self):
        self.client.request.side_effect = [(200, detail(status='shutdown'))]
        preview = await self.ops.lifecycle(APP_ID, 'start')
        self.assertEqual(preview['current_status'], 'shutdown')
        self.assertEqual(preview['status'], 'confirmation_required')

    async def test_busy_application_blocks_every_action(self):
        for action in ('start', 'stop', 'restart'):
            with self.subTest(action=action):
                self.client.request.side_effect = [(200, detail(current_actions=[{'action': 'restart'}]))]
                with self.assertRaises(McpToolError) as ctx:
                    await self.ops.lifecycle(APP_ID, action)
                self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_unknown_application_fails_closed(self):
        self.client.request.side_effect = [(200, {'id': 'someone-else', 'status': 'normal'})]
        with self.assertRaises(McpToolError) as ctx:
            await self.ops.lifecycle(APP_ID, 'stop')
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')


class LifecycleExecutionTests(LifecycleTestCase):
    async def test_confirm_posts_dedicated_lifecycle_paths(self):
        for action, status in (('start', 'shutdown'), ('stop', 'normal'), ('restart', 'normal')):
            with self.subTest(action=action):
                self.client.request.reset_mock()
                self.client.request.side_effect = [
                    (200, detail(status=status)),
                    (200, detail(status=status)),
                    (202, {'job_id': 'job-' + action}),
                ]
                preview = await self.ops.lifecycle(APP_ID, action)
                result = await self.ops.lifecycle(APP_ID, action, True, preview['plan_id'])
                self.assertEqual(result['status'], 'accepted')
                self.assertFalse(result['complete'])
                self.assertEqual(result['job_id'], 'job-' + action)
                self.assertEqual(result['application_id'], APP_ID)
                self.assertEqual(result['action'], action)
                self.assertTrue(result['notices']['warnings'])
                self.assertIn('show_operation_job_status', result['job_follow_up'])
                self.assertIn('wait_operation_job_complete', result['job_follow_up'])
                self.assertEqual(result['plan_id'], preview['plan_id'])
                calls = self.client.request.call_args_list
                self.assertEqual([c.args[0] for c in calls], ['GET', 'GET', 'POST'])
                self.assertEqual(calls[0].args[1], READ_PATH)
                self.assertEqual(calls[2].args, ('POST', APP_PATH + '/' + action))
                self.assertIsNone(calls[2].kwargs.get('body'))
                self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'accepted')
                self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['job_id'], 'job-' + action)

    async def test_write_gate_blocks_before_any_call(self):
        self.client.request.side_effect = [(200, detail())]
        preview = await self.ops.lifecycle(APP_ID, 'stop')
        self.client.request.reset_mock()
        for environ in ({'HUAWEICLOUD_MCP_READ_ONLY': 'true'}, {'SUPABASE_ENABLE_WRITES': 'false'}):
            with self.subTest(environ=environ):
                with patch.dict(os.environ, environ):
                    with self.assertRaises(McpToolError) as ctx:
                        await self.ops.lifecycle(APP_ID, 'stop', True, preview['plan_id'])
                self.assertEqual(ctx.exception.code, 'MCP_READ_ONLY')
        self.client.request.assert_not_awaited()

    async def test_definite_rejection_marks_plan_failed(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, detail()),
            RecoveryError('MCP_INVALID_ARGS', 'rejected', 'invalid_request', 'fix it'),
        ]
        preview = await self.ops.lifecycle(APP_ID, 'restart')
        with self.assertRaises(McpToolError):
            await self.ops.lifecycle(APP_ID, 'restart', True, preview['plan_id'])
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'failed')

    async def test_transport_failure_marks_unknown_and_never_replays(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, detail()),
            RecoveryError('MCP_SDK_ERROR', 'boom', 'service_unavailable', 'retry later'),
        ]
        preview = await self.ops.lifecycle(APP_ID, 'restart')
        with self.assertRaises(McpToolError) as ctx:
            await self.ops.lifecycle(APP_ID, 'restart', True, preview['plan_id'])
        self.assertEqual(ctx.exception.recovery['category'], 'submission_unknown')
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'unknown')
        self.client.request.side_effect = [(200, detail())]
        with self.assertRaises(McpToolError) as ctx:
            await self.ops.lifecycle(APP_ID, 'restart', True, preview['plan_id'])
        self.assertEqual(ctx.exception.code, 'MCP_GUARDRAIL_BLOCKED')

    async def test_response_without_job_marks_unknown(self):
        self.client.request.side_effect = [
            (200, detail()),
            (200, detail()),
            (202, {}),
        ]
        preview = await self.ops.lifecycle(APP_ID, 'stop')
        with self.assertRaises(McpToolError):
            await self.ops.lifecycle(APP_ID, 'stop', True, preview['plan_id'])
        self.assertEqual(self.ops.plans.inspect(preview['plan_id'])['state'], 'unknown')


class JobFollowUpTests(LifecycleTestCase):
    async def test_mutate_success_carries_job_follow_up(self):
        target = {'id': 'app-1', 'status': 'normal', 'current_actions': []}
        key_page = {'total_count': 1, 'data': [{'id': 'key-1', 'status': 'normal',
                                                'type': 'secret', 'name': 'k'}]}
        cases = [
            ('ssl', {'enable_ssl': False}, [(200, target), (202, {'job_id': 'job-ssl'})]),
            ('eip', {'is_bind': False}, [(200, target), (202, {'job_id': 'job-eip'})]),
            ('auth_flags', {'enable_anonymous_users': False}, [(200, target), (202, {'job_id': 'job-flags'})]),
            ('reset_key', {'key_id': 'key-1'}, [(200, target), (200, key_page), (202, {'job_id': 'job-key'})]),
        ]
        for action, body, responses in cases:
            with self.subTest(action=action):
                preview = await self.ops.mutate('app-1', action, body)
                self.assertNotIn('job_follow_up', preview)
                self.client.request.side_effect = responses
                result = await self.ops.mutate('app-1', action, body, True, preview['plan_id'])
                self.assertEqual(result['status'], 'accepted')
                self.assertIn('show_operation_job_status', result['job_follow_up'])

    async def test_delete_application_carries_job_follow_up(self):
        preview = await self.ops.delete_application(APP_ID, False)
        self.assertNotIn('job_follow_up', preview)
        self.client.request.side_effect = [(200, detail()), (202, {'job_id': 'job-app'})]
        result = await self.ops.delete_application(APP_ID, False, True, preview['plan_id'])
        self.assertEqual(result['status'], 'accepted')
        self.assertIn('show_operation_job_status', result['job_follow_up'])

    async def test_delete_with_instance_prompts_both_jobs_separately(self):
        preview = await self.ops.delete_application(APP_ID, True)
        self.client.request.side_effect = [
            (200, detail(managed_instance={'id': INSTANCE_ID, 'name': 'pg-1'})),
            (200, {'total_count': 1, 'data': [{'id': APP_ID, 'managed_instance': {'id': INSTANCE_ID}}]}),
            (200, {'total_count': 1, 'instances': [{'id': INSTANCE_ID, 'name': 'pg-1', 'charge_info': {'charge_mode': 'postPaid'}}]}),
            (202, {'job_id': 'job-app'}),
            (200, {'job_id': 'job-inst'}),
        ]
        result = await self.ops.delete_application(APP_ID, True, True, preview['plan_id'])
        self.assertEqual(result['instance_job_id'], 'job-inst')
        self.assertIn('instance_job_id', result['job_follow_up'])
        self.assertIn('分别查询', result['job_follow_up'])

    async def test_delete_managed_instance_carries_job_follow_up(self):
        preview = await self.ops.delete_managed_instance(APP_ID, INSTANCE_ID)
        self.assertNotIn('job_follow_up', preview)
        self.client.request.side_effect = [
            (200, detail(managed_instance={'id': INSTANCE_ID, 'name': 'pg-1'})),
            (200, {'total_count': 1, 'data': [{'id': APP_ID, 'managed_instance': {'id': INSTANCE_ID}}]}),
            (200, {'total_count': 1, 'instances': [{'id': INSTANCE_ID, 'name': 'pg-1', 'charge_info': {'charge_mode': 'postPaid'}}]}),
            (200, {'job_id': 'job-77'}),
        ]
        result = await self.ops.delete_managed_instance(APP_ID, INSTANCE_ID, True, preview['plan_id'])
        self.assertEqual(result['status'], 'accepted')
        self.assertIn('show_operation_job_status', result['job_follow_up'])

    async def test_submit_creation_keeps_dedicated_progress_tool(self):
        self.client.request.return_value = (202, {'job_id': 'job-9', 'application_id': APP_ID})
        result = await self.ops.submit_creation({'name': 'demo'})
        self.assertEqual(result['status'], 'accepted')
        self.assertNotIn('job_follow_up', result)
