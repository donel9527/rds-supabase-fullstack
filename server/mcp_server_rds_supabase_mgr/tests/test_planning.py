import unittest
from mcp_server_supabase.service.planning import PlanningService

BASICS = {'basic_options': {'name': {'suggested': 'supabase-app-1115'},
                            'version': {'recommended': '1.0.0'},
                            'mode': {'recommended': 'Single'},
                            'flavor_ref': {'recommended': 'rds.supabase.n1.large.2'}},
          'probe_status': {'application_flavors_single': 'ok'}}

NEWLY_INSTANCE = {'scenario': 'newly_instance', 'mode': 'Single',
                  'managed_instance_field_options': {
                      'datastore.version': {'recommended': '18'},
                      'flavor_ref': {'recommended': 'rds.pg.n1.medium.2'},
                      'volume.type': {'recommended': 'ESSD'},
                      'volume.size': {'recommended': 40},
                      'charge_info': {'recommended': {'charge_mode': 'postPaid'}},
                      'availability_zone': {'values': ['cn-east-3a', 'cn-east-3b']},
                      'port': {'recommended': 5432},
                      'enterprise_project_id': {'recommended': '0'}},
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
    def __init__(self): self.calls = []
    async def discover(self, az_code): self.calls.append(az_code); return BASICS


class FakeCatalog:
    def __init__(self, rows=None): self.calls = []; self.rows = rows or []
    async def discover_db_instance_for_create(self, scenario, mode=None, instance_id=None):
        self.calls.append((scenario, mode, instance_id))
        if scenario == 'newly_instance': return NEWLY_INSTANCE
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
    def make(self, rows=None, network_newly=None):
        basics = FakeBasics(); catalog = FakeCatalog(rows); network = FakeNetwork(newly=network_newly)
        return PlanningService(basics=basics, catalog=catalog, network=network)

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
        m3 = result['step_modules']['network_control']
        self.assertEqual(m3['placement']['vpc_id'], 'v1')
        self.assertEqual(m3['security_group_plan']['plan_type'], 'specification')
        eip = result['eip_baseline']
        self.assertEqual(eip['purchase_method']['recommended']['charge_mode'], 'postPaid')
        self.assertEqual(eip['bandwidth']['recommended_size_mbps'], 300)
        self.assertIn('5_bgp', eip['bandwidth']['type'])
        self.assertIn('CreatePublicip', eip['purchase'])
        flow = result['creation_flow']
        self.assertEqual([s['step'] for s in flow], list(range(1, len(flow) + 1)))
        self.assertEqual(flow[0]['phase'], 'network_ready')
        self.assertEqual(len([s for s in flow if s['phase'] == 'security_groups']), 5)
        tools_in_flow = [s['tool'] for s in flow]
        self.assertIn('create_supabase_application', tools_in_flow)
        self.assertIn('show_supabase_creation_progress', tools_in_flow)
        self.assertEqual(flow[-1]['tool'], 'show_supabase_application')
        self.assertEqual(result['decision_points'], [])
        self.assertTrue(any('文件' in note for note in result['security_notes']))
        post_tools = [p.get('tool') for p in result['post_creation_flow']]
        self.assertIn('create_supabase_eip', post_tools)
        self.assertIn('bind_supabase_eip', post_tools)
        self.assertIn('bind_supabase_eip', result['eip_baseline']['bind'])

    async def test_default_recommendation_adds_network_creation_step(self):
        service = self.make(network_newly=NETWORK_NEWLY_DEFAULT)
        result = await service.arrangement('newly_instance', az_code='cn-east-3a',
                                           needs_storage=False, needs_public_access=False, needs_ssl=False)
        first = result['creation_flow'][0]
        self.assertEqual(first['tool'], 'console/KooCLI')
        self.assertIn('default_create', first['action'])

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
        self.assertEqual(len([s for s in flow if s['phase'] == 'security_groups']), 3)
        self.assertIn('show_supabase_creation_progress', [s['tool'] for s in flow])

    async def test_intents_shape_post_creation_flow(self):
        result = await self.make().arrangement('newly_instance', az_code='cn-east-3a',
                                               needs_storage=False, needs_public_access=False, needs_ssl=False)
        post = result['post_creation_flow']
        self.assertTrue(any('private_ip' in str(p.get('action')) for p in post))
        self.assertFalse(any(p.get('tool') == 'change_supabase_eip' for p in post))
        self.assertTrue(any('http 访问' in str(p.get('action')) for p in post))
        self.assertTrue(any('接入信息交付' in str(p.get('action')) for p in post))
        self.assertEqual(result['eip_baseline']['applies_when'],
                         '本编排未启用公网访问——不购买 EIP，接入用 private_ip')

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
        self.assertEqual((await service.ssl(True))['execution'], 'not_executed')
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
