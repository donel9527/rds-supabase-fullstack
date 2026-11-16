import copy
import unittest
from mcp_server_supabase.service.planning import PlanningService

BASICS = {'basic_options': {'name': {'suggested': 'supabase-app-1115'},
                            'version': {'recommended': '1.0.0'},
                            'mode': {'recommended': 'Single'},
                            'flavor_ref': {'recommended': 'rds.supabase.n1.large.2',
                                           'values': ['rds.supabase.n1.large.2'],
                                           'groups': [{'group_type': 'general', 'label': '通用型',
                                                       'specs': [{'spec_code': 'rds.supabase.n1.large.2', 'vcpus': 2, 'ram': 4}]}]}},
          'probe_status': {'application_flavors_single': 'ok'}}

NEWLY_INSTANCE = {'scenario': 'newly_instance', 'mode': 'Single',
                  'managed_instance_field_options': {
                      'datastore.version': {'recommended': '18'},
                      'flavor_ref': {'recommended': 'rds.pg.n1.medium.2',
                                     'values': ['rds.pg.n1.medium.2.ha', 'rds.pg.n1.large.2.ha', 'rds.pg.x1.4xlarge.8.ha'],
                                     'groups': [{'group_type': 'general', 'label': '通用型',
                                                 'specs': [{'spec_code': 'rds.pg.n1.medium.2.ha', 'vcpus': 2, 'ram': 4,
                                                            'instance_mode': 'ha', 'availability_zones': ['cn-east-3a', 'cn-east-3b']},
                                                           {'spec_code': 'rds.pg.n1.large.2.ha', 'vcpus': 4, 'ram': 8,
                                                            'instance_mode': 'ha', 'availability_zones': ['cn-east-3a']}]},
                                                {'group_type': 'dedicated', 'label': '专属型',
                                                 'specs': [{'spec_code': 'rds.pg.x1.4xlarge.8.ha', 'vcpus': 16, 'ram': 128,
                                                            'instance_mode': 'ha', 'availability_zones': ['cn-east-3a']}]}],
                                     'note': '实例规格，形如 rds.pg.n1.medium.2；与应用规格（rds.supabase.*）是两回事'},
                      'volume.type': {'recommended': 'ESSD',
                                      'values': ['ESSD', 'CLOUDSSD', 'GPSSD2'],
                                      'options': [{'value': 'ESSD', 'label': '极速型SSD', 'note': 'ESSD',
                                                   'compatible_group_types': ['dedicated']},
                                                  {'value': 'CLOUDSSD', 'label': 'SSD云盘', 'note': 'CLOUDSSD',
                                                   'compatible_group_types': ['general', 'dedicated']},
                                                  {'value': 'GPSSD2', 'label': '通用型SSD V2', 'note': 'GPSSD2',
                                                   'compatible_group_types': ['general', 'dedicated']}],
                                      'note': '按 mode 过滤后的可售盘型'},
                      'volume.size': {'recommended': 40},
                      'charge_info': {'recommended': {'charge_mode': 'postPaid'}},
                      'availability_zone': {'values': ['cn-east-3a', 'cn-east-3b']},
                      'port': {'recommended': 5432},
                      'enterprise_project_id': {'recommended': 'cddc3f1f-6c3e-4d0f-a1f1-2b5bb2d6b2a6'}},
                  'discovery_status': {'engine_versions': 'ok', 'flavors': 'ok', 'storage_types': 'ok'},
                  'top_level_reminder': ['r1', 'r2', 'r3', 'r4']}

SG_STEPS_5 = [{'tool': 'create_supabase_security_group', 'args': {'name': 'supabase-app-sg'}, 'returns': 'security_group_id'},
              {'tool': 'add_supabase_security_group_rule', 'args': {'port': 8443}},
              {'tool': 'add_supabase_security_group_rule', 'args': {'port': 5432}},
              {'tool': 'create_supabase_security_group', 'args': {'name': 'supabase-db-sg'}, 'returns': 'security_group_id'},
              {'tool': 'add_supabase_security_group_rule', 'args': {'port': 5432}}]

NETWORK_NEWLY = {'scenario': 'newly_instance', 'preference': 'sufficient', 'vpc_id': 'v1', 'subnet_id': 's1',
                 'subnet_cidr': '192.168.0.0/24', 'basic_config_usage': {'vpc_id': 'v1', 'subnet_id': 's1'},
                 'security_group_plan': {'plan_type': 'specification', 'apply_steps': SG_STEPS_5}}

NETWORK_NEWLY_DEFAULT = {'scenario': 'newly_instance', 'preference': 'default_recommendation', 'vpc_id': None,
                         'subnet_cidr': '192.168.0.0/24', 'default_create': {'vpc': {}},
                         'security_group_plan': {'plan_type': 'specification', 'apply_steps': SG_STEPS_5}}


def instance_row(i, actions=None):
    return {'id': 'i%d' % i, 'name': 'pg-%d' % i,
            'status': 'REBOOTING' if actions else 'ACTIVE',
            'datastore': {'type': 'PostgreSQL', 'version': '%d' % (15 + i)},
            'ha': {'mode': 'single'}, 'port': 5432 + i,
            'nodes': [{'availability_zone': 'cn-east-3a'}],
            'created': '2026-11-01T00:00:00Z',
            'current_actions': actions or [], 'vpc_id': 'v1', 'subnet_id': 's1',
            'security_group_id': 'g%d' % i}


class FakeBasics:
    def __init__(self, basics=None): self.calls = []; self.basics = basics or BASICS
    async def discover(self, az_code): self.calls.append(az_code); return self.basics


class FakeCatalog:
    def __init__(self, rows=None, newly=None): self.calls = []; self.rows = rows or []; self.newly = newly or NEWLY_INSTANCE
    async def discover_db_instance_for_create(self, scenario, mode=None, instance_id=None):
        self.calls.append((scenario, mode, instance_id))
        if scenario == 'newly_instance': return self.newly
        if instance_id is None: return {'scenario': 'existed_instance', 'candidates': self.rows}
        match = next((row for row in self.rows if row['id'] == instance_id), None)
        return {'scenario': 'existed_instance', 'instance_id': instance_id,
                'basic': {'id': instance_id}, 'configuration': {'port': 5433}, 'network': {'vpc_id': 'v1'}}


class FakeNetwork:
    def __init__(self, newly=None, existed=None):
        self.calls = []; self.newly = newly or NETWORK_NEWLY; self.existed = existed
    async def discover_network_for_create(self, scenario, availability_zone=None, instance_id=None, detect_access_ip=False):
        self.calls.append((scenario, availability_zone, instance_id, detect_access_ip))
        return self.newly if scenario == 'newly_instance' else self.existed


class ArrangementTests(unittest.IsolatedAsyncioTestCase):
    def make(self, rows=None, network_newly=None, basics=None, newly=None):
        basics_service = FakeBasics(basics); catalog = FakeCatalog(rows, newly); network = FakeNetwork(newly=network_newly)
        return PlanningService(basics=basics_service, catalog=catalog, network=network)

    async def test_invalid_manage_type_and_page(self):
        result = await PlanningService().arrangement('unknown')
        self.assertEqual(result['error']['code'], 'MCP_INVALID_ARGS')
        result = await self.make().arrangement('newly_instance', page=0)
        self.assertEqual(result['error']['code'], 'MCP_INVALID_ARGS')

    async def test_newly_full_arrangement(self):
        service = self.make()
        result = await service.arrangement('newly_instance', az_code='cn-east-3a', mode='Single',
                                           needs_storage=True, needs_public_access=True,
                                           needs_ssl=False, needs_email_login=False, needs_github_login=False)
        self.assertEqual(result['status'], 'arrangement_baseline')
        self.assertEqual(result['execution'], 'not_executed')
        self.assertIn('不创建任何资源', result['declaration'])
        source = result['managed_instance_source']
        self.assertEqual(source['decision'], 'newly_instance')
        self.assertTrue(source['options'][0]['recommended'])
        self.assertIn('确定性结论', source['requirement'])
        m1 = result['step_modules']['supabase_basics']
        self.assertEqual(m1['status'], 'fixed')
        self.assertEqual(m1['baseline']['name'], 'supabase-app-1115')
        self.assertEqual(m1['baseline']['version'], '1.0.0')
        self.assertEqual(m1['baseline']['availability_zone'], 'cn-east-3a')
        self.assertEqual(m1['baseline']['storage_component'], {'enabled': True, 'note': '桶名与持久 AK/SK 经本地请求文件'})
        m2 = result['step_modules']['managed_instance']
        self.assertEqual(m2['baseline']['datastore']['version'], '18')
        self.assertEqual(m2['baseline']['port'], 5432)
        self.assertEqual(m2['baseline']['security_group_id'], '<建组后回填（模块3 apply_steps）>')
        self.assertEqual(m2['baseline']['enterprise_project_id'], 'cddc3f1f-6c3e-4d0f-a1f1-2b5bb2d6b2a6')
        m3 = result['step_modules']['network_control']
        self.assertEqual(m3['placement']['vpc_id'], 'v1')
        self.assertEqual(m3['security_group_plan']['plan_type'], 'specification')
        obs = result['step_modules']['obs_integration']
        self.assertEqual(obs['acquisition']['recommended'], 'new')
        self.assertTrue(obs['new_bucket_spec']['bucket_name'].startswith('supabase-'))
        self.assertEqual([s['tool'] for s in result['creation_flow'] if s['phase'] == 'obs_integration'],
                         ['discover_supabase_storage'])
        eip = result['step_modules']['public_access']
        self.assertEqual(eip['status'], 'planned')
        self.assertIn('按需计费（固定，不支持包周期）', eip['billing_mode']['fixed'])
        self.assertIn('0.02', eip['billing_mode']['fixed'])   # official IP-retention fee example
        self.assertEqual([o['method'] for o in eip['purchase_method']['options']], ['bandwidth', 'traffic'])
        self.assertIn('0.64', eip['purchase_method']['options'][1]['note'])   # official traffic-price example
        self.assertIn('300Mbps', eip['purchase_method']['options'][1]['note'])   # traffic per-EIP peak cap
        self.assertIn('traffic', eip['bandwidth']['size_range_mbps'])
        self.assertIn('用户决策', eip['bandwidth']['size_decision'])   # no default size - the user decides
        self.assertNotIn('recommended_size_mbps', eip['bandwidth'])
        self.assertIn('5_bgp', eip['bandwidth']['type'])
        self.assertIn('CreatePublicip', eip['purchase'])
        flow = result['creation_flow']
        self.assertEqual([s['step'] for s in flow], list(range(1, len(flow) + 1)))
        self.assertEqual(flow[0]['phase'], 'network_ready')
        self.assertFalse([s for s in flow if s['phase'] == 'security_groups'])  # automatic inside the creation tool
        tools_in_flow = [s['tool'] for s in flow]
        self.assertIn('create_supabase_with_new_instance', tools_in_flow)
        self.assertIn('show_supabase_creation_progress', tools_in_flow)
        self.assertEqual(flow[-1]['tool'], 'show_supabase_application')
        self.assertEqual(result['decision_points'], [])
        self.assertTrue(any('文件' in note for note in result['security_notes']))
        post_tools = [p.get('tool') for p in result['post_creation_flow']]
        self.assertIn('create_supabase_eip', post_tools)
        self.assertIn('bind_supabase_eip', post_tools)
        self.assertIn('bind_supabase_eip', result['step_modules']['public_access']['bind'])

    async def test_newly_arrangement_without_eps_omits_the_baseline_field(self):
        no_eps = copy.deepcopy(NEWLY_INSTANCE)
        no_eps['managed_instance_field_options'].pop('enterprise_project_id', None)
        result = await self.make(newly=no_eps).arrangement('newly_instance', az_code='cn-east-3a', mode='Single',
                                                           needs_storage=False, needs_public_access=False,
                                                           needs_ssl=False, needs_email_login=False, needs_github_login=False)
        self.assertEqual(result['status'], 'arrangement_baseline')
        baseline = result['step_modules']['managed_instance']['baseline']
        self.assertNotIn('enterprise_project_id', baseline)   # personal accounts: field omitted entirely

    async def test_default_recommendation_adds_network_creation_step(self):
        service = self.make(network_newly=NETWORK_NEWLY_DEFAULT)
        result = await service.arrangement('newly_instance', az_code='cn-east-3a',
                                           needs_storage=False, needs_public_access=False, needs_ssl=False)
        first = result['creation_flow'][0]
        self.assertEqual(first['tool'], 'console/KooCLI')
        self.assertIn('default_create', first['action'])

    async def test_same_flavor_match_and_volume_adaptation(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a', mode='Single',
                                               needs_storage=False, needs_public_access=False, needs_ssl=False)
        baseline = result['step_modules']['managed_instance']['baseline']
        self.assertEqual(baseline['flavor_ref'], 'rds.pg.n1.medium.2.ha')
        self.assertEqual(baseline['flavor_match'], {'app_flavor_ref': 'rds.supabase.n1.large.2',
                                                    'app_group_type': 'general',
                                                    'app_group_label': '通用型',
                                                    'matched_spec': 'rds.pg.n1.medium.2.ha',
                                                    'match_basis': 'group_type+vcpus+ram'})
        self.assertEqual(baseline['volume']['type'], 'CLOUDSSD')
        self.assertEqual(baseline['volume']['type_basis'], '与匹配规格（group_type=general）实时兼容')

    async def test_old_structure_falls_back_to_recommended(self):
        basics = copy.deepcopy(BASICS)
        del basics['basic_options']['flavor_ref']['groups']
        newly = copy.deepcopy(NEWLY_INSTANCE)
        del newly['managed_instance_field_options']['flavor_ref']['groups']
        del newly['managed_instance_field_options']['volume.type']['options']
        result = await self.make(basics=basics, newly=newly).arrangement('newly_instance', az_code='cn-east-3a',
                                                                         needs_public_access=False, needs_ssl=False)
        baseline = result['step_modules']['managed_instance']['baseline']
        self.assertEqual(baseline['flavor_ref'], 'rds.pg.n1.medium.2')
        self.assertNotIn('flavor_match', baseline)
        self.assertEqual(baseline['volume']['type'], 'ESSD')
        self.assertNotIn('type_basis', baseline['volume'])
        mixed = await self.make(basics=basics).arrangement('newly_instance', az_code='cn-east-3a',
                                                           needs_public_access=False, needs_ssl=False)
        mixed_baseline = mixed['step_modules']['managed_instance']['baseline']
        self.assertEqual(mixed_baseline['flavor_ref'], 'rds.pg.n1.medium.2')
        self.assertNotIn('flavor_match', mixed_baseline)
        self.assertEqual(mixed_baseline['volume']['type'], 'ESSD')
        self.assertNotIn('type_basis', mixed_baseline['volume'])

    async def test_flavor_and_volume_interaction_texts(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a',
                                               needs_public_access=False, needs_ssl=False)
        m1 = result['step_modules']['supabase_basics']
        self.assertIn('应用规格单独询问', m1['flavor_interaction'])
        self.assertIn('推荐通用型 2U4G', m1['flavor_interaction'])
        m2 = result['step_modules']['managed_instance']
        self.assertIn('实例规格与应用规格分开单独询问', m2['flavor_interaction'])
        self.assertIn('group_type', m2['flavor_interaction'])
        self.assertIn('磁盘类型明确展示', m2['volume_interaction'])
        pending = await self.make().arrangement('newly_instance')
        self.assertNotIn('flavor_interaction', pending['step_modules']['supabase_basics'])
        self.assertIn('实例规格与应用规格分开单独询问', pending['step_modules']['managed_instance']['flavor_interaction'])
        existed = await self.make().arrangement('existed_instance', needs_public_access=False, needs_ssl=False)
        existed_m2 = existed['step_modules']['managed_instance']
        self.assertNotIn('flavor_interaction', existed_m2)
        self.assertNotIn('volume_interaction', existed_m2)

    async def test_flavor_match_falls_back_to_group_type(self):
        basics = copy.deepcopy(BASICS)
        block = basics['basic_options']['flavor_ref']
        block['recommended'] = 'rds.supabase.n1.small.2'
        block['values'] = ['rds.supabase.n1.small.2']
        block['groups'][0]['specs'] = [{'spec_code': 'rds.supabase.n1.small.2', 'vcpus': 1, 'ram': 2}]
        result = await self.make(basics=basics).arrangement('newly_instance', az_code='cn-east-3a',
                                                            needs_public_access=False, needs_ssl=False)
        baseline = result['step_modules']['managed_instance']['baseline']
        self.assertEqual(baseline['flavor_match']['match_basis'], 'group_type')
        self.assertEqual(baseline['flavor_match']['matched_spec'], 'rds.pg.n1.medium.2.ha')
        self.assertEqual(baseline['flavor_ref'], 'rds.pg.n1.medium.2.ha')

    async def test_volume_prefers_essd_when_compatible(self):
        newly = copy.deepcopy(NEWLY_INSTANCE)
        for option in newly['managed_instance_field_options']['volume.type']['options']:
            if option['value'] == 'ESSD':
                option['compatible_group_types'] = ['general', 'dedicated']
        result = await self.make(newly=newly).arrangement('newly_instance', az_code='cn-east-3a',
                                                          needs_public_access=False, needs_ssl=False)
        volume = result['step_modules']['managed_instance']['baseline']['volume']
        self.assertEqual(volume['type'], 'ESSD')
        self.assertEqual(volume['type_basis'], '与匹配规格（group_type=general）实时兼容')

    async def test_missing_az_leaves_basics_pending(self):
        result = await self.make().arrangement('newly_instance', needs_storage=False,
                                               needs_public_access=False, needs_ssl=False)
        m1 = result['step_modules']['supabase_basics']
        self.assertEqual(m1['status'], 'pending_decision')
        self.assertIsNone(m1['baseline'])
        self.assertTrue(any('az_code' in d for d in result['decision_points']))

    async def test_existed_paginates_and_surfaces_action_locks(self):
        rows = [instance_row(i, actions=['REBOOT'] if i == 0 else None) for i in range(25)]
        service = self.make(rows=rows)
        result = await service.arrangement('existed_instance', needs_public_access=False, needs_ssl=False)
        m2 = result['step_modules']['managed_instance']
        self.assertEqual(m2['status'], 'instance_selection')
        self.assertEqual(m2['pagination']['page'], 1)
        self.assertEqual(m2['pagination']['page_size'], 20)
        self.assertEqual(m2['pagination']['total_count'], 25)
        self.assertEqual(m2['pagination']['total_pages'], 2)
        self.assertEqual(len(m2['candidates_page']), 20)
        self.assertIn('重大操作', m2['action_lock'])
        self.assertIn('排除', m2['action_lock'])
        locked = m2['candidates_page'][0]
        self.assertEqual(locked['current_actions'], ['REBOOT'])
        self.assertEqual(locked['datastore_version'], '15')
        self.assertEqual(locked['deployment_type'], 'single')
        self.assertEqual(locked['port'], 5432)
        self.assertEqual(locked['availability_zones'], ['cn-east-3a'])
        self.assertEqual(locked['created'], '2026-11-01T00:00:00Z')
        result = await service.arrangement('existed_instance', page=2)
        self.assertEqual(len(result['step_modules']['managed_instance']['candidates_page']), 5)

    async def test_existed_with_instance_id_fixes_modules(self):
        service = self.make(rows=[instance_row(1)])
        service.network = FakeNetwork(existed={'vpc_id': 'v1', 'subnet_id': 's1',
                                               'subnet_cidr': '192.168.0.0/24',
                                               'basic_config_usage': {'vpc_id': 'v1', 'subnet_id': 's1'},
                                               'security_group_plan': {'plan_type': 'specification',
                                                                      'apply_steps': SG_STEPS_5[:3],
                                                                      'database_group': {'action': '不动'}}})
        result = await service.arrangement('existed_instance', instance_id='i1',
                                           needs_public_access=False, needs_ssl=False)
        m2 = result['step_modules']['managed_instance']
        self.assertEqual(m2['status'], 'fixed')
        self.assertIn('root', m2['baseline']['existing_instance']['database_name'])
        m3 = result['step_modules']['network_control']
        self.assertEqual(m3['status'], 'fixed')
        self.assertEqual(m3['security_group_plan']['database_group']['action'], '不动')
        flow = result['creation_flow']
        self.assertEqual(flow[0]['phase'], 'instance_confirm')
        self.assertFalse([s for s in flow if s['phase'] == 'security_groups'])  # automatic inside the creation tool
        self.assertIn('create_supabase_link_exist_instance', [s['tool'] for s in flow])
        self.assertIn('show_supabase_creation_progress', [s['tool'] for s in flow])

    async def test_intents_shape_post_creation_flow(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a',
                                               needs_storage=False, needs_public_access=False, needs_ssl=False)
        post = result['post_creation_flow']
        self.assertTrue(any('private_ip' in str(p.get('action')) for p in post))
        self.assertFalse(any(p.get('tool') == 'change_supabase_eip' for p in post))
        self.assertTrue(any('http 访问' in str(p.get('action')) for p in post))
        self.assertTrue(any('接入信息交付' in str(p.get('action')) for p in post))
        self.assertEqual(result['step_modules']['public_access']['delivery'],
                         '内网交付 private_ip；不购买 EIP、不开公网入方向')
        self.assertNotIn('eip_baseline', result)
        self.assertNotIn('obs_integration', result['step_modules'])
        self.assertFalse(any(s['phase'] == 'obs_integration' for s in result['creation_flow']))

    async def test_ssl_module_planned_when_enabled(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a',
                                               needs_storage=False, needs_public_access=True, needs_ssl=True)
        module = result['step_modules']['ssl_configuration']
        self.assertEqual(module['status'], 'planned')
        self.assertEqual(module['source_tools'],
                         ['list_ssl_certificates', 'purchase_supabase_ssl_cert', 'change_supabase_ssl'])
        self.assertEqual([option['key'] for option in module['acquisition']['options']],
                         ['reuse', 'purchase', 'import_own'])
        self.assertEqual(module['acquisition']['recommended'], 'purchase')
        self.assertIn('DV_SSL_CERT_BASIC', module['acquisition']['options'][1]['note'])
        self.assertIn('File', module['domain_note'])
        self.assertIn('auto_dns_auth', module['domain_note'])
        self.assertIn('change_supabase_ssl', module['enable_flow'][0])
        self.assertTrue(any('中断' in item for item in module['impact']))
        self.assertTrue(any('api_external_url' in item for item in module['impact']))
        self.assertNotIn('eip_baseline', result)
        post_tools = [p.get('tool') for p in result['post_creation_flow']]
        self.assertIn('list_ssl_certificates', post_tools)
        self.assertIn('purchase_supabase_ssl_cert', post_tools)
        self.assertIn('change_supabase_ssl', post_tools)
        self.assertNotIn('console', post_tools)
        self.assertTrue(any('purchase_supabase_ssl_cert' in item for item in result['missing']))

    async def test_ssl_module_excluded_when_disabled(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a',
                                               needs_storage=False, needs_public_access=False, needs_ssl=False)
        module = result['step_modules']['ssl_configuration']
        self.assertEqual(module['status'], 'excluded')
        self.assertIn('change_supabase_ssl', module['note'])
        self.assertNotIn('acquisition', module)
        post_tools = [p.get('tool') for p in result['post_creation_flow']]
        self.assertNotIn('list_ssl_certificates', post_tools)
        self.assertNotIn('purchase_supabase_ssl_cert', post_tools)
        self.assertTrue(any('http 访问' in str(p.get('action')) for p in result['post_creation_flow']))

    async def test_public_access_module_excluded_when_disabled(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a',
                                               needs_storage=False, needs_public_access=False, needs_ssl=False)
        module = result['step_modules']['public_access']
        self.assertEqual(module['status'], 'excluded')
        self.assertEqual(module['delivery'], '内网交付 private_ip；不购买 EIP、不开公网入方向')
        self.assertNotIn('purchase_method', module)
        self.assertNotIn('eip_baseline', result)

    async def test_intent_modules_absent_and_decision_points_when_omitted(self):
        result = await self.make().arrangement('newly_instance')
        self.assertNotIn('ssl_configuration', result['step_modules'])
        self.assertNotIn('public_access', result['step_modules'])
        self.assertNotIn('eip_baseline', result)
        decisions = ' '.join(result['decision_points'])
        self.assertIn('needs_ssl', decisions)
        self.assertIn('证书可经 MCP 购买或复用已有', decisions)
        self.assertIn('needs_public_access', decisions)

    async def test_omitted_intents_become_decisions(self):
        result = await self.make().arrangement('newly_instance')
        decisions = ' '.join(result['decision_points'])
        for needle in ('needs_storage', 'needs_public_access', 'needs_ssl', 'az_code'):
            self.assertIn(needle, decisions)
        post = result['post_creation_flow']
        self.assertTrue(any(p.get('decision') and 'needs_email_login' in p['decision'] for p in post))
        self.assertTrue(any(p.get('decision') and 'needs_github_login' in p['decision'] for p in post))


class PlanningAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_ssl(self):
        service = PlanningService()
        self.assertEqual((await service.ssl(False))['status'], 'planning_only')
        enabled = await service.ssl(True)
        self.assertEqual(enabled['execution'], 'not_executed')
        self.assertIn('list_ssl_certificates', enabled['steps'][0])
        self.assertIn('purchase_supabase_ssl_cert', enabled['acquisition'])
        self.assertFalse(any('certificate' in item for item in enabled['missing']))
        self.assertEqual(len(service.capabilities()['scenarios']), 6)

    async def test_adapter(self):
        class FixtureClient:
            async def list_certificates(self):
                return {'source': 'test_fixture', 'certificates': []}
        result = await PlanningService(FixtureClient()).ssl(True)
        self.assertEqual(result['certificates']['source'], 'test_fixture')
        self.assertEqual(result['execution'], 'not_executed')


if __name__ == '__main__':
    unittest.main()
