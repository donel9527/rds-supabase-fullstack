import os
import tempfile
import unittest
from pathlib import Path
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient, flatten_params
from mcp_server_supabase.service.ssl_cert import SslCertService, SCM_REGION, UNLOCATED_NOTE

CERT_ROW={'id':'scs1794734768375','name':'fixture-cert','domain':'www.fitz-liul.com','sans':None,
          'type':'DV_SSL_CERT_BASIC','brand':'SYMANTEC','status':'PAID','expire_time':None,
          'domain_type':'SINGLE_DOMAIN','domain_count':1,'enterprise_project_id':'0',
          'deploy_support':True,'validity_period':1,'signature_algorithm':'SHA256WithRSA2048',
          'wildcard_count':0,'description':'dropped-by-whitelist'}
CERT_VIEW={'id':'scs1794734768375','name':'fixture-cert','domain':'www.fitz-liul.com','sans':None,
           'type':'DV_SSL_CERT_BASIC','brand':'SYMANTEC','status':'PAID','expire_time':None,
           'domain_type':'SINGLE_DOMAIN','domain_count':1,'enterprise_project_id':'0'}
APPLY=dict(apply_domain='www.example.com',domain_method='DNS',applicant_name='Fitz',
           applicant_email='ops@example.com',applicant_phone='13800000000')


class FakeScmCli:
    def __init__(self):
        self.region=SCM_REGION
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


class SslCertServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.koocli=FakeScmCli()
        self.service=SslCertService(self.koocli)

    async def purchase(self,**overrides):
        kwargs=dict(cert_brand='TRUSTASIA',cert_type='DV_SSL_CERT',domain_type='SINGLE_DOMAIN',
                    effective_time=1,order_number=1,domain_numbers=1,is_auto_pay=False)
        kwargs.update(overrides)
        return await self.service.purchase_cert(**kwargs)

    def test_service_pins_scm_region_regardless_of_env(self):
        os.environ['HUAWEICLOUD_REGION']='cn-east-3'
        service=SslCertService()
        self.assertEqual(service.koocli.region,'cn-north-4')
        argv=KoocliClient(binary='/usr/local/bin/hcloud',region=SCM_REGION).argv('SCM','ListCertificates',{'limit':50})
        self.assertIn('--cli-region=cn-north-4',argv)
        self.assertNotIn('--cli-region=cn-east-3',argv)
        argv=KoocliClient(binary='/usr/local/bin/hcloud',region='').argv('SCM','ListCertificates',{})
        self.assertEqual([item for item in argv if item.startswith('--cli-region')],[])

    async def test_list_certificates_whitelist_note_and_limit_flag(self):
        self.koocli.push({'certificates':[CERT_ROW,'broken']})
        result=await self.service.list_certificates()
        self.assertEqual(result['total'],2)
        self.assertEqual(result['data']['certificates'][0],CERT_VIEW)
        self.assertNotIn('deploy_support',result['data']['certificates'][0])
        self.assertEqual(result['data']['certificates'][1],{field:None for field in CERT_VIEW})
        self.assertEqual(self.koocli.calls,[('SCM','ListCertificates',{'limit':50})])
        self.assertIn('cn-north-4',result['note'])
        self.assertIn('PAID',result['note'])
        self.assertIn('change_supabase_ssl',result['note'])

    async def test_list_certificates_empty(self):
        self.koocli.push({'certificates':[]})
        result=await self.service.list_certificates()
        self.assertEqual(result['data'],{'certificates':[]})
        self.assertEqual(result['total'],0)

    async def test_list_limit_bounds_and_unreadable_fail_closed(self):
        for bad in (0,101,'50',2.5):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.list_certificates(bad)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        for broken in ({'certificates':'broken'},{},None):
            self.koocli.push(broken)
            with self.assertRaises(McpToolError) as ctx:
                await self.service.list_certificates()
            self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
            self.assertEqual(ctx.exception.message,'SCM certificate list unreadable')
        self.assertEqual([c[2] for c in self.koocli.calls],3* [{'limit':50}])
        self.koocli.push({'certificates':[]})
        await self.service.list_certificates(100)
        self.assertEqual(self.koocli.calls[-1],('SCM','ListCertificates',{'limit':100}))

    async def test_list_failure_propagates_structured_error(self):
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI ListCertificates failed with exit code 1'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.list_certificates()
        self.assertEqual(ctx.exception.code,'MCP_CLI_ERROR')

    async def test_purchase_invalid_arguments_rejected_before_any_call(self):
        for case in ({'cert_brand':'DIGICERT'},{'cert_type':'FREE'},{'domain_type':'MULTI'},
                     {'effective_time':0},{'effective_time':11},{'effective_time':'1'},
                     {'order_number':0},{'order_number':101},{'order_number':'2'},
                     {'domain_numbers':2,'domain_type':'SINGLE_DOMAIN'},
                     {'domain_numbers':2,'domain_type':'WILDCARD'},
                     {'domain_numbers':1,'domain_type':'MULTI_DOMAIN'},
                     {'domain_numbers':101,'domain_type':'MULTI_DOMAIN'},
                     {'is_auto_pay':'yes'},{'is_auto_pay':1}):
            with self.assertRaises(McpToolError) as ctx:
                await self.purchase(**case)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_partial_apply_block_is_rejected_with_named_fields(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(apply_domain='www.example.com',domain_method='DNS')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        for name in ('applicant_name','applicant_email','applicant_phone'):
            self.assertIn(name,ctx.exception.message)
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(apply_domain='www.example.com',domain_method='DNS',
                                applicant_name='Fitz',applicant_email='no-at-sign',applicant_phone='13800000000')
        self.assertIn('applicant_email',ctx.exception.message)
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(apply_domain='www.example.com',domain_method='dns',
                                applicant_name='Fitz',applicant_email='ops@example.com',applicant_phone='13800000000')
        self.assertIn('domain_method',ctx.exception.message)
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(apply_domain='www.example.com',domain_method='File',
                                applicant_name='',applicant_email='ops@example.com',applicant_phone='13800000000')
        self.assertIn('applicant_name',ctx.exception.message)
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(apply_domain='www.example.com',domain_method='File',
                                applicant_name='Fitz',applicant_email='ops@example.com',applicant_phone='no-digits')
        self.assertIn('applicant_phone',ctx.exception.message)
        self.assertEqual(self.koocli.calls,[])

    async def test_preview_returns_plan_id_without_calls(self):
        result=await self.purchase()
        self.assertEqual(result['status'],'preview')
        self.assertEqual(result['execution'],'not_executed')
        self.assertTrue(result['plan_id'])
        self.assertEqual(result['params'],{'cert_brand':'TRUSTASIA','cert_type':'DV_SSL_CERT',
                                           'domain_type':'SINGLE_DOMAIN','effective_time':1,
                                           'order_number':1,'domain_numbers':1,'is_auto_pay':False})
        self.assertEqual(result['billing'],{'免费档':'DV_SSL_CERT_BASIC 免订单费',
                                            '付费档':'按 品牌×类型×年限×张数 计费',
                                            '支付':'is_auto_pay=true 自动扣款；false 生成待支付订单，须控制台/费用中心支付后交付'})
        self.assertIsNone(result['apply'])
        self.assertEqual(len(result['impact']),3)
        self.assertEqual(self.koocli.calls,[])

    async def test_preview_with_apply_block_and_free_tier(self):
        result=await self.purchase(cert_brand='SYMANTEC',cert_type='DV_SSL_CERT_BASIC',**APPLY)
        self.assertEqual(result['status'],'preview')
        self.assertEqual(result['apply']['apply_domain'],'www.example.com')
        self.assertEqual(result['apply']['applicant_email'],'ops@example.com')
        self.assertIn('File',result['apply']['note'])
        self.assertIn('公网 IP 证书仅支持 File',result['apply']['note'])
        self.assertTrue(result['plan_id'])
        self.assertEqual(self.koocli.calls,[])

    async def test_confirm_subscribes_without_apply(self):
        preview=await self.purchase(cert_brand='SYMANTEC',cert_type='DV_SSL_CERT_BASIC')
        self.koocli.push({'order_id':'CS12345'})
        result=await self.purchase(cert_brand='SYMANTEC',cert_type='DV_SSL_CERT_BASIC',
                                   confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'subscribed')
        self.assertEqual(result['order_id'],'CS12345')
        self.assertIsNone(result['certificate_id'])
        self.assertEqual(result['subscribe_response'],{'order_id':'CS12345'})
        self.assertFalse(result['apply']['attempted'])
        self.assertIn('未提供申请块',result['apply']['reason'])
        self.assertIn('免费档',result['note'])
        self.assertIn('订单号 CS12345',result['note'])
        service,operation,params=self.koocli.last()
        self.assertEqual((service,operation),('SCM','SubscribeCertificate'))
        self.assertEqual(params,{'agree_privacy_protection':True,'cert_brand':'SYMANTEC',
                                 'cert_type':'DV_SSL_CERT_BASIC','domain_type':'SINGLE_DOMAIN',
                                 'domain_numbers':1,'effective_time':1,'order_number':1,
                                 'is_auto_pay':False})
        flags=set(flatten_params(params))
        self.assertIn('--agree_privacy_protection=True',flags)
        self.assertIn('--cert_type=DV_SSL_CERT_BASIC',flags)
        self.assertIn('--is_auto_pay=False',flags)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_confirm_chains_subscribe_then_apply(self):
        preview=await self.purchase(**APPLY)
        self.koocli.push({'order_id':'CS2','certificate_id':'scs3000'})
        self.koocli.push({'apply_result':'ok'})
        result=await self.purchase(**APPLY,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'subscribed_and_applied')
        self.assertEqual(result['apply'],{'attempted':True,'certificate_id':'scs3000',
                                           'response':{'apply_result':'ok'}})
        self.assertEqual([c[1] for c in self.koocli.calls],['SubscribeCertificate','ApplyCertificate'])
        service,operation,params=self.koocli.calls[1]
        self.assertEqual((service,operation),('SCM','ApplyCertificate'))
        self.assertEqual(params,{'certificate_id':'scs3000','agree_privacy_protection':True,
                                 'domain':'www.example.com','domain_method':'DNS',
                                 'applicant_name':'Fitz','applicant_email':'ops@example.com',
                                 'applicant_phone':'13800000000'})
        flags=set(flatten_params(params))
        self.assertIn('--certificate_id=scs3000',flags)
        self.assertIn('--agree_privacy_protection=True',flags)
        self.assertIn('change_supabase_ssl',result['note'])
        self.assertIn('待支付订单',result['note'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_confirm_locates_cert_via_list_fallback(self):
        preview=await self.purchase(**APPLY)
        self.koocli.push({'order_id':'CS7'})
        self.koocli.push({'certificates':[CERT_ROW,
                                          {'id':'scs7777','domain':'www.example.com','status':'PAID','expire_time':1},
                                          {'id':'scs8888','domain':'www.example.com','status':'ISSUED'},
                                          {'id':'scs9998','sans':['www.example.com'],'status':'PAID'},
                                          {'id':'scs9999','domain':'www.example.com','status':'PAID','expire_time':4102444800}]})
        self.koocli.push({'apply':'ok'})
        result=await self.purchase(**APPLY,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'subscribed_and_applied')
        self.assertEqual(result['apply']['certificate_id'],'scs9999')
        self.assertEqual([c[1] for c in self.koocli.calls],['SubscribeCertificate','ListCertificates','ApplyCertificate'])
        self.assertEqual(self.koocli.calls[1][2],{'limit':100})

    async def test_confirm_degrades_when_certificate_unlocatable(self):
        preview=await self.purchase(**APPLY)
        self.koocli.push({'order_id':'CS8'})
        self.koocli.push({'certificates':[]})
        result=await self.purchase(**APPLY,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'subscribed_apply_unlocated')
        self.assertEqual(result['apply'],{'attempted':False,'reason':UNLOCATED_NOTE})
        self.assertIn('list_ssl_certificates',result['note'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')
        preview=await self.purchase(**APPLY,cert_brand='VTRUS')
        self.koocli.push({'order_id':'CS9'})
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI ListCertificates failed with exit code 1'))
        result=await self.purchase(**APPLY,cert_brand='VTRUS',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'subscribed_apply_unlocated')
        self.assertEqual([c[1] for c in self.koocli.calls],
                         ['SubscribeCertificate','ListCertificates','SubscribeCertificate','ListCertificates'])

    async def test_apply_failure_recorded_not_raised(self):
        preview=await self.purchase(**APPLY)
        self.koocli.push({'order_id':'CS5','certificate_id':'scs5'})
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI ApplyCertificate failed with exit code 1: rejected'))
        result=await self.purchase(**APPLY,confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'subscribed_apply_failed')
        self.assertEqual(result['apply']['attempted'],True)
        self.assertEqual(result['apply']['certificate_id'],'scs5')
        self.assertIn('rejected',result['apply']['error'])
        self.assertIn('申请提交失败',result['note'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_write_gate_blocks_execution(self):
        preview=await self.purchase()
        os.environ['SUPABASE_ENABLE_WRITES']='false'
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='true'
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_broken_or_changed_plan_refused_and_left_prepared(self):
        preview=await self.purchase()
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(confirm=True,plan_id='bogus')
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        for changed in ({'order_number':2},{'cert_brand':'VTRUS'},dict(APPLY)):
            with self.assertRaises(McpToolError) as ctx:
                await self.purchase(**changed,confirm=True,plan_id=preview['plan_id'])
            self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')
        self.koocli.push({'order_id':'CS10','certificate_id':'scs10'})
        await self.purchase(confirm=True,plan_id=preview['plan_id'])
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual([c[1] for c in self.koocli.calls],['SubscribeCertificate'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_subscribe_failure_keeps_unknown(self):
        preview=await self.purchase()
        self.koocli.push(McpToolError('MCP_CLI_ERROR','boom'))
        with self.assertRaises(McpToolError) as ctx:
            await self.purchase(confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.assertEqual(ctx.exception.recovery['category'],'submission_unknown')
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    def test_limited_bounds_unknown_responses(self):
        fat={'order_id':'CS1','blob':object(),'nested':{'inner':'v','deep':{'x':'y'}},
             'list':['a',{'certificate_id':'scs1'},'b'],'extra':'v'}
        view=SslCertService._limited(fat)
        self.assertEqual(view['order_id'],'CS1')
        self.assertTrue(view['blob'])
        self.assertIsInstance(view['blob'],str)
        self.assertEqual(view['nested'],{'inner':'v','deep':{'x':'y'}})
        self.assertEqual(view['list'],['a',{'certificate_id':'scs1'},'b'])
        self.assertEqual(SslCertService._limited('raw'),'raw')
        self.assertEqual(SslCertService._limited(None),None)
        self.assertEqual(SslCertService._find_first(fat,('order_id','orderId')),'CS1')
        self.assertEqual(SslCertService._find_first({'data':{'certificates':[{'certificate_id':'scs9'}]}},
                                                    ('certificate_id','cert_id','id')),'scs9')
        self.assertEqual(SslCertService._find_first({'id':123},('certificate_id','cert_id','id')),'123')
        self.assertIsNone(SslCertService._find_first({'data':'flat'},('certificate_id','cert_id','id')))


if __name__=='__main__':
    unittest.main()
