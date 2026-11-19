import os
import tempfile
import unittest
from pathlib import Path
from mcp_server_supabase.service.ledger import ResourceLedger

APP='ad9079c304464c33a4f2fd516d4a3b16in32'
EIP='11111111-1111-4111-8111-111111111111'
INSTANCE='ee36e15f94ed4432adb3ada163620d82in03'


class ResourceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ledger=ResourceLedger(Path(self.tmp.name)/'resources.sqlite3')

    def test_record_upsert_preserves_created_time_and_merges_detail(self):
        self.ledger.record('eip',EIP,name='eip-1',auto_created=True,detail={'address':'1.2.3.4'})
        first=self.ledger.get('eip',EIP)
        self.ledger.record('eip',EIP,name='eip-2',auto_created=True,detail={'billing_method':'traffic'})
        second=self.ledger.get('eip',EIP)
        self.assertEqual(first['created_time'],second['created_time'])
        self.assertEqual(second['name'],'eip-2')
        self.assertEqual(second['detail'],{'address':'1.2.3.4','billing_method':'traffic'})
        self.assertTrue(second['auto_created'])

    def test_record_safe_returns_warning_on_fault_not_raise(self):
        class Broken(ResourceLedger):
            def record(self,*args,**kwargs):raise RuntimeError('disk full')
        warning=Broken().record_safe('eip',EIP)
        self.assertIn('资源记录写入失败',warning)

    def test_bind_preserves_provenance_and_defaults_reused_on_insert(self):
        self.ledger.record('eip',EIP,name='flow-eip',auto_created=True,detail={'address':'1.2.3.4'})
        self.ledger.bind('eip',EIP,APP,detail={'provenance':'bind_supabase_eip'})
        row=self.ledger.get('eip',EIP)
        self.assertTrue(row['auto_created'])       # flow-created stays flow-created
        self.assertEqual(row['application_id'],APP)
        self.assertEqual(row['detail']['address'],'1.2.3.4')
        self.ledger.bind('eip','22222222-2222-4222-8222-222222222222',APP)
        self.assertFalse(self.ledger.get('eip','22222222-2222-4222-8222-222222222222')['auto_created'])

    def test_application_deleted_merges_context_and_sets_deleted_time(self):
        self.ledger.record('application',APP,name='web',auto_created=True,
                           detail={'managed_instance':{'id':'i-1','origin':'newly_instance'}})
        self.ledger.application_deleted(APP,{'instance_retained':True,'instance_id':'i-1'})
        row=self.ledger.get('application',APP)
        self.assertIsNotNone(row['deleted_time'])
        self.assertEqual(row['detail']['managed_instance']['id'],'i-1')
        self.assertTrue(row['detail']['deletion']['instance_retained'])

    def test_application_deleted_inserts_when_record_missing(self):
        self.ledger.application_deleted(APP,{'instance_retained':False})
        row=self.ledger.get('application',APP)
        self.assertIsNotNone(row['deleted_time'])
        self.assertFalse(row['detail']['deletion']['instance_retained'])

    def test_cleaned_and_rows_filtering(self):
        self.ledger.record('eip',EIP,application_id=APP)
        self.ledger.record('obs_bucket','supabase-demo',application_id=APP,auto_created=False)
        self.ledger.cleaned('obs_bucket','supabase-demo')
        self.assertEqual([row['resource_id'] for row in self.ledger.rows(application_id=APP)],
                         [EIP])                                  # cleaned rows leave the active set
        self.assertEqual(len(self.ledger.rows(application_id=APP,active_only=False)),2)
        self.assertEqual([row['kind'] for row in self.ledger.rows(kind='obs_bucket',active_only=False)],
                         ['obs_bucket'])

    def test_detach_clears_binding_keeps_record(self):
        self.ledger.record('security_group',EIP,application_id=APP,auto_created=True)
        self.ledger.detach('security_group',EIP)
        row=self.ledger.get('security_group',EIP)
        self.assertIsNone(row['application_id'])
        self.assertTrue(row['auto_created'])

    def test_symlink_rejected(self):
        target=Path(self.tmp.name)/'real.sqlite3';target.write_text('x')
        link=Path(self.tmp.name)/'link.sqlite3';link.symlink_to(target)
        with self.assertRaises(RuntimeError):
            ResourceLedger(link).record('eip',EIP)

    def test_invalid_kind_and_id(self):
        with self.assertRaises(ValueError):
            self.ledger.record('not_a_kind',EIP)
        with self.assertRaises(ValueError):
            self.ledger.record('eip','')


class CreationFlowRecordingTests(unittest.IsolatedAsyncioTestCase):
    """The creation flow records the application anchor, both security groups
    and the ensured OBS bucket into the resource ledger."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ledger=ResourceLedger(Path(self.tmp.name)/'resources.sqlite3')

    async def test_record_creation_writes_all_resources(self):
        from mcp_server_supabase.service.creation_flow import CreationFlowService
        flow=CreationFlowService(ledger=self.ledger)
        result={'status':'accepted','job_id':'job-1','application_id':APP,'instance_id':INSTANCE}
        groups={'application_group_id':'33333333-3333-4333-8333-333333333333',
                'database_group_id':'44444444-4444-4444-8444-444444444444'}
        body={'name':'web-app','managed_instance':{'id':INSTANCE}}
        prepared_obs={'bucket':'supabase-web-app','created':True}
        warnings=flow._record_creation(result,'newly_instance',groups,body,prepared_obs)
        self.assertIsNone(warnings)
        app=self.ledger.get('application',APP)
        self.assertEqual(app['detail']['managed_instance']['id'],INSTANCE)
        self.assertEqual(app['detail']['managed_instance']['origin'],'newly_instance')
        sg_app=self.ledger.get('security_group',groups['application_group_id'])
        self.assertEqual(sg_app['detail']['role'],'application')
        self.assertEqual(sg_app['application_id'],APP)
        sg_db=self.ledger.get('security_group',groups['database_group_id'])
        self.assertEqual(sg_db['detail']['role'],'database')
        bucket=self.ledger.get('obs_bucket','supabase-web-app')
        self.assertTrue(bucket['auto_created'])
        self.assertEqual(bucket['application_id'],APP)

    async def test_record_creation_without_ledger_is_silent(self):
        from mcp_server_supabase.service.creation_flow import CreationFlowService
        flow=CreationFlowService()
        self.assertIsNone(flow._record_creation({'application_id':APP},{},{},None,None))


class HookRecordingTests(unittest.IsolatedAsyncioTestCase):
    """Post-success ledger hooks: EIP creation, application deletion and
    security-group deletion write the ledger without changing tool contracts."""

    def setUp(self):
        import tempfile
        from unittest.mock import patch
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'SUPABASE_ENABLE_WRITES':'true',
                                        'HUAWEICLOUD_MCP_READ_ONLY':'false'})
        self.env.start();self.addCleanup(self.env.stop)

    async def test_eip_creation_records_provenance(self):
        from mcp_server_supabase.service.eip import EipService
        from mcp_server_supabase.service.plans import PlanStore
        from unittest.mock import AsyncMock
        koocli=AsyncMock();koocli.region='cn-east-3';koocli.token='fixture'
        koocli.call=AsyncMock(side_effect=[
            {'publicips':[{'id':'baseline-other'}]},
            {'publicip':{'id':EIP,'public_ip_address':'1.2.3.4','alias':'eip-1'}},
            {'publicip':{'id':EIP}}])
        service=EipService(koocli,PlanStore(Path(self.tmp.name)/'plans.db'),ledger=self.ledger_())
        result=await service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',
                                              bandwidth_size_mbps=50,confirm=False)
        plan=result['plan_id']
        result=await service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',
                                              bandwidth_size_mbps=50,confirm=True,plan_id=plan)
        row=self.ledger_().get('eip',EIP)
        self.assertTrue(row['auto_created'])
        self.assertEqual(row['detail']['address'],'1.2.3.4')
        self.assertEqual(row['detail']['billing_method'],'bandwidth')

    def ledger_(self):
        if not hasattr(self,'_ledger'):
            self._ledger=ResourceLedger(Path(self.tmp.name)/'resources.sqlite3')
        return self._ledger
