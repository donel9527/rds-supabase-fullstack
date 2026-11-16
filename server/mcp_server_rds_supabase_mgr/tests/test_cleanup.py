import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.failures import RecoveryError

EIP_ID='11111111-1111-4111-8111-111111111111'
ADDRESS='123.60.101.251'
APP='ad9079c304464c33a4f2fd516d4a3b16in32'
BUCKET='supabase-demo-app'
INSTANCE='ee36e15f94ed4432adb3ada163620d82in03'


class FakeCleanupCli:
    """Combined stub: JSON-API .call() for the EIP service, obsutil .obs() for OBS."""

    def __init__(self):
        self.region='cn-east-3'; self.token='fixture'
        self.api_calls=[]; self.api_results=[]
        self.obs_calls=[]; self.obs_results=[]

    def push_api(self,result): self.api_results.append(result)
    def push_obs(self,result): self.obs_results.append(result)

    async def call(self,service,operation,params=None):
        self.api_calls.append((service,operation,params))
        result=self.api_results.pop(0)
        if isinstance(result,Exception):raise result
        return result

    async def obs(self,operation,args=None,flags=None,region=None):
        self.obs_calls.append((operation,args,flags))
        result=self.obs_results.pop(0)
        if isinstance(result,Exception):raise result
        return result


class CleanupTestsBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from mcp_server_supabase.service.cleanup import CleanupService
        from mcp_server_supabase.service.plans import PlanStore
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'SUPABASE_ENABLE_WRITES':'true',
                                        'HUAWEICLOUD_MCP_READ_ONLY':'false'})
        self.env.start();self.addCleanup(self.env.stop)
        self.koocli=FakeCleanupCli()
        self.client=AsyncMock()
        self.client.endpoint='https://example.invalid';self.client.project='project';self.client.token='fixture'
        self.service=CleanupService(self.client,self.koocli,PlanStore(Path(self.tmp.name)/'state.db'))

    def apps_page(self,rows):
        return {'total_count':len(rows),'data':rows}

    def empty_sweep(self):
        self.client.request.side_effect=[(200,self.apps_page([]))]


class DeleteEipTests(CleanupTestsBase):
    async def test_preview_makes_no_cloud_calls(self):
        preview=await self.service.delete_eip(EIP_ID,ADDRESS,False)
        self.assertEqual(preview['status'],'confirmation_required')
        self.assertEqual(preview['public_ip_id'],EIP_ID)
        self.assertEqual(len(preview['warnings']),3)
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.client.request.await_count,0)
        self.assertEqual(self.koocli.api_calls,[])

    async def test_happy_path_deletes_eip(self):
        preview=await self.service.delete_eip(EIP_ID,ADDRESS,False)
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.empty_sweep()
        self.koocli.push_api({})
        result=await self.service.delete_eip(EIP_ID,ADDRESS,True,preview['plan_id'])
        self.assertEqual(result['status'],'applied')
        self.assertEqual(result['public_ip'],ADDRESS)
        operations=[call[1] for call in self.koocli.api_calls]
        self.assertEqual(operations,['ShowPublicIp','DeletePublicip'])
        self.assertEqual(self.koocli.api_calls[0][0],'EIP')
        methods=[c.args[0] for c in self.client.request.call_args_list]
        self.assertEqual(methods,['GET'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_address_mismatch_blocked_before_submission(self):
        preview=await self.service.delete_eip(EIP_ID)
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':'5.6.7.8'}})
        self.empty_sweep()
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_eip(EIP_ID,'1.2.3.4',True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertIn('mismatch',ctx.exception.message)
        self.assertEqual([c[1] for c in self.koocli.api_calls],['ShowPublicIp'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_eip_referenced_by_live_app_blocked(self):
        preview=await self.service.delete_eip(EIP_ID)
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.client.request.side_effect=[(200,self.apps_page([{'id':APP,'name':'web','direct_eip':ADDRESS}]))]
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_eip(EIP_ID,None,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertIn(APP,ctx.exception.hint)
        self.assertEqual([c[1] for c in self.koocli.api_calls],['ShowPublicIp'])

    async def test_identity_not_verified(self):
        preview=await self.service.delete_eip(EIP_ID)
        self.koocli.push_api({'publicip':{'id':'other','public_ip_address':ADDRESS}})
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_eip(EIP_ID,None,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')

    async def test_delete_failure_marks_unknown(self):
        preview=await self.service.delete_eip(EIP_ID)
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.empty_sweep()
        self.koocli.push_api(McpToolError('MCP_CLI_ERROR','backend rejected'))
        with self.assertRaises(RecoveryError):
            await self.service.delete_eip(EIP_ID,None,True,preview['plan_id'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    async def test_readonly_gate_blocks(self):
        preview=await self.service.delete_eip(EIP_ID)
        with patch.dict(os.environ,{'HUAWEICLOUD_MCP_READ_ONLY':'true'}):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.delete_eip(EIP_ID,None,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.koocli.api_calls,[])

    async def test_invalid_uuid_rejected(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_eip('not-a-uuid')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')

    async def test_replay_rejected(self):
        preview=await self.service.delete_eip(EIP_ID)
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.empty_sweep()
        self.koocli.push_api({})
        await self.service.delete_eip(EIP_ID,None,True,preview['plan_id'])
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.empty_sweep()
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_eip(EIP_ID,None,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')


class DeleteBucketTests(CleanupTestsBase):
    async def test_preview_bucket(self):
        preview=await self.service.delete_bucket(BUCKET,False)
        self.assertEqual(preview['status'],'confirmation_required')
        self.assertEqual(preview['bucket'],BUCKET)
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.koocli.obs_calls,[])

    async def test_happy_path_deletes_empty_bucket(self):
        preview=await self.service.delete_bucket(BUCKET,False)
        self.koocli.push_obs('stat ok')
        self.empty_sweep()
        self.koocli.push_obs('Folder number:0, File number:0')
        self.koocli.push_obs('Delete bucket successfully')
        result=await self.service.delete_bucket(BUCKET,True,preview['plan_id'])
        self.assertEqual(result['status'],'applied')
        operations=[call[0] for call in self.koocli.obs_calls]
        self.assertEqual(operations,['stat','ls','rm'])
        self.assertEqual(self.koocli.obs_calls[1],('ls',['obs://'+BUCKET+'/'],['-limit=1']))
        self.assertEqual(self.koocli.obs_calls[2],('rm',['obs://'+BUCKET],['-f']))
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_non_empty_bucket_blocked(self):
        preview=await self.service.delete_bucket(BUCKET,False)
        self.koocli.push_obs('stat ok')
        self.empty_sweep()
        self.koocli.push_obs('obs://%s/someobject 1024 2026-11-16\nTotal size: 1024'%BUCKET)
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_bucket(BUCKET,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual([call[0] for call in self.koocli.obs_calls],['stat','ls'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_bucket_referenced_by_live_app_blocked(self):
        preview=await self.service.delete_bucket(BUCKET,False)
        self.koocli.push_obs('stat ok')
        self.client.request.side_effect=[(200,self.apps_page(
            [{'id':APP,'name':'web','storage_component':{'enabled':True,'bucket':BUCKET}}]))]
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_bucket(BUCKET,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertIn(APP,ctx.exception.hint)

    async def test_absent_bucket_returns_already_absent(self):
        preview=await self.service.delete_bucket(BUCKET,False)
        self.koocli.push_obs(McpToolError('MCP_CLI_ERROR','KooCLI rm failed with exit code 1: [NoSuchBucket]'))
        result=await self.service.delete_bucket(BUCKET,True,preview['plan_id'])
        self.assertEqual(result['status'],'already_absent')
        self.assertEqual(result['execution'],'not_executed')
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_invalid_bucket_name_rejected(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.delete_bucket('Bad_Name')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')


class CleanWorkspaceTests(CleanupTestsBase):
    async def test_preview_pins_scope(self):
        preview=await self.service.clean_workspace(BUCKET,APP,False)
        self.assertEqual(preview['workspace'],'obs://%s/%s/'%(BUCKET,APP))
        self.assertEqual(preview['safety']['scope'],'obs://%s/%s/'%(BUCKET,APP))
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.koocli.obs_calls,[])

    async def test_happy_path_cleans_only_the_workspace(self):
        preview=await self.service.clean_workspace(BUCKET,APP,False)
        self.empty_sweep()
        self.koocli.push_obs('stat ok')
        self.koocli.push_obs('obs://%s/%s/:\nobs://%s/%s/logo.png 1024\nobs://%s/%s/data/x.csv 2048\nobs://%s/%s/a.bin 10'
                             %(BUCKET,APP,BUCKET,APP,BUCKET,APP,BUCKET,APP))
        self.koocli.push_obs('Succeeded number: 3, Failed number: 0')
        self.koocli.push_obs('folder marker deleted')
        result=await self.service.clean_workspace(BUCKET,APP,True,preview['plan_id'])
        self.assertEqual(result['status'],'applied')
        self.assertEqual(result['deleted'],3)
        self.assertEqual(result['delete_failed'],0)
        self.assertEqual(result['objects_listed'],3)
        rm_calls=[call for call in self.koocli.obs_calls if call[0]=='rm']
        self.assertEqual(rm_calls[0],('rm',['obs://%s/%s/'%(BUCKET,APP)],['-r','-f']))
        self.assertEqual(rm_calls[1],('rm',['obs://%s/%s/'%(BUCKET,APP)],['-f']))

    async def test_live_application_blocked_before_any_obs_call(self):
        preview=await self.service.clean_workspace(BUCKET,APP,False)
        self.client.request.side_effect=[(200,self.apps_page([{'id':APP,'name':'web'}]))]
        with self.assertRaises(McpToolError) as ctx:
            await self.service.clean_workspace(BUCKET,APP,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertIn('delete_supabase_application',ctx.exception.hint)
        self.assertEqual(self.koocli.obs_calls,[])

    async def test_empty_workspace_is_already_clean(self):
        preview=await self.service.clean_workspace(BUCKET,APP,False)
        self.empty_sweep()
        self.koocli.push_obs('stat ok')
        self.koocli.push_obs('No objects found')
        result=await self.service.clean_workspace(BUCKET,APP,True,preview['plan_id'])
        self.assertEqual(result['status'],'already_clean')
        self.assertEqual(result['objects'],0)
        self.assertEqual([call[0] for call in self.koocli.obs_calls],['stat','ls'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_partial_failure_reports_counts(self):
        preview=await self.service.clean_workspace(BUCKET,APP,False)
        self.empty_sweep()
        self.koocli.push_obs('stat ok')
        self.koocli.push_obs('obs://%s/%s/logo.png 1024\nobs://%s/%s/data/x.csv 2048\nobs://%s/%s/a.bin 10'
                             %(BUCKET,APP,BUCKET,APP,BUCKET,APP))
        self.koocli.push_obs('Succeeded number: 2, Failed number: 1')
        self.koocli.push_obs('folder marker deleted')
        result=await self.service.clean_workspace(BUCKET,APP,True,preview['plan_id'])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['deleted'],2)
        self.assertEqual(result['delete_failed'],1)
        self.assertIn('failed=1',result.get('warning_extra',''))

    async def test_absent_bucket_returns_already_absent(self):
        preview=await self.service.clean_workspace(BUCKET,APP,False)
        self.empty_sweep()
        self.koocli.push_obs(McpToolError('MCP_CLI_ERROR','status 404 NoSuchBucket'))
        result=await self.service.clean_workspace(BUCKET,APP,True,preview['plan_id'])
        self.assertEqual(result['status'],'already_absent')

    async def test_invalid_application_id_rejected(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.clean_workspace(BUCKET,'../escape')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')


class ConfinementParsingTests(unittest.TestCase):
    def test_object_rows_never_leave_the_requested_prefix(self):
        from mcp_server_supabase.service.cleanup import object_rows
        text=('obs://%s/%s/:\n'
              'obs://%s/%s/logo.png 1024\n'
              'obs://%s/otherapp/logo.png 512\n'
              'obs://%s/%sexact/x.bin 8\n'
              'obs://other-bucket/%s/y.bin 8\n'
              'Total size: 1024')%(BUCKET,APP,BUCKET,APP,BUCKET,BUCKET,APP,APP)
        rows=object_rows(text,BUCKET,APP+'/')
        self.assertEqual(rows,[APP+'/logo.png'])

    def test_deletion_counts_parses_both_wordings(self):
        from mcp_server_supabase.service.cleanup import deletion_counts
        self.assertEqual(deletion_counts('Succeeded number: 3, Failed number: 1'),(3,1))
        self.assertEqual(deletion_counts('Succeeded count: 2\nFailed count: 0'),(2,0))
        self.assertEqual(deletion_counts('nothing matched'),(None,None))


class ResidualsAndBatchTests(CleanupTestsBase):
    """场景七: ledger-scoped residual inventory and the one-click batch cleanup."""

    APP_SG='33333333-3333-4333-8333-333333333333'
    DB_SG='44444444-4444-4444-8444-444444444444'

    def setUp(self):
        super().setUp()
        from mcp_server_supabase.service.ledger import ResourceLedger
        self.ledger=ResourceLedger(Path(self.tmp.name)/'resources.sqlite3')
        self.service.ledger=self.ledger

    def seed(self,instance_retained=True):
        self.ledger.record('application',APP,name='web-app',auto_created=True,
                           detail={'scenario':'newly_instance',
                                   'managed_instance':{'id':INSTANCE,'origin':'newly_instance'}})
        self.ledger.application_deleted(APP,{'instance_retained':instance_retained,
                                              'instance_id':INSTANCE,
                                              'instance_cascade':not instance_retained})
        self.ledger.record('eip',EIP_ID,name='flow-eip',auto_created=True,
                           application_id=APP,detail={'address':ADDRESS})
        self.ledger.record('obs_bucket',BUCKET,auto_created=True,application_id=APP,
                           detail={'ensured_by':'creation_flow'})
        self.ledger.record('security_group',self.APP_SG,
                           name='supabase-app-sg',auto_created=True,application_id=APP,
                           detail={'role':'application'})
        self.ledger.record('security_group',self.DB_SG,
                           name='supabase-db-sg',auto_created=True,application_id=APP,
                           detail={'role':'database'})

    def instances_page(self,exists=True):
        rows=[{'id':INSTANCE,'name':'pg-1','status':'ACTIVE'}] if exists else []
        return (200,{'total_count':len(rows),'instances':rows})

    def inventory_fixtures(self,workspace_objects=True):
        """One full _residual_inventory pass: EIP read + bucket stat + workspace ls
        (only when the workspace holds objects) + instance inventory REST."""
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS,'status':'FREE'}})
        self.koocli.push_obs('stat ok')
        if workspace_objects:
            self.koocli.push_obs('obs://%s/%s/logo.png 1024'%(BUCKET,APP))
        else:
            self.koocli.push_obs('')

    def empty_sweep(self):
        self.client.request.side_effect=[(200,self.apps_page([]))]

    async def test_residuals_inventory_and_recommendations(self):
        self.seed(instance_retained=True)
        self.inventory_fixtures()
        self.client.request.side_effect=[self.instances_page(exists=True)]
        result=await self.service.residuals(APP)
        self.assertEqual(result['application']['deleted'],True)
        self.assertEqual(result['application']['instance_live']['exists'],True)
        self.assertTrue(result['eip'][0]['auto_created'])
        self.assertIn('建议删除',result['eip'][0]['recommendation'])
        self.assertEqual(result['obs_workspaces'][0]['objects'],1)
        self.assertIn('高危提醒',result['obs_workspaces'][0]['high_risk_billing_note'])
        sg_db=[row for row in result['security_groups'] if row['role']=='database'][0]
        self.assertIn('实例保留中',sg_db['blocked'])
        self.assertEqual(result['one_click']['tool'],'cleanup_supabase_residuals')
        self.assertIn('eip',result['categories'])

    async def test_residuals_require_ledger_record(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.residuals(APP)
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')
        self.assertIn('资源记录',ctx.exception.message)

    async def test_residuals_require_ledger_enabled(self):
        self.service.ledger=None
        with self.assertRaises(McpToolError) as ctx:
            await self.service.residuals(APP)
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')

    async def test_cleanup_all_preview_lists_inventory_without_writes(self):
        self.seed()
        self.inventory_fixtures()
        self.client.request.side_effect=[self.instances_page(exists=False)]
        preview=await self.service.cleanup_all(APP,True,True,True,True,False)
        self.assertEqual(preview['status'],'confirmation_required')
        self.assertEqual(preview['flags'],{'eip':True,'obs_bucket':True,
                                           'obs_workspace':True,'security_groups':True})
        self.assertEqual(len(preview['warnings']),4)
        self.assertTrue(any('高危提醒' in w for w in preview['warnings']))
        self.assertIn('inventory',preview)
        self.assertEqual(self.koocli.api_calls[-1][0:2],('EIP','ShowPublicIp'))   # reads only

    async def test_cleanup_all_full_path_deletes_every_category(self):
        self.seed(instance_retained=False)      # instance cascade-deleted: db group deletable
        # instance_retained=False -> the residual inventory performs no instance REST call
        self.inventory_fixtures()
        preview=await self.service.cleanup_all(APP,True,True,True,True,False)
        # submit-time fresh inventory (no REST either)
        self.inventory_fixtures()
        # KooCLI queues consume in call order; the three REST sweeps share one list
        self.client.request.side_effect=[(200,self.apps_page([])) for _ in range(3)]
        # EIP: verify read + delete
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.koocli.push_api({})
        # workspace: stat + listing, then rm with counts + folder-marker removal
        self.koocli.push_obs('stat ok')
        self.koocli.push_obs('obs://%s/%s/logo.png 1024'%(BUCKET,APP))
        self.koocli.push_obs('Succeeded number: 1, Failed number: 0')
        self.koocli.push_obs('folder marker deleted')
        # bucket: stat + empty listing, then rm
        self.koocli.push_obs('stat ok')
        self.koocli.push_obs('')
        self.koocli.push_obs('deleted')
        # security groups: verify + delete_group_now re-verify + delete, per group
        for group_id in (self.APP_SG,self.DB_SG):
            for _ in range(2):
                self.koocli.push_api({'security_group':{'id':group_id,
                    'tags':[{'key':'AUTO_CREATE','value':'true'},
                            {'key':'USE_FOR','value':'Supabase'}]}})
            self.koocli.push_api({})
        result=await self.service.cleanup_all(APP,True,True,True,True,True,preview['plan_id'])
        self.assertEqual(result['status'],'applied')
        for category in ('eip','obs_workspace','obs_bucket','security_groups'):
            outcomes=[row['outcome'] for row in result['results'][category]]
            self.assertTrue(outcomes and all(outcome=='deleted' for outcome in outcomes),category)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')
        active={row['kind'] for row in self.ledger.rows(application_id=APP)}
        self.assertEqual(active,set())                     # ledger marked everything cleaned

    async def test_cleanup_all_blocks_db_group_when_instance_retained(self):
        self.seed(instance_retained=True)
        self.inventory_fixtures()
        self.client.request.side_effect=[self.instances_page(exists=True)]
        preview=await self.service.cleanup_all(APP,False,False,False,True,False)
        self.inventory_fixtures()
        self.client.request.side_effect=[self.instances_page(exists=True)]
        for _ in range(2):                                 # app group verify + re-verify
            self.koocli.push_api({'security_group':{'id':self.APP_SG,
                'tags':[{'key':'AUTO_CREATE','value':'true'},
                        {'key':'USE_FOR','value':'Supabase'}]}})
        self.koocli.push_api({})                           # DeleteSecurityGroup/v3
        result=await self.service.cleanup_all(APP,False,False,False,True,True,preview['plan_id'])
        roles={row['role']:row['outcome'] for row in result['results']['security_groups']}
        self.assertEqual(roles['application'],'deleted')
        self.assertEqual(roles['database'],'blocked')
        self.assertIn('实例保留中',[row['reason'] for row in result['results']['security_groups']
                                   if row['role']=='database'][0])

    async def test_cleanup_all_requires_explicit_booleans(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.service.cleanup_all(APP,None,True,True,True)
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')

    async def test_cleanup_all_replay_rejected(self):
        self.seed(instance_retained=False)
        # retained=False -> no inventory REST; eip-only flags
        self.inventory_fixtures(workspace_objects=False)
        preview=await self.service.cleanup_all(APP,True,False,False,False,False)
        self.inventory_fixtures(workspace_objects=False)
        self.koocli.push_api({'publicip':{'id':EIP_ID,'public_ip_address':ADDRESS}})
        self.empty_sweep()
        self.koocli.push_api({})
        await self.service.cleanup_all(APP,True,False,False,False,True,preview['plan_id'])
        # replay: fresh inventory runs before the claim rejects the reused plan
        self.inventory_fixtures(workspace_objects=False)
        with self.assertRaises(McpToolError) as ctx:
            await self.service.cleanup_all(APP,True,False,False,False,True,preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
