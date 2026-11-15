"""Pure text rendering for tool responses: a CJK-aware layout engine (display-width
padding, box-drawing tables, vertical flow charts) plus per-tool renderers that turn
the discover/plan/eip payloads into readable multi-block strings. Rendering never
raises - missing keys degrade to '-'."""
import json
import unicodedata


def width(text):
    """Display width: East Asian W/F count 2, everything else 1; non-str is str()-ed."""
    if not isinstance(text,str):text=str(text)
    total=0
    for char in text:
        total+=2 if unicodedata.east_asian_width(char) in ('W','F') else 1
    return total


def _truncate(text,columns):
    """Clip to the given display width, marking the cut with an ellipsis."""
    if not isinstance(text,str):text=str(text)
    if width(text)<=columns:return text
    kept='';used=0
    for char in text:
        step=2 if unicodedata.east_asian_width(char) in ('W','F') else 1
        if used+step>columns-1:break
        kept+=char;used+=step
    return kept+'…'


def pad(text,columns):
    """Right-pad with spaces to the display width; over-wide text is truncated."""
    if not isinstance(text,str):text=str(text)
    if columns<1:return ''
    text=_truncate(text,columns)
    return text+' '*(columns-width(text))


def _cell(value):
    if value is None:return '-'
    if isinstance(value,bool):return str(value).lower()
    if not isinstance(value,str):value=str(value)
    return value.replace('\n',' ')


def table(headers,rows):
    """Box-drawing table with CJK-aware column alignment; empty data renders '(无数据)'."""
    headers=[_cell(h) for h in (headers if isinstance(headers,(list,tuple)) else [])]
    if not headers:return ''
    normalized=[]
    data=rows if isinstance(rows,(list,tuple)) else []
    if not data:data=[['(无数据)']+['']*(len(headers)-1)]
    for row in data:
        if not isinstance(row,(list,tuple)):row=[row]
        cells=list(row)[:len(headers)]
        cells+=['']*(len(headers)-len(cells))
        normalized.append([_cell(c) for c in cells])
    widths=[width(h) for h in headers]
    for cells in normalized:
        for index,cell in enumerate(cells):
            widths[index]=max(widths[index],width(cell))
    def border(left,middle,right):
        return left+middle.join('─'*(w+2) for w in widths)+right
    def content(cells):
        return '│'+'│'.join(' '+pad(cell,widths[index])+' ' for index,cell in enumerate(cells))+'│'
    lines=[border('┌','┬','┐'),content(headers),border('├','┼','┤')]
    lines.extend(content(cells) for cells in normalized)
    lines.append(border('└','┴','┘'))
    return '\n'.join(lines)


def flow(steps):
    """Vertical flow chart: each step is a titled box (detail lines inside), steps
    connected by an indented '▼' arrow."""
    data=steps if isinstance(steps,(list,tuple)) else []
    blocks=[]
    for number,step in enumerate(data,1):
        if not isinstance(step,dict):step={}
        title=str(step.get('title') or '')
        detail=step.get('detail')
        if detail is None:lines=[]
        elif isinstance(detail,(list,tuple)):lines=[str(item) for item in detail]
        else:lines=[str(detail)]
        header='─ 步骤 %d ─ %s ' % (number,title)
        inner=max([width(header)]+[width(line)+2 for line in lines])
        box=['┌'+header+'─'*(inner-width(header))+'┐']
        box.extend('│ '+pad(line,inner-2)+' │' for line in lines)
        box.append('└'+'─'*inner+'┘')
        blocks.append('\n'.join(box))
    return '\n  ▼\n'.join(blocks)


def block(title,body):
    """One titled block: '【title】' header line followed by the body text."""
    if isinstance(body,str):text=body
    elif isinstance(body,(list,tuple)):text='\n'.join(str(item) for item in body)
    elif body is None:text=''
    else:text=str(body)
    title=str(title)
    if not text:return '【%s】' % title
    return '【%s】\n%s' % (title,text)


def _clip(text,columns):
    """Single-line, width-clipped cell text for renderer descriptions."""
    if text is None:return '-'
    if isinstance(text,(dict,list)):text=json.dumps(text,ensure_ascii=False)
    elif not isinstance(text,str):text=str(text)
    return _truncate(text,columns)


def _dict(value):
    return value if isinstance(value,dict) else {}


def _list(value):
    if isinstance(value,(list,tuple)):return list(value)
    return []


def _scalar(value):
    if value is None:return '-'
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False)
    if isinstance(value,bool):return str(value).lower()
    return str(value)


def _baseline_rows(baseline):
    rows=[]
    for key,value in _dict(baseline).items():
        shown=_clip(value,50) if isinstance(value,dict) else _scalar(value)
        rows.append([key,shown])
    return rows


def _candidate_parts(result):
    """(page,total_pages,total_count,rows) for a candidate listing - the direct tool
    response carries 'candidates', the arrangement module a paged 'candidates_page'."""
    result=_dict(result)
    rows=result.get('candidates_page')
    if rows is None:rows=result.get('candidates')
    rows=_list(rows)
    pagination=_dict(result.get('pagination'))
    page=pagination.get('page')
    total=pagination.get('total_pages')
    count=pagination.get('total_count')
    if page is None:page=1
    if total is None:total=1
    if count is None:count=len(rows)
    return page,total,count,rows


def _candidate_table(result):
    page,total,count,rows=_candidate_parts(result)
    table_rows=[]
    for row in rows:
        row=_dict(row)
        actions=row.get('current_actions')
        if isinstance(actions,(list,tuple)):
            actions=','.join(str(a) for a in actions if a is not None)
        azs=row.get('availability_zones')
        if isinstance(azs,(list,tuple)):
            azs=','.join(str(a) for a in azs if a is not None)
        if azs in (None,''):azs=row.get('availability_zone')
        version=row.get('datastore_version')
        if version is None:version=_dict(row.get('datastore')).get('version')
        table_rows.append([row.get('id'),row.get('name'),row.get('status'),version,
                           row.get('deployment_type'),row.get('port'),azs,row.get('created'),
                           actions if actions not in (None,'') else '-'])
    return table(['ID','名称','状态','版本','部署类型','端口','AZ','创建时间','当前操作'],table_rows)


def _db_instance_blocks(result):
    """The three managed-instance views as blocks: candidate listing, one instance's
    basic/configuration/network detail, or the new-instance field-option baseline."""
    result=_dict(result)
    if 'candidates_page' in result or 'candidates' in result:
        page,total,count,rows=_candidate_parts(result)
        return [block('可托管实例列表（第 %s/%s 页，共 %s 个）' % (page,total,count),_candidate_table(result))]
    if 'basic' in result:
        basic=_dict(result.get('basic'))
        configuration=_dict(result.get('configuration'))
        datastore=_dict(configuration.get('datastore'))
        volume=_dict(configuration.get('volume'))
        ha=_dict(configuration.get('ha'))
        basic_table=table(['ID','名称','状态','规格','VCPU','内存'],
                          [[basic.get('id'),basic.get('name'),basic.get('status'),
                            basic.get('spec_code'),basic.get('vcpus'),basic.get('ram')]])
        config_table=table(['引擎','版本','端口','HA','磁盘类型','磁盘大小'],
                           [[datastore.get('type'),datastore.get('version'),configuration.get('port'),
                             ha.get('mode'),volume.get('type'),volume.get('size')]])
        network=_dict(result.get('network'))
        network_table=table(['VPC','子网','安全组'],
                            [[network.get('vpc_id'),network.get('subnet_id'),network.get('security_group_id')]])
        return [block('实例信息',basic_table+'\n\n'+config_table),block('网络',network_table)]
    fields=_dict(result.get('managed_instance_field_options'))
    rows=[]
    for key in sorted(fields):
        option=_dict(fields.get(key))
        recommended=option.get('recommended')
        if recommended is None:recommended=option.get('fixed')
        values=' / '.join(_scalar(v) for v in _list(option.get('values')))
        rows.append([key,_scalar(recommended),_clip(values,30),_clip(option.get('note'),40)])
    mode=result.get('mode')
    blocks=[block('托管实例参数基线（mode %s）' % (mode if mode is not None else '-'),
                  table(['字段','推荐','可选值','说明'],rows))]
    reminder=_list(result.get('top_level_reminder'))
    if reminder:
        blocks.append(block('提醒',[str(item) for item in reminder]))
    return blocks


def _module_supabase(module):
    if module.get('status')=='fixed':
        body=table(['字段','基线'],_baseline_rows(module.get('baseline')))
    else:
        body=str(module.get('hint') or '-')
    return block('模块一：Supabase 基本信息',body)


def _module_instance(module):
    if 'candidates_page' in module or 'candidates' in module:
        body=_candidate_table(module)
    elif module.get('status')=='fixed':
        parts=[table(['字段','基线'],_baseline_rows(module.get('baseline')))]
        instance=module.get('instance')
        if isinstance(instance,dict) and 'basic' in instance:
            parts.extend(_db_instance_blocks(instance))
        body='\n\n'.join(parts)
    else:
        body=str(module.get('hint') or '-')
    return block('模块二：托管实例',body)


def _module_network(module):
    if module.get('status')=='fixed':
        placement=_dict(module.get('placement'))
        plan=_dict(module.get('security_group_plan'))
        database=_dict(plan.get('database_group'))
        rows=[[key,placement.get(key)] for key in
              ('preference','vpc_id','vpc_name','subnet_id','subnet_name','subnet_cidr','availability_zone')]
        if database.get('action')=='不动':
            action='不动（现有组 %s）' % _scalar(database.get('current_security_group_id'))
        else:
            ingress=_dict(database.get('ingress'))
            action='新建 %s：入方向 %s/%s 放通 %s' % (_scalar(database.get('name')),_scalar(ingress.get('protocol')),
                                                    _scalar(ingress.get('port')),_scalar(ingress.get('source_cidr')))
        rows.append(['数据库组动作',action])
        body=table(['项','值'],rows)
    else:
        body=str(module.get('hint') or '-')
    return block('模块三：网络控制',body)


def render_basic_options(result):
    """discover_supabase_create_basic_options -> basics table plus the security-group
    strategy table."""
    result=_dict(result)
    options=_dict(result.get('basic_options'))
    def field(key):return _dict(options.get(key))
    def recommended(key):
        block_value=field(key)
        value=block_value.get('suggested')
        if value is None:value=block_value.get('recommended')
        return value
    def note(key):return field(key).get('note')
    def joined(key):
        return '；'.join(str(item) for item in _list(field(key).get('requirements')))
    storage=_dict(field('storage_component').get('recommended'))
    password=field('password')
    password_parts=[]
    if password.get('login_user') is not None:
        password_parts.append('登录用户 %s' % password.get('login_user'))
    password_parts.append(joined('password'))
    az=result.get('az_code')
    if az is None:az='-'
    values=lambda key:' / '.join(_scalar(v) for v in _list(field(key).get('values')))
    basics_rows=[
        ['name',recommended('name'),_clip(joined('name'),60)],
        ['version',recommended('version'),note('version')],
        ['mode',recommended('mode'),note('mode')],
        ['flavor_ref',recommended('flavor_ref'),note('flavor_ref')],
        ['availability_zone',values('availability_zone'),note('availability_zone')],
        ['password','-',_clip('；'.join(password_parts),60)],
        ['storage_component',storage.get('enabled'),note('storage_component')],
    ]
    strategy=_dict(result.get('security_group_strategy'))
    application=_dict(strategy.get('application_group'))
    ingress=_dict(application.get('ingress'))
    egress=_dict(application.get('egress'))
    database=_dict(strategy.get('database_group'))
    sg_rows=[
        ['应用组','入',ingress.get('port'),ingress.get('note')],
        ['应用组','出',egress.get('port'),egress.get('note')],
        ['数据库组','-','-',_clip(database.get('strategy'),60)],
    ]
    return '\n\n'.join([
        block('Supabase 基本信息（AZ %s）' % az,table(['字段','推荐','说明'],basics_rows)),
        block('安全组推荐策略',table(['组','方向','端口','说明'],sg_rows)),
    ])


def render_db_instance(result):
    """discover_db_instance_for_create -> candidate listing, one instance's detail, or
    the new-instance parameter baseline plus reminders."""
    return '\n\n'.join(_db_instance_blocks(result))


def render_network(result):
    """discover_network_for_create -> placement table, security-group specification
    table, optional precondition, and the apply-steps flow."""
    result=_dict(result)
    placement_rows=[[key,result.get(key)] for key in
                    ('preference','vpc_id','vpc_name','vpc_cidr','subnet_id','subnet_name',
                     'subnet_cidr','availability_zone','available_ip_count')]
    plan=_dict(result.get('security_group_plan'))
    application=_dict(plan.get('application_group'))
    ingress=_dict(application.get('ingress'))
    egress=_dict(application.get('egress'))
    sources=' / '.join('%s:%s' % (_dict(o).get('key'),_dict(o).get('source_cidr'))
                       for o in _list(ingress.get('source_cidr_options')))
    sg_rows=[
        ['应用组','入',ingress.get('protocol'),ingress.get('port'),sources,_clip(ingress.get('purpose'),40)],
        ['应用组','出',egress.get('protocol'),egress.get('port'),egress.get('destination_cidr'),
         _clip(egress.get('purpose'),40)],
    ]
    database=_dict(plan.get('database_group'))
    if result.get('scenario')=='existed_instance' or database.get('action')=='不动':
        sg_rows.append(['数据库组','不动','-','-',database.get('current_security_group_id'),
                        _clip(database.get('note'),40)])
    else:
        d_in=_dict(database.get('ingress'))
        d_out=_dict(database.get('egress'))
        sg_rows.append(['数据库组','入',d_in.get('protocol'),d_in.get('port'),d_in.get('source_cidr'),
                        _clip(d_in.get('purpose'),40)])
        sg_rows.append(['数据库组','出',d_out.get('protocol'),d_out.get('port'),d_out.get('destination_cidr'),
                        _clip(d_out.get('note'),40)])
    blocks=[block('网络选址',table(['项','值'],placement_rows)),
            block('安全组规格（仅规格，不创建资源）',table(['组','方向','协议','端口','网段','用途'],sg_rows))]
    if plan.get('precondition'):
        blocks.append(block('前提',plan.get('precondition')))
    steps=_list(plan.get('apply_steps'))
    if steps:
        flow_steps=[]
        for index,step in enumerate(steps,1):
            step=_dict(step)
            args=step.get('args')
            detail=json.dumps(args,ensure_ascii=False) if args is not None else None
            flow_steps.append({'title':'%s %s' % (index,step.get('tool')),'detail':detail})
        blocks.append(block('执行步骤',flow(flow_steps)))
    return '\n\n'.join(blocks)


def render_arrangement(result):
    """plan_supabase_creation_arrangement -> source decision, the three step modules,
    the EIP purchase baseline, the step-numbered creation flow and post-creation flow."""
    result=_dict(result)
    source=_dict(result.get('managed_instance_source'))
    lines=[]
    for option in _list(source.get('options')):
        option=_dict(option)
        badge='（推荐且默认）' if option.get('recommended') else ''
        lines.append('- %s%s：%s' % (option.get('name'),badge,option.get('note')))
    decision=source.get('decision')
    lines.append('已确认：%s' % (decision if decision is not None else '-'))
    lines.append(_scalar(source.get('requirement')))
    modules=_dict(result.get('step_modules'))
    blocks=[block('托管实例来源决策',lines),
            _module_supabase(_dict(modules.get('supabase_basics'))),
            _module_instance(_dict(modules.get('managed_instance'))),
            _module_network(_dict(modules.get('network_control')))]
    eip=_dict(result.get('eip_baseline'))
    purchase=_dict(eip.get('purchase_method'))
    recommended=_dict(purchase.get('recommended'))
    bandwidth=_dict(eip.get('bandwidth'))
    options_note='；'.join('%s：%s' % (_dict(o).get('name'),_dict(o).get('note'))
                          for o in _list(purchase.get('options')))
    size=bandwidth.get('recommended_size_mbps')
    bandwidth_note='；'.join(str(bandwidth.get(key)) for key in
                             ('share_type','type','size_range_mbps') if bandwidth.get(key) is not None)
    eip_rows=[
        ['购买方式',recommended.get('name'),options_note],
        ['带宽','%sM' % size if size is not None else '-',bandwidth_note],
        ['绑定',_clip(eip.get('bind'),60),_clip(eip.get('post_bind'),60)],
    ]
    blocks.append(block('EIP 购买基线',table(['项','推荐','说明'],eip_rows)))
    flow_steps=[]
    for entry in _list(result.get('creation_flow')):
        entry=_dict(entry)
        args=entry.get('args')
        if args is not None:detail=_clip(json.dumps(args,ensure_ascii=False),60)
        elif entry.get('action') is not None:detail=_clip(str(entry.get('action')),60)
        else:detail=None
        flow_steps.append({'title':'%s. %s [%s]' % (entry.get('step'),entry.get('tool'),entry.get('phase')),
                           'detail':detail})
    blocks.append(block('创建流程（1:1 严格执行）',flow(flow_steps)))
    post_lines=[]
    for entry in _list(result.get('post_creation_flow')):
        entry=_dict(entry)
        if entry.get('decision') is not None:
            post_lines.append('- 待决策：%s' % entry.get('decision'))
            continue
        detail=entry.get('action')
        if detail is None:detail=entry.get('args')
        post_lines.append('- %s：%s' % (entry.get('tool') or '-',_clip(detail,60)))
    blocks.append(block('创建后动作',post_lines))
    decisions=_list(result.get('decision_points'))
    if decisions:
        blocks.append(block('待决策',['- %s' % str(item) for item in decisions]))
    return '\n\n'.join(blocks)


def render_eip(result):
    """EIP payload -> the idle-EIP selection table, or the bound elastic EIP's
    property table (with the pending-payment order line when present)."""
    result=_dict(result)
    if result.get('mode')=='idle_selection':
        rows=[[_dict(e).get('id'),_dict(e).get('public_ip_address'),_dict(e).get('alias'),
               _dict(e).get('status'),_dict(e).get('bandwidth_size_mbps'),_dict(e).get('charge_mode')]
              for e in _list(result.get('idle_eips'))]
        return block('空闲 EIP（选定其一可直接绑定，不新建）',
                     table(['ID','地址','别名','状态','带宽 M','计费'],rows))
    rows=[[key,result.get(key)] for key in
          ('id','public_ip_address','alias','status','bandwidth_size_mbps','charge_mode','publicip_type','share_type')]
    if result.get('order_id') is not None:
        rows.append(['订单 ID（控制台支付后生效）',result.get('order_id')])
    return block('弹性 EIP',table(['属性','值'],rows))
