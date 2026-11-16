import unittest
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.service.instance_catalog import InstanceCatalog, NetworkDiscovery, BasicOptionsDiscovery


class FakeKoocli:
    def __init__(self):
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


class InstanceCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from mcp_server_supabase.service.instance_catalog import InstanceCatalog
        self.koocli=FakeKoocli()
        self.eps_koocli=FakeKoocli()
        self.catalog=InstanceCatalog(self.koocli,self.eps_koocli)

    async def test_engine_versions_happy_path(self):
        rows=[{'id':'ds-15','name':'15'},{'id':'ds-17','name':'17'}]
        self.koocli.push({'dataStores':rows})
        result=await self.catalog.list_engine_versions()
        self.assertEqual(self.koocli.last(),('RDS','ListDatastores',{'database_name':'PostgreSQL'}))
        self.assertEqual(result['data'],rows)
        self.assertIn('create-with-new-instance',result['note'])
        self.assertIn('az_status',result['note'])

    async def test_flavors_happy_path_with_major_version(self):
        rows=[{'spec_code':'rds.pg.xlarge.arm','vcpus':4,'ram':16,
               'az_status':{'cn-east-3a':'normal'},'instance_mode':'single','version_name':'17'}]
        self.koocli.push({'flavors':rows})
        result=await self.catalog.list_flavors('17')
        self.assertEqual(self.koocli.last(),('RDS','ListFlavors',
                                             {'database_name':'PostgreSQL','version_name':'17'}))
        self.assertEqual(result['data'],rows)

    async def test_flavors_without_version_omits_the_key(self):
        self.koocli.push({'flavors':[]})
        result=await self.catalog.list_flavors()
        service,operation,params=self.koocli.last()
        self.assertEqual((service,operation),('RDS','ListFlavors'))
        self.assertEqual(params,{'database_name':'PostgreSQL'})
        self.assertNotIn('version_name',params)
        self.assertEqual(result['data'],[])

    async def test_flavors_rejects_non_major_versions_before_any_call(self):
        for bad in ('17.11.260901','','x','123'):
            with self.assertRaises(McpToolError) as ctx:
                await self.catalog.list_flavors(bad)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_storage_types_normalize_ha_mode_case(self):
        rows=[{'name':'ESSD','az_status':{'cn-east-3a':'normal'},'support_compute_group_type':['x86']}]
        self.koocli.push({'storage_type':rows})
        result=await self.catalog.list_storage_types('17','Single')
        self.assertEqual(self.koocli.last(),('RDS','ListStorageTypes',
                                             {'database_name':'PostgreSQL','version_name':'17','ha_mode':'single'}))
        self.assertEqual(result['data'],rows)
        self.koocli.push({'storage_type':rows})
        await self.catalog.list_storage_types('16','Ha')
        self.assertEqual(self.koocli.last()[2]['ha_mode'],'ha')
        self.assertEqual(self.koocli.last()[2]['version_name'],'16')

    async def test_storage_types_reject_bad_mode_and_missing_version(self):
        for ha_mode in ('replication','x','cluster'):
            with self.assertRaises(McpToolError) as ctx:
                await self.catalog.list_storage_types('17',ha_mode)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        with self.assertRaises(McpToolError) as ctx:
            await self.catalog.list_storage_types(None,'single')
        self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        for bad in ('17.11.260901','x'):
            with self.assertRaises(McpToolError) as ctx:
                await self.catalog.list_storage_types(bad,'ha')
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_missing_or_malformed_response_lists_fail_closed(self):
        self.koocli.push({'dataStores':None})
        with self.assertRaises(McpToolError) as ctx:
            await self.catalog.list_engine_versions()
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.koocli.push({})
        with self.assertRaises(McpToolError) as ctx:
            await self.catalog.list_flavors()
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')
        self.koocli.push({'storage_type':'broken'})
        with self.assertRaises(McpToolError) as ctx:
            await self.catalog.list_storage_types('17','ha')
        self.assertEqual(ctx.exception.code,'MCP_SDK_ERROR')

    async def test_koocli_errors_pass_through_unchanged(self):
        for method,args in ((self.catalog.list_engine_versions,()),
                            (self.catalog.list_flavors,('17',)),
                            (self.catalog.list_storage_types,('17','ha'))):
            self.koocli.push(McpToolError('MCP_CLI_ERROR','boom'))
            with self.assertRaises(McpToolError) as ctx:
                await method(*args)
            self.assertEqual(ctx.exception.code,'MCP_CLI_ERROR')

    async def test_data_passes_through_safe_sanitization(self):
        rows=[{'spec_code':'rds.pg.s1.xlarge','secret_key':'leak','nested':{'password':'leak','size':100}}]
        self.koocli.push({'flavors':rows})
        result=await self.catalog.list_flavors()
        self.assertEqual(result['data'],[{'spec_code':'rds.pg.s1.xlarge','nested':{'size':100}}])

    def _push_sources(self,versions=('15','17'),flavors=None,storage=None,vpcs=None,subnets=None,groups=None,eps='default'):
        """Push the six probe results in the implementation's call order:
        Datastores, Flavors, StorageTypes, Vpcs, Subnets, SecurityGroups.
        eps: 'default' (default project plus one business project), None (empty
        list), an Exception (query failure) or a raw response payload."""
        if eps=='default':
            eps={'enterprise_projects':[{'id':'cddc3f1f-6c3e-4d0f-a1f1-2b5bb2d6b2a6','name':'taurus-dev','description':'开发项目','status':1},
                                        {'id':'a9832d3a-8e3a-4d8f-9c2b-1f2e3d4c5b6a','name':'default','description':'默认企业项目','status':1}]}
        elif eps is None:
            eps={'enterprise_projects':[]}
        self.eps_koocli.push(eps)
        if flavors is None:
            flavors=[{'spec_code':'rds.pg.n1.medium.2','vcpus':'2','ram':4,'group_type':'general','instance_mode':'single',
                      'az_status':{'cn-east-3a':'normal','cn-east-3b':'sellout'}},
                     {'spec_code':'rds.pg.x1.large.4','vcpus':'4','ram':16,'group_type':'dedicated','instance_mode':'ha',
                      'az_status':{'cn-east-3a':'normal'}},
                     {'spec_code':'rds.pg.n1.large.2','vcpus':'4','ram':8,'group_type':'general','instance_mode':'single',
                      'az_status':{'cn-east-3b':'normal'}},
                     {'spec_code':'rds.pg.ex.large.2','vcpus':'2','ram':4,'group_type':'exotic','instance_mode':'single',
                      'az_status':{'cn-east-3a':'normal'}},
                     {'spec_code':'rds.pg.n1.xlarge.2','vcpus':'8','ram':16,'group_type':'general','instance_mode':'single',
                      'az_status':{'cn-east-3a':'sellout','cn-east-3b':'sellout'}}]
        if storage is None:
            storage=[{'name':'ULTRAHIGH','az_status':{'cn-east-3a':'normal'},'support_compute_group_type':['general','dedicated']},
                     {'name':'ESSD','az_status':{'cn-east-3a':'normal'},'support_compute_group_type':['general','dedicated','armFlavors']}]
        if vpcs is None:vpcs=[{'id':'vpc-1','name':'net-a'}]
        if subnets is None:subnets=[{'id':'subnet-1','name':'sub-a','vpc_id':'vpc-1'}]
        if groups is None:
            groups=[{'id':'sg-1','name':'db-dedicated','tags':[{'key':'AUTO_CREATE','value':'true'},{'key':'USE_FOR','value':'Supabase'}]},
                    {'id':'sg-2','name':'shared'}]
        self.koocli.push({'dataStores':[{'id':'ds-'+v,'name':v} for v in versions]})
        self.koocli.push({'flavors':flavors})
        self.koocli.push({'storage_type':storage})
        self.koocli.push(vpcs if isinstance(vpcs,Exception) else {'vpcs':vpcs})
        self.koocli.push(subnets if isinstance(subnets,Exception) else {'subnets':subnets})
        self.koocli.push(groups if isinstance(groups,Exception) else {'security_groups':groups})

    async def test_discover_db_instance_for_create_single_happy_path(self):
        self._push_sources()
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        self.assertEqual([c[1] for c in self.koocli.calls],
                         ['ListDatastores','ListFlavors','ListStorageTypes'])
        self.assertEqual(self.koocli.calls[2],('RDS','ListStorageTypes',
                                               {'database_name':'PostgreSQL','version_name':'17','ha_mode':'single'}))
        self.assertEqual(len(self.koocli.calls),3)  # network/group probes removed
        self.assertEqual(result['mode'],'Single')
        options=result['managed_instance_field_options']
        self.assertEqual(options['datastore.type'],{'fixed':'PostgreSQL'})
        self.assertEqual(options['datastore.version']['values'],['15','17'])
        self.assertEqual(options['datastore.version']['recommended'],'17')
        self.assertEqual(options['flavor_ref']['values'],
                         ['rds.pg.n1.medium.2','rds.pg.x1.large.4','rds.pg.n1.large.2','rds.pg.ex.large.2'])
        self.assertEqual(options['flavor_ref']['recommended'],'rds.pg.n1.medium.2')
        self.assertEqual(options['flavor_ref']['groups'],
                         [{'group_type':'general','label':'通用型','specs':[
                               {'spec_code':'rds.pg.n1.medium.2','vcpus':'2','ram':4,'instance_mode':'single','availability_zones':['cn-east-3a']},
                               {'spec_code':'rds.pg.n1.large.2','vcpus':'4','ram':8,'instance_mode':'single','availability_zones':['cn-east-3b']}]},
                          {'group_type':'dedicated','label':'独享型（仅云盘SSD支持）','specs':[
                               {'spec_code':'rds.pg.x1.large.4','vcpus':'4','ram':16,'instance_mode':'ha','availability_zones':['cn-east-3a']}]},
                          {'group_type':'exotic','label':'exotic','specs':[
                               {'spec_code':'rds.pg.ex.large.2','vcpus':'2','ram':4,'instance_mode':'single','availability_zones':['cn-east-3a']}]}])
        expanded=[spec['spec_code'] for group in options['flavor_ref']['groups'] for spec in group['specs']]
        self.assertEqual(sorted(expanded),sorted(options['flavor_ref']['values']))
        self.assertIn('分开单独询问',options['flavor_ref']['note'])
        self.assertIn('不截断',options['flavor_ref']['note'])
        self.assertEqual(options['volume.type']['values'],['ULTRAHIGH','ESSD'])
        self.assertEqual(options['volume.type']['recommended'],'ESSD')
        self.assertEqual(options['volume.type']['options'],
                         [{'value':'ULTRAHIGH','label':'SSD','note':'','compatible_group_types':['general','dedicated']},
                          {'value':'ESSD','label':'极速型SSD','note':'仅支持独享型规格实例','compatible_group_types':['general','dedicated','armFlavors']}])
        self.assertIn('中文名',options['volume.type']['note'])
        self.assertIn('support_compute_group_type',options['volume.type']['note'])
        self.assertEqual(options['volume.size'],{'minimum':40,'maximum':40000,'recommended':40,'note':'GB'})
        self.assertEqual(options['charge_info']['values'],
                         [{'charge_mode':'postPaid'},
                          {'charge_mode':'prePaid','period_type':'month','period_num':1},
                          {'charge_mode':'prePaid','period_type':'year','period_num':1}])
        self.assertEqual(options['charge_info']['recommended'],{'charge_mode':'postPaid'})
        self.assertEqual(options['ha.mode'],{'fixed':'Single'})
        self.assertEqual(options['ha.replication_mode'],{'values':['async','sync'],'recommended':'async'})
        self.assertEqual(options['availability_zone']['values'],['cn-east-3a','cn-east-3b'])
        self.assertEqual(options['port'],{'recommended':5432,'note':'默认端口，可省略'})
        tz=options['basic_config.time_zone']
        self.assertEqual(len(tz['values']),25)
        self.assertEqual(tz['values'][0],'UTC-12:00')
        self.assertEqual(tz['values'][-1],'UTC+12:00')
        self.assertEqual(tz['recommended'],'UTC+08:00')
        self.assertIn('整段',tz['note'])
        self.assertIn('中国北京',tz['note'])
        self.assertIn('对照表',tz['note'])
        self.assertEqual(options['enterprise_project_id'],
                         {'values':['cddc3f1f-6c3e-4d0f-a1f1-2b5bb2d6b2a6','a9832d3a-8e3a-4d8f-9c2b-1f2e3d4c5b6a'],
                          'projects':[{'id':'cddc3f1f-6c3e-4d0f-a1f1-2b5bb2d6b2a6','name':'taurus-dev','description':'开发项目'},
                                      {'id':'a9832d3a-8e3a-4d8f-9c2b-1f2e3d4c5b6a','name':'default','description':'默认企业项目'}],
                          'recommended':'a9832d3a-8e3a-4d8f-9c2b-1f2e3d4c5b6a',
                          'note':'企业项目账号：从可用的企业项目列表选择归属，默认选中 default 项目；仅新建实例场景需要填写'})
        self.assertEqual(self.eps_koocli.calls,[('EPS','ListEnterpriseProject',None)])
        self.assertEqual(options['password'],{'note':'8-32 位三类字符，用户经本地请求文件提供，工具不生成'})
        self.assertEqual(options['configuration_id'],{'note':'参数模板 ID，可选，默认不传；取值范围为 ListConfigurations 返回的参数模板 id'})
        self.assertEqual(options['security_group_id']['values'],[])
        self.assertIsNone(options['security_group_id']['recommended'])
        self.assertIn('新建专用数据库组',options['security_group_id']['note'])
        self.assertNotIn('network',result)  # network scope moved to discover_available_network_for_create
        self.assertEqual(set(result['discovery_status']),{'engine_versions','flavors','storage_types','enterprise_projects'})
        self.assertTrue(all(value=='ok' for value in result['discovery_status'].values()))
        self.assertEqual(result['top_level_reminder'][:3],
                         ['availability_zone 必须与顶层一致（服务端强制校验）',
                          '数据库密码与应用密码同规则，可同值',
                          '本工具只服务新建实例场景；托管已有实例用 list_supabase_manageable_instances'])
        self.assertEqual(result['scenario'],'newly_instance')
        self.assertNotIn('security_group_plan',result)

    async def test_eps_query_failure_degrades_to_omittable_field(self):
        self._push_sources(eps=McpToolError('MCP_CLI_ERROR','EPS.0004 Permission error.'))
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        options=result['managed_instance_field_options']
        self.assertEqual(options['enterprise_project_id'],
                         {'recommended':None,
                          'note':'企业项目列表查询不可用（个人账号、未启用企业项目或全局服务权限缺失）：本字段可省略，省略时归属由服务端决定'})
        self.assertTrue(result['discovery_status']['enterprise_projects'].startswith('error: '))

    async def test_eps_empty_list_is_omittable(self):
        self._push_sources(eps=None)
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        options=result['managed_instance_field_options']
        self.assertEqual(options['enterprise_project_id'],
                         {'recommended':None,'note':'未查到可用的企业项目：本字段可省略，省略时归属由服务端决定'})
        self.assertEqual(result['discovery_status']['enterprise_projects'],'ok')

    async def test_eps_filters_disabled_projects_and_recommends_default_by_name(self):
        self._push_sources(eps={'enterprise_projects':[{'id':'ep-on','name':'live','status':1},
                                                       {'id':'ep-off','name':'frozen','status':2},
                                                       {'id':'ep-other','name':'other'}]})
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        field=result['managed_instance_field_options']['enterprise_project_id']
        self.assertEqual(field['values'],['ep-on','ep-other'])
        self.assertEqual([project['name'] for project in field['projects']],['live','other'])
        self.assertIsNone(field['recommended'])   # no project named default in the list
        self.assertIn('discover_network_for_create',result['top_level_reminder'][-1])

    async def test_discover_db_instance_for_create_ha_mode_shapes_storage_query(self):
        self._push_sources()
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Ha')
        self.assertEqual(self.koocli.calls[2][2],{'database_name':'PostgreSQL','version_name':'17','ha_mode':'ha'})
        self.assertEqual(result['mode'],'Ha')
        options=result['managed_instance_field_options']
        self.assertEqual(options['ha.mode'],{'fixed':'Ha'})
        self.assertIn('两个不同 AZ',options['availability_zone']['note'])
        self.assertTrue(all(value=='ok' for value in result['discovery_status'].values()))

    async def test_discover_db_instance_for_create_survives_total_sellout(self):
        self._push_sources(flavors=[{'spec_code':'rds.pg.n1.medium.2','vcpus':'2','ram':4,'group_type':'general',
                                     'instance_mode':'single','az_status':{'cn-east-3a':'sellout'}}])
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        options=result['managed_instance_field_options']
        self.assertEqual(options['flavor_ref']['values'],[])
        self.assertEqual(options['flavor_ref']['groups'],[])
        self.assertIsNone(options['flavor_ref']['recommended'])
        self.assertEqual(options['availability_zone']['values'],[])
        self.assertTrue(all(value=='ok' for value in result['discovery_status'].values()))

    async def test_flavor_values_are_not_truncated_and_match_groups(self):
        flavors=[{'spec_code':'rds.pg.gen.medium.%d'%index,'vcpus':str(index%8+1),'ram':index%16+1,'group_type':'general',
                  'instance_mode':'single','az_status':{'cn-east-3a':'normal'}} for index in range(1,26)]
        self._push_sources(flavors=flavors)
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        flavor=result['managed_instance_field_options']['flavor_ref']
        self.assertEqual(len(flavor['values']),25)
        expanded=[spec['spec_code'] for group in flavor['groups'] for spec in group['specs']]
        self.assertEqual(len(expanded),25)
        self.assertEqual(sorted(expanded),sorted(flavor['values']))

    async def test_flavor_groups_sort_general_before_dedicated_and_keep_unknown_last(self):
        flavors=[{'spec_code':'rds.pg.x1.large.4','vcpus':'4','ram':16,'group_type':'dedicated','instance_mode':'ha',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.n1.medium.2','vcpus':'2','ram':4,'group_type':'general','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.arm.large.2','vcpus':'4','ram':8,'group_type':'armFlavors','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.mystery.large.2','vcpus':'4','ram':8,'group_type':'mystery','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.bare.large.2','vcpus':'4','ram':8,'instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}}]
        self._push_sources(flavors=flavors)
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        groups=result['managed_instance_field_options']['flavor_ref']['groups']
        self.assertEqual([group['group_type'] for group in groups],['general','dedicated','armFlavors','mystery','未知'])
        self.assertEqual([group['label'] for group in groups],
                         ['通用型','独享型（仅云盘SSD支持）','鲲鹏通用增强型','mystery','未知'])

    async def test_flavor_groups_sort_specs_by_vcpus_ram_and_spec_code(self):
        flavors=[{'spec_code':'rds.pg.n1.c','vcpus':'4','ram':8,'group_type':'general','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.n1.a','vcpus':'8','ram':8,'group_type':'general','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.n1.b','vcpus':'4','ram':4,'group_type':'general','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}},
                 {'spec_code':'rds.pg.n1.d','vcpus':'bad','ram':None,'group_type':'general','instance_mode':'single',
                  'az_status':{'cn-east-3a':'normal'}}]
        self._push_sources(flavors=flavors)
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        specs=result['managed_instance_field_options']['flavor_ref']['groups'][0]['specs']
        self.assertEqual([spec['spec_code'] for spec in specs],['rds.pg.n1.d','rds.pg.n1.b','rds.pg.n1.c','rds.pg.n1.a'])

    async def test_volume_options_label_unknown_storage_names(self):
        storage=[{'name':'QUANTUMSSD','az_status':{'cn-east-3a':'normal'}},
                 {'name':'ESSD','az_status':{'cn-east-3a':'normal'},'support_compute_group_type':['dedicated']}]
        self._push_sources(storage=storage)
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        volume=result['managed_instance_field_options']['volume.type']
        self.assertEqual(volume['values'],['QUANTUMSSD','ESSD'])
        self.assertEqual(volume['options'][0],{'value':'QUANTUMSSD','label':'QUANTUMSSD','note':'','compatible_group_types':[]})
        self.assertEqual(volume['options'][1],{'value':'ESSD','label':'极速型SSD','note':'仅支持独享型规格实例',
                                               'compatible_group_types':['dedicated']})

    async def test_discover_db_instance_for_create_has_no_network_or_group_sections(self):
        self._push_sources()
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        # Network placement and the security-group plan belong to discover_network_for_create:
        # no probe, no section here - this tool covers instance fields only.
        self.assertNotIn('network',result)
        self.assertNotIn('security_group_plan',result)
        self.assertEqual(set(result['discovery_status']),{'engine_versions','flavors','storage_types','enterprise_projects'})
        sg=result['managed_instance_field_options']['security_group_id']
        self.assertEqual(sg['values'],[])
        self.assertIsNone(sg['recommended'])
        self.assertIn('discover_network_for_create',result['top_level_reminder'][-1])
        self.assertEqual(result['managed_instance_field_options']['flavor_ref']['recommended'],'rds.pg.n1.medium.2')

    async def test_existed_scenario_lists_candidates_without_cloud_catalog_calls(self):
        async def candidates(kind, az_code=None, mode=None):
            return {'data': {'instances': [{'id': 'i1', 'name': 'pg-1', 'status': 'ACTIVE'}]}}
        self.catalog.operations=type('Ops',(),{'creation_candidates':candidates})()
        result=await self.catalog.discover_db_instance_for_create('existed_instance')
        self.assertEqual(result['scenario'],'existed_instance')
        self.assertEqual(result['candidates'],[{'id':'i1','name':'pg-1','status':'ACTIVE'}])
        self.assertIn('instance_id',result['acquisition'])
        self.assertEqual(self.koocli.calls,[])

    async def test_existed_scenario_returns_instance_sections(self):
        row={'id':'i1','name':'pg-1','status':'ACTIVE','spec_code':'rds.pg.n1.large.2','vcpus':2,'ram':4,
             'datastore':{'type':'PostgreSQL','version':'17'},'port':5432,
             'volume':{'type':'ESSD','size':40},'vpc_id':'v1','subnet_id':'s1','security_group_id':'g1'}
        async def candidates(kind, az_code=None, mode=None):
            return {'data': {'instances': [row]}}
        self.catalog.operations=type('Ops',(),{'creation_candidates':candidates})()
        result=await self.catalog.discover_db_instance_for_create('existed_instance',instance_id='i1')
        self.assertEqual(result['basic'],{'id':'i1','name':'pg-1','status':'ACTIVE',
                                           'spec_code':'rds.pg.n1.large.2','vcpus':2,'ram':4})
        self.assertEqual(result['configuration']['port'],5432)
        self.assertEqual(result['configuration']['volume'],{'type':'ESSD','size':40})
        self.assertEqual(result['network']['vpc_id'],'v1')
        self.assertEqual(result['network']['security_group_id'],'g1')
        self.assertIn('discover_network_for_create',result['network']['note'])
        self.assertEqual(self.koocli.calls,[])

    async def test_existed_scenario_unknown_instance_rejected(self):
        async def candidates(kind, az_code=None, mode=None):
            return {'data': {'instances': []}}
        self.catalog.operations=type('Ops',(),{'creation_candidates':candidates})()
        with self.assertRaises(McpToolError) as ctx:
            await self.catalog.discover_db_instance_for_create('existed_instance',instance_id='nope')
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')
        self.assertEqual(self.koocli.calls,[])

    async def test_existed_scenario_empty_inventory_is_not_an_error(self):
        # Live shape on cn-east-3 with no attachable instances: {"data": {"total_count": 0}} - no list key at all.
        async def candidates(kind, az_code=None, mode=None):
            return {'data': {'total_count': 0}, 'creation_ready': False}
        self.catalog.operations=type('Ops',(),{'creation_candidates':candidates})()
        result=await self.catalog.discover_db_instance_for_create('existed_instance')
        self.assertEqual(result['candidates'],[])
        with self.assertRaises(McpToolError) as ctx:
            await self.catalog.discover_db_instance_for_create('existed_instance',instance_id='nope')
        self.assertEqual(ctx.exception.code,'MCP_NOT_FOUND')

    async def test_invalid_scenario_rejected_before_any_call(self):
        for bad in ('new','existed','newly','Newly_Instance',None,1):
            with self.assertRaises(McpToolError) as ctx:
                await self.catalog.discover_db_instance_for_create(bad)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_discover_db_instance_for_create_rejects_invalid_mode_before_any_call(self):
        for bad in ('single','ha','',None,'Cluster'):
            with self.assertRaises(McpToolError) as ctx:
                await self.catalog.discover_db_instance_for_create('newly_instance',bad)
            self.assertEqual(ctx.exception.code,'MCP_INVALID_ARGS')
        self.assertEqual(self.koocli.calls,[])

    async def test_discover_db_instance_for_create_sorts_shuffled_versions_and_uses_max(self):
        self._push_sources(versions=('15','18','13'))
        result=await self.catalog.discover_db_instance_for_create('newly_instance','Single')
        options=result['managed_instance_field_options']
        self.assertEqual(options['datastore.version']['values'],['13','15','18'])
        self.assertEqual(options['datastore.version']['recommended'],'18')
        self.assertEqual(self.koocli.calls[2][2]['version_name'],'18')

    def test_catalog_tools_register_under_new_names(self):
        from mcp_server_supabase.tools import operations

        class RecordingServer:
            def __init__(self):self.names=[]
            def tool(self):
                def decorate(func):
                    self.names.append(func.__name__)
                    return func
                return decorate

        server=RecordingServer()
        operations.register(server)
        for name in ('list_db_instance_engine_versions','list_db_instance_flavors_with_azs',
                     'list_db_instance_storage_types','discover_db_instance_for_create',
                     'discover_network_for_create'):
            self.assertIn(name,server.names)
        for old in ('list_supabase_engine_versions','list_supabase_instance_flavors',
                    'list_supabase_instance_storage_types','discover_supabase_link_create_options',
                    'discover_db_instance_create_options','discover_available_network_for_create'):
            self.assertNotIn(old,server.names)


if __name__=='__main__':
    unittest.main()


def fake_calls(ops):
    return ops.koocli.calls


class NetworkDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def make(self, pages, instances=None):
        fake = FakeKoocli()
        for page in pages:
            fake.push(page)
        ops = None
        if instances is not None:
            async def candidates(kind, az_code=None, mode=None):
                return {'data': {'instances': instances}}
            ops = type('Ops', (), {'creation_candidates': candidates})()
        return NetworkDiscovery(fake, ops), fake

    def vpc(self, vid, name='vpc'):
        return {'id': vid, 'name': name, 'cidr': '192.168.0.0/16'}

    def subnet(self, sid, free, vpc_id, status='ACTIVE', az='cn-east-3a'):
        row = {'id': sid, 'name': 'subnet-' + sid, 'vpc_id': vpc_id, 'cidr': '192.168.%s.0/24' % sid,
               'status': status, 'availability_zone': az}
        if free is not None:
            row['available_ip_address_count'] = free
        return row

    async def test_prefers_two_free_ips(self):
        ops, fake = self.make([
            {'vpcs': [self.vpc('v1')]},
            {'subnets': [self.subnet('s1', 251, 'v1')]},
        ])
        result = await ops.discover_network_for_create('newly_instance')
        self.assertEqual(result['scenario'], 'newly_instance')
        self.assertEqual(result['subnet_id'], 's1')
        self.assertEqual(result['preference'], 'sufficient')
        self.assertEqual(result['basic_config_usage'], {'vpc_id': 'v1', 'subnet_id': 's1'})
        self.assertEqual(result['available_ip_count'], 251)
        self.assertEqual(fake.calls[1], ('VPC', 'ListSubnets', {'limit': 100, 'vpc_id': 'v1'}))
        plan = result['security_group_plan']
        self.assertEqual(plan['plan_type'], 'specification')
        self.assertIn('不创建任何资源', plan['declaration'])
        self.assertEqual(plan['application_group']['name'], 'supabase-app-sg')
        self.assertEqual(plan['application_group']['ingress']['port'], 8443)
        self.assertEqual(plan['application_group']['egress']['destination_cidr'], '192.168.s1.0/24')
        self.assertEqual(plan['database_group']['ingress']['source_cidr'], '192.168.s1.0/24')
        self.assertEqual([o['key'] for o in plan['application_group']['ingress']['source_cidr_options']],
                         ['open', 'detected', 'custom'])
        self.assertIsNone(plan['application_group']['ingress']['source_cidr_options'][1]['source_cidr'])
        self.assertEqual([step['tool'] for step in plan['apply_steps']],
                         ['create_supabase_security_group', 'add_supabase_security_group_rule',
                          'add_supabase_security_group_rule', 'create_supabase_security_group',
                          'add_supabase_security_group_rule'])
        self.assertEqual(plan['apply_steps'][2]['args']['source_cidr'], '192.168.s1.0/24')

    async def test_falls_back_to_one_free_ip(self):
        ops, _ = self.make([
            {'vpcs': [self.vpc('v1')]},
            {'subnets': [self.subnet('s1', 1, 'v1')]},
        ])
        result = await ops.discover_network_for_create('newly_instance')
        self.assertEqual(result['preference'], 'fallback')
        self.assertEqual(result['available_ip_count'], 1)

    async def test_walks_vpcs_until_match(self):
        ops, _ = self.make([
            {'vpcs': [self.vpc('v1', 'empty'), self.vpc('v2', 'good')]},
            {'subnets': [self.subnet('s0', 0, 'v1')]},          # v1: exhausted
            {'subnets': [self.subnet('s1', 5, 'v2')]},            # v2: sufficient
        ])
        result = await ops.discover_network_for_create('newly_instance')
        self.assertEqual(result['vpc_id'], 'v2')
        self.assertEqual(result['subnet_id'], 's1')
        self.assertEqual(len(result['inspected_vpcs']), 1)  # v1 recorded, v2 matched

    async def test_skips_non_active_and_unknown_availability(self):
        ops, _ = self.make([
            {'vpcs': [self.vpc('v1')]},
            {'subnets': [self.subnet('s1', 251, 'v1', status='ERROR'), self.subnet('s2', None, 'v1')]},
        ])
        result = await ops.discover_network_for_create('newly_instance')
        self.assertEqual(result['subnet_id'], 's2')          # unknown availability used as fallback
        self.assertEqual(result['preference'], 'fallback')

    async def test_subnet_error_records_and_continues(self):
        from huaweicloud_mcp_core.errors import McpToolError as Err
        ops, _ = self.make([
            {'vpcs': [self.vpc('v1'), self.vpc('v2')]},
            Err('MCP_CLI_ERROR', 'boom'),                      # v1 subnet query fails
            {'subnets': [self.subnet('s2', 3, 'v2')]},
        ])
        result = await ops.discover_network_for_create('newly_instance')
        self.assertEqual(result['vpc_id'], 'v2')
        self.assertTrue(any('boom' in str(item.get('error', '')) for item in result['inspected_vpcs']))

    async def test_no_match_returns_default_recommendation(self):
        ops, _ = self.make([
            {'vpcs': [self.vpc('v1')]},
            {'subnets': [self.subnet('s1', 0, 'v1')]},
        ])
        result = await ops.discover_network_for_create('newly_instance', availability_zone='cn-east-3a')
        self.assertEqual(result['preference'], 'default_recommendation')
        self.assertIsNone(result['vpc_id'])
        self.assertEqual(result['vpc_name'], 'default_vpc')
        self.assertEqual(result['vpc_cidr'], '192.168.0.0/16')
        self.assertEqual(result['subnet_name'], 'default_subnet')
        self.assertEqual(result['subnet_cidr'], '192.168.0.0/24')
        self.assertEqual(result['availability_zone'], 'cn-east-3a')
        self.assertEqual(result['default_create']['subnet']['gateway_ip'], '192.168.0.1')
        self.assertIsNone(result['basic_config_usage'])
        self.assertTrue(any(item.get('error') == 'no eligible subnet' for item in result['inspected_vpcs']))
        plan = result['security_group_plan']
        self.assertEqual(plan['application_group']['egress']['destination_cidr'], '192.168.0.0/24')
        self.assertEqual(plan['database_group']['ingress']['source_cidr'], '192.168.0.0/24')
        self.assertIn('default_create', plan['precondition'])

    async def test_empty_region_returns_default_recommendation(self):
        ops, _ = self.make([{'vpcs': []}])
        result = await ops.discover_network_for_create('newly_instance')
        self.assertEqual(result['preference'], 'default_recommendation')
        self.assertEqual(result['vpc_name'], 'default_vpc')
        self.assertIsNone(result['availability_zone'])

    async def test_rejects_invalid_scenario_and_missing_instance_id(self):
        ops, _ = self.make([])
        with self.assertRaises(McpToolError) as ctx:
            await ops.discover_network_for_create('new')
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        self.assertEqual(fake_calls(ops), [])
        with self.assertRaises(McpToolError) as ctx:
            await ops.discover_network_for_create('existed_instance')
        self.assertEqual(ctx.exception.code, 'MCP_INVALID_ARGS')
        ops2, _ = self.make([], instances=[])
        with self.assertRaises(McpToolError) as ctx:
            await ops2.discover_network_for_create('existed_instance', instance_id='i1')
        self.assertEqual(ctx.exception.code, 'MCP_NOT_FOUND')

    async def test_existed_takes_network_from_instance_and_keeps_db_group(self):
        instances = [{'id': 'i1', 'name': 'pg-1', 'vpc_id': 'v1', 'subnet_id': 's1',
                      'security_group_id': 'g1'}]
        ops, fake = self.make([{'subnets': [{'id': 's1', 'cidr': '192.168.5.0/24', 'vpc_id': 'v1'}]}],
                              instances=instances)
        result = await ops.discover_network_for_create('existed_instance', instance_id='i1')
        self.assertEqual(fake.last(), ('VPC', 'ListSubnets', {'limit': 100, 'vpc_id': 'v1'}))
        self.assertEqual(result['subnet_cidr'], '192.168.5.0/24')
        self.assertEqual(result['basic_config_usage'], {'vpc_id': 'v1', 'subnet_id': 's1'})
        plan = result['security_group_plan']
        self.assertEqual(plan['application_group']['egress']['destination_cidr'], '192.168.5.0/24')
        self.assertEqual(plan['database_group']['action'], '不动')
        self.assertEqual(plan['database_group']['current_security_group_id'], 'g1')
        self.assertNotIn('precondition', plan)
        self.assertEqual(len(plan['apply_steps']), 3)  # app group only; the instance's group stays untouched
        self.assertEqual(plan['apply_steps'][2]['args']['source_cidr'], '192.168.5.0/24')

    async def test_detect_access_ip_fills_the_detected_option(self):
        ops, _ = self.make([{'vpcs': []}])
        ops._detect_access_cidr = lambda: '1.2.3.4/32'
        result = await ops.discover_network_for_create('newly_instance', detect_access_ip=True)
        options = result['security_group_plan']['application_group']['ingress']['source_cidr_options']
        self.assertEqual(options[1]['source_cidr'], '1.2.3.4/32')
        self.assertIn('已探测', options[1]['note'])

    async def test_detect_failure_degrades_to_note(self):
        ops, _ = self.make([{'vpcs': []}])
        ops._detect_access_cidr = lambda: None
        result = await ops.discover_network_for_create('newly_instance', detect_access_ip=True)
        options = result['security_group_plan']['application_group']['ingress']['source_cidr_options']
        self.assertIsNone(options[1]['source_cidr'])
        self.assertIn('探测失败', options[1]['note'])


class BasicOptionsTests(unittest.IsolatedAsyncioTestCase):
    def make(self, results, existing_names=None):
        ops = type('FakeOps', (), {})()
        ops.calls = []
        async def candidates(kind, az_code=None, mode=None):
            ops.calls.append((kind, az_code, mode))
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        ops.creation_candidates = candidates
        async def read(kind, application_id=None, limit=10, offset=0, **filters):
            ops.calls.append((kind, limit))
            return {'data': [{'name': name} for name in (existing_names or [])]}
        ops.read = read
        return BasicOptionsDiscovery(ops), ops

    def flavor_page(self, specs, group_type='general'):
        return {'data': {'flavors': [{'mode': 'single', 'version': '1.0.0', 'vcpus': 2, 'ram': 4,
                                      'group_type': group_type, 'spec_code': spec,
                                      'availability_zones': [{'code': 'cn-east-3a', 'status': 'normal'},
                                                             {'code': 'cn-east-3b', 'status': 'sellout'}]}
                                     for spec in specs]}}

    async def test_happy_path_single_and_ha(self):
        ops, fake = self.make([
            self.flavor_page(['rds.supabase.n1.large.2', 'rds.supabase.n1.large.4']),
            self.flavor_page(['rds.supabase.n1.large.2.ha']),
        ])
        result = await ops.discover('cn-east-3a')
        self.assertTrue(result['ha_supported'])
        self.assertEqual(result['basic_options']['mode']['values'], ['Single', 'Ha'])
        self.assertEqual(result['basic_options']['version']['recommended'], '1.0.0')
        self.assertEqual(result['basic_options']['flavor_ref']['recommended'], 'rds.supabase.n1.large.2')
        self.assertEqual(result['basic_options']['flavor_ref']['values'],
                         ['rds.supabase.n1.large.2', 'rds.supabase.n1.large.4'])
        self.assertEqual(result['basic_options']['flavor_ref']['groups'],
                         [{'group_type': 'general', 'label': '通用型', 'specs': [
                             {'spec_code': 'rds.supabase.n1.large.2', 'vcpus': 2, 'ram': 4,
                              'instance_mode': None, 'availability_zones': ['cn-east-3a']},
                             {'spec_code': 'rds.supabase.n1.large.4', 'vcpus': 2, 'ram': 4,
                              'instance_mode': None, 'availability_zones': ['cn-east-3a']}]}])
        self.assertIn('分开单独询问', result['basic_options']['flavor_ref']['note'])
        self.assertIn('全部可售规格', result['basic_options']['flavor_ref']['note'])
        self.assertEqual(fake.calls, [('flavors', 'cn-east-3a', 'Single'), ('flavors', 'cn-east-3a', 'Ha'), ('applications', 100)])
        self.assertIn('discover_network_for_create', str(result['excluded_scopes']))
        name_field = result['basic_options']['name']
        self.assertTrue(name_field['suggested'].startswith('supabase-app-'))
        self.assertTrue(any('64 字节' in r for r in name_field['requirements']))
        self.assertTrue(any('字母或中文开头' in r for r in name_field['requirements']))
        password = result['basic_options']['password']
        self.assertEqual(password['login_user'], 'supabase')
        self.assertTrue(any('8~32' in r for r in password['requirements']))
        self.assertTrue(any('三种' in r for r in password['requirements']))
        self.assertEqual(result['probe_status']['existing_application_names'], 'ok')
        strategy=result['security_group_strategy']
        self.assertFalse(strategy['determined'])
        self.assertIn('不创建任何资源',strategy['declaration'])
        self.assertIn('discover_network_for_create',strategy['reason'])
        self.assertEqual(strategy['application_group']['ingress']['port'],8443)
        self.assertEqual(strategy['application_group']['egress']['port'],5432)
        self.assertIn('新建实例场景',strategy['database_group']['strategy'])

    async def test_ha_probe_rejection_means_single_only(self):
        from huaweicloud_mcp_core.errors import McpToolError as Err
        ops, _ = self.make([
            self.flavor_page(['rds.supabase.n1.large.2']),
            Err('MCP_INVALID_ARGS', 'backend rejected'),
        ])
        result = await ops.discover('cn-east-3a')
        self.assertFalse(result['ha_supported'])
        self.assertEqual(result['basic_options']['mode']['values'], ['Single'])
        self.assertIn('error:', result['probe_status']['application_flavors_ha'])

    async def test_az_sale_filter(self):
        page = self.flavor_page(['rds.supabase.a'])
        page['data']['flavors'][0]['availability_zones'] = [{'code': 'cn-east-3a', 'status': 'sellout'},
                                                            {'code': 'cn-east-3b', 'status': 'normal'}]
        ops, _ = self.make([page, self.flavor_page([])])
        result = await ops.discover('cn-east-3a')
        # nothing saleable in cn-east-3a -> falls back to unfiltered spec list with the note
        self.assertEqual(result['basic_options']['flavor_ref']['values'], ['rds.supabase.a'])
        spec = result['basic_options']['flavor_ref']['groups'][0]['specs'][0]
        self.assertEqual(spec['availability_zones'], ['cn-east-3b'])

    async def test_flavor_groups_fall_back_to_main_az_field_and_tolerate_missing(self):
        page = {'data': {'flavors': [
            {'mode': 'single', 'version': '1.0.0', 'vcpus': 2, 'ram': 4, 'group_type': 'general',
             'spec_code': 'rds.supabase.n1.large.2', 'availability_zone': 'cn-east-3a'},
            {'mode': 'single', 'version': '1.0.0', 'vcpus': 2, 'ram': 4, 'spec_code': 'rds.supabase.z.large.2'}]}}
        ops, _ = self.make([page, self.flavor_page([])])
        result = await ops.discover('cn-east-3a')
        flavor = result['basic_options']['flavor_ref']
        self.assertEqual([group['group_type'] for group in flavor['groups']], ['general', '未知'])
        self.assertEqual(flavor['groups'][0]['specs'][0]['availability_zones'], ['cn-east-3a'])
        self.assertEqual(flavor['groups'][1]['specs'][0]['availability_zones'], [])

    async def test_flavor_values_not_truncated_across_many_specs(self):
        specs = ['rds.supabase.n1.small.%d' % index for index in range(1, 26)]
        ops, _ = self.make([self.flavor_page(specs), self.flavor_page([])])
        result = await ops.discover('cn-east-3a')
        flavor = result['basic_options']['flavor_ref']
        self.assertEqual(len(flavor['values']), 25)
        expanded = [spec['spec_code'] for group in flavor['groups'] for spec in group['specs']]
        self.assertEqual(sorted(expanded), sorted(flavor['values']))

    async def test_suggested_name_avoids_collisions(self):
        import datetime
        stamp = datetime.date.today().strftime('%m%d')
        ops, _ = self.make([
            self.flavor_page(['rds.supabase.n1.large.2']),
            self.flavor_page([]),
        ], existing_names=['supabase-app-' + stamp, 'supabase-app-' + stamp + '-1'])
        result = await ops.discover('cn-east-3a')
        suggested = result['basic_options']['name']['suggested']
        self.assertEqual(suggested, 'supabase-app-' + stamp + '-2')

    async def test_name_listing_failure_degrades_to_requirements_only(self):
        from huaweicloud_mcp_core.errors import McpToolError as Err
        discovery, fake = self.make([
            self.flavor_page(['rds.supabase.n1.large.2']),
            self.flavor_page([]),
        ])
        async def broken_read(*args, **kwargs):
            raise Err('MCP_SDK_ERROR', 'listing unavailable')
        fake.read = broken_read
        result = await discovery.discover('cn-east-3a')
        self.assertIn('error:', result['probe_status']['existing_application_names'])
        self.assertTrue(result['basic_options']['name']['suggested'])  # suggestion still present

    async def test_invalid_az_rejected(self):
        ops, _ = self.make([])
        for bad in ('', 'not-an-az', 'CN-EAST-3A'):
            with self.assertRaises(Exception):
                await ops.discover(bad)
