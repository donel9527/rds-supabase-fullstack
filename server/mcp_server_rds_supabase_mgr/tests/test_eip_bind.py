import os
import tempfile
import unittest
from pathlib import Path
from huaweicloud_mcp_core.errors import McpToolError

APP='supabase-app-0001in32'
EIP_ID='11111111-1111-4111-8111-111111111111'
IP='116.63.11.22'


class FakeKoocli:
    def __init__(self):
        self.region='cn-north-4'
        self.token='fixture'
        self.calls=[]
        self.results=[]

    def push(self,result):
        self.results.append(result)

    async def call(self,service,operation,params=None):
        self.calls.append((service,operation,params))
        result=self.results.pop(0)
        if isinstance(result,Exception):raise result
        return result

    def last(self):
        return self.calls[-1]


class FailingOps:
    """Mirrors the live behavior: an exact-ID filter on an unknown application is rejected
    by the backend outright (HTTP 400), which must surface as an ownership MCP_NOT_FOUND."""

    async def read(self,kind,application_id=None,limit=10,offset=0,**filters):
        raise McpToolError('MCP_INVALID_ARGS','API returned HTTP 400 (backend: error_code=400)')


class FakeOps:
    """Echoes the requested application id; set rows to [] or a foreign id to miss."""

    def __init__(self):
        self.calls=[]
        self.rows=None

    async def read(self,kind,application_id=None,limit=10,offset=0,**filters):
        self.calls.append((kind,application_id))
        rows=self.rows if self.rows is not None else [{'id':application_id}]
        return {'data':list(rows)}


class EipBindTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from mcp_server_supabase.service.eip_bind import EipBindService
        from mcp_server_supabase.service.plans import PlanStore
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.koocli=FakeKoocli()
        self.operations=FakeOps()
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.service=EipBindService(self.operations,self.koocli,PlanStore())

    async def test_backend_filter_rejection_maps_to_ownership_not_found(self):
        from mcp_server_supabase.service.eip_bind import EipBindService
        service=EipBindService(operations=FailingOps(),koocli=FakeKoocli())
        with self.assertRaises(McpToolError) as ctx:
            await service.bind_public_ip('app-in32','00000000-0000-0000-0000-000000000000','1.2.3.4')
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')

    async def test_instance_id_must_be_supabase_application(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip('app-xxx',EIP_ID,IP)
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.operations.calls,[])

    async def test_invalid_uuid_or_address_rejected_locally(self):
        for bad_id in ('not-a-uuid',123):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.bind_public_ip(APP,bad_id,IP)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,'300.1.1.1')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.operations.calls,[])

    async def test_unknown_application_is_refused(self):
        self.operations.rows=[]
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True)
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')
        self.assertEqual(self.operations.calls,[('applications',APP)])
        self.assertEqual(self.koocli.calls,[])
        self.operations.rows=[{'id':'supabase-otherin32'}]
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True)
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')

    async def test_preview_never_calls_koocli(self):
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(preview['status'],'confirmation_required')
        self.assertEqual(preview['execution'],'not_executed')
        self.assertEqual(preview['changes'],{'instance_id':APP,'is_bind':True,'public_ip':IP,'public_ip_id':EIP_ID})
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.operations.calls,[('applications',APP)])

    async def test_execute_submits_attach_eip_exactly(self):
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.koocli.push({})
        result=await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(self.koocli.last(),('RDS','AttachEip',
                                             {'instance_id':APP,'is_bind':True,'public_ip':IP,'public_ip_id':EIP_ID}))
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['eip'],{'public_ip':IP,'public_ip_id':EIP_ID})
        self.assertTrue(result['post_bind'])

    async def test_execute_blocked_without_write_gate(self):
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        del os.environ['SUPABASE_ENABLE_WRITES']
        with self.assertRaises(McpToolError) as ctx:
            await self.service.bind_public_ip(APP,EIP_ID,IP,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_full_positive_path(self):
        preview=await self.service.bind_public_ip(APP,EIP_ID,IP)
        self.assertEqual(len(preview['warnings']),2)
        self.koocli.push({})
        result=await self.service.bind_public_ip(APP,EIP_ID,IP,True,preview['plan_id'])
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['job'],'eip bind')
        self.assertEqual(result['instance_id'],APP)
        self.assertEqual(result['post_bind'],'立即 update_supabase_auth_config 同步 api_external_url，并探活验证')
        self.assertEqual(self.koocli.last(),('RDS','AttachEip',
                                             {'instance_id':APP,'is_bind':True,'public_ip':IP,'public_ip_id':EIP_ID}))
        self.assertEqual(self.operations.calls,[('applications',APP),('applications',APP)])


if __name__=='__main__':
    unittest.main()
