import os
import tempfile
import unittest
from pathlib import Path
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import flatten_params
from mcp_server_supabase.service.eip import EipService

TAG_VALUE='Supabase应用公网访问，自动创建的'


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


class EipServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.koocli=FakeKoocli()
        self.service=EipService(self.koocli)

    async def test_idle_eips_short_circuit_purchase(self):
        self.koocli.push({'publicips':[{'id':'e1','status':'FREE','public_ip_address':'1.2.3.4','alias':'old'},
                                       {'id':'e2','status':'ACTIVE','public_ip_address':'5.6.7.8','alias':'busy'},
                                       {'id':'e3','public_ip_address':'7.7.7.7'},
                                       {'id':'e4','associate_instance_id':'port-1'}]})
        result=await self.service.ensure_publicip()
        self.assertEqual(result['mode'],'idle_selection')
        self.assertEqual(result['idle_eips'][0],{'id':'e1','public_ip_address':'1.2.3.4','alias':'old','status':'FREE',
                                                 'bandwidth_size_mbps':None,'charge_mode':None,
                                                 'publicip_type':None,'share_type':None})
        self.assertEqual([e['id'] for e in result['idle_eips']],['e1','e3'])
        self.assertIn('bind_supabase_eip',result['note'])
        self.assertNotIn('plan_id',result)
        self.assertEqual(self.koocli.calls,[('EIP','ListPublicips',{'limit':100})])

    async def test_unreadable_idle_list_fails_closed(self):
        for broken in ({'publicips':'broken'},{}):
            self.koocli.push(broken)
            with self.assertRaises(McpToolError) as ctx:
                await self.service.ensure_publicip()
            self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
            self.assertEqual(ctx.exception.message,'EIP list unreadable')

    async def test_no_idle_preview_requires_confirmation(self):
        self.koocli.push({'publicips':[]})
        result=await self.service.ensure_publicip()
        self.assertEqual(result['mode'],'confirmation_required')
        self.assertEqual(result['status'],'confirmation_required')
        self.assertEqual(result['execution'],'not_executed')
        self.assertTrue(result['plan_id'])
        self.assertEqual(result['charge_mode'],'postPaid')
        self.assertEqual(result['eip'],{'id':None,'public_ip_address':None,'alias':None,'status':None,
                                        'bandwidth_size_mbps':300,'charge_mode':'postPaid',
                                        'publicip_type':'5_bgp（全动态 BGP）','share_type':'PER（独享）'})
        self.assertEqual(result['recommendation'],{'charge_mode':'按需购买（postPaid）推荐',
                                                    'bandwidth':'全动态 BGP，5-1000M，推荐 300M'})
        self.assertEqual(result['warnings'],['新购 EIP 立即计费','包周期需控制台支付订单后生效'])
        self.assertEqual([c[1] for c in self.koocli.calls],['ListPublicips'])

    async def test_postpaid_execute_creates_and_tags(self):
        self.koocli.push({'publicips':[]})
        preview=await self.service.ensure_publicip(name='app-eip')
        self.assertEqual(preview['eip']['alias'],'app-eip')
        self.koocli.push({'publicips':[]})
        self.koocli.push({'publicip':{'id':'e-9','status':'ACTIVE','public_ip_address':'9.9.9.9',
                                      'bandwidth':{'size':300,'share_type':'PER','charge_mode':'bandwidth'}}})
        self.koocli.push({})
        result=await self.service.ensure_publicip(name='app-eip',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual([c[1] for c in self.koocli.calls],
                         ['ListPublicips','ListPublicips','CreatePublicip','BatchCreatePublicipTags'])
        service,operation,params=self.koocli.calls[2]
        self.assertEqual((service,operation),('EIP','CreatePublicip'))
        self.assertEqual(params['publicip']['type'],'5_bgp')
        self.assertEqual(params['publicip']['ip_version'],4)
        self.assertEqual(params['publicip']['alias'],'app-eip')
        self.assertEqual(params['bandwidth']['name'],'app-eip')
        self.assertEqual(params['bandwidth']['share_type'],'PER')
        self.assertEqual(params['bandwidth']['size'],300)
        self.assertEqual(params['bandwidth']['charge_mode'],'bandwidth')
        flags=set(flatten_params(params))
        self.assertIn('--publicip.type=5_bgp',flags)
        self.assertIn('--publicip.alias=app-eip',flags)
        self.assertIn('--publicip.ip_version=4',flags)
        self.assertIn('--bandwidth.share_type=PER',flags)
        self.assertIn('--bandwidth.size=300',flags)
        self.assertIn('--bandwidth.charge_mode=bandwidth',flags)
        tag_params=self.koocli.calls[3][2]
        self.assertEqual(tag_params['action'],'create')
        self.assertEqual(tag_params['publicip_id'],'e-9')
        self.assertEqual(tag_params['tags'],[{'key':'USAGE_FOR','value':TAG_VALUE}])
        tag_flags=set(flatten_params(tag_params))
        self.assertIn('--tags.1.key=USAGE_FOR',tag_flags)
        self.assertIn('--tags.1.value='+TAG_VALUE,tag_flags)
        self.assertEqual(result['mode'],'created')
        self.assertEqual(result['status'],'created')
        self.assertEqual(result['tag'],'USAGE_FOR='+TAG_VALUE)
        self.assertEqual(result['eip']['id'],'e-9')
        self.assertEqual(result['eip']['public_ip_address'],'9.9.9.9')
        self.assertEqual(result['eip']['bandwidth_size_mbps'],300)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_prefer_idle_false_skips_the_idle_query(self):
        preview=await self.service.ensure_publicip(prefer_idle=False)
        self.assertEqual(preview['mode'],'confirmation_required')
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.koocli.calls,[])

    async def test_invalid_arguments_rejected_before_any_call(self):
        for case in ({'charge_mode':'x'},{'bandwidth_size_mbps':4},{'bandwidth_size_mbps':1001},
                     {'bandwidth_size_mbps':'300'},{'name':123},{'name':'x'*65},
                     {'charge_mode':'prePaid'},
                     {'charge_mode':'prePaid','period_type':'week','period_num':1},
                     {'charge_mode':'prePaid','period_type':'month'},
                     {'charge_mode':'prePaid','period_type':'month','period_num':0},
                     {'charge_mode':'prePaid','period_type':'month','period_num':10},
                     {'charge_mode':'prePaid','period_type':'year','period_num':4}):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.ensure_publicip(prefer_idle=False,**case)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_write_gate_blocks_execution(self):
        preview=await self.service.ensure_publicip(prefer_idle=False)
        os.environ['SUPABASE_ENABLE_WRITES']='false'
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='true'
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_broken_plan_refused_and_left_prepared(self):
        preview=await self.service.ensure_publicip(prefer_idle=False)
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id='bogus')
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,bandwidth_size_mbps=100,
                                               confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')
        self.koocli.push({'publicip':{'id':'e-5','public_ip_address':'5.5.5.5'}})
        self.koocli.push({})
        await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id=preview['plan_id'])
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(len(self.koocli.calls),2)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_prepaid_execute_returns_order_id(self):
        preview=await self.service.ensure_publicip(prefer_idle=False,charge_mode='prePaid',
                                                   period_type='month',period_num=3)
        self.assertEqual(preview['charge_mode'],'prePaid')
        self.assertEqual(self.koocli.calls,[])
        self.koocli.push({'publicip':{'id':'e-8','status':'PENDING_CREATE','public_ip_address':'8.8.8.8'},
                          'order_id':'CS123'})
        result=await self.service.ensure_publicip(prefer_idle=False,charge_mode='prePaid',period_type='month',
                                                  period_num=3,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['mode'],'created')
        self.assertEqual(result['order_id'],'CS123')
        self.assertEqual(result['eip']['public_ip_address'],'8.8.8.8')
        self.assertIn('包周期',result['note'])
        service,operation,params=self.koocli.last()
        self.assertEqual((service,operation),('EIP','CreatePrePaidPublicip'))
        self.assertEqual(params['publicip']['type'],'5_bgp')
        self.assertEqual(params['bandwidth']['size'],300)
        self.assertEqual(params['extendParam'],{'period_type':'month','period_num':3})
        flags=set(flatten_params(params))
        self.assertIn('--extendParam.period_type=month',flags)
        self.assertIn('--extendParam.period_num=3',flags)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')
        preview=await self.service.ensure_publicip(prefer_idle=False,charge_mode='prePaid',period_type='year',
                                                   period_num=1,name='app-eip')
        self.koocli.push({'data':{'order_id':'CS456'},'publicip':{'id':'e-6'}})
        result=await self.service.ensure_publicip(prefer_idle=False,charge_mode='prePaid',period_type='year',
                                                  period_num=1,name='app-eip',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['order_id'],'CS456')
        self.assertEqual([c[1] for c in self.koocli.calls],['CreatePrePaidPublicip','CreatePrePaidPublicip'])

    async def test_write_failure_keeps_unknown(self):
        preview=await self.service.ensure_publicip(prefer_idle=False)
        self.koocli.push(McpToolError('MCP_CLI_ERROR','boom'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.assertEqual(ctx.exception.recovery['category'],'submission_unknown')
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    async def test_tag_failure_after_create_keeps_unknown(self):
        preview=await self.service.ensure_publicip(prefer_idle=False)
        self.koocli.push({'publicip':{'id':'e-7','public_ip_address':'7.7.7.7'}})
        self.koocli.push(McpToolError('MCP_CLI_ERROR','tag failed'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    def test_view_tolerates_flat_and_nested_shapes(self):
        view=EipService._view({'id':'p1','publicip_address':'2.2.2.2','bandwidth_size':50,
                               'bandwidth_share_type':'PER','charge_mode':'bandwidth','type':'5_bgp'})
        self.assertEqual(view['public_ip_address'],'2.2.2.2')
        self.assertEqual(view['bandwidth_size_mbps'],50)
        self.assertEqual(view['charge_mode'],'bandwidth')
        self.assertEqual(view['publicip_type'],'5_bgp')
        self.assertEqual(view['share_type'],'PER')
        view=EipService._view({'publicip':{'type':'5_bgp','ip_address':'1.1.1.1','alias':'a'},
                               'bandwidth':{'size':10,'share_type':'PER','charge_mode':'traffic'}})
        self.assertEqual(view['public_ip_address'],'1.1.1.1')
        self.assertEqual(view['bandwidth_size_mbps'],10)
        self.assertEqual(view['charge_mode'],'traffic')
        self.assertEqual(view['publicip_type'],'5_bgp')
        self.assertEqual(view['alias'],'a')
        self.assertEqual(EipService._view('broken'),{'id':None,'public_ip_address':None,'alias':None,'status':None,
                                                     'bandwidth_size_mbps':None,'charge_mode':None,
                                                     'publicip_type':None,'share_type':None})


if __name__=='__main__':
    unittest.main()
