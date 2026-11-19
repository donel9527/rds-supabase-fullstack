import os
import tempfile
import unittest
from pathlib import Path
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.failures import RecoveryError

APP='supabase-app-0001in32'
EIP_ID='11111111-1111-4111-8111-111111111111'
IP='116.63.11.22'
APP_PATH='/v3/{project}/ai-application/'+APP+'/supabase'


class FakeClient:
    def __init__(self):
        self.calls=[]
        self.results=[]

    def push(self,result):
        self.results.append(result)

    async def request(self,method,path,body=None,query=None,headers=None):
        self.calls.append((method,path,body))
        result=self.results.pop(0)
        if isinstance(result,Exception):raise result
        return result


class FakeOps:
    """Operations double: detail path, stable digest, injected client."""

    def __init__(self,client):
        self.client=client

    def app(self,application_id):
        return '/v3/{project}/ai-application/'+application_id+'/supabase'

    def intent_digest(self,method,path,body):
        return 'digest:'+method+':'+path


class FakeLedger:
    def __init__(self):
        self.binds=[]

    def bind_safe(self,kind,key,owner,detail=None):
        self.binds.append((kind,key,owner,detail))
        return None


def target(**overrides):
    row={'id':APP,'status':'normal','current_actions':None,'public_ip':None}
    row.update(overrides)
    return row


class EipBindTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from mcp_server_supabase.service.eip_bind import EipBindService
        from mcp_server_supabase.service.plans import PlanStore
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.client=FakeClient()
        self.operations=FakeOps(self.client)
        self.ledger=FakeLedger()
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.service=EipBindService(self.operations,PlanStore(),self.ledger)

    def put_count(self):
        return sum(1 for method,_,_ in self.client.calls if method=='PUT')

    async def test_local_validations_reject_before_any_read(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip('app-xxx',EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        for bad_id in ('not-a-uuid',123):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.bind_public_ip(APP,bad_id,IP)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,'300.1.1.1')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.client.calls,[])

    async def test_definitive_404_is_ownership_not_found_with_source_hint(self):
        self.client.push(RecoveryError('MCP_NOT_FOUND','API returned HTTP 404','not_found','recheck target'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')
        self.assertIn('不是本环境管理',str(ctx.exception))
        self.assertIn('核对源',ctx.exception.hint or '')
        self.assertEqual(self.client.calls[0][0],'GET')
        self.assertEqual(self.client.calls[0][1],APP_PATH)

    async def test_other_read_failures_are_not_masqueraded_as_ownership(self):
        self.client.push(RecoveryError('MCP_SDK_ERROR','API returned HTTP 503','service_unavailable','pause queries'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.assertNotIn('不是本环境管理',str(ctx.exception))

    async def test_detail_id_mismatch_is_ownership_not_found(self):
        self.client.push((200,{'id':'supabase-otherin32','status':'normal'}))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')

    async def test_non_normal_or_busy_application_is_blocked(self):
        self.client.push((200,target(status='stopped')))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.client.push((200,target(current_actions=['rebooting'])))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.put_count(),0)

    async def test_already_bound_application_is_directed_to_change_tool(self):
        self.client.push((200,target(public_ip='116.63.11.99')))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertIn('change_supabase_eip',ctx.exception.hint or '')

    async def test_preview_reads_detail_but_never_submits(self):
        self.client.push((200,target()))
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(preview['status'],'confirmation_required')
        self.assertEqual(preview['execution'],'not_executed')
        self.assertEqual(preview['changes'],{'is_bind':True,'public_ip_id':EIP_ID,'public_ip_address':IP})
        self.assertEqual(len(preview['warnings']),3)
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.client.calls,[(('GET'),APP_PATH,None)])
        self.assertEqual(self.put_count(),0)

    async def test_execute_submits_public_eip_exactly(self):
        self.client.push((200,target()))
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.client.push((200,target()))
        self.client.push((202,{'job_id':'job-0001'}))
        result=await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(self.client.calls[-1],('PUT',APP_PATH+'/public-eip',
                                                {'is_bind':True,'public_ip_id':EIP_ID,'public_ip_address':IP}))
        self.assertEqual(result['status'],'accepted')
        self.assertEqual(result['job_id'],'job-0001')
        self.assertEqual(result['instance_id'],APP)
        self.assertEqual(result['eip'],{'public_ip':IP,'public_ip_id':EIP_ID})
        self.assertTrue(result['post_bind'])
        self.assertEqual(self.ledger.binds,[('eip',EIP_ID,APP,{'address':IP,'provenance':'bind_supabase_eip（首次绑定）'})])

    async def test_execute_blocked_without_write_gate(self):
        self.client.push((200,target()))
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        del os.environ['SUPABASE_ENABLE_WRITES']
        self.client.push((200,target()))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.put_count(),0)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_guard_block_leaves_plan_unclaimed(self):
        self.client.push((200,target()))
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.client.push((200,target(public_ip='116.63.11.99')))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.put_count(),0)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_plan_is_single_use(self):
        self.client.push((200,target()))
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.client.push((200,target()));self.client.push((202,{'job_id':'job-0001'}))
        await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.client.push((200,target()))
        with self.assertRaises(McpToolError):
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(self.put_count(),1)

    async def test_definite_backend_rejection_fails_plan_without_unknown_state(self):
        self.client.push((200,target()))
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.client.push((200,target()))
        self.client.push(RecoveryError('MCP_INVALID_ARGS','API returned HTTP 400','invalid_request','check contract'))
        with self.assertRaises(McpToolError):
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'failed')


if __name__=='__main__':
    unittest.main()
