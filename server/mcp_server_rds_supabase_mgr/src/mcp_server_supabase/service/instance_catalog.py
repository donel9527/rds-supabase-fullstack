"""RDS PostgreSQL catalog reads (engine versions, flavors, storage types) via KooCLI for the create-with-new-instance scenario, plus a one-call dependency discovery that pre-fills the managed_instance request body."""
import asyncio
import ipaddress
import re
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.service.operations import safe

NOTE=('Catalog for the create-with-new-instance scenario: pick the PostgreSQL engine version, flavor and storage type '
      'before creating the managed instance. Only AZs whose az_status is normal are purchasable; each flavor and '
      'storage row carries its own AZ sale status.')

GROUP_TYPE_LABELS={'normal':'通用增强型','normal2':'通用增强II型','armFlavors':'鲲鹏通用增强型','dedicatenormal':'x86独享型','armlocalssd':'鲲鹏通用型','normallocalssd':'x86通用型','general':'通用型','dedicated':'独享型（仅云盘SSD支持）','rapid':'独享型（仅极速型SSD支持）','bigmem':'超大内存型','bigmen':'超大内存型'}
GROUP_TYPE_ORDER=['general','dedicated','rapid','dedicatenormal','bigmem','normal','normal2','armFlavors','armlocalssd','normallocalssd']
STORAGE_TYPE_LABELS={'ULTRAHIGH':('SSD',''),'LOCALSSD':('本地SSD',''),'CLOUDSSD':('SSD云盘','仅支持通用型和独享型规格实例'),'ESSD':('极速型SSD','仅支持独享型规格实例'),'GPSSD2':('通用型SSD V2','')}

STORAGE_SKIPPED='skipped - engine version unavailable'

EPS_REGION='cn-north-4'   # EPS is a global service with a narrow KooCLI region list
EPS_NOTE_OK='企业项目账号：从可用的企业项目列表选择归属，默认选中 default 项目；仅新建实例场景需要填写'
EPS_NOTE_UNAVAILABLE='企业项目列表查询不可用（个人账号、未启用企业项目或全局服务权限缺失）：本字段可省略，省略时归属由服务端决定'
EPS_NOTE_EMPTY='未查到可用的企业项目：本字段可省略，省略时归属由服务端决定'


async def _eps_field(eps_koocli):
    """Conditional enterprise-project selector for the newly-instance scenario only.
    EPS-enabled accounts get the live project list (default = the project named
    "default", whatever its real ID); any query failure degrades to an omittable
    field - the request then omits it and the backend assigns placement."""
    data=await eps_koocli.call('EPS','ListEnterpriseProject')
    rows=None
    if isinstance(data,dict):
        for key in ('enterprise_projects','items','data'):
            if isinstance(data.get(key),list):rows=data[key];break
    projects=[]
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        pid,name=row.get('id'),row.get('name')
        if not pid or not name:continue
        status=row.get('status')
        if status not in (None,1,'1',True):continue   # 1=启用；停用项目不可写入新资源
        projects.append({'id':str(pid),'name':str(name),'description':row.get('description') or ''})
    if not projects:
        return {'recommended':None,'note':EPS_NOTE_EMPTY}
    default_id=next((project['id'] for project in projects if project['name'].lower()=='default'),None)
    return {'values':[project['id'] for project in projects],
            'projects':projects,
            'recommended':default_id,
            'note':EPS_NOTE_OK}


def _error_text(error):
    message=getattr(error,'message',None) or str(error) or error.__class__.__name__
    return ' '.join(str(message).split())[:60]


def _failure(error):
    return '（查询失败：'+error+'）'


def _int_or_zero(value):
    try:return int(value)
    except (TypeError,ValueError):return 0


def _normal_azs(row):
    az_status=row.get('az_status')
    if isinstance(az_status,dict):
        return sorted(str(az) for az,status in az_status.items() if status=='normal')
    zones=row.get('availability_zones')
    if isinstance(zones,list):
        codes=[az.get('code') for az in zones
               if isinstance(az,dict) and az.get('code') and az.get('status')=='normal']
        if codes:return sorted(str(code) for code in codes)
    main=row.get('availability_zone')
    if isinstance(main,str) and main:return [main]
    return []


def _flavor_groups(rows):
    buckets={}
    for row in rows:
        if not isinstance(row,dict):continue
        group_type=row.get('group_type')
        if not isinstance(group_type,str) or not group_type:group_type='未知'
        buckets.setdefault(group_type,[]).append(row)
    def order(group_type):
        return GROUP_TYPE_ORDER.index(group_type) if group_type in GROUP_TYPE_ORDER else len(GROUP_TYPE_ORDER)
    groups=[]
    for group_type in sorted(buckets,key=order):
        specs=[{'spec_code':row.get('spec_code'),'vcpus':row.get('vcpus'),'ram':row.get('ram'),
                'instance_mode':row.get('instance_mode'),'availability_zones':_normal_azs(row)}
               for row in buckets[group_type]]
        specs.sort(key=lambda spec:(_int_or_zero(spec['vcpus']),_int_or_zero(spec['ram']),str(spec['spec_code'])))
        groups.append({'group_type':group_type,'label':GROUP_TYPE_LABELS.get(group_type,group_type),'specs':specs})
    return groups


async def _manageable_rows(ops):
    """Attachable PG instances for application_type=supabase (the same source as
    list_supabase_manageable_instances); the row shape follows the origin response."""
    result=await ops.creation_candidates('manageable')
    data=result.get('data') if isinstance(result,dict) else result
    rows=None
    if isinstance(data,dict):
        for key in ('instances','items','data'):
            if isinstance(data.get(key),list):rows=data[key];break
        if rows is None:rows=[]   # an object without a list key is a valid empty inventory (live: {"total_count": 0})
    elif isinstance(data,list):rows=data
    elif data is None:rows=[]
    else:
        raise McpToolError('MCP_SDK_ERROR','manageable-instance list unreadable')
    return [row for row in rows if isinstance(row,dict) and row.get('id')]


async def _find_manageable(ops,instance_id):
    rows=await _manageable_rows(ops)
    match=next((row for row in rows if row.get('id')==instance_id),None)
    if match is None:
        raise McpToolError('MCP_NOT_FOUND','instance_id is not an attachable PG instance',
                           hint='List the candidates first: discover_db_instance_for_create(existed_instance) '
                                'or list_supabase_manageable_instances.')
    return match


class InstanceCatalog:
    """Read-only RDS engine-level catalogs; the Supabase origin does not serve them, so they run through KooCLI."""

    def __init__(self,koocli=None,eps_koocli=None,operations=None):
        self.koocli=koocli or KoocliClient()
        self.eps_koocli=eps_koocli or KoocliClient(region=EPS_REGION)
        self.operations=operations

    async def list_engine_versions(self):
        data=await self.koocli.call('RDS','ListDatastores',{'database_name':'PostgreSQL'})
        return {'data':safe(self._rows(data,'dataStores')),'note':NOTE}

    async def list_flavors(self,version_name=None):
        params={'database_name':'PostgreSQL'}
        if version_name is not None:
            self._require_major(version_name)
            params['version_name']=version_name
        data=await self.koocli.call('RDS','ListFlavors',params)
        return {'data':safe(self._rows(data,'flavors')),'note':NOTE}

    async def list_storage_types(self,version_name,ha_mode):
        self._require_major(version_name)
        mode=str(ha_mode).lower()
        if mode not in ('single','ha'):
            raise McpToolError('MCP_INVALID_ARGS','ha_mode must be single or ha')
        data=await self.koocli.call('RDS','ListStorageTypes',
                                    {'database_name':'PostgreSQL','version_name':version_name,'ha_mode':mode})
        return {'data':safe(self._rows(data,'storage_type')),'note':NOTE}

    def _ops(self):
        if self.operations is None:
            from mcp_server_supabase.service.operations import Operations
            self.operations=Operations()
        return self.operations

    async def discover_db_instance_for_create(self,scenario,mode=None,instance_id=None):
        """Per-source discovery for the managed-instance step of the scenario creation tools.
        newly_instance: engine versions, instance flavors with per-AZ sale status and
        mode-filtered storage types, assembled into a recommended value for every
        managed_instance request-body field; each source fails independently.
        existed_instance: the attachable PG candidates, or - with instance_id - that
        instance's basic/configuration/network information for the attach decision.
        Security-group planning belongs to discover_network_for_create."""
        if scenario not in ('newly_instance','existed_instance'):
            raise McpToolError('MCP_INVALID_ARGS','scenario must be newly_instance or existed_instance (与创建场景工具的 manage_type 一致)')
        if scenario=='existed_instance':
            return await self._existed_instance_options(instance_id)
        if mode not in ('Single','Ha'):
            raise McpToolError('MCP_INVALID_ARGS','mode must be Single or Ha')
        storage_mode='ha' if mode=='Ha' else 'single'
        # Engine versions run first: the storage probe depends on the highest major version.
        version_names=[]
        version_error=''
        try:
            versions=await self.list_engine_versions()
            version_names=[row.get('name') for row in versions['data']
                           if isinstance(row,dict) and row.get('name')]
        except Exception as error:
            version_error=_error_text(error)
        candidates=[]
        for name in version_names:
            try:candidates.append((int(name),str(name)))
            except (ValueError,TypeError):continue
        ordered=[];seen=set()
        for number,name in sorted(candidates):
            if number not in seen:
                seen.add(number);ordered.append(name)
        highest=ordered[-1] if ordered else None
        # The remaining sources run concurrently; a single failure degrades only its own section.
        # Network placement and the security-group plan belong to discover_network_for_create
        # (same scenario values as manage_type); this tool no longer touches either.
        flavors_result,storage_result,eps_result=await asyncio.gather(
            self.list_flavors(),
            self.list_storage_types(highest,storage_mode) if highest is not None else _skipped_probe(),
            _eps_field(self.eps_koocli),
            return_exceptions=True)
        flavor_rows,flavor_error=self._rows_of(flavors_result,'data')
        if storage_result is None:
            storage_rows,storage_error=[],STORAGE_SKIPPED
        else:
            storage_rows,storage_error=self._rows_of(storage_result,'data')
        if isinstance(eps_result,BaseException):
            eps_field,eps_error={'recommended':None,'note':EPS_NOTE_UNAVAILABLE},_error_text(eps_result)
        else:
            eps_field,eps_error=eps_result,None
        saleable=[]
        saleable_rows=[]
        normal_azs=set()
        for row in flavor_rows:
            az_status=row.get('az_status') if isinstance(row,dict) else None
            if not isinstance(az_status,dict):continue
            normal=[az for az,status in az_status.items() if status=='normal']
            normal_azs.update(normal)
            if normal and row.get('spec_code'):
                saleable.append(row['spec_code'])
                saleable_rows.append(row)
        volume_names=[]
        volume_options=[]
        for row in storage_rows:
            if not isinstance(row,dict) or not row.get('name'):continue
            name=row['name']
            label,note=STORAGE_TYPE_LABELS.get(name,(name,''))
            volume_names.append(name)
            volume_options.append({'value':name,'label':label,'note':note,
                                   'compatible_group_types':row.get('support_compute_group_type') or []})
        volume_recommended=next((name for name in volume_names if 'ESSD' in name),
                                volume_names[0] if volume_names else None)
        def option_note(base,error):
            return base+_failure(error) if error else base
        options={
            'datastore.type':{'fixed':'PostgreSQL'},
            'datastore.version':{'values':ordered,'recommended':highest,
                                 'note':option_note('PostgreSQL 引擎大版本',version_error)},
            'flavor_ref':{'values':saleable,'recommended':saleable[0] if saleable else None,
                          'groups':_flavor_groups(saleable_rows),
                          'note':option_note('实例规格按 group_type 分大类展示（全部可售规格，不截断）；编排时与 Supabase 应用规格分开单独询问用户；推荐默认与应用规格同档；与应用规格（rds.supabase.*）是两回事',flavor_error)},
            'volume.type':{'values':volume_names,'recommended':volume_recommended,'options':volume_options,
                           'note':option_note('磁盘类型明确展示中文名与官方说明供用户选择；compatible_group_types 为本局点实时兼容的规格类型（support_compute_group_type），最终以服务端校验为准',storage_error)},
            'volume.size':{'minimum':40,'maximum':40000,'recommended':40,'note':'GB'},
            'charge_info':{'values':[{'charge_mode':'postPaid'}],
                           'recommended':{'charge_mode':'postPaid'},
                           'note':'仅按需计费（postPaid，固定，不支持包周期）：计费项=实例规格+存储空间（必选），备份空间免费额度=存储容量 100%、超出部分按需计费，公网带宽/跨区域备份为可选计费项；按秒计费、整点小时结算，自实例创建成功时间点起计费至删除；计费规则 https://support.huaweicloud.com/price-rds-pg/rds_00_0005.html'},
            'ha.mode':{'fixed':mode},
            'ha.replication_mode':{'values':['async','sync'],'recommended':'async'},
            'availability_zone':{'values':sorted(normal_azs),'note':'Ha 模式需两个不同 AZ（主+备）'},
            'basic_config.time_zone':{'values':['UTC%+03d:00'%offset for offset in range(-12,13)],
                                      'recommended':'UTC+08:00',
                                      'note':'时区，可省略；随 basic_config.time_zone 提交。PostgreSQL 引擎仅支持整段 '
                                             'UTC-12:00~UTC+12:00（不支持半点，如 UTC+08:30）；时区名称与 UTC 偏移量对照见 '
                                             'RDS for SQL Server 时区对照表（China Standard Time = UTC+08:00，北京/重庆/香港/乌鲁木齐）；'
                                             '默认推荐中国北京（UTC+08:00）'},
            'port':{'recommended':5432,'note':'默认端口，可省略'},
            'enterprise_project_id':eps_field,
            'password':{'note':'8-32 位三类字符，用户经本地请求文件提供，工具不生成'},
            'security_group_id':{'values':[],'recommended':None,
                                 'note':'新建专用数据库组，不推荐既有组、不复用共享组；'
                                        '建组与出入方向规则由 discover_network_for_create（scenario 同 manage_type）给出'},
            'configuration_id':{'note':'参数模板 ID，可选，默认不传；取值范围为 ListConfigurations 返回的参数模板 id'},
        }
        status=lambda error:'error: '+error if error else 'ok'
        return {'scenario':'newly_instance',
                'mode':mode,
                'managed_instance_field_options':options,
                'top_level_reminder':['availability_zone 必须与顶层一致（服务端强制校验）',
                                      '数据库密码与应用密码同规则，可同值',
                                      '本工具只服务新建实例场景；托管已有实例用 list_supabase_manageable_instances',
                                      '网络与安全组：调 discover_network_for_create（scenario 与 manage_type 一致）选定网络，并按其 security_group_plan 建组配规则'],
                'discovery_status':{'engine_versions':status(version_error),
                                    'flavors':status(flavor_error),
                                    'storage_types':status(storage_error),
                                    'enterprise_projects':status(eps_error)}}

    async def _existed_instance_options(self,instance_id):
        rows=await _manageable_rows(self._ops())
        if instance_id is None:
            return {'scenario':'existed_instance',
                    'acquisition':'候选与 list_supabase_manageable_instances 同源（可挂载到 Supabase 应用的 PG 实例）；'
                                  '从中选定一个后以 instance_id 再次调用本工具，获取其基础/配置/网络信息；'
                                  '创建请求使用 create_supabase_link_exist_instance(manage_type=existed_instance, '
                                  'existing_instance={"instance_id":..., "database_name":"root", "database_pwd":...})',
                    'candidates':rows,
                    'note':'候选存在不等于可创建成功（规格/状态仍由服务端校验）'}
        match=await _find_manageable(self._ops(),instance_id)
        return {'scenario':'existed_instance',
                'instance_id':instance_id,
                'basic':{'id':match.get('id'),'name':match.get('name'),'status':match.get('status'),
                         'spec_code':match.get('spec_code'),'vcpus':match.get('vcpus'),'ram':match.get('ram')},
                'configuration':{'datastore':match.get('datastore'),'ha':match.get('ha'),
                                  'port':match.get('port'),'volume':match.get('volume'),
                                  'enterprise_project_id':match.get('enterprise_project_id')},
                'network':{'vpc_id':match.get('vpc_id'),'subnet_id':match.get('subnet_id'),
                           'security_group_id':match.get('security_group_id'),
                           'note':'子网 CIDR 与应用侧安全组规则见 discover_network_for_create(existed_instance, instance_id)'}}

    def _rows_of(self,result,key):
        """Tolerant extraction for gathered probes: exceptions report, missing response keys stay empty."""
        if isinstance(result,BaseException):
            return [],_error_text(result)
        rows=result.get(key) if isinstance(result,dict) else None
        return (rows if isinstance(rows,list) else []),''

    def _require_major(self,version_name):
        if not isinstance(version_name,str) or not re.fullmatch(r'\d{1,2}',version_name):
            raise McpToolError('MCP_INVALID_ARGS','version_name must be a major version like 17',
                               hint='Complete version numbers are not accepted here: take the major version first '
                                     '(list_db_instance_engine_versions), then filter ListFlavors with it.')
        return version_name

    def _rows(self,data,key):
        rows=data.get(key) if isinstance(data,dict) else None
        if not isinstance(rows,list):
            raise McpToolError('MCP_SDK_ERROR','Catalog response is missing the '+key+' list',
                               hint='Verify the RDS response contract with `hcloud RDS <Operation> --help` before continuing.')
        return rows


class NetworkDiscovery:
    """Network placement and the security-group plan for the scenario creation tools,
    by instance source (scenario, same values as manage_type).

    newly_instance: walks the VPC/subnet inventory through KooCLI (>=2 free IPs preferred,
    >=1 fallback) and, with the chosen subnet CIDR, states both groups' creation
    configuration - application group (8443 ingress with three source options, 5432
    egress to the subnet) and database group (5432 ingress from the subnet, default
    allow-all egress). existed_instance: takes VPC/subnet from the given attachable
    instance, leaves the instance's security group untouched and applies the same
    application-group rules. All internal rule CIDRs are the chosen subnet's CIDR."""

    def __init__(self,koocli=None,operations=None):
        self.koocli=koocli or KoocliClient()
        self.operations=operations

    def _ops(self):
        if self.operations is None:
            from mcp_server_supabase.service.operations import Operations
            self.operations=Operations()
        return self.operations

    async def discover_network_for_create(self,scenario,availability_zone=None,instance_id=None,detect_access_ip=False):
        if scenario not in ('newly_instance','existed_instance'):
            raise McpToolError('MCP_INVALID_ARGS','scenario must be newly_instance or existed_instance (与创建场景工具的 manage_type 一致)')
        if scenario=='existed_instance':
            return await self._existed_network(instance_id,detect_access_ip)
        placement=await self._discover_placement(availability_zone)
        plan=self._security_group_plan('newly_instance',placement['subnet_cidr'],detect_access_ip)
        if placement.get('preference')=='default_recommendation':
            plan['precondition']='先执行 default_create 建好默认 VPC/子网，再建组配规则'
        return {**placement,'scenario':'newly_instance','security_group_plan':plan}

    async def _existed_network(self,instance_id,detect_access_ip):
        if not isinstance(instance_id,str) or not instance_id:
            raise McpToolError('MCP_INVALID_ARGS','existed_instance 需要 instance_id（候选见 discover_db_instance_for_create(existed_instance)）')
        match=await _find_manageable(self._ops(),instance_id)
        vpc_id=match.get('vpc_id');subnet_id=match.get('subnet_id')
        subnet_cidr=None
        if vpc_id:
            data=await self.koocli.call('VPC','ListSubnets',{'limit':100,'vpc_id':vpc_id})
            subnets=data.get('subnets') if isinstance(data,dict) else None
            for subnet in subnets if isinstance(subnets,list) else []:
                if isinstance(subnet,dict) and subnet.get('id')==subnet_id:
                    subnet_cidr=subnet.get('cidr');break
        if not subnet_cidr:
            raise McpToolError('MCP_NOT_FOUND','无法从实例的 VPC 中取到子网 CIDR',
                               hint='确认实例的 vpc_id/subnet_id 有效后重试')
        plan=self._security_group_plan('existed_instance',subnet_cidr,detect_access_ip)
        plan['database_group']['current_security_group_id']=match.get('security_group_id')
        return {'scenario':'existed_instance','instance_id':instance_id,
                'vpc_id':vpc_id,'subnet_id':subnet_id,'subnet_cidr':subnet_cidr,
                'basic_config_usage':{'vpc_id':vpc_id,'subnet_id':subnet_id},
                'security_group_plan':plan}

    def _security_group_plan(self,scenario,subnet_cidr,detect_access_ip):
        """Specification for the two dedicated groups - nothing is created here. The
        application group gates the product: 8443 ingress without which the app cannot
        be logged into and 5432 egress without which it cannot reach the database; the
        database group (new instances only) needs the database-port ingress from the
        chosen subnet CIDR. The real creation follows apply_steps strictly."""
        detected=self._detect_access_cidr() if detect_access_ip else None
        detect_note='传 detect_access_ip=true 自动探测当前设备出口 IP'
        if detect_access_ip:
            detect_note='已探测' if detected else '探测失败（可自查出口 IP 后改用自定义）'
        source_options=[
            {'key':'open','source_cidr':'0.0.0.0/0',
             'note':'默认全开；/0 规则经 KooCLI CreateSecurityGroupRule 配置（MCP 规则工具拒收 /0）'},
            {'key':'detected','source_cidr':detected,
             'note':'当前设备访问网段（出口 IP /32，动态出口可放宽为 /24 或改自定义）。'+detect_note},
            {'key':'custom','source_cidr':None,'note':'用户自定义网段，须为有界 CIDR'},
        ]
        application_group={'name':'supabase-app-sg','description':'Supabase应用（自动创建）',
                           'ingress':{'protocol':'tcp','port':8443,
                                      'purpose':'应用服务入口——不放通无法登录 Supabase 应用',
                                      'source_cidr_options':source_options},
                           'egress':{'protocol':'tcp','port':5432,'destination_cidr':subnet_cidr,
                                     'purpose':'连接托管数据库——不放通则应用异常不可用'}}
        if scenario=='newly_instance':
            database_group={'name':'supabase-db-sg','description':'数据库接入（自动创建）',
                            'ingress':{'protocol':'tcp','port':5432,'source_cidr':subnet_cidr,
                                       'purpose':'应用连接数据库——不放通则 Supabase 异常，功能不可用'},
                            'egress':{'destination_cidr':'0.0.0.0/0','note':'默认放行，无需额外规则'}}
        else:
            database_group={'action':'不动',
                            'current_security_group_id':None,
                            'note':'已有实例的安全组保持现状，不做任何变更'}
        apply_steps=[
            {'tool':'create_supabase_security_group',
             'args':{'name':application_group['name'],'description':application_group['description']},
             'returns':'security_group_id'},
            {'tool':'add_supabase_security_group_rule',
             'args':{'group_id':'<新应用组的 security_group_id>','direction':'ingress','protocol':'tcp','port':8443,
                     'source_cidr':'<三选一：默认 0.0.0.0/0（经 KooCLI）/ 当前设备网段 / 自定义>'}},
            {'tool':'add_supabase_security_group_rule',
             'args':{'group_id':'<新应用组的 security_group_id>','direction':'egress','protocol':'tcp','port':5432,
                     'source_cidr':subnet_cidr}},
        ]
        if scenario=='newly_instance':
            apply_steps+= [
                {'tool':'create_supabase_security_group',
                 'args':{'name':database_group['name'],'description':database_group['description']},
                 'returns':'security_group_id'},
                {'tool':'add_supabase_security_group_rule',
                 'args':{'group_id':'<新数据库组的 security_group_id>','direction':'ingress','protocol':'tcp','port':5432,
                         'source_cidr':subnet_cidr}},
            ]
        return {'plan_type':'specification',
                'declaration':'本工具不创建任何资源；以下为安全组配置规格、选项与推荐，真实创建时严格遵循'
                              '（create_supabase_security_group / add_supabase_security_group_rule，全 0 网段经 KooCLI）',
                'application_group':application_group,'database_group':database_group,
                'apply_steps':apply_steps,
                'note':'规则中的网段均为所选 VPC 子网 CIDR（%s）；应用组入方向来源三选一：默认全 0 / 当前设备网段 / 自定义'%subnet_cidr}

    def _detect_access_cidr(self):
        """Best-effort probe of the current device public egress IP (the MCP server runs
        on the user machine): a /32 CIDR or None. Short timeouts, never fatal. The SSL
        context uses certifi when present - python.org builds on macOS often miss the
        system CA store, which would otherwise fail every https probe."""
        import urllib.request
        import ipaddress
        import ssl
        context=None
        try:
            import certifi
            context=ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        for url in ('https://ifconfig.me/ip','https://checkip.amazonaws.com','https://api.ipify.org'):
            try:
                request=urllib.request.Request(url,headers={'User-Agent':'curl/8.4.0'})
                with urllib.request.urlopen(request,timeout=3,context=context) as response:
                    address=ipaddress.ip_address(response.read().decode().strip())
                return str(address)+'/32'
            except Exception:
                continue
        return None

    async def _discover_placement(self,availability_zone):
        minimum_ips=2;fallback_minimum=1
        vpcs_data=await self.koocli.call('VPC','ListVpcs/v3',{'limit':100})
        vpcs=vpcs_data.get('vpcs') if isinstance(vpcs_data,dict) else None
        if not isinstance(vpcs,list):
            raise McpToolError('MCP_SDK_ERROR','VPC inventory unreadable')
        inspected=[]
        for vpc in vpcs:
            if not isinstance(vpc,dict) or not vpc.get('id'):continue
            vpc_id=vpc['id']
            try:
                sub_data=await self.koocli.call('VPC','ListSubnets',{'limit':100,'vpc_id':vpc_id})
            except McpToolError as error:
                inspected.append({'vpc_id':vpc_id,'vpc_name':vpc.get('name'),'error':error.message})
                continue
            subnets=sub_data.get('subnets') if isinstance(sub_data,dict) else None
            candidates=[]
            fallback=None
            for subnet in subnets if isinstance(subnets,list) else []:
                if not isinstance(subnet,dict) or not subnet.get('id'):continue
                if subnet.get('status') not in (None,'ACTIVE'):continue
                free=subnet.get('available_ip_address_count')
                free=free if type(free) is int else None
                entry={'vpc_id':vpc_id,'vpc_name':vpc.get('name'),'vpc_cidr':vpc.get('cidr'),
                       'subnet_id':subnet['id'],'subnet_name':subnet.get('name'),
                       'subnet_cidr':subnet.get('cidr'),'availability_zone':subnet.get('availability_zone'),
                       'available_ip_count':free}
                if free is not None and free>=minimum_ips:
                    candidates.append(entry)
                elif free is not None and free>=fallback_minimum and fallback is None:
                    fallback=entry
                elif free is None:
                    # Availability unknown: treat as fallback candidate only when nothing better is known.
                    if fallback is None:fallback={**entry,'available_ip_count':None}
            if candidates:
                return self._result(candidates[0],minimum_ips,fallback_minimum,inspected,preference='sufficient')
            if fallback is not None:
                return self._result(fallback,minimum_ips,fallback_minimum,inspected,preference='fallback')
            inspected.append({'vpc_id':vpc_id,'vpc_name':vpc.get('name'),'error':'no eligible subnet'})
        # Nothing exists to reuse: recommend the standard defaults instead of failing.
        # Huawei Cloud's default private range 192.168.0.0/16 is valid across all regions;
        # the default subnet 192.168.0.0/24 should be placed in the target availability zone
        # (the AZ the managed RDS instance will live in).
        return self._default_recommendation(availability_zone,minimum_ips,fallback_minimum,inspected)

    def _default_recommendation(self,availability_zone,minimum_ips,fallback_minimum,inspected):
        create={'vpc':{'name':'default_vpc','cidr':'192.168.0.0/16'},
                'subnet':{'name':'default_subnet','cidr':'192.168.0.0/24',
                          'availability_zone':availability_zone,
                          'gateway_ip':'192.168.0.1'}}
        return {'preference':'default_recommendation',
                'vpc_id':None,'vpc_name':'default_vpc','vpc_cidr':'192.168.0.0/16',
                'subnet_id':None,'subnet_name':'default_subnet','subnet_cidr':'192.168.0.0/24',
                'availability_zone':availability_zone,
                'available_ip_count':None,
                'ip_requirement':{'preferred':minimum_ips,'fallback':fallback_minimum},
                'default_create':create,
                'basic_config_usage':None,
                'note':'No existing VPC/subnet is usable in this region. The recommended default is VPC default_vpc '
                       '(192.168.0.0/16, the standard private range valid in all Huawei Cloud regions) with subnet '
                       'default_subnet (192.168.0.0/24) placed in the target availability zone. Create them first '
                       '(console or KooCLI: CreateVpc then CreateSubnet with the gateway 192.168.0.1), then re-run '
                       'discovery - basic_config requires the created vpc_id and subnet_id.',
                'inspected_vpcs':inspected}

    def _result(self,entry,minimum_ips,fallback_minimum,inspected,preference):
        return {**entry,
                'preference':preference,
                'ip_requirement':{'preferred':minimum_ips,'fallback':fallback_minimum},
                'basic_config_usage':{'vpc_id':entry['vpc_id'],'subnet_id':entry['subnet_id']},
                'note':'Fill these values into the Supabase creation request basic_config (vpc_id, subnet_id). '
                       'available_ip_count comes from the VPC service; a fallback pick means fewer free IPs than preferred - verify capacity before creating.',
                'inspected_vpcs':inspected}


class BasicOptionsDiscovery:
    """One-call discovery of the Supabase application's own creation basics.

    Covers the top-level application fields only - name/version/mode/flavor/
    availability_zone plus the deployment-mode probe. Network placement and the
    security-group plan are owned by NetworkDiscovery.discover_network_for_create;
    the managed PG instance fields by InstanceCatalog.discover_db_instance_for_create.
    """

    def __init__(self,operations=None):
        self.operations=operations

    def _ops(self):
        if self.operations is None:
            from mcp_server_supabase.service.operations import Operations
            self.operations=Operations()
        return self.operations

    def _security_group_strategy(self):
        """Guidance-only strategy: instance and network are not chosen yet, so rule CIDRs
        cannot be pinned down - the concrete plan comes from discover_network_for_create
        once the scenario is known."""
        return {'determined':False,
                'declaration':'本工具不创建任何资源；以下为推荐方法策略，具体规格由 discover_network_for_create 输出',
                'reason':'实例与网络尚未选定，以下为推荐方法策略；具体建组与出入方向规则由 discover_network_for_create（scenario 与 manage_type 一致）给出',
                'application_group':{
                    'ingress':{'protocol':'tcp','port':8443,'note':'应用服务入口，不放通无法登录；来源三选一：默认全 0 / 当前设备网段 / 自定义'},
                    'egress':{'protocol':'tcp','port':5432,'note':'放通托管数据库端口，不放通则应用异常不可用'}},
                'database_group':{
                    'strategy':'新建实例场景：新建专用组并放通数据库端口入方向（来源=所选子网 CIDR）；已有实例场景：保持现状不动'}}

    def _suggest_name(self,existing):
        """A rules-compliant, collision-free reference name.

        Rules: 4-64 chars (<=64 UTF-8 bytes with Chinese at 3 bytes each), starts
        with a letter or Chinese character, case-sensitive, letters/digits/hyphen/
        underscore/Chinese only. The suggestion is deterministic per day so the
        agent can quote it across turns without re-querying.
        """
        import datetime
        stamp=datetime.date.today().strftime('%m%d')
        base='supabase-app-'+stamp
        candidate=base
        index=1
        while candidate in existing:
            index+=1
            candidate='%s-%d'%(base,index)
        return candidate

    async def discover(self,az_code):
        az_code=az_code if isinstance(az_code,str) and re.fullmatch(r'[a-z]{2,}-[a-z]+-\d+[a-z]',az_code or '') else None
        if not az_code:
            raise McpToolError('MCP_INVALID_ARGS','az_code must be an availability-zone code like cn-east-3a (query it via list_supabase_flavors_with_azs)')
        probes={}
        flavors_single=flavors_ha=None
        try:
            result=await self._ops().creation_candidates('flavors',az_code=az_code,mode='Single')
            flavors_single=result.get('data') if isinstance(result,dict) else None
            flavors_single=flavors_single.get('flavors') if isinstance(flavors_single,dict) else flavors_single
            if not isinstance(flavors_single,list):flavors_single=[]
            probes['application_flavors_single']='ok'
        except McpToolError as error:
            probes['application_flavors_single']='error: '+_error_text(error)
        try:
            result=await self._ops().creation_candidates('flavors',az_code=az_code,mode='Ha')
            flavors_ha=result.get('data') if isinstance(result,dict) else None
            flavors_ha=flavors_ha.get('flavors') if isinstance(flavors_ha,dict) else flavors_ha
            if not isinstance(flavors_ha,list):flavors_ha=[]
            probes['application_flavors_ha']='ok'
        except McpToolError as error:
            probes['application_flavors_ha']='error: '+_error_text(error)
            flavors_ha=None  # a 400 rejection is the documented signal that Ha is unsupported here
        ha_supported=isinstance(flavors_ha,list) and bool(flavors_ha)
        rows=flavors_single if isinstance(flavors_single,list) else []
        existing_names=set()
        try:
            listing=await self._ops().read('applications',limit=100)
            for row in (listing.get('data') or []):
                if isinstance(row,dict) and row.get('name'):existing_names.add(str(row['name']))
            probes['existing_application_names']='ok'
        except McpToolError as error:
            probes['existing_application_names']='error: '+_error_text(error)
        versions=sorted({str(row.get('version')) for row in rows if isinstance(row,dict) and row.get('version')})
        # Application flavors carry per-AZ sale status; keep only specs saleable in the requested AZ.
        def saleable(row):
            return any(isinstance(az,dict) and az.get('code')==az_code and az.get('status')=='normal'
                       for az in row.get('availability_zones') or [])
        specs=[row for row in rows if isinstance(row,dict) and row.get('spec_code')]
        saleable_specs=[row for row in specs if saleable(row)]
        preferred=saleable_specs or specs
        suggested_name=self._suggest_name(existing_names)
        options={
            'name':{'requirements':['长度 4-64 个字符；含中文时不超过 64 字节（一个中文字符占 3 字节）',
                                    '必须以字母或中文开头',
                                    '区分大小写',
                                    '可包含字母、数字、中划线、下划线或中文，不能包含其他特殊字符'],
                    'suggested':suggested_name,
                    'note':'按规则给出参考名（已对照现有应用列表确保不重复）；用户可改名，最终名称由用户确认'},
            'version':{'values':versions,'recommended':versions[-1] if versions else None,
                       'note':'Supabase 应用版本（x.y.z，非 PG 引擎版本）；取可用最高版'},
            'mode':{'values':['Single','Ha'] if ha_supported else ['Single'],
                    'recommended':'Single',
                    'note':'Single 单机 / Ha 主备；Ha 是否可用按局点实时探测（本次探测：%s）'%('支持' if ha_supported else '不支持')},
            'flavor_ref':{'values':[row['spec_code'] for row in preferred],
                          'recommended':preferred[0]['spec_code'] if preferred else None,
                          'groups':_flavor_groups(preferred),
                          'note':'应用规格（rds.supabase.*）——编排时与托管实例规格分开单独询问：展示全部可售规格（含规格类型/vCPU/内存）供用户选择或自定义输入；推荐通用型 2U4G；与托管实例规格（rds.pg.*）是两回事'},
            'availability_zone':{'values':[az_code],
                                 'note':'本次查询的 AZ；Ha 模式需两个不同 AZ（主+备），用 list_supabase_flavors_with_azs 查全部可售 AZ'},
            'password':{'login_user':'supabase',
                        'requirements':['密码为 8~32 个字符',
                                        '至少包含以下字符中的三种：大写字母、小写字母、数字和特殊字符 ~ ! @ # $ % ^ * - _ = + ? ,'],
                        'note':'dashboard 登录用户固定为 supabase；密码由用户经本地请求文件提供，工具不生成、不回显'},
            'storage_component':{'values':[{'enabled':False},{'enabled':True}],
                                 'recommended':{'enabled':False},
                                 'note':'OBS 存储对接：有图片/视频/大文件需求才启用；启用需桶名与 AK/SK（经本地请求文件）'},
        }
        return {'az_code':az_code,
                'basic_options':options,
                'ha_supported':ha_supported,
                'security_group_strategy':self._security_group_strategy(),
                'excluded_scopes':['network (basic_config vpc/subnet) -> discover_network_for_create',
                                   'managed instance fields -> discover_db_instance_for_create'],
                'probe_status':probes,
                'note':'Top-level application basics for create_supabase_create_basic_options. '
                       'Flavor sale status is per-AZ from the Supabase flavor API; the Ha probe uses the same API - '
                       'a rejection means this environment supports Single only.'}
