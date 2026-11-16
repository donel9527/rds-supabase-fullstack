import unittest
from mcp_server_supabase import visual


def basic_options_fixture():
    return {'az_code':'cn-east-3a','ha_supported':False,
            'basic_options':{
                'name':{'suggested':'supabase-app-1115',
                        'requirements':['长度 4-64 个字符','必须以字母或中文开头']},
                'version':{'values':['1.0.0','1.1.0'],'recommended':'1.1.0','note':'取可用最高版'},
                'mode':{'values':['Single','Ha'],'recommended':'Single','note':'Single 单机 / Ha 主备'},
                'flavor_ref':{'values':['rds.supabase.n1.medium.2'],'recommended':'rds.supabase.n1.medium.2',
                              'note':'应用规格（rds.supabase.*）'},
                'availability_zone':{'values':['cn-east-3a'],'note':'本次查询的 AZ'},
                'password':{'login_user':'supabase','requirements':['密码为 8~32 个字符','至少包含三种字符']},
                'storage_component':{'values':[{'enabled':False},{'enabled':True}],
                                     'recommended':{'enabled':False},'note':'OBS 存储对接'}},
            'security_group_strategy':{
                'determined':False,'reason':'实例与网络尚未选定',
                'application_group':{'ingress':{'protocol':'tcp','port':8443,'note':'应用服务入口'},
                                     'egress':{'protocol':'tcp','port':5432,'note':'放通托管数据库端口'}},
                'database_group':{'strategy':'新建实例场景：新建专用组；已有实例场景：保持现状不动'}}}


def basic_options_groups_fixture():
    result=basic_options_fixture()
    result['basic_options']['flavor_ref']={
        'values':['rds.supabase.n1.medium.2','rds.supabase.n1.large.2'],
        'recommended':'rds.supabase.n1.medium.2','note':'应用规格（rds.supabase.*）',
        'groups':[
            {'group_type':'general','label':'通用型','specs':[
                {'spec_code':'rds.supabase.n1.medium.2','vcpus':2,'ram':4,
                 'instance_mode':'Single','availability_zones':['cn-east-3a']},
                {'spec_code':'rds.supabase.n1.large.2','vcpus':4,'ram':8,
                 'instance_mode':'Single','availability_zones':['cn-east-3a']}]}]}
    return result


def candidates_fixture():
    return {'scenario':'existed_instance',
            'pagination':{'page':1,'page_size':20,'total_count':25,'total_pages':2},
            'candidates_page':[
                {'id':'i1','name':'pg-1','status':'ACTIVE','datastore_version':'15','deployment_type':'single',
                 'port':5433,'availability_zones':['cn-east-3a'],'created':'2026-11-01T00:00:00Z',
                 'current_actions':['REBOOT']},
                {'id':'i2','name':'pg-2','status':'REBOOTING','datastore_version':'16','deployment_type':'ha',
                 'port':5434,'availability_zones':['cn-east-3a','cn-east-3b'],'created':'2026-11-02T00:00:00Z',
                 'current_actions':[]}]}


def instance_detail_fixture():
    return {'scenario':'existed_instance','instance_id':'i1',
            'basic':{'id':'i1','name':'pg-1','status':'ACTIVE','spec_code':'rds.pg.n1.medium.2','vcpus':2,'ram':4},
            'configuration':{'datastore':{'type':'PostgreSQL','version':'15'},'port':5433,
                             'ha':{'mode':'single'},'volume':{'type':'ESSD','size':40}},
            'network':{'vpc_id':'v1','subnet_id':'s1','security_group_id':'g1'}}


def newly_instance_fixture():
    return {'scenario':'newly_instance','mode':'Single',
            'managed_instance_field_options':{
                'datastore.type':{'fixed':'PostgreSQL'},
                'datastore.version':{'values':['15','16','17'],'recommended':'17','note':'PostgreSQL 引擎大版本'},
                'flavor_ref':{'values':['rds.pg.n1.medium.2','rds.pg.n1.large.2'],'recommended':'rds.pg.n1.medium.2',
                              'note':'实例规格，形如 rds.pg.n1.medium.2'},
                'volume.size':{'minimum':40,'maximum':40000,'recommended':40,'note':'GB'},
                'charge_info':{'values':[{'charge_mode':'postPaid'}],'recommended':{'charge_mode':'postPaid'},
                               'note':'包周期返回订单走订单工具支付'}},
            'top_level_reminder':['availability_zone 必须与顶层一致（服务端强制校验）',
                                  '数据库密码与应用密码同规则，可同值']}


def flavor_groups_fixture():
    return {'scenario':'newly_instance','mode':'Single',
            'managed_instance_field_options':{
                'datastore.type':{'fixed':'PostgreSQL'},
                'datastore.version':{'values':['17','18'],'recommended':'18','note':'PostgreSQL 引擎大版本'},
                'flavor_ref':{'values':['rds.pg.n1.medium.2','rds.pg.n1.large.2','rds.pg.x1.2xlarge.4.ha'],
                              'recommended':'rds.pg.n1.medium.2','note':'实例规格，形如 rds.pg.n1.medium.2',
                              'groups':[
                                  {'group_type':'general','label':'通用型','specs':[
                                      {'spec_code':'rds.pg.n1.medium.2','vcpus':2,'ram':4,
                                       'instance_mode':'single','availability_zones':['cn-east-3a']},
                                      {'spec_code':'rds.pg.n1.large.2','vcpus':4,'ram':8,
                                       'instance_mode':'single','availability_zones':['cn-east-3a']}]},
                                  {'group_type':'rapid','label':'独享型（仅极速型SSD支持）','specs':[
                                      {'spec_code':'rds.pg.x1.2xlarge.4.ha','vcpus':8,'ram':32,
                                       'instance_mode':'ha','availability_zones':['cn-east-3a','cn-east-3b']}]}]},
                'volume.type':{'values':['ESSD','CLOUDSSD','ULTRAHIGH','LOCALSSD'],'recommended':'ESSD',
                               'note':'按 mode 过滤后的可售盘型',
                               'options':[
                                   {'value':'ESSD','label':'极速型SSD','note':'仅支持独享型规格实例',
                                    'compatible_group_types':['rapid']},
                                   {'value':'CLOUDSSD','label':'SSD云盘','note':'仅支持通用型和独享型规格实例',
                                    'compatible_group_types':['general','normal2','dedicated','dedicatenormal',
                                                              'armFlavors','armlocalssd','normallocalssd','bigmem']},
                                   {'value':'ULTRAHIGH','label':'SSD','note':'高性能云盘',
                                    'compatible_group_types':[]},
                                   {'value':'LOCALSSD','label':'本地SSD','note':'本地盘',
                                    'compatible_group_types':None}]},
                'volume.size':{'minimum':40,'maximum':40000,'recommended':40,'note':'GB'}},
            'top_level_reminder':['availability_zone 必须与顶层一致（服务端强制校验）']}


def network_newly_fixture():
    return {'scenario':'newly_instance','preference':'sufficient','vpc_id':'v1','vpc_name':'vpc-1',
            'vpc_cidr':'192.168.0.0/16','subnet_id':'s1','subnet_name':'subnet-1','subnet_cidr':'192.168.0.0/24',
            'availability_zone':'cn-east-3a','available_ip_count':250,
            'security_group_plan':{
                'plan_type':'specification','precondition':'先建默认网络，再建组配规则',
                'application_group':{'name':'supabase-app-sg',
                    'ingress':{'protocol':'tcp','port':8443,'purpose':'应用服务入口——不放通无法登录',
                               'source_cidr_options':[{'key':'open','source_cidr':'0.0.0.0/0'},
                                                      {'key':'detected','source_cidr':'1.2.3.4/32'},
                                                      {'key':'custom','source_cidr':None}]},
                    'egress':{'protocol':'tcp','port':5432,'destination_cidr':'192.168.0.0/24',
                              'purpose':'连接托管数据库——不放通则应用异常不可用'}},
                'database_group':{'name':'supabase-db-sg',
                    'ingress':{'protocol':'tcp','port':5432,'source_cidr':'192.168.0.0/24','purpose':'应用连接数据库'},
                    'egress':{'destination_cidr':'0.0.0.0/0','note':'默认放行，无需额外规则'}},
                'apply_steps':[
                    {'tool':'create_supabase_security_group','args':{'name':'supabase-app-sg'},
                     'returns':'security_group_id'},
                    {'tool':'add_supabase_security_group_rule',
                     'args':{'group_id':'<新应用组的 security_group_id>','direction':'ingress','port':8443}}]}}


def network_existed_fixture():
    return {'scenario':'existed_instance','instance_id':'i1','vpc_id':'v1','subnet_id':'s1',
            'subnet_cidr':'192.168.0.0/24',
            'security_group_plan':{
                'application_group':{'name':'supabase-app-sg',
                    'ingress':{'protocol':'tcp','port':8443,'purpose':'应用服务入口',
                               'source_cidr_options':[{'key':'open','source_cidr':'0.0.0.0/0'}]},
                    'egress':{'protocol':'tcp','port':5432,'destination_cidr':'192.168.0.0/24','purpose':'连接托管数据库'}},
                'database_group':{'action':'不动','current_security_group_id':'g9','note':'保持现状，不做任何变更'},
                'apply_steps':[{'tool':'create_supabase_security_group','args':{'name':'supabase-app-sg'}}]}}


def arrangement_fixture():
    return {'status':'arrangement_baseline','execution':'not_executed','manage_type':'newly_instance',
            'managed_instance_source':{
                'decision':'newly_instance',
                'options':[{'value':'newly_instance','name':'新建实例','recommended':True,
                            'note':'应用与托管 PG 一并创建，参数全链路可控'},
                           {'value':'existed_instance','name':'已有实例','note':'挂载现有可托管 PG；实例参数不可改'}],
                'requirement':'两种方式必须先向用户明确呈现并拿到确定性结论'},
            'step_modules':{
                'supabase_basics':{'status':'fixed',
                    'baseline':{'name':'supabase-app-1115','version':'1.1.0','mode':'Single',
                                'flavor_ref':'rds.supabase.n1.medium.2','availability_zone':'cn-east-3a',
                                'storage_component':{'enabled':False},
                                'password':'经本地请求文件提供（8-32 位三类字符）'}},
                'managed_instance':{'status':'fixed',
                    'baseline':{'datastore':{'type':'PostgreSQL','version':'18'},
                                'flavor_ref':'rds.pg.n1.medium.2','port':5432},
                    'top_level_reminder':['availability_zone 必须与顶层一致']},
                'network_control':{'status':'fixed',
                    'placement':{'preference':'sufficient','vpc_id':'v1','vpc_name':'vpc-1','subnet_id':'s1',
                                 'subnet_name':'subnet-1','subnet_cidr':'192.168.0.0/24',
                                 'availability_zone':'cn-east-3a'},
                    'security_group_plan':{'database_group':{
                        'name':'supabase-db-sg',
                        'ingress':{'protocol':'tcp','port':5432,'source_cidr':'192.168.0.0/24'}}}}},
            'eip_baseline':{
                'purchase_method':{'options':[{'charge_mode':'postPaid','name':'按需购买','note':'随用随停，成本可控'},
                                              {'charge_mode':'prePaid','name':'包周期','note':'长期稳定运行再选'}],
                                   'recommended':{'charge_mode':'postPaid','name':'按需购买'}},
                'bandwidth':{'share_type':'PER（独享带宽）','type':'全动态 BGP（publicip.type=5_bgp）',
                             'size_range_mbps':'5-1000','recommended_size_mbps':300},
                'bind':'change_supabase_eip(application_id, is_bind=true, public_ip_id, public_ip_address)',
                'post_bind':'绑定成功后必须 update_supabase_auth_config 同步 api_external_url'},
            'creation_flow':[
                {'step':1,'phase':'network_ready','tool':'discover_network_for_create',
                 'action':'直接采用已选定的 VPC/子网填入 basic_config'},
                {'step':2,'phase':'security_groups','tool':'create_supabase_security_group',
                 'args':{'name':'supabase-app-sg'},'returns':'security_group_id'}],
            'post_creation_flow':[
                {'tool':'console/KooCLI','action':'按 eip_baseline 购买 EIP 并打标'},
                {'tool':'change_supabase_eip','args':{'application_id':'<id>','is_bind':True,'public_ip_id':'<EIP ID>'}},
                {'decision':'needs_email_login 是否启用邮箱登录'}],
            'decision_points':['az_code：可售 AZ 待选（list_supabase_flavors_with_azs）']}


def arrangement_flavor_match_fixture():
    result=arrangement_fixture()
    result['step_modules']['supabase_basics']['flavor_interaction']=(
        '应用规格与实例规格分开单独询问；应用规格从全部可售规格中选择或自定义，推荐通用型 2U4G')
    instance=result['step_modules']['managed_instance']
    instance['baseline']['flavor_match']={
        'app_flavor_ref':'rds.supabase.n1.medium.2','app_group_type':'general','app_group_label':'通用型',
        'matched_spec':'rds.pg.n1.medium.2','match_basis':'group_type+vcpus+ram'}
    instance['baseline']['volume']={'type':'ESSD','size':40,
                                    'type_basis':'与应用规格档位（通用型）实时兼容'}
    instance['flavor_interaction']=('实例规格按 group_type 十大类分组展示全部可售规格，默认推荐与应用同档（通用型），'
                                    '如需其他档位按分组清单另选')
    instance['volume_interaction']=('磁盘类型展示中文名与实时兼容规格类型；ESSD 仅兼容独享型（极速型SSD）规格，'
                                    'CLOUDSSD 兼容通用型与独享型')
    return result


class WidthTests(unittest.TestCase):
    def test_width_mixed(self):
        self.assertEqual(visual.width('abc'),3)
        self.assertEqual(visual.width('中文'),4)
        self.assertEqual(visual.width('中a'),3)
        self.assertEqual(visual.width(''),0)
        self.assertEqual(visual.width(123),3)
        self.assertEqual(visual.width(None),4)

    def test_pad_fills(self):
        self.assertEqual(visual.pad('ab',5),'ab   ')
        self.assertEqual(visual.pad('中文',6),'中文  ')
        self.assertEqual(visual.pad('中',3),'中 ')

    def test_pad_truncates(self):
        self.assertEqual(visual.pad('中文abc',5),'中文…')
        self.assertEqual(visual.pad('abcdef',3),'ab…')
        self.assertEqual(visual.pad('中文',1),'…')
        for text,columns in (('中文abc',5),('abcdef',3),('中文',1),('abc',10)):
            self.assertLessEqual(visual.width(visual.pad(text,columns)),columns)


class TableTests(unittest.TestCase):
    def test_mixed_alignment_and_borders(self):
        out=visual.table(['字段','值'],[['名称','supabase-app'],['状态','ACTIVE']])
        lines=out.split('\n')
        self.assertEqual(len(lines),6)
        self.assertEqual(len({visual.width(line) for line in lines}),1)
        self.assertTrue(lines[0].startswith('┌') and lines[0].endswith('┐'))
        self.assertTrue(lines[1].startswith('│') and lines[1].endswith('│'))
        self.assertTrue(lines[2].startswith('├') and lines[2].endswith('┤') and '┼' in lines[2])
        self.assertTrue(lines[3].startswith('│') and lines[3].endswith('│'))
        self.assertTrue(lines[-1].startswith('└') and lines[-1].endswith('┘'))
        self.assertIn('名称',out)
        self.assertIn('ACTIVE',out)

    def test_none_cells_and_empty_rows(self):
        out=visual.table(['a','b'],[[None,'x'],['y',None]])
        self.assertEqual(out.count('-'),2)
        out=visual.table(['a'],[])
        self.assertIn('(无数据)',out)
        out=visual.table(['a'],None)
        self.assertIn('(无数据)',out)


class FlowTests(unittest.TestCase):
    def test_flow_steps_and_arrows(self):
        out=visual.flow([{'title':'one','detail':['line1','line2']},
                         {'title':'two','detail':'solo'},
                         {'title':'three','detail':None}])
        self.assertIn('┌─ 步骤 1 ─ one ┐',out)
        self.assertIn('line1',out)
        self.assertIn('solo',out)
        self.assertIn('┌─ 步骤 3 ─ three ┐',out)
        self.assertIn('  ▼',out)
        self.assertEqual(out.count('  ▼'),2)
        self.assertIn('└',out)
        self.assertIn('┘',out)

    def test_flow_box_width_consistent(self):
        out=visual.flow([{'title':'规格','detail':['中文 line']}])
        lines=out.split('\n')
        self.assertEqual(len({visual.width(line) for line in lines}),1)


class BlockTests(unittest.TestCase):
    def test_block_shapes(self):
        self.assertEqual(visual.block('标题','正文'),'【标题】\n正文')
        self.assertEqual(visual.block('标题',['a','b']),'【标题】\na\nb')
        self.assertEqual(visual.block('标题',None),'【标题】')


class RenderBasicOptionsTests(unittest.TestCase):
    def test_full_fixture(self):
        out=visual.render_basic_options(basic_options_fixture())
        self.assertIn('【Supabase 基本信息（AZ cn-east-3a）】',out)
        self.assertIn('supabase-app-1115',out)
        self.assertIn('1.1.0',out)
        self.assertIn('rds.supabase.n1.medium.2',out)
        self.assertIn('登录用户 supabase',out)
        self.assertIn('长度 4-64 个字符；必须以字母或中文开头',out)
        self.assertIn('false',out)
        self.assertIn('【安全组推荐策略】',out)
        self.assertIn('8443',out)
        self.assertIn('应用服务入口',out)
        self.assertIn('新建实例场景：新建专用组；已有实例场景：保持现状不动',out)

    def test_missing_keys_do_not_raise(self):
        out=visual.render_basic_options({})
        self.assertIn('【Supabase 基本信息（AZ -）】',out)
        self.assertIn('【安全组推荐策略】',out)


class RenderBasicOptionsGroupsTests(unittest.TestCase):
    def test_application_flavor_groups_block(self):
        out=visual.render_basic_options(basic_options_groups_fixture())
        self.assertIn('【应用规格分组】',out)
        self.assertIn('通用型（general）｜ rds.supabase.n1.medium.2（2 vCPU/4 GB）',out)
        self.assertIn('rds.supabase.n1.large.2（4 vCPU/8 GB）',out)
        self.assertIn('【安全组推荐策略】',out)

    def test_groups_block_absent_without_groups(self):
        out=visual.render_basic_options(basic_options_fixture())
        self.assertNotIn('【应用规格分组】',out)

    def test_groups_tolerate_missing_label_and_specs(self):
        payload=basic_options_fixture()
        payload['basic_options']['flavor_ref']={'recommended':'rds.supabase.n1.medium.2',
                                                'groups':[{'group_type':'general'}]}
        out=visual.render_basic_options(payload)
        self.assertIn('【应用规格分组】',out)
        self.assertIn('general（general）｜ -',out)


class RenderDbInstanceTests(unittest.TestCase):
    def test_candidate_listing(self):
        out=visual.render_db_instance(candidates_fixture())
        self.assertIn('【可托管实例列表（第 1/2 页，共 25 个）】',out)
        self.assertIn('当前操作',out)
        self.assertIn('REBOOT',out)
        self.assertIn('pg-1',out)
        self.assertIn('ACTIVE',out)

    def test_candidate_listing_without_pagination(self):
        out=visual.render_db_instance({'scenario':'existed_instance',
                                       'candidates':[{'id':'i1','name':'pg-1','status':'ACTIVE'},
                                                     {'id':'i2','name':'pg-2','status':'ACTIVE'}]})
        self.assertIn('【可托管实例列表（第 1/1 页，共 2 个）】',out)

    def test_instance_detail(self):
        out=visual.render_db_instance(instance_detail_fixture())
        self.assertIn('【实例信息】',out)
        self.assertIn('PostgreSQL',out)
        self.assertIn('ESSD',out)
        self.assertIn('rds.pg.n1.medium.2',out)
        self.assertIn('【网络】',out)
        self.assertIn('g1',out)

    def test_newly_baseline(self):
        out=visual.render_db_instance(newly_instance_fixture())
        self.assertIn('托管实例参数基线（mode Single）',out)
        self.assertIn('PostgreSQL',out)
        self.assertIn('{"charge_mode": "postPaid"}',out)
        self.assertIn('【提醒】',out)
        self.assertIn('availability_zone 必须与顶层一致（服务端强制校验）',out)

    def test_missing_keys_do_not_raise(self):
        out=visual.render_db_instance({})
        self.assertIn('托管实例参数基线（mode -）',out)


class RenderDbInstanceGroupsTests(unittest.TestCase):
    def test_flavor_groups_block(self):
        out=visual.render_db_instance(flavor_groups_fixture())
        self.assertIn('【实例规格分组】',out)
        self.assertIn('通用型（general）｜ rds.pg.n1.medium.2（2 vCPU/4 GB） · rds.pg.n1.large.2（4 vCPU/8 GB）',out)
        self.assertIn('独享型（仅极速型SSD支持）（rapid）｜ rds.pg.x1.2xlarge.4.ha（8 vCPU/32 GB）',out)

    def test_volume_options_block(self):
        out=visual.render_db_instance(flavor_groups_fixture())
        self.assertIn('【磁盘类型】',out)
        header=[line for line in out.split('\n') if line.startswith('│ 值 ')][0]
        for column in ('中文名','说明','兼容规格类型'):
            self.assertIn(column,header)
        self.assertIn('极速型SSD',out)
        self.assertIn('仅支持独享型规格实例',out)
        self.assertIn('SSD云盘',out)
        self.assertIn('仅支持通用型和独享型规格实例',out)
        self.assertIn('rapid',out)
        self.assertIn('general,normal2,dedicated',out)
        ultra=[line for line in out.split('\n') if line.startswith('│ ULTRAHIGH ')]
        self.assertEqual(len(ultra),1)
        self.assertEqual([cell.strip() for cell in ultra[0].split('│')][-2],'-')

    def test_blocks_absent_without_groups_and_options(self):
        out=visual.render_db_instance(newly_instance_fixture())
        self.assertNotIn('【实例规格分组】',out)
        self.assertNotIn('【磁盘类型】',out)

    def test_volume_options_tolerate_partial_entries(self):
        payload={'scenario':'newly_instance','mode':'Single',
                 'managed_instance_field_options':{
                     'flavor_ref':{'recommended':'rds.pg.n1.medium.2','groups':[{'group_type':'general'}]},
                     'volume.type':{'recommended':'ESSD','options':[{'value':'ESSD'}]}}}
        out=visual.render_db_instance(payload)
        self.assertIn('【实例规格分组】',out)
        self.assertIn('general（general）｜ -',out)
        self.assertIn('【磁盘类型】',out)
        self.assertIn('ESSD',out)


class RenderNetworkTests(unittest.TestCase):
    def test_newly_fixture(self):
        out=visual.render_network(network_newly_fixture())
        self.assertIn('【网络选址】',out)
        self.assertIn('vpc-1',out)
        self.assertIn('250',out)
        self.assertIn('【安全组规格（仅规格，不创建资源）】',out)
        self.assertIn('open:0.0.0.0/0 / detected:1.2.3.4/32 / custom:None',out)
        self.assertIn('应用服务入口——不放通无法登录',out)
        self.assertIn('数据库组',out)
        self.assertIn('【前提】',out)
        self.assertIn('先建默认网络，再建组配规则',out)
        self.assertIn('【执行步骤】',out)
        self.assertIn('1 create_supabase_security_group',out)
        self.assertIn('2 add_supabase_security_group_rule',out)

    def test_existed_fixture_database_group_untouched(self):
        out=visual.render_network(network_existed_fixture())
        self.assertIn('不动',out)
        self.assertIn('g9',out)

    def test_missing_keys_do_not_raise(self):
        out=visual.render_network({})
        self.assertIn('【网络选址】',out)
        self.assertIn('【安全组规格（仅规格，不创建资源）】',out)


class RenderArrangementTests(unittest.TestCase):
    def test_full_fixture(self):
        out=visual.render_arrangement(arrangement_fixture())
        self.assertIn('【托管实例来源决策】',out)
        self.assertIn('- 新建实例（推荐且默认）：应用与托管 PG 一并创建，参数全链路可控',out)
        self.assertIn('- 已有实例：挂载现有可托管 PG；实例参数不可改',out)
        self.assertIn('已确认：newly_instance',out)
        self.assertIn('两种方式必须先向用户明确呈现并拿到确定性结论',out)
        self.assertIn('【模块一：Supabase 基本信息】',out)
        self.assertIn('supabase-app-1115',out)
        self.assertIn('{"enabled": false}',out)
        self.assertIn('【模块二：托管实例】',out)
        self.assertIn('{"type": "PostgreSQL", "version": "18"}',out)
        self.assertIn('rds.pg.n1.medium.2',out)
        self.assertIn('【模块三：网络控制】',out)
        self.assertIn('新建 supabase-db-sg：入方向 tcp/5432 放通 192.168.0.0/24',out)
        self.assertIn('【EIP 购买基线】',out)
        self.assertIn('按需购买',out)
        self.assertIn('300M',out)
        self.assertIn('change_supabase_eip(application_id, is_bind=true, public_ip',out)
        self.assertIn('【创建流程（1:1 严格执行）】',out)
        self.assertIn('1. discover_network_for_create [network_ready]',out)
        self.assertIn('2. create_supabase_security_group [security_groups]',out)
        self.assertIn('"name": "supabase-app-sg"',out)
        self.assertIn('【创建后动作】',out)
        self.assertIn('- console/KooCLI：按 eip_baseline 购买 EIP 并打标',out)
        self.assertIn('"application_id": "<id>"',out)
        self.assertIn('- 待决策：needs_email_login 是否启用邮箱登录',out)
        self.assertIn('【待决策】',out)
        self.assertIn('az_code：可售 AZ 待选',out)

    def test_eip_bandwidth_user_decision_renders_without_default(self):
        result=arrangement_fixture()
        result['eip_baseline']['bandwidth']={'share_type':'PER（独享带宽）','type':'全动态 BGP（publicip.type=5_bgp）',
                                            'size_range_mbps':'5-1000',
                                            'size_decision':'大小由用户决策（无默认推荐）——采购前向用户确认后填入 create_supabase_eip(bandwidth_size_mbps=<5-1000>)'}
        out=visual.render_arrangement(result)
        self.assertIn('【EIP 购买基线】',out)
        self.assertIn('用户决策',out)
        self.assertIn('大小由用户决策（无默认推荐）',out)
        self.assertNotIn('300M',out)   # no default bandwidth anymore

    def test_instance_selection_module_reuses_candidate_table(self):
        result=arrangement_fixture()
        result['step_modules']['managed_instance']={
            'status':'instance_selection',
            'pagination':{'page':1,'page_size':20,'total_count':1,'total_pages':1},
            'candidates_page':[{'id':'i1','name':'pg-1','status':'ACTIVE','current_actions':[]}]}
        out=visual.render_arrangement(result)
        self.assertIn('【模块二：托管实例】',out)
        self.assertIn('pg-1',out)
        self.assertIn('当前操作',out)

    def test_pending_modules_render_hint(self):
        result=arrangement_fixture()
        result['step_modules']={
            'supabase_basics':{'status':'pending_decision','hint':'回填 az_code 重新生成本编排'},
            'managed_instance':{'status':'pending_decision','hint':'先在模块2选定实例'},
            'network_control':{'status':'pending_decision','hint':'先在模块2选定实例，再以 instance_id 生成网络编排'}}
        out=visual.render_arrangement(result)
        self.assertIn('【模块一：Supabase 基本信息】',out)
        self.assertIn('回填 az_code 重新生成本编排',out)
        self.assertIn('【模块二：托管实例】',out)
        self.assertIn('【模块三：网络控制】',out)

    def test_existed_network_module_shows_untouched_group(self):
        result=arrangement_fixture()
        result['step_modules']['network_control']={
            'status':'fixed','placement':{'vpc_id':'v1','subnet_id':'s1','subnet_cidr':'192.168.0.0/24'},
            'security_group_plan':{'database_group':{'action':'不动','current_security_group_id':'g9'}}}
        out=visual.render_arrangement(result)
        self.assertIn('不动（现有组 g9）',out)

    def test_missing_keys_do_not_raise(self):
        out=visual.render_arrangement({})
        self.assertIn('【托管实例来源决策】',out)
        self.assertIn('【模块一：Supabase 基本信息】',out)
        self.assertIn('【模块二：托管实例】',out)
        self.assertIn('【模块三：网络控制】',out)
        self.assertNotIn('【EIP 购买基线】',out)
        self.assertNotIn('【SSL 配置】',out)
        self.assertNotIn('【公网访问（EIP）】',out)
        self.assertIn('【创建流程（1:1 严格执行）】',out)
        self.assertIn('【创建后动作】',out)
        self.assertNotIn('【待决策】',out)


class RenderArrangementFlavorMatchTests(unittest.TestCase):
    def test_flavor_match_row_and_interactions(self):
        out=visual.render_arrangement(arrangement_flavor_match_fixture())
        self.assertIn('规格匹配',out)
        self.assertIn('rds.pg.n1.medium.2（与应用 rds.supabase.n1.medium.2 同档：通用型，'
                      '依据 group_type+vcpus+ram）',out)
        self.assertIn('ESSD（与应用规格档位（通用型）实时兼容）｜ 40 GB',out)
        self.assertIn('规格交互：应用规格与实例规格分开单独询问',out)
        self.assertIn('规格交互：实例规格按 group_type 十大类分组展示全部可售规格，默认推荐与应用同档',out)
        self.assertIn('磁盘类型交互：磁盘类型展示中文名与实时兼容规格类型',out)

    def test_flavor_match_row_defaults_basis_when_missing(self):
        result=arrangement_flavor_match_fixture()
        del result['step_modules']['managed_instance']['baseline']['flavor_match']['match_basis']
        out=visual.render_arrangement(result)
        self.assertIn('依据 group_type+vcpus+ram）',out)

    def test_flavor_match_absent_without_fields(self):
        out=visual.render_arrangement(arrangement_fixture())
        self.assertNotIn('规格匹配',out)
        self.assertNotIn('规格交互',out)
        self.assertNotIn('磁盘类型交互',out)

    def test_interactions_render_for_hint_modules_too(self):
        result=arrangement_fixture()
        result['step_modules']['managed_instance']={'status':'pending_decision','hint':'先在模块2选定实例',
                                                    'volume_interaction':'磁盘类型展示中文名与实时兼容规格类型'}
        out=visual.render_arrangement(result)
        self.assertIn('先在模块2选定实例',out)
        self.assertIn('磁盘类型交互：磁盘类型展示中文名与实时兼容规格类型',out)


class RenderEipTests(unittest.TestCase):
    def test_idle_selection(self):
        out=visual.render_eip({'mode':'idle_selection','idle_eips':[
            {'id':'e1','public_ip_address':'1.2.3.4','alias':'a1','status':'idle',
             'bandwidth_size_mbps':300,'charge_mode':'postPaid'}]})
        self.assertIn('【空闲 EIP（选定其一可直接绑定，不新建）】',out)
        self.assertIn('1.2.3.4',out)
        self.assertIn('300',out)
        self.assertIn('postPaid',out)

    def test_elastic_properties(self):
        out=visual.render_eip({'id':'e2','public_ip_address':'5.6.7.8','alias':'a2','status':'bind',
                                'bandwidth_size_mbps':300,'charge_mode':'postPaid','publicip_type':'5_bgp',
                                'share_type':'PER','order_id':'CS123'})
        self.assertIn('【弹性 EIP】',out)
        self.assertIn('5.6.7.8',out)
        self.assertIn('5_bgp',out)
        self.assertIn('订单 ID（控制台支付后生效）',out)
        self.assertIn('CS123',out)

    def test_missing_keys_do_not_raise(self):
        out=visual.render_eip({})
        self.assertIn('【弹性 EIP】',out)


class ToleranceTests(unittest.TestCase):
    def test_every_renderer_tolerates_empty_and_partial(self):
        renderers=(visual.render_basic_options,visual.render_db_instance,visual.render_network,
                   visual.render_arrangement,visual.render_eip,visual.render_ssl_certificates,
                   visual.render_ssl_purchase)
        partials=(visual.render_basic_options({'az_code':'cn-east-3a'}),
                  visual.render_db_instance({'scenario':'existed_instance'}),
                  visual.render_network({'scenario':'newly_instance'}),
                  visual.render_arrangement({'manage_type':'newly_instance'}),
                  visual.render_eip({'mode':'idle_selection'}),
                  visual.render_ssl_certificates({'total':1}),
                  visual.render_ssl_purchase({'status':'preview','params':{'brand':'TRUSTASIA'}}))
        for renderer in renderers:
            for payload in ({},None):
                with self.subTest(renderer=renderer.__name__,payload=payload):
                    self.assertTrue(isinstance(renderer(payload),str))
        for output in partials:
            self.assertTrue(isinstance(output,str))


def storage_options_fixture():
    return {'mode':'storage_options',
            'credential':{'temporary':True,
                          'detail':'OBS 临时凭证含 SecurityToken，有效期约 1 小时',
                          'notice':'临时凭证过期后需重新获取，长期运行建议固定 AK/SK'},
            'reuse':{'option':'reuse','note':'私有桶优先；Public 桶须评估风险后再复用',
                     'buckets':[
                         {'name':'fitz-assets-private','location':'cn-east-3','public_status':'私有',
                          'risk_note':'-'},
                         {'name':'fitz-assets-public','location':'cn-east-3','public_status':'Public',
                          'risk_note':'公网可读，存在数据泄露风险，不建议复用'}],
                     'read_test':{'passed':True,'detail':'全部桶 ListObjects 读探测通过'}},
            'new_bucket':{'option':'new','note':'私有 STANDARD 桶并阻断公共访问，参数全链路可控',
                          'spec':{'bucket_name':'supabase-storage-1115',
                                  'storage_class':'STANDARD','bucket_type':'OBJECT','redundancy':'多AZ',
                                  'block_public_access':True,'region':'cn-east-3','enterprise_project':'0',
                                  'storage_component_hint':{
                                      'bucket':'supabase-storage-1115',
                                      'ak_sk':'经本地请求文件提供，不落盘不回显'}}},
            'storage_component_note':'桶名即 spec.bucket_name；AK/SK 经本地请求文件提供'}


def storage_created_fixture():
    return {'status':'ok',
            'spec':{'bucket_name':'supabase-storage-1115','storage_class':'STANDARD','bucket_type':'OBJECT',
                    'redundancy':'多AZ','block_public_access':True,'region':'cn-east-3',
                    'enterprise_project':'0'},
            'storage_component_hint':{'bucket':'supabase-storage-1115',
                                      'ak_sk':'AKSK 经本地请求文件提供，不落盘不回显'},
            'note':'桶 supabase-storage-1115 已创建并完成 storage_component 对接',
            'warnings':[]}


def storage_pending_fixture():
    return {'status':'confirmation_required',
            'bucket':{'bucket_name':'supabase-storage-1115','storage_class':'STANDARD','bucket_type':'OBJECT',
                      'redundancy':'多AZ','block_public_access':True,'region':'cn-east-3',
                      'enterprise_project':'0'},
            'note':'预览完成，等待确认后创建',
            'warnings':['确认后才会真正创建桶','包周期实例的订单需控制台支付']}


def arrangement_obs_fixture():
    result=arrangement_fixture()
    result['step_modules']['obs_integration']={
        'source_tool':'discover_supabase_storage',
        'acquisition':{'recommended':'new',
                       'options':[{'key':'reuse','name':'复用已有桶','note':'私有桶优先，需读探测通过'},
                                  {'key':'new','name':'新建桶','note':'私有 STANDARD 桶，阻断公共访问'}]},
        'new_bucket_spec':{'bucket_name':'supabase-storage-1115','storage_class':'STANDARD',
                           'bucket_type':'OBJECT','redundancy':'多AZ','block_public_access':True,
                           'region':'cn-east-3','enterprise_project':'0'},
        'credential':{'temporary':True,'notice':'临时凭证含 SecurityToken，过期需重新获取'}}
    return result


def arrangement_ssl_public_fixture():
    result=arrangement_fixture()
    del result['eip_baseline']
    result['step_modules']['ssl_configuration']={
        'status':'planned',
        'acquisition':{'recommended':'purchase',
                       'options':[{'key':'reuse','name':'复用已有证书',
                                   'note':'list_ssl_certificates 盘点账号已有证书，选定 cert_id 直接用于 change_supabase_ssl'},
                                  {'key':'purchase','name':'购买新证书',
                                   'note':'purchase_supabase_ssl_cert 两段式购买+申请；免费档 DV_SSL_CERT_BASIC 推荐'},
                                  {'key':'import_own','name':'导入自有证书',
                                   'note':'用户已在 SCM 持有证书，提供 cert_id 挂载'}]},
        'domain_note':'证书绑定域名须可用；纯 EIP 公网 IP 无域名时仅支持文件验证',
        'enable_flow':['list_ssl_certificates：盘点可复用证书，无合适再购买',
                       'purchase_supabase_ssl_cert：两段式购买并申请（免费档推荐）',
                       'change_supabase_ssl：以选定 cert_id 开启 SSL，低峰执行'],
        'impact':['SSL 切换短暂中断，低峰执行','生效后访问协议变 https，api_external_url 与回调地址须同步']}
    result['step_modules']['public_access']={
        'status':'planned',
        'applies_when':'公网访问（needs_public_access；建议默认启用）',
        'purchase_method':{'options':[{'charge_mode':'postPaid','name':'按需购买','note':'随用随停，成本可控'},
                                      {'charge_mode':'prePaid','name':'包周期','note':'长期稳定运行再选'}],
                           'recommended':{'charge_mode':'postPaid','name':'按需购买'}},
        'bandwidth':{'share_type':'PER（独享带宽）','type':'全动态 BGP（publicip.type=5_bgp）',
                     'size_range_mbps':'5-1000','recommended_size_mbps':300},
        'purchase':'优先空闲：create_supabase_eip(prefer_idle=true) 先列未绑定 EIP 供用户选定',
        'bind':'bind_supabase_eip(instance_id, public_ip_id, public_ip)（三重校验，RDS AttachEip）',
        'post_bind':'绑定成功后必须 update_supabase_auth_config 同步 api_external_url'}
    return result


def arrangement_modules_excluded_fixture():
    result=arrangement_fixture()
    del result['eip_baseline']
    result['step_modules']['ssl_configuration']={'status':'excluded',
                                                 'note':'本次不开 SSL：应用走 http 访问（enable_ssl=false）'}
    result['step_modules']['public_access']={'status':'excluded',
                                             'note':'内网交付 private_ip；不购买 EIP、不开公网入方向'}
    return result


def ssl_certificates_fixture():
    return {'data':{'certificates':[
                {'id':'scm-1001','name':'wildcard-example','domain':'*.example.com',
                 'sans':['a.example.com','b.example.com'],'type':'DV_SSL_CERT','brand':'GEOTRUST',
                 'status':'ISSUED','expire_time':'2027-03-01T00:00:00Z','domain_type':'WILDCARD',
                 'domain_count':1,'enterprise_project_id':'0'},
                {'id':'scm-1002','name':'ip-cert','domain':'123.60.101.251','sans':[],
                 'type':'DV_SSL_CERT_BASIC','brand':'TRUSTASIA','status':'PAID','expire_time':None,
                 'domain_type':'SINGLE_DOMAIN','domain_count':1,'enterprise_project_id':'0'}]},
            'total':2,
            'note':'SCM 为账号级全局资源（全局服务，region 固定 cn-north-4）'}


def ssl_purchase_preview_fixture():
    return {'status':'preview','plan_id':'plan-ssl-9',
            'params':{'brand':'TRUSTASIA','type':'DV_SSL_CERT_BASIC','domain_type':'SINGLE_DOMAIN',
                      'effective_time':1,'order_number':1,'is_auto_pay':False},
            'billing':{'tier':'免费档','note':'DV_SSL_CERT_BASIC 免费，订阅即生效，无需支付订单'},
            'apply':{'domain':'123.60.101.251','domain_method':'File','auto_dns_auth':False,
                     'applicant':{'name':'张三','email':'zhang@example.com','phone':'13800000000'}},
            'impact':['免费档无需支付；付费档生成待支付订单，支付后才可申请签发',
                      '纯 EIP 公网 IP 证书仅支持文件验证']}


def ssl_purchase_confirm_fixture():
    return {'status':'submitted','plan_id':'plan-ssl-9','certificate_id':'scm-2001',
            'subscription':{'certificate_id':'scm-2001','status':'PAID','expire_time':'2027-11-15'},
            'apply':{'status':'apply_submitted','domain_method':'File',
                     'track':['订阅完成','证书申请已提交，等待域名验证']}}


class RenderStorageTests(unittest.TestCase):
    def test_storage_options_full(self):
        out=visual.render_storage(storage_options_fixture())
        self.assertIn('【OBS 存储方案（大文件/图片/视频承载）】',out)
        self.assertIn('- 复用已有桶：私有桶优先；Public 桶须评估风险后再复用',out)
        self.assertIn('- 新建桶（推荐、默认）：私有 STANDARD 桶并阻断公共访问，参数全链路可控',out)
        self.assertIn('【凭证模式】',out)
        self.assertIn('临时凭证（含 SecurityToken）',out)
        self.assertIn('【可复用桶（私有优先）】',out)
        self.assertIn('桶名',out)
        self.assertIn('公共状态',out)
        self.assertIn('风险提示',out)
        self.assertIn('fitz-assets-public',out)
        self.assertIn('公网可读，存在数据泄露风险，不建议复用',out)
        self.assertIn('【新桶完整参数配置（推荐）】',out)
        self.assertIn('supabase-storage-1115',out)
        self.assertIn('STANDARD',out)
        self.assertIn('多AZ',out)
        self.assertIn('经本地请求文件提供，不落盘不回显',out)
        self.assertIn('挂载',out)
        self.assertIn('【storage_component 对应】',out)
        self.assertIn('桶名即 spec.bucket_name；AK/SK 经本地请求文件提供',out)

    def test_storage_options_read_test_failed(self):
        result=storage_options_fixture()
        result['reuse']['read_test']={'passed':False,'detail':'fitz-assets-public 无 ListObjects 权限'}
        out=visual.render_storage(result)
        self.assertIn('读测试未通过：fitz-assets-public 无 ListObjects 权限',out)

    def test_storage_options_notice_omitted_when_none(self):
        result=storage_options_fixture()
        del result['credential']['notice']
        out=visual.render_storage(result)
        self.assertNotIn('notice',out)

    def test_long_note_wraps_without_truncation(self):
        note='存储对接说明'*25
        result=storage_options_fixture()
        result['storage_component_note']=note
        out=visual.render_storage(result)
        section=out.split('【storage_component 对应】\n',1)[1]
        lines=section.split('\n')
        self.assertGreater(len(lines),1)
        self.assertNotIn('…',section)
        for line in lines:
            self.assertLessEqual(visual.width(line),90)
        self.assertEqual(''.join(lines),note)

    def test_created_ok(self):
        out=visual.render_storage(storage_created_fixture())
        self.assertIn('【新桶参数规格】',out)
        self.assertIn('supabase-storage-1115',out)
        self.assertIn('STANDARD',out)
        self.assertIn('【状态】',out)
        self.assertIn('已创建：桶 supabase-storage-1115 已创建并完成 storage_component 对接',out)
        self.assertIn('AKSK 经本地请求文件提供，不落盘不回显',out)
        self.assertIn('挂载',out)
        self.assertNotIn('【注意】',out)

    def test_confirmation_required(self):
        out=visual.render_storage(storage_pending_fixture())
        self.assertIn('【新桶参数规格】',out)
        self.assertIn('supabase-storage-1115',out)
        self.assertIn('【状态】',out)
        self.assertIn('待确认（预览返回 plan_id）',out)
        self.assertIn('【注意】',out)
        self.assertIn('确认后才会真正创建桶',out)
        self.assertIn('包周期实例的订单需控制台支付',out)

    def test_missing_keys_do_not_raise(self):
        for payload in ({},None,{'mode':'storage_options'},{'status':'ok'}):
            with self.subTest(payload=payload):
                self.assertTrue(isinstance(visual.render_storage(payload),str))


class RenderArrangementObsTests(unittest.TestCase):
    def test_obs_integration_block(self):
        out=visual.render_arrangement(arrangement_obs_fixture())
        self.assertIn('【OBS 桶对接（大文件存储场景）】',out)
        self.assertIn('- 复用已有桶：私有桶优先，需读探测通过',out)
        self.assertIn('- 新建桶：私有 STANDARD 桶，阻断公共访问（推荐/默认）',out)
        self.assertIn('supabase-storage-1115',out)
        self.assertIn('凭证提示：临时凭证含 SecurityToken，过期需重新获取',out)
        self.assertIn('【模块三：网络控制】',out)
        self.assertIn('【EIP 购买基线】',out)

    def test_without_obs_key_output_unchanged(self):
        out=visual.render_arrangement(arrangement_fixture())
        self.assertNotIn('OBS 桶对接',out)

    def test_credential_line_only_when_temporary(self):
        result=arrangement_obs_fixture()
        result['step_modules']['obs_integration']['credential']={'temporary':False,
                                                                 'notice':'长期 AK/SK'}
        out=visual.render_arrangement(result)
        self.assertIn('【OBS 桶对接（大文件存储场景）】',out)
        self.assertNotIn('凭证提示',out)


class RenderArrangementSslPublicTests(unittest.TestCase):
    def test_ssl_and_public_access_modules(self):
        out=visual.render_arrangement(arrangement_ssl_public_fixture())
        self.assertIn('【SSL 配置】',out)
        self.assertIn('状态：planned',out)
        self.assertIn('- 复用已有证书：list_ssl_certificates 盘点账号已有证书，选定 cert_id 直接用于 change_supabase_ssl',out)
        self.assertIn('- 购买新证书：purchase_supabase_ssl_cert 两段式购买+申请；免费档 DV_SSL_CERT_BASIC 推荐（推荐）',out)
        self.assertIn('- 导入自有证书：用户已在 SCM 持有证书，提供 cert_id 挂载',out)
        self.assertIn('域名与 IP 前提：证书绑定域名须可用；纯 EIP 公网 IP 无域名时仅支持文件验证',out)
        self.assertIn('启用流程：',out)
        self.assertIn('1. list_ssl_certificates：盘点可复用证书，无合适再购买',out)
        self.assertIn('3. change_supabase_ssl：以选定 cert_id 开启 SSL，低峰执行',out)
        self.assertIn('- SSL 切换短暂中断，低峰执行',out)
        self.assertIn('【公网访问（EIP）】',out)
        self.assertIn('按需购买',out)
        self.assertIn('300M',out)
        self.assertIn('bind_supabase_eip',out)
        self.assertIn('update_supabase_auth_config 同步 api_externa',out)
        self.assertNotIn('【EIP 购买基线】',out)
        self.assertIn('【模块三：网络控制】',out)

    def test_excluded_modules_render_notices(self):
        out=visual.render_arrangement(arrangement_modules_excluded_fixture())
        self.assertIn('【SSL 配置】',out)
        self.assertIn('状态：excluded（已排除）',out)
        self.assertIn('本次不开 SSL：应用走 http 访问（enable_ssl=false）',out)
        self.assertIn('【公网访问（EIP）】',out)
        self.assertIn('内网交付 private_ip；不购买 EIP、不开公网入方向',out)
        self.assertNotIn('【EIP 购买基线】',out)

    def test_excluded_modules_fall_back_to_default_notes(self):
        result=arrangement_fixture()
        del result['eip_baseline']
        result['step_modules']['ssl_configuration']={'status':'excluded'}
        result['step_modules']['public_access']={'status':'excluded'}
        out=visual.render_arrangement(result)
        self.assertIn('本次不开 SSL：应用保持 http 访问',out)
        self.assertIn('内网交付：不购买 EIP、不开公网入方向，接入用 private_ip',out)

    def test_excluded_public_access_uses_delivery_key(self):
        result=arrangement_fixture()
        del result['eip_baseline']
        result['step_modules']['public_access']={'status':'excluded',
                                                 'delivery':'内网交付 private_ip；不购买 EIP、不开公网入方向'}
        out=visual.render_arrangement(result)
        self.assertIn('【公网访问（EIP）】',out)
        self.assertIn('状态：excluded（已排除）',out)
        self.assertIn('内网交付 private_ip；不购买 EIP、不开公网入方向',out)

    def test_modules_absent_renders_legacy_eip_baseline(self):
        out=visual.render_arrangement(arrangement_fixture())
        self.assertNotIn('【SSL 配置】',out)
        self.assertNotIn('【公网访问（EIP）】',out)
        self.assertIn('【EIP 购买基线】',out)

    def test_public_access_module_wins_over_stale_eip_baseline(self):
        result=arrangement_ssl_public_fixture()
        result['eip_baseline']={'purchase_method':{'recommended':{'name':'按需购买'}},
                                'bandwidth':{'recommended_size_mbps':300}}
        out=visual.render_arrangement(result)
        self.assertIn('【公网访问（EIP）】',out)
        self.assertNotIn('【EIP 购买基线】',out)


class RenderSslCertificatesTests(unittest.TestCase):
    def test_full_fixture(self):
        out=visual.render_ssl_certificates(ssl_certificates_fixture())
        self.assertIn('【账号已有 SSL 证书（共 2 张）】',out)
        self.assertIn('scm-1001',out)
        self.assertIn('wildcard-example',out)
        self.assertIn('*.example.com（另含 SAN 2 个）',out)
        self.assertIn('123.60.101.251',out)
        self.assertIn('DV_SSL_CERT_BASIC',out)
        self.assertIn('GEOTRUST',out)
        self.assertIn('TRUSTASIA',out)
        self.assertIn('PAID',out)
        self.assertIn('2027-03-01T00:00:00Z',out)
        self.assertIn('状态说明：PAID=已购待申请；其余状态以 SCM 返回为准',out)
        self.assertIn('提示：证书 ID 即 change_supabase_ssl 的 cert_id 入参',out)
        self.assertIn('SCM 为账号级全局资源',out)

    def test_bare_certificates_envelope(self):
        out=visual.render_ssl_certificates({'certificates':[
            {'id':'scm-1','name':'c1','domain':'a.example.com','sans':[],'type':'OV_SSL_CERT',
             'brand':'GLOBALSIGN','status':'PAID','expire_time':'2027-01-01'}],
            'total':1,'note':'note from top level'})
        self.assertIn('【账号已有 SSL 证书（共 1 张）】',out)
        self.assertIn('scm-1',out)
        self.assertIn('note from top level',out)

    def test_missing_keys_do_not_raise(self):
        for payload in ({},None,{'data':{}},{'data':{'certificates':[]}},{'total':3}):
            with self.subTest(payload=payload):
                self.assertTrue(isinstance(visual.render_ssl_certificates(payload),str))
        out=visual.render_ssl_certificates({})
        self.assertIn('【账号已有 SSL 证书（共 0 张）】',out)
        self.assertIn('(无数据)',out)
        self.assertIn('状态说明：PAID=已购待申请',out)


class RenderSslPurchaseTests(unittest.TestCase):
    def test_preview_full(self):
        out=visual.render_ssl_purchase(ssl_purchase_preview_fixture())
        self.assertIn('【证书购买预览】',out)
        self.assertIn('plan-ssl-9',out)
        self.assertIn('【购买参数】',out)
        self.assertIn('品牌',out)
        self.assertIn('TRUSTASIA',out)
        self.assertIn('类型',out)
        self.assertIn('DV_SSL_CERT_BASIC',out)
        self.assertIn('域名类型',out)
        self.assertIn('年限',out)
        self.assertIn('1 年',out)
        self.assertIn('张数',out)
        self.assertIn('1 张',out)
        self.assertIn('自动支付',out)
        self.assertIn('false',out)
        self.assertIn('【计费】',out)
        self.assertIn('免费档',out)
        self.assertIn('【证书申请】',out)
        self.assertIn('域名验证方式',out)
        self.assertIn('文件验证',out)
        self.assertIn('【影响】',out)
        self.assertIn('付费档生成待支付订单',out)
        self.assertIn('纯 EIP 公网 IP 证书仅支持文件验证',out)

    def test_confirm_full(self):
        out=visual.render_ssl_purchase(ssl_purchase_confirm_fixture())
        self.assertIn('【证书购买结果】',out)
        self.assertIn('submitted',out)
        self.assertIn('scm-2001',out)
        self.assertIn('【订阅结果】',out)
        self.assertIn('PAID',out)
        self.assertIn('【申请轨迹】',out)
        self.assertIn('文件验证',out)
        self.assertIn('证书申请已提交，等待域名验证',out)

    def test_confirm_with_pending_order_and_extra_blocks(self):
        result=ssl_purchase_confirm_fixture()
        result['status']='order_created'
        result['order_id']='CS123456'
        result['application']={'apply_status':'not_started','domain_method':'DNS',
                               'auto_dns_auth':True}
        del result['apply']
        result['warnings']=['付费档订单支付后才能申请签发']
        out=visual.render_ssl_purchase(result)
        self.assertIn('order_created',out)
        self.assertIn('CS123456',out)
        self.assertIn('【申请轨迹】',out)
        self.assertIn('DNS 验证',out)
        self.assertIn('自动 DNS 验证',out)
        self.assertIn('【注意】',out)
        self.assertIn('付费档订单支付后才能申请签发',out)

    def test_missing_keys_do_not_raise(self):
        for payload in ({},None,{'status':'preview'},{'status':'submitted'},
                        {'status':'order_created','subscription':{}}):
            with self.subTest(payload=payload):
                self.assertTrue(isinstance(visual.render_ssl_purchase(payload),str))
        out=visual.render_ssl_purchase({'status':'preview'})
        self.assertIn('【证书购买预览】',out)
        self.assertIn('【购买参数】',out)
        self.assertIn('(无数据)',out)


def creation_preview_fixture():
    return {'status':'confirmation_required','scenario':'newly_instance',
            'request':{'name':'supabase-app-1115','version':'1.1.0','mode':'Single',
                       'flavor_ref':'rds.supabase.n1.medium.2',
                       'basic_config':{'vpc_id':'v1','subnet_id':'s1','availability_zone':'cn-east-3a'},
                       'managed_instance':{'datastore':{'type':'PostgreSQL','version':'17'},
                                           'flavor_ref':'rds.pg.n1.medium.2',
                                           'volume':{'type':'ESSD','size':40}}},
            'security_group_plan':{
                'application_group':{'name':'supabase-app-sg','ingress':{'port':8443,'cidr':'0.0.0.0/0'}},
                'database_group':{'name':'supabase-db-sg','ingress':{'port':5432,'cidr':'192.168.0.0/24'}},
                'egress':{'port':5432,'cidr':'192.168.0.0/24'},
                'note':'确认后随应用创建一并建组配规则'},
            'warnings':['确认后才会真正提交创建','包周期实例将返回订单，需支付后生效'],
            'plan_id':'plan-123'}


def creation_submitted_fixture():
    return {'status':'submitted','scenario':'newly_instance','job_id':'job-1','application_id':'app-1',
            'instance_id':'inst-1','instance_job_id':'job-2',
            'security_groups':{
                'application_group_id':'sg-app-1','database_group_id':'sg-db-1',
                'rules':[{'group':'应用组','direction':'ingress','port':8443,'cidr':'0.0.0.0/0'},
                         {'group':'应用组','direction':'egress','port':5432,'cidr':'192.168.0.0/24'},
                         {'group':'数据库组','direction':'ingress','port':5432,'cidr':'192.168.0.0/24'}]},
            'workflow':{'track':{'tool':'show_supabase_creation_progress',
                                 'args':{'application_id':'app-1','application_job_id':'job-1',
                                         'instance_id':'inst-1','instance_job_id':'job-2'}},
                        'reminder':'实例创建完成后应用创建才会开始，请轮询至 succeeded',
                        'after_completion':{
                            'eip_automation':[
                                {'tool':'create_supabase_eip',
                                 'args':{'charge_mode':'postPaid','bandwidth_size_mbps':300}},
                                {'tool':'bind_supabase_eip',
                                 'args':{'application_id':'app-1','public_ip_id':'<EIP ID>'}},
                                {'tool':'console/KooCLI','action':'为已绑定的 EIP 打标 supabase-managed'}],
                            'note':'绑定成功后 update_supabase_auth_config 同步 api_external_url'}},
            'plan_id':'plan-123'}


def creation_submitted_existed_fixture():
    result=creation_submitted_fixture()
    result['scenario']='existed_instance'
    result['instance_id']=None
    result['instance_job_id']=None
    result['security_groups']={
        'application_group_id':'sg-app-2','database_group_id':None,
        'database_group':'不动（保持实例现状）',
        'rules':[{'group':'应用组','direction':'ingress','port':8443,'cidr':'0.0.0.0/0'},
                 {'group':'应用组','direction':'egress','port':5432,'cidr':'192.168.0.0/24'}]}
    return result


def creation_order_fixture():
    result=creation_submitted_fixture()
    result['status']='order_created'
    result['order_id']='CS123456'
    return result


class RenderCreationFlowTests(unittest.TestCase):
    def test_preview_full(self):
        out=visual.render_creation_flow(creation_preview_fixture())
        self.assertIn('【创建任务预览（场景 newly_instance）】',out)
        self.assertIn('plan-123',out)
        self.assertIn('【请求体（脱敏）】',out)
        self.assertIn('supabase-app-1115',out)
        self.assertIn('rds.supabase.n1.medium.2',out)
        self.assertIn('"vpc_id": "v1"',out)
        self.assertIn('"type": "PostgreSQL"',out)
        self.assertIn('【将自动创建的安全组】',out)
        self.assertIn('8443',out)
        self.assertIn('5432',out)
        self.assertIn('0.0.0.0/0',out)
        self.assertIn('192.168.0.0/24',out)
        self.assertIn('【注意】',out)
        self.assertIn('确认后才会真正提交创建',out)
        self.assertIn('包周期实例将返回订单，需支付后生效',out)

    def test_submitted_full(self):
        out=visual.render_creation_flow(creation_submitted_fixture())
        self.assertIn('【创建任务已下发（场景 newly_instance）】',out)
        self.assertIn('submitted',out)
        self.assertIn('job-1',out)
        self.assertIn('app-1',out)
        self.assertIn('inst-1',out)
        self.assertIn('job-2',out)
        self.assertIn('【自动创建的安全组】',out)
        self.assertIn('sg-app-1',out)
        self.assertIn('sg-db-1',out)
        self.assertIn('8443',out)
        self.assertIn('0.0.0.0/0',out)
        self.assertIn('【工作流】',out)
        self.assertIn('跟踪：show_supabase_creation_progress',out)
        self.assertIn('"application_id": "app-1"',out)
        self.assertIn('实例创建完成后应用创建才会开始，请轮询至 succeeded',out)
        self.assertIn('【创建完成后：EIP 自动化】',out)
        self.assertIn('1. create_supabase_eip',out)
        self.assertIn('"charge_mode": "postPaid"',out)
        self.assertIn('2. bind_supabase_eip',out)
        self.assertIn('3. console/KooCLI',out)
        self.assertIn('为已绑定的 EIP 打标 supabase-managed',out)
        self.assertIn('绑定成功后 update_supabase_auth_config 同步 api_external_url',out)

    def test_submitted_existed_database_untouched(self):
        out=visual.render_creation_flow(creation_submitted_existed_fixture())
        self.assertIn('【创建任务已下发（场景 existed_instance）】',out)
        self.assertIn('数据库组：不动（保持实例现状）',out)
        self.assertIn('sg-app-2',out)

    def test_order_created(self):
        out=visual.render_creation_flow(creation_order_fixture())
        self.assertIn('order_created',out)
        self.assertIn('CS123456（控制台/订单工具支付后生效）',out)

    def test_missing_keys_do_not_raise(self):
        for payload in ({},None,{'status':'confirmation_required'},
                        {'status':'submitted','security_groups':{'database_group_id':None},
                         'workflow':{'track':{},'after_completion':{}}}):
            with self.subTest(payload=payload):
                self.assertTrue(isinstance(visual.render_creation_flow(payload),str))
        out=visual.render_creation_flow({})
        self.assertIn('【创建任务已下发（场景 -）】',out)
        self.assertIn('status',out)


if __name__=='__main__':
    unittest.main()
