import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.service.obs import ObsService

PROBE_NOTE='公共状态仅对前 10 个桶检测；Public 桶有匿名公开风险，尽量不用（优先私有桶）'
LS_TEXT='\n'.join(['Start at 2026-11-15 08:00:00.000000000 +0000 UTC','',
                   'Bucket                   CreationDate             Location       BucketType     ',
                   'obs://alpha-bucket       2026-05-01T10:20:30Z     cn-east-3      OBJECT         ',
                   'obs://beta-bucket        2026-06-02T11:22:33Z     cn-east-3      OBJECT         ',
                   'obs://gamma-bucket       2026-07-03T12:33:44Z     cn-north-4     OBJECT         ',
                   '',
                   'Total count: 3'])


class FakeObsCli:
    def __init__(self,security_token=''):
        self.region='cn-east-3'
        self.token='fixture'
        self._security_token=security_token
        self.calls=[]
        self.results=[]

    def push(self,result):
        self.results.append(result)

    async def obs(self,operation,args=None,flags=None,region=None):
        self.calls.append((operation,args,flags))
        result=self.results.pop(0)
        if isinstance(result,Exception):raise result
        return result


class FakeProcess:
    def __init__(self,returncode=0,stdout=b'',stderr=b''):
        self.returncode=None
        self._returncode=returncode
        self._stdout=stdout
        self._stderr=stderr
        self.killed=False

    async def communicate(self):
        self.returncode=self._returncode
        return self._stdout,self._stderr

    async def wait(self):
        self.returncode=self._returncode

    def kill(self):
        self.killed=True


class ObsServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=os.environ.copy()
        os.environ['SUPABASE_STATE_FILE']=str(Path(self.tmp.name)/'state.db')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='false'
        self.addCleanup(lambda:os.environ.clear() or os.environ.update(self.env))
        self.koocli=FakeObsCli()
        self.service=ObsService(self.koocli)

    def test_credential_mode_temporary_and_persistent(self):
        service=ObsService(FakeObsCli(security_token='tok'))
        mode=service.credential_mode()
        self.assertTrue(mode['temporary'])
        self.assertEqual(mode['detail'],'当前环境为临时凭证（含 SecurityToken），不能作为应用的持久存储凭据')
        self.assertEqual(mode['notice'],'请用户提供长期 AK/SK（经本地请求文件写入 storage_component，或更新环境变量）后再对接，'
                                        '否则凭证过期后应用将无法访问 OBS；可先做一次读测试确认现有凭证的 OBS 权限')
        mode=self.service.credential_mode()
        self.assertFalse(mode['temporary'])
        self.assertEqual(mode['detail'],'环境凭证为长期 AK/SK，可直接复用')
        self.assertIsNone(mode['notice'])

    def test_bucket_name_for_sanitizes_and_bounds(self):
        self.assertEqual(self.service.bucket_name_for('My App!测试'),'supabase-my-app')
        self.assertEqual(self.service.bucket_name_for('ABC-def_1.2'),'supabase-abc-def-1-2')
        self.assertEqual(self.service.bucket_name_for('--My--App--'),'supabase-my-app')
        for short in ('','a','!!'):
            name=self.service.bucket_name_for(short)
            self.assertRegex(name,r'^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$')
        name=self.service.bucket_name_for('x'*100)
        self.assertEqual(len(name),56)
        self.assertTrue(name.startswith('supabase-'))
        self.assertLessEqual(len(name),63)
        name=self.service.bucket_name_for('a'*46+'-b'*10)
        self.assertEqual(len(name),55)
        self.assertTrue(name.endswith('a'))

    def test_new_bucket_spec_baseline(self):
        self.assertEqual(self.service.new_bucket_spec('supabase-x'),{
            'bucket_name':'supabase-x',
            'storage_class':'标准存储（standard，固定）',
            'bucket_type':'私有（private，固定）',
            'redundancy':'多AZ存储（multi-az，默认）',
            'block_public_access':'开启（默认开启，固定不可修改）',
            'region':'cn-east-3（与环境当前项目保持一致，自动推导）',
            'enterprise_project':'default（默认企业项目）',
            'storage_component_hint':{'bucket':'supabase-x','ak_sk':'经本地请求文件提供'}})
        self.assertEqual(self.service.new_bucket_spec('supabase-x','single_az')['redundancy'],'单AZ存储（single_az）')

    async def test_list_buckets_parses_and_probes_status(self):
        self.koocli.push(LS_TEXT)
        self.koocli.push('Public status of bucket "alpha-bucket": Public')
        self.koocli.push('Public status of bucket "beta-bucket": not public')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','status probe failed'))
        result=await self.service.list_buckets()
        self.assertEqual([b['name'] for b in result['data']],['beta-bucket','gamma-bucket','alpha-bucket'])   # 私有桶优先排序，Public 殿后
        self.assertEqual(result['data'][0]['location'],'cn-east-3')
        self.assertEqual(result['data'][1]['location'],'cn-north-4')
        self.assertEqual([b['public_status'] for b in result['data']],['Private','未知','Public'])
        self.assertIsNone(result['data'][0]['risk_note'])
        self.assertIsNone(result['data'][1]['risk_note'])
        self.assertIsNotNone(result['data'][2]['risk_note'])
        self.assertTrue(result['read_test']['passed'])
        self.assertEqual(result['note'],PROBE_NOTE)
        self.assertEqual([c[0] for c in self.koocli.calls],
                         ['ls','get-bucket-public-status','get-bucket-public-status','get-bucket-public-status'])
        self.assertEqual(self.koocli.calls[1][1],['obs://alpha-bucket'])
        self.assertEqual(self.koocli.calls[3][1],['obs://gamma-bucket'])

    async def test_list_buckets_empty_output_means_no_buckets(self):
        self.koocli.push('Start at 2026-11-15 08:00:00.000000000 +0000 UTC\n\nBucket number: 0')
        result=await self.service.list_buckets()
        self.assertEqual(result,{'data':[],'read_test':{'passed':True,'detail':'ls 成功，无桶'}})
        self.assertEqual([c[0] for c in self.koocli.calls],['ls'])

    async def test_list_buckets_error_is_returned_not_raised(self):
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI ls failed with exit code 1'))
        result=await self.service.list_buckets()
        self.assertEqual(result,{'data':[],'read_test':{'passed':False,'detail':'KooCLI ls failed with exit code 1'},
                                 'note':PROBE_NOTE,'error':'KooCLI ls failed with exit code 1'})

    async def test_list_buckets_probes_only_first_ten(self):
        rows=['Bucket                  Creation Time          Storage Class      Location      Obs Version']
        for index in range(11):
            rows.append(f'obs://bucket-{index:02d}       2026-05-01T10:20:30Z     cn-east-3      OBJECT')
        self.koocli.push('\n'.join(rows))
        for _ in range(10):
            self.koocli.push('The bucket is not public')
        result=await self.service.list_buckets()
        self.assertEqual(len(result['data']),11)
        self.assertEqual(len(self.koocli.calls),11)
        self.assertEqual(result['data'][9]['public_status'],'Private')
        self.assertEqual(result['data'][10]['public_status'],'未知')
        self.assertIsNone(result['data'][10]['risk_note'])

    async def test_discover_storage_composes_options(self):
        self.koocli.push(LS_TEXT)
        self.koocli.push('Public status of bucket "alpha-bucket": Public')
        self.koocli.push('Public status of bucket "beta-bucket": not public')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','status probe failed'))
        result=await self.service.discover_storage('My App')
        self.assertEqual(result['mode'],'storage_options')
        self.assertFalse(result['credential']['temporary'])
        self.assertEqual(result['credential']['detail'],'环境凭证为长期 AK/SK，可直接复用')
        self.assertEqual(result['reuse']['option'],'复用已有桶')
        self.assertEqual(result['reuse']['note'],'私有桶优先；公共桶提示风险尽量不用；无可复用桶则转新建')
        self.assertEqual([b['name'] for b in result['reuse']['buckets']],['beta-bucket','gamma-bucket','alpha-bucket'])
        self.assertTrue(result['reuse']['read_test']['passed'])
        self.assertEqual(result['new_bucket']['option'],'新建桶（推荐、默认）')
        self.assertEqual(result['new_bucket']['note'],'全新私有桶，完全隔离，安全可靠')
        self.assertEqual(result['new_bucket']['spec']['bucket_name'],'supabase-my-app')
        self.assertIn('create_supabase_with_new_instance',result['storage_component_note'])
        self.assertIn('补开对接',result['storage_component_note'])

    async def test_discover_storage_defaults_and_tolerates_failure(self):
        self.koocli.push(McpToolError('MCP_CLI_ERROR','ls denied'))
        result=await self.service.discover_storage()
        self.assertEqual(result['mode'],'storage_options')
        self.assertEqual(result['reuse']['buckets'],[])
        self.assertFalse(result['reuse']['read_test']['passed'])
        self.assertEqual(result['new_bucket']['spec']['bucket_name'],'supabase-supabase-app')

    async def test_create_bucket_preview_makes_no_calls(self):
        result=await self.service.create_bucket('My App')
        self.assertEqual(result['status'],'confirmation_required')
        self.assertEqual(result['execution'],'not_executed')
        self.assertEqual(result['spec']['bucket_name'],'supabase-my-app')
        self.assertEqual(result['spec']['redundancy'],'多AZ存储（multi-az，默认）')
        self.assertEqual(result['warnings'],['新桶立即产生少量存储计费',
                                             '推荐在创建请求携带 storage_component 时一次挂载成型；未启用的应用事后可经 update_supabase_storage 补开对接（桶名+AK/SK 全量凭据）'])
        self.assertTrue(result['plan_id'])
        self.assertEqual(self.koocli.calls,[])

    async def test_create_bucket_executes_mb_and_blocks_public_access(self):
        preview=await self.service.create_bucket('My App')
        self.koocli.push('Create bucket successfully')
        self.koocli.push('Set the public-access-block of bucket successfully')
        result=await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['bucket']['bucket_name'],'supabase-my-app')
        self.assertEqual(result['bucket']['block_public_access'],'开启（默认开启，固定不可修改）')
        self.assertEqual(result['storage_component_hint'],{'bucket':'supabase-my-app','ak_sk':'经本地请求文件提供'})
        self.assertEqual(result['note'],'桶已创建（并已设置阻止公共访问）；把 bucket 与持久 AK/SK 经本地请求文件写入 storage_component，'
                                        '随 create_supabase_application 提交完成对接')
        self.assertEqual([c[0] for c in self.koocli.calls],['mb','put-public-access-block'])
        operation,args,flags=self.koocli.calls[0]
        self.assertEqual((operation,args),('mb',['obs://supabase-my-app']))
        self.assertEqual(set(flags),{'-acl=private','-location=cn-east-3','-sc=standard','-epid=0','-az=multi-az'})
        operation,args,flags=self.koocli.calls[1]
        self.assertEqual((operation,args),('put-public-access-block',['obs://supabase-my-app']))
        self.assertEqual(flags,['-public-access-block-configuration=BlockPublicAcls=true,'
                                 'IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_create_bucket_retries_with_suffix_on_conflict(self):
        preview=await self.service.create_bucket('My App')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI mb failed with exit code 1: The bucket already exists'))
        self.koocli.push('Create bucket successfully')
        self.koocli.push('Set the public-access-block of bucket successfully')
        result=await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'ok')
        name=result['bucket']['bucket_name']
        self.assertTrue(name.startswith('supabase-my-app-'))
        self.assertEqual(len(name.rsplit('-',1)[1]),4)
        self.assertLessEqual(len(name),63)
        self.assertEqual([c[0] for c in self.koocli.calls],['mb','mb','put-public-access-block'])
        self.assertEqual(self.koocli.calls[1][1],[f'obs://{name}'])
        self.assertEqual(result['storage_component_hint']['bucket'],name)

    async def test_create_bucket_retries_on_chinese_and_conflict_markers(self):
        preview=await self.service.create_bucket('Retry 测试')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI mb failed: 桶已存在'))
        self.koocli.push('Create bucket successfully')
        self.koocli.push('Set the public-access-block of bucket successfully')
        result=await self.service.create_bucket('Retry 测试',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'ok')
        self.assertTrue(result['bucket']['bucket_name'].startswith('supabase-retry-'))
        preview=await self.service.create_bucket('App Two')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI mb failed: 409 Conflict'))
        self.koocli.push('Create bucket successfully')
        self.koocli.push('Set the public-access-block of bucket successfully')
        result=await self.service.create_bucket('App Two',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'ok')
        self.assertTrue(result['bucket']['bucket_name'].startswith('supabase-app-two-'))

    async def test_create_bucket_conflict_exhausts_retries(self):
        preview=await self.service.create_bucket('My App')
        for _ in range(3):
            self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI mb failed: 409 conflict'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_CLI_ERROR')
        self.assertEqual([c[0] for c in self.koocli.calls],['mb','mb','mb'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    async def test_create_bucket_unrelated_failure_raises_as_is(self):
        preview=await self.service.create_bucket('My App')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI mb failed with exit code 1: access denied'))
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_CLI_ERROR')
        self.assertIn('access denied',ctx.exception.message)
        self.assertEqual(self.koocli.calls[0][0],'mb')
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'unknown')

    async def test_public_access_block_failure_recorded_in_note(self):
        preview=await self.service.create_bucket('My App')
        self.koocli.push('Create bucket successfully')
        self.koocli.push(McpToolError('MCP_CLI_ERROR','KooCLI put-public-access-block failed with exit code 1: denied'))
        result=await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['bucket']['bucket_name'],'supabase-my-app')
        self.assertIn('阻止公共访问设置未成功',result['note'])
        self.assertIn('KooCLI put-public-access-block failed with exit code 1: denied',result['note'])
        self.assertIn('需控制台补设',result['note'])
        self.assertIn('storage_component',result['note'])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')

    async def test_create_bucket_single_az_omits_az_flag(self):
        preview=await self.service.create_bucket('My App',redundancy='single_az')
        self.assertEqual(preview['spec']['redundancy'],'单AZ存储（single_az）')
        self.koocli.push('Create bucket successfully')
        self.koocli.push('Set the public-access-block of bucket successfully')
        result=await self.service.create_bucket('My App',redundancy='single_az',confirm=True,plan_id=preview['plan_id'])
        flags=self.koocli.calls[0][2]
        self.assertNotIn('-az=multi-az',flags)
        self.assertEqual(set(flags),{'-acl=private','-location=cn-east-3','-sc=standard','-epid=0'})
        self.assertEqual(result['bucket']['redundancy'],'单AZ存储（single_az）')

    async def test_invalid_arguments_rejected_before_any_call(self):
        for case in ({'app_name':123},{'app_name':None},{'app_name':''},{'app_name':'x'*65},
                     {'app_name':'ok','redundancy':'dual_az'},{'app_name':'ok','redundancy':'MULTI_AZ'}):
            with self.assertRaises(McpToolError) as ctx:
                await self.service.create_bucket(**case)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_write_gate_blocks_execution(self):
        preview=await self.service.create_bucket('My App')
        os.environ['SUPABASE_ENABLE_WRITES']='false'
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        os.environ['SUPABASE_ENABLE_WRITES']='true';os.environ['HUAWEICLOUD_MCP_READ_ONLY']='true'
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_READ_ONLY')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')

    async def test_broken_plan_refused_and_left_prepared(self):
        preview=await self.service.create_bucket('My App')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',confirm=True,plan_id='bogus')
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',redundancy='single_az',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(self.koocli.calls,[])
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'prepared')
        self.koocli.push('Create bucket successfully')
        self.koocli.push('Set the public-access-block of bucket successfully')
        await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        with self.assertRaises(McpToolError) as ctx:
            await self.service.create_bucket('My App',confirm=True,plan_id=preview['plan_id'])
        self.assertEqual(ctx.exception.code,'MCP_GUARDRAIL_BLOCKED')
        self.assertEqual(len(self.koocli.calls),2)
        self.assertEqual(self.service.plans.inspect(preview['plan_id'])['state'],'accepted')


class KoocliObsChannelTests(unittest.IsolatedAsyncioTestCase):
    def client(self,**kwargs):
        defaults=dict(binary='/usr/local/bin/hcloud',region='cn-east-3',ak='AK',sk='SK',
                      security_token='',timeout=5)
        defaults.update(kwargs)
        return KoocliClient(**defaults)

    async def test_obs_builds_obsutil_argv_and_returns_plain_text(self):
        proc=FakeProcess(stdout=b'  Create bucket successfully \n')
        runner=AsyncMock(return_value=proc)
        with patch('asyncio.create_subprocess_exec',runner):
            text=await self.client().obs('mb',args=['obs://bucket-a'],flags=['-acl=private','-sc=standard'])
        self.assertEqual(text,'Create bucket successfully')
        self.assertEqual(list(runner.call_args[0]),
                         ['/usr/local/bin/hcloud','OBS','mb','obs://bucket-a','-acl=private','-sc=standard',
                          '-i=AK','-k=SK','-e=obs.cn-east-3.myhuaweicloud.com'])

    async def test_obs_injects_security_token_and_skips_blank_region(self):
        proc=FakeProcess(stdout=b'ok')
        runner=AsyncMock(return_value=proc)
        with patch('asyncio.create_subprocess_exec',runner):
            await self.client(security_token='TOK',region='').obs('ls')
        self.assertEqual(list(runner.call_args[0]),
                         ['/usr/local/bin/hcloud','OBS','ls',
                          '-i=AK','-k=SK','-t=TOK'])

    async def test_obs_missing_binary_rejected_before_spawn(self):
        with self.assertRaises(McpToolError) as ctx:
            await self.client(binary='').obs('ls')
        self.assertEqual(ctx.exception.code,'MCP_CLI_MISSING')

    async def test_obs_failure_uses_shared_raise_failure(self):
        proc=FakeProcess(returncode=1,stdout=b'Error: bucket already exists')
        with patch('asyncio.create_subprocess_exec',AsyncMock(return_value=proc)):
            with self.assertRaises(McpToolError) as ctx:
                await self.client().obs('mb',args=['obs://bucket-a'])
        self.assertEqual(ctx.exception.code,'MCP_CLI_ERROR')
        self.assertIn('already exists',ctx.exception.message)

    async def test_obs_timeout_kills_process(self):
        class SlowProcess(FakeProcess):
            async def communicate(self):
                await asyncio.sleep(30)
        proc=SlowProcess()
        with patch('asyncio.create_subprocess_exec',AsyncMock(return_value=proc)):
            with self.assertRaises(McpToolError) as ctx:
                await self.client(timeout=0.05).obs('ls')
        self.assertEqual(ctx.exception.code,'MCP_CLI_TIMEOUT')
        self.assertTrue(proc.killed)

    async def test_obs_spawn_failure_maps_to_missing(self):
        with patch('asyncio.create_subprocess_exec',AsyncMock(side_effect=FileNotFoundError())):
            with self.assertRaises(McpToolError) as ctx:
                await self.client().obs('ls')
        self.assertEqual(ctx.exception.code,'MCP_CLI_MISSING')


if __name__=='__main__':
    unittest.main()
