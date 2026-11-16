import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.creation_flow import CreationFlowService
from mcp_server_supabase.service.network import Network
from mcp_server_supabase.service.operations import Operations
from mcp_server_supabase.service.plans import PlanStore

VPC_ID='fff3b97c-8821-44e5-b16e-788a745292f0'
SUBNET_ID='bba70694-b1aa-47a6-b6d1-cfc9563e0ec2'
SUBNET_CIDR='192.168.0.0/24'
APP_GROUP='11111111-1111-4111-8111-111111111111'
DB_GROUP='22222222-2222-4222-8222-222222222222'
INSTANCE_ID='33333333-3333-4333-8333-333333333333'
TAGS=[{'key':'AUTO_CREATE','value':'true'},{'key':'USE_FOR','value':'Supabase'}]

NEW_BODY={'name':'flow-app','basic_config':{'region':'cn-east-3','vpc_id':VPC_ID,'subnet_id':SUBNET_ID},
          'storage_component':{'enabled':False},'version':'1.0.0','mode':'Single',
          'flavor_ref':'rds.supabase.n1.large.2','availability_zone':'cn-east-3a',
          'password':'Fixture-Secret1','manage_type':'newly_instance',
          'managed_instance':{'datastore':{'type':'PostgreSQL','version':'17'},
                              'charge_info':{'charge_mode':'postPaid'},
                              'flavor_ref':'rds.pg.n1.medium.2','volume':{'type':'ESSD','size':40},
                              'availability_zone':'cn-east-3a',
                              'security_group_id':'99999999-9999-4999-8999-999999999999',
                              'password':'Fixture-Secret1','enterprise_project_id':'cddc3f1f-6c3e-4d0f-a1f1-2b5bb2d6b2a6'},
          'security_group_id':'88888888-8888-4888-8888-888888888888'}

EXIST_BODY={'name':'flow-app','basic_config':{'region':'cn-east-3','vpc_id':VPC_ID,'subnet_id':SUBNET_ID},
            'storage_component':{'enabled':False},'version':'1.0.0','mode':'Single',
            'flavor_ref':'rds.supabase.n1.large.2','availability_zone':'cn-east-3a',
            'password':'Fixture-Secret1','manage_type':'existed_instance',
            'existing_instance':{'instance_id':INSTANCE_ID,'database_name':'root','database_pwd':'fixture-secret'}}

STORAGE_BODY=dict(NEW_BODY,storage_component={'enabled':True,'bucket_name':'supabase-flow-app',
                                               'ak':'fixture-ak','sk':'fixture-sk'})
STORAGE_EXIST_BODY=dict(EXIST_BODY,storage_component={'enabled':True,'bucket_name':'supabase-flow-app',
                                                      'ak':'fixture-ak','sk':'fixture-sk'})


class FakeKoocli:
    def __init__(self):
        self.region='cn-east-3'
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


class FakeNetwork:
    """Records every execute-only primitive call; group ids are valid canonical UUIDs."""

    def __init__(self,koocli=None,fail_on_group=None):
        self.koocli=koocli
        self.fail_on_group=fail_on_group
        self.created=0
        self.groups=[]
        self.rules=[]

    async def create_group_now(self,name,description):
        self.created+=1
        if self.fail_on_group==self.created:
            raise McpToolError('MCP_CLI_ERROR','group creation failed')
        self.groups.append({'name':name,'description':description})
        return {'id':APP_GROUP if name=='supabase-app-sg' else DB_GROUP}

    async def add_rule_now(self,group_id,source_cidr,port,direction='ingress',protocol='tcp'):
        self.rules.append({'group_id':group_id,'source_cidr':source_cidr,'port':port,
                           'direction':direction,'protocol':protocol})
        return {}


class FakeObs:
    """Records ensure_bucket_now calls; scripted results can rename (collision backfill)."""

    def __init__(self,result):
        self.result=result
        self.calls=[]

    async def ensure_bucket_now(self,bucket_name,redundancy='multi_az'):
        self.calls.append((bucket_name,redundancy))
        return dict(self.result)


class FakeOps:
    """Instance-candidate source and scripted creation submissions."""

    def __init__(self,rows=None,result=None):
        self.rows=rows if rows is not None else []
        self.result=result if result is not None else {'status':'accepted','job_id':'job-1','application_id':'app-1'}
        self.submitted=[]
        self.candidates_calls=0

    async def creation_candidates(self,kind,az_code=None,mode=None):
        self.candidates_calls+=1
        return {'data':{'instances':self.rows}}

    async def submit_creation(self,body,plan_id=None):
        self.submitted.append((body,plan_id))
        return dict(self.result)


class CreationFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.requests=Path(self.tmp.name)/'requests.json'
        self.requests.write_text(json.dumps({'new':NEW_BODY,'exist':EXIST_BODY,'new-obs':STORAGE_BODY,
                                              'exist-obs':STORAGE_EXIST_BODY}),encoding='utf-8')
        os.chmod(self.requests,0o600)
        os.environ['SUPABASE_REQUESTS_FILE']=str(self.requests)
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.koocli=FakeKoocli()
        self.network=FakeNetwork(self.koocli)
        self.ops=FakeOps(rows=[{'id':INSTANCE_ID,'name':'pg-1','vpc_id':VPC_ID,'subnet_id':SUBNET_ID}],
                         result={'status':'accepted','job_id':'job-1','application_id':'app-1',
                                 'instance_id':'pg-1','instance_job_id':'pgjob-1'})
        self.plans=PlanStore()
        self.flow=CreationFlowService(operations=self.ops,network=self.network,koocli=self.koocli,
                                      plans=self.plans,detector=lambda:'1.2.3.4/32')

    def push_subnets(self):
        self.koocli.push({'subnets':[{'id':SUBNET_ID,'cidr':SUBNET_CIDR}]})

    def test_defaults_construct_real_primitives(self):
        service=CreationFlowService()
        self.assertIsInstance(service.network,Network)
        self.assertIs(service.koocli,service.network.koocli)
        self.assertIsNone(service.detector)

    def test_default_detector_uses_network_discovery(self):
        with patch('mcp_server_supabase.service.instance_catalog.NetworkDiscovery._detect_access_cidr',
                   return_value='9.9.9.9/32'):
            self.assertEqual(self.flow._detect_egress(),'9.9.9.9/32')

    async def test_manage_type_mismatch_rejected_before_any_call(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.link_exist_instance('new')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('exist')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.network.groups,[]);self.assertEqual(self.network.rules,[])
        self.assertEqual(self.ops.submitted,[]);self.assertEqual(self.ops.candidates_calls,0)
        self.assertEqual(self.koocli.calls,[])

    def storage_flow(self,obs_result):
        return CreationFlowService(operations=self.ops,network=self.network,koocli=self.koocli,
                                   plans=self.plans,detector=lambda:'1.2.3.4/32',
                                   obs=FakeObs(obs_result))

    async def test_storage_enabled_preview_carries_obs_plan(self):
        self.push_subnets()
        flow=self.storage_flow({'bucket':'supabase-flow-app','created':True,'note':'x'})
        result=await flow.with_new_instance('new-obs')
        self.assertEqual(result['obs_plan']['bucket'],'supabase-flow-app')
        self.assertIn('确保桶存在',result['obs_plan']['action'])
        self.assertFalse(result['obs_plan']['credential']['temporary'])
        self.assertEqual(flow.obs.calls,[])
        self.assertIn('自动创建并注入请求体',result['security_group_plan']['note'])

    async def test_temporary_credentials_surface_in_preview_warnings(self):
        self.push_subnets()
        self.koocli._security_token='TOK'
        flow=self.storage_flow({'bucket':'supabase-flow-app','created':True,'note':'x'})
        result=await flow.with_new_instance('new-obs')
        self.assertTrue(result['obs_plan']['credential']['temporary'])
        self.assertTrue(any('存储凭据' in w for w in result['warnings']))

    async def test_storage_disabled_preview_has_no_obs_plan(self):
        self.push_subnets()
        result=await self.flow.with_new_instance('new')
        self.assertIsNone(result['obs_plan'])

    async def test_storage_execute_backfills_renamed_bucket_and_echoes_obs(self):
        self.push_subnets()
        flow=self.storage_flow({'bucket':'supabase-flow-app-a1b2','created':True,'note':'桶已新建'})
        preview=await flow.with_new_instance('new-obs')
        self.push_subnets()
        result=await flow.with_new_instance('new-obs',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(flow.obs.calls,[('supabase-flow-app','multi_az')])
        submitted=self.ops.submitted[-1][0]
        self.assertEqual(submitted['storage_component']['bucket_name'],'supabase-flow-app-a1b2')
        self.assertEqual(result['obs']['bucket'],'supabase-flow-app-a1b2')
        self.assertTrue(result['obs']['created'])

    async def test_storage_execute_keeps_existing_bucket_name(self):
        self.push_subnets()
        flow=self.storage_flow({'bucket':'supabase-flow-app','created':False,'note':'桶已存在'})
        preview=await flow.with_new_instance('new-obs')
        self.push_subnets()
        result=await flow.with_new_instance('new-obs',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(self.ops.submitted[-1][0]['storage_component']['bucket_name'],'supabase-flow-app')
        self.assertFalse(result['obs']['created'])

    async def test_storage_execute_ensure_failure_fails_plan_without_submission(self):
        self.push_subnets()
        failing=FakeObs({'bucket':'x','created':True,'note':'x'})
        async def broken(bucket_name,redundancy='multi_az'):
            raise McpToolError('MCP_CLI_ERROR','obs unreachable')
        failing.ensure_bucket_now=broken
        flow=CreationFlowService(operations=self.ops,network=self.network,koocli=self.koocli,
                                 plans=self.plans,detector=lambda:'1.2.3.4/32',obs=failing)
        preview=await flow.with_new_instance('new-obs')
        self.push_subnets()
        with self.assertRaises(McpToolError):
            await flow.with_new_instance('new-obs',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(self.ops.submitted,[])
        self.assertEqual(self.network.groups,[{'name':'supabase-app-sg','description':'Supabase应用（自动创建）'},
                                              {'name':'supabase-db-sg','description':'数据库接入（自动创建）'}])

    async def test_new_preview_is_read_only(self):
        self.push_subnets()
        result=await self.flow.with_new_instance('new')
        self.assertEqual(result['status'],'confirmation_required')
        self.assertEqual(result['execution'],'not_executed')
        self.assertEqual(result['scenario'],'newly_instance')
        self.assertEqual(result['security_group_plan']['application_group'],
                         {'name':'supabase-app-sg','ingress':{'port':8443,'cidr':'1.2.3.4/32'}})
        self.assertEqual(result['security_group_plan']['database_group'],
                         {'name':'supabase-db-sg','ingress':{'port':5432,'cidr':SUBNET_CIDR}})
        self.assertEqual(result['security_group_plan']['egress'],{'port':5432,'cidr':SUBNET_CIDR})
        self.assertEqual(len(result['warnings']),2)
        self.assertTrue(result['plan_id'])
        self.assertNotIn('Fixture-Secret1',str(result));self.assertNotIn('fixture-secret',str(result))
        self.assertEqual(self.koocli.calls,[('VPC','ListSubnets',{'limit':100,'vpc_id':VPC_ID})])
        self.assertEqual(self.network.groups,[]);self.assertEqual(self.network.rules,[])
        self.assertEqual(self.ops.submitted,[])

    async def test_open_ingress_goes_through_koocli(self):
        self.push_subnets()
        preview=await self.flow.with_new_instance('new',public_access_cidr='open')
        self.assertEqual(preview['security_group_plan']['application_group']['ingress']['cidr'],'0.0.0.0/0')
        self.push_subnets()
        self.koocli.push({'security_group_rule':{'id':'r-open'}})
        result=await self.flow.with_new_instance('new',public_access_cidr='open',
                                                 confirm=True,plan_id=preview['plan_id'])
        rule_calls=[call for call in self.koocli.calls if call[1]=='CreateSecurityGroupRule/v3']
        self.assertEqual(len(rule_calls),1)
        self.assertEqual(rule_calls[0],('VPC','CreateSecurityGroupRule/v3',
                                        {'security_group_rule':{'security_group_id':APP_GROUP,'direction':'ingress',
                                                                'ethertype':'IPv4','protocol':'tcp','multiport':'8443',
                                                                'remote_ip_prefix':'0.0.0.0/0','action':'allow','priority':1}}))
        self.assertFalse(any(rule['port']==8443 for rule in self.network.rules))
        self.assertTrue(any(rule['port']==5432 and rule['direction']=='egress' for rule in self.network.rules))
        self.assertEqual(result['security_groups']['rules'][0]['cidr'],'0.0.0.0/0')

    async def test_new_execute_provisions_both_groups_and_submits(self):
        self.push_subnets()
        preview=await self.flow.with_new_instance('new')
        self.push_subnets()
        result=await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual([g['name'] for g in self.network.groups],['supabase-app-sg','supabase-db-sg'])
        self.assertEqual([g['description'] for g in self.network.groups],
                         ['Supabase应用（自动创建）','数据库接入（自动创建）'])
        self.assertEqual(self.network.rules,
                         [{'group_id':APP_GROUP,'source_cidr':'1.2.3.4/32','port':8443,'direction':'ingress','protocol':'tcp'},
                          {'group_id':APP_GROUP,'source_cidr':SUBNET_CIDR,'port':5432,'direction':'egress','protocol':'tcp'},
                          {'group_id':DB_GROUP,'source_cidr':SUBNET_CIDR,'port':5432,'direction':'ingress','protocol':'tcp'}])
        self.assertEqual(len(self.ops.submitted),1)
        body,used_plan=self.ops.submitted[0]
        self.assertEqual(used_plan,preview['plan_id'])
        self.assertEqual(body['security_group_id'],APP_GROUP)
        self.assertEqual(body['managed_instance']['security_group_id'],DB_GROUP)
        self.assertEqual(result['job_id'],'job-1');self.assertEqual(result['application_id'],'app-1')
        self.assertEqual(result['instance_id'],'pg-1');self.assertEqual(result['instance_job_id'],'pgjob-1')
        self.assertEqual(result['security_groups']['application_group_id'],APP_GROUP)
        self.assertEqual(result['security_groups']['database_group_id'],DB_GROUP)
        self.assertEqual(result['workflow']['track'],
                         {'tool':'show_supabase_creation_progress',
                          'args':{'application_id':'app-1','application_job_id':'job-1',
                                  'instance_job_id':'pgjob-1','instance_id':'pg-1'}})
        steps=result['workflow']['after_completion']['eip_automation']
        self.assertEqual([step['tool'] for step in steps],
                         ['create_supabase_eip','bind_supabase_eip','update_supabase_auth_config'])
        self.assertIn('空闲 EIP 优先复用',result['workflow']['after_completion']['note'])

    async def test_exist_execute_single_group_and_top_level_injection_only(self):
        self.ops.result={'status':'accepted','job_id':'job-2','application_id':'app-2'}
        self.push_subnets()
        preview=await self.flow.link_exist_instance('exist')
        self.assertEqual(preview['scenario'],'existed_instance')
        self.assertEqual(preview['security_group_plan']['database_group'],'不动（保持实例现状）')
        self.push_subnets()
        result=await self.flow.link_exist_instance('exist',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual([g['name'] for g in self.network.groups],['supabase-app-sg'])
        self.assertEqual(self.network.rules,
                         [{'group_id':APP_GROUP,'source_cidr':'1.2.3.4/32','port':8443,'direction':'ingress','protocol':'tcp'},
                          {'group_id':APP_GROUP,'source_cidr':SUBNET_CIDR,'port':5432,'direction':'egress','protocol':'tcp'}])
        body,used_plan=self.ops.submitted[0]
        self.assertEqual(body['security_group_id'],APP_GROUP)
        self.assertNotIn('managed_instance',body)
        self.assertEqual(result['security_groups']['database_group_id'],None)
        self.assertEqual(result['security_groups']['database_group'],'不动（保持实例现状）')
        self.assertEqual(result['workflow']['track'],
                         {'tool':'show_supabase_creation_progress',
                          'args':{'application_id':'app-2','application_job_id':'job-2'}})
        self.assertEqual(self.ops.candidates_calls,2)

    async def test_prepaid_order_response_tracks_the_order(self):
        self.ops.result={'status':'order_created','order_id':'CS-1','job_id':None}
        self.push_subnets()
        preview=await self.flow.with_new_instance('new')
        self.push_subnets()
        result=await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'order_created')
        self.assertEqual(result['order_id'],'CS-1')
        self.assertEqual(result['workflow']['track'],{'tool':'get_supabase_order','args':{'order_id':'CS-1'}})
        self.assertIn('pay_supabase_order',result['workflow']['reminder'])
        self.assertEqual(result['security_groups']['application_group_id'],APP_GROUP)

    async def test_invalid_custom_cidr_rejected(self):
        for bad in ('300.0.0.0/8','0.0.0.0/0','10.0.0.0/0','192.168.1.5/24','',None,123):
            with self.assertRaises(McpToolError) as ctx:
                await self.flow._ingress_cidr(bad)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(await self.flow._ingress_cidr('203.0.113.0/24'),'203.0.113.0/24')
        self.assertEqual(await self.flow._ingress_cidr('open'),'0.0.0.0/0')
        self.assertEqual(await self.flow._ingress_cidr('auto'),'1.2.3.4/32')
        self.assertEqual(self.koocli.calls,[])

    async def test_detector_failure_blocks_auto(self):
        self.flow.detector=lambda:None
        self.push_subnets()
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('new')
        self.assertEqual(ctx.exception.code,'MCP_CLI_ERROR')
        self.assertEqual(self.network.groups,[]);self.assertEqual(self.network.rules,[])
        self.assertEqual(self.ops.submitted,[])

    async def test_write_gate_blocks_and_keeps_plan_prepared(self):
        self.push_subnets()
        preview=await self.flow.with_new_instance('new')
        self.push_subnets()
        os.environ['SUPABASE_ENABLE_WRITES']='false'
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='true'
        self.push_subnets()
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.assertEqual(self.network.groups,[]);self.assertEqual(self.network.rules,[])
        self.assertEqual(self.ops.submitted,[]);self.assertEqual(self.koocli.calls,
                         [('VPC','ListSubnets',{'limit':100,'vpc_id':VPC_ID})]*3)
        self.assertEqual(self.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_plan_claim_enforces_identity_and_single_use(self):
        self.push_subnets()
        preview=await self.flow.with_new_instance('new')
        self.push_subnets()
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('new',confirm=True,plan_id='bogus')
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.push_subnets()
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('new',public_access_cidr='203.0.113.0/24',
                                              confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.network.groups,[]);self.assertEqual(self.ops.submitted,[])
        self.assertEqual(self.plans.inspect(preview['plan_id'])['state'],'prepared')
        self.push_subnets()
        await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(len(self.ops.submitted),1)
        self.push_subnets()
        with self.assertRaises(McpToolError) as ctx:
            await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(len(self.ops.submitted),1)

    async def test_group_failure_midway_marks_plan_failed(self):
        self.network.fail_on_group=2
        self.push_subnets()
        preview=await self.flow.with_new_instance('new')
        self.push_subnets()
        with self.assertRaises(McpToolError):
            await self.flow.with_new_instance('new',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual([g['name'] for g in self.network.groups],['supabase-app-sg'])
        self.assertEqual(len(self.network.rules),2)
        self.assertEqual(self.ops.submitted,[])
        self.assertEqual(self.plans.inspect(preview['plan_id'])['state'],'failed')


class NetworkNowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.koocli=FakeKoocli()
        self.network=Network(self.koocli,PlanStore())

    async def test_create_group_now_posts_tagged_body(self):
        self.koocli.push({'security_group':{'id':APP_GROUP,'name':'supabase-app-sg'}})
        group=await self.network.create_group_now('supabase-app-sg','Supabase应用（自动创建）')
        self.assertEqual(group['id'],APP_GROUP)
        self.assertEqual(self.koocli.last(),('VPC','CreateSecurityGroup/v3',
                                             {'security_group':{'name':'supabase-app-sg',
                                                                'description':'Supabase应用（自动创建）',
                                                                'tags':TAGS}}))
        self.koocli.push({})
        with self.assertRaises(McpToolError) as ctx:
            await self.network.create_group_now('supabase-db-sg','数据库接入（自动创建）')
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.assertEqual(ctx.exception.message,'CreateSecurityGroup/v3 returned no security_group')

    async def test_create_group_now_validates_arguments(self):
        for name in ('x'*65,'bad name',123,None):
            with self.assertRaises(McpToolError) as ctx:
                await self.network.create_group_now(name,'d')
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        for description in ('x'*256,'<script>'):
            with self.assertRaises(McpToolError) as ctx:
                await self.network.create_group_now('g',description)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_add_rule_now_posts_native_rule_body(self):
        self.koocli.push({'security_group_rule':{'id':'r-1','security_group_id':APP_GROUP}})
        rule=await self.network.add_rule_now(APP_GROUP,'192.0.2.0/24',8443)
        self.assertEqual(rule['id'],'r-1')
        self.assertEqual(self.koocli.last(),('VPC','CreateSecurityGroupRule/v3',
                                             {'security_group_rule':{'security_group_id':APP_GROUP,'direction':'ingress',
                                                                     'ethertype':'IPv4','protocol':'tcp','multiport':'8443',
                                                                     'remote_ip_prefix':'192.0.2.0/24','action':'allow','priority':1}}))
        self.koocli.push({})
        self.assertEqual(await self.network.add_rule_now(APP_GROUP,SUBNET_CIDR,5432,'egress'),{})
        self.assertEqual(self.koocli.last()[2]['security_group_rule']['direction'],'egress')
        self.assertEqual(self.koocli.last()[2]['security_group_rule']['multiport'],'5432')
        self.koocli.push({'security_group_rule':{'id':'r-6'}})
        self.assertEqual((await self.network.add_rule_now(APP_GROUP,'2001:db8::/64',5433))['id'],'r-6')
        self.assertEqual(self.koocli.last()[2]['security_group_rule']['ethertype'],'IPv6')

    async def test_add_rule_now_rejects_world_and_bad_arguments(self):
        for source in ('0.0.0.0/0','::/0','192.0.2.0/33','invalid'):
            with self.assertRaises(McpToolError) as ctx:
                await self.network.add_rule_now(APP_GROUP,source,8443)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        for args in ((APP_GROUP,'192.0.2.0/24',8443,'in'),
                     (APP_GROUP,'192.0.2.0/24',8443,'ingress','icmp'),
                     ('not-a-uuid','192.0.2.0/24',8443),
                     (APP_GROUP,'192.0.2.0/24','8443'),
                     (APP_GROUP,'192.0.2.0/24',0)):
            with self.assertRaises(McpToolError) as ctx:
                await self.network.add_rule_now(*args)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])


class SubmitCreationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.client=AsyncMock();self.client.endpoint='https://example.invalid'
        self.client.project='project';self.client.token='fixture'
        self.ops=Operations(self.client,PlanStore())
        self.sequence=0

    def armed(self):
        """Issue and claim one plan so submit_creation can finish it."""
        self.sequence+=1
        digest='digest-%d'%self.sequence
        plan=self.ops.plans.issue(digest)['plan_id']
        self.ops.plans.claim(plan,digest)
        return plan

    async def test_job_branch_echoes_identifiers_and_notices(self):
        self.client.request.return_value=(202,{'job_id':'job-1','application_id':'app-1',
                                                'instance_id':'pg-1','instance_job_id':'pgjob-1'})
        result=await self.ops.submit_creation(copy.deepcopy(NEW_BODY))
        self.assertEqual(result['status'],'accepted');self.assertEqual(result['job_id'],'job-1')
        self.assertEqual(result['application_id'],'app-1');self.assertEqual(result['instance_id'],'pg-1')
        self.assertEqual(result['instance_job_id'],'pgjob-1')
        self.assertEqual(result['plan_id'],None);self.assertFalse(result['completion_verified'])
        self.assertEqual(len(result['warnings']),3);self.assertIn('follow_up',result)
        self.assertEqual(self.client.request.call_args.args,('POST','/v3/{project}/ai-application/supabases'))
        self.assertEqual(self.client.request.call_args.kwargs['body'],NEW_BODY)

    async def test_job_branch_finishes_accepted_plan(self):
        plan=self.armed()
        self.client.request.return_value=(202,{'job_id':'job-9','application_id':'app-9'})
        result=await self.ops.submit_creation(copy.deepcopy(NEW_BODY),plan)
        self.assertEqual(result['plan_id'],plan)
        self.assertEqual(self.ops.plans.inspect(plan)['state'],'accepted')
        self.assertEqual(self.ops.plans.record(plan)['job_id'],'job-9')

    async def test_prepaid_order_branch(self):
        self.client.request.return_value=(202,{'order_id':'CS-77'})
        result=await self.ops.submit_creation(copy.deepcopy(NEW_BODY))
        self.assertEqual(result['status'],'order_created');self.assertEqual(result['order_id'],'CS-77')
        self.assertEqual(result['job_id'],None)
        self.assertTrue(any('pay_supabase_order' in warning for warning in result['warnings']))
        self.assertEqual(len(result['warnings']),6)

    async def test_failure_states_finish_the_plan(self):
        plan=self.armed()
        self.client.request.side_effect=McpToolError('MCP_INVALID_ARGS','HTTP 400')
        with self.assertRaises(McpToolError):
            await self.ops.submit_creation(copy.deepcopy(NEW_BODY),plan)
        self.assertEqual(self.ops.plans.inspect(plan)['state'],'failed')
        plan=self.armed()
        self.client.request.side_effect=RecoveryError('MCP_INVALID_ARGS','HTTP 400','invalid_request','fix')
        with self.assertRaises(RecoveryError):
            await self.ops.submit_creation(copy.deepcopy(NEW_BODY),plan)
        self.assertEqual(self.ops.plans.inspect(plan)['state'],'failed')
        plan=self.armed()
        self.client.request.side_effect=RecoveryError('MCP_SDK_ERROR','unreachable','transport_or_response','reconcile')
        with self.assertRaises(RecoveryError) as ctx:
            await self.ops.submit_creation(copy.deepcopy(NEW_BODY),plan)
        self.assertEqual(ctx.exception.message,'Creation result unknown')
        self.assertEqual(self.ops.plans.inspect(plan)['state'],'unknown')
        plan=self.armed()
        self.client.request.side_effect=None;self.client.request.return_value=(202,{})
        with self.assertRaises(McpToolError):
            await self.ops.submit_creation(copy.deepcopy(NEW_BODY),plan)
        self.assertEqual(self.ops.plans.inspect(plan)['state'],'unknown')


if __name__=='__main__':
    unittest.main()


class PasswordComplexityTests(unittest.IsolatedAsyncioTestCase):
    """Advisory password warnings and the dashboard credential note ride on both
    creation previews and the accepted response; the cloud rules stay authoritative."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'SUPABASE_ENABLE_WRITES':'true',
                                        'HUAWEICLOUD_MCP_READ_ONLY':'false',
                                        'SUPABASE_STATE_FILE':str(Path(self.tmp.name)/'state.db'),
                                        'SUPABASE_REQUESTS_FILE':str(Path(self.tmp.name)/'requests.json')})
        self.env.start();self.addCleanup(self.env.stop)
        self.koocli=FakeKoocli()
        self.network=FakeNetwork(self.koocli)
        self.flow=CreationFlowService(network=self.network,koocli=self.koocli,
                                       plans=PlanStore(Path(self.tmp.name)/'plans.db'),
                                       detector=lambda:'1.2.3.4/32')
        self.requests=Path(self.tmp.name)/'requests.json'
        self.requests.write_text(json.dumps({'new':NEW_BODY,'risky':dict(NEW_BODY,password='FixTure$ecret1')}),encoding='utf-8')
        os.chmod(self.requests,0o600)

    def push_subnets(self):
        self.koocli.push({'subnets':[{'id':SUBNET_ID,'cidr':'192.168.0.0/24'}]})

    async def test_safe_password_no_warning_but_credential_note_present(self):
        self.push_subnets()
        result=await self.flow.with_new_instance('new')
        self.assertFalse(any('特殊字符' in w for w in result['warnings']))
        self.assertEqual(result['dashboard_credential']['login_user'],'supabase')
        self.assertIn('create.password',result['dashboard_credential']['password_source'])

    async def test_unsafe_password_surfaces_transcription_warning(self):
        self.push_subnets()
        result=await self.flow.with_new_instance('risky')
        self.assertTrue(any('create.password' in w and '特殊字符' in w for w in result['warnings']))
        self.assertTrue(any('12-16 位' in w for w in result['warnings']))
