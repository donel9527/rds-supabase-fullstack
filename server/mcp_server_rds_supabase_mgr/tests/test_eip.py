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
        result=await self.service.ensure_publicip(billing_method='bandwidth',bandwidth_size_mbps=300)
        self.assertEqual(result['mode'],'confirmation_required')
        self.assertEqual(result['status'],'confirmation_required')
        self.assertEqual(result['execution'],'not_executed')
        self.assertTrue(result['plan_id'])
        self.assertEqual(result['billing_method'],'bandwidth')
        self.assertEqual(result['eip'],{'id':None,'public_ip_address':None,'alias':None,'status':None,
                                        'bandwidth_size_mbps':300,'billing_method':'bandwidth',
                                        'publicip_type':'5_bgp（全动态 BGP）','share_type':'PER（独享）'})
        self.assertEqual(result['billing'],{'mode':'按需计费（固定，不支持包周期）——秒级计费按小时结算，自 EIP 创建起计费至释放',
                                             'method':'按带宽计费——带宽费按带宽峰值×时长（不限流量），流量大或访问量稳定场景更优',
                                             'fee_components':'费用 = 带宽费/流量费 + 弹性公网IP保有费（未绑定云资源且未释放时收取，官方示例 0.02 元/小时）',
                                             'unit_price_reference':'阶梯计费：0-5M 统一单价、超 5M 按每 Mbps 计费；官方示例 6Mbps≈0.565 元/小时（随地域浮动，以价格详情为准）',
                                             'price_source':'精确单价以官网价格详情为准：https://www.huaweicloud.com/pricing.html?tab=detail#/eip',
                                             'traffic_limit':None})
        self.assertEqual(result['warnings'],['按带宽计费——带宽费按带宽峰值×时长（不限流量），流量大或访问量稳定场景更优——已由用户确认（300 Mbps）',
                                             '带宽/流量均为收费项：自 EIP 创建起持续计费直至释放'])
        self.assertEqual([c[1] for c in self.koocli.calls],['ListPublicips'])

    async def test_purchase_without_billing_method_is_rejected(self):
        self.koocli.push({'publicips':[]})
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(bandwidth_size_mbps=100)
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertIn('计费方式',ctx.exception.message)
        self.assertIn('bandwidth',ctx.exception.message)
        self.assertIn('traffic',ctx.exception.message)
        self.assertEqual(self.koocli.calls,[('EIP','ListPublicips',{'limit':100})])

    async def test_purchase_without_bandwidth_is_rejected_as_user_decision(self):
        self.koocli.push({'publicips':[]})
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(billing_method='bandwidth')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertIn('用户决策',ctx.exception.message)
        self.assertIn('收费',ctx.exception.message)   # the guard forces the charge notice
        self.assertEqual(self.koocli.calls,[('EIP','ListPublicips',{'limit':100})])

    async def test_chosen_bandwidth_flows_through_preview(self):
        self.koocli.push({'publicips':[]})
        result=await self.service.ensure_publicip(billing_method='bandwidth',bandwidth_size_mbps=50)
        self.assertEqual(result['eip']['bandwidth_size_mbps'],50)

    async def test_traffic_method_preview_execute_and_peak_cap(self):
        self.koocli.push({'publicips':[]})
        preview=await self.service.ensure_publicip(billing_method='traffic',bandwidth_size_mbps=100)
        self.assertEqual(preview['billing_method'],'traffic')
        self.assertIn('按流量计费',preview['billing']['method'])
        self.assertIn('0.64',preview['billing']['unit_price_reference'])
        self.assertIn('300Mbps',preview['billing']['traffic_limit'])
        self.koocli.push({'publicips':[]})
        self.koocli.push({'publicip':{'id':'e-10','status':'ACTIVE','public_ip_address':'10.0.0.1'}})
        self.koocli.push({})
        result=await self.service.ensure_publicip(billing_method='traffic',bandwidth_size_mbps=100,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['mode'],'created')
        service,operation,params=self.koocli.calls[-2]
        self.assertEqual(operation,'CreatePublicip')
        self.assertEqual(params['bandwidth']['charge_mode'],'traffic')
        self.assertEqual(params['bandwidth']['size'],100)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='traffic',bandwidth_size_mbps=500)
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertIn('300',ctx.exception.message)   # official per-EIP traffic-mode peak cap

    async def test_postpaid_execute_creates_and_tags(self):
        self.koocli.push({'publicips':[]})
        preview=await self.service.ensure_publicip(name='app-eip',billing_method='bandwidth',bandwidth_size_mbps=300)
        self.assertEqual(preview['eip']['alias'],'app-eip')
        self.koocli.push({'publicips':[]})
        self.koocli.push({'publicip':{'id':'e-9','status':'ACTIVE','public_ip_address':'9.9.9.9',
                                      'bandwidth':{'size':300,'share_type':'PER','charge_mode':'bandwidth'}}})
        self.koocli.push({})
        result=await self.service.ensure_publicip(name='app-eip',billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
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
        preview=await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300)
        self.assertEqual(preview['mode'],'confirmation_required')
        self.assertTrue(preview['plan_id'])
        self.assertEqual(self.koocli.calls,[])

    async def test_invalid_arguments_rejected_before_any_call(self):
        for case in ({'billing_method':'x'},{'billing_method':'prePaid'},{'bandwidth_size_mbps':4},{'bandwidth_size_mbps':1001},
                     {'bandwidth_size_mbps':'300'},{'bandwidth_size_mbps':None},{'name':123},{'name':'x'*65},
                     {'billing_method':'traffic','bandwidth_size_mbps':301}):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.ensure_publicip(prefer_idle=False,**case)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_write_gate_blocks_execution(self):
        preview=await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300)
        os.environ['SUPABASE_ENABLE_WRITES']='false'
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='true'
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_broken_plan_refused_and_left_prepared(self):
        preview=await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300)
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id='bogus')
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=100,
                                               confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')
        self.koocli.push({'publicip':{'id':'e-5','public_ip_address':'5.5.5.5'}})
        self.koocli.push({})
        await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(len(self.koocli.calls),2)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_write_failure_keeps_unknown(self):
        preview=await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300)
        self.koocli.push(McpToolError('MCP_CLI_ERROR','boom'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.assertEqual(ctx.exception.recovery['category'],'submission_unknown')
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    async def test_tag_failure_after_create_keeps_unknown(self):
        preview=await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300)
        self.koocli.push({'publicip':{'id':'e-7','public_ip_address':'7.7.7.7'}})
        self.koocli.push(McpToolError('MCP_CLI_ERROR','tag failed'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.ensure_publicip(prefer_idle=False,billing_method='bandwidth',bandwidth_size_mbps=300,confirm=True,plan_id=preview['plan_id'])
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
