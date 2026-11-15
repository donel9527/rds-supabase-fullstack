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


def _spec_text(spec):
    """One catalog spec as 'spec_code（vcpus vCPU/ram GB）'; missing sizing keeps the code alone."""
    spec=_dict(spec)
    code=_scalar(spec.get('spec_code'))
    vcpus=spec.get('vcpus');ram=spec.get('ram')
    if vcpus is None or ram is None:return code
    return '%s（%s vCPU/%s GB）' % (code,_scalar(vcpus),_scalar(ram))


def _flavor_groups_block(title,flavor):
    """Grouped flavor catalog: one line per group - 'label（group_type）｜ spec · spec' - wrapped
    at the ' · ' separators once the line passes 90 display columns."""
    groups=_list(_dict(flavor).get('groups'))
    if not groups:return None
    lines=[]
    for group in groups:
        group=_dict(group)
        label=group.get('label')
        if label is None:label=group.get('group_type')
        head='%s（%s）｜ ' % (_scalar(label),_scalar(group.get('group_type')))
        specs=[_spec_text(spec) for spec in _list(group.get('specs'))] or ['-']
        current=head;used=width(head)
        for index,spec in enumerate(specs):
            piece=(' · ' if index else '')+spec
            if used+width(piece)>90 and used>width(head):
                lines.append(current);current=spec;used=width(spec)
            else:
                current+=piece;used+=width(piece)
        lines.append(current)
    return block(title,'\n'.join(lines))


def _volume_options_block(volume):
    """Storage-type catalog: value / Chinese label / official note / live compatible group types."""
    options=_list(_dict(volume).get('options'))
    if not options:return None
    rows=[]
    for option in options:
        option=_dict(option)
        compatible=_list(option.get('compatible_group_types'))
        rows.append([option.get('value'),option.get('label'),_clip(option.get('note'),50),
                     ','.join(str(item) for item in compatible) if compatible else '-'])
    return block('磁盘类型',table(['值','中文名','说明','兼容规格类型'],rows))


def _flavor_match_text(match):
    """The app-to-instance flavor match as one summary line."""
    match=_dict(match)
    basis=match.get('match_basis')
    if basis is None:basis='group_type+vcpus+ram'
    if not isinstance(basis,str):basis=str(basis)
    return '%s（与应用 %s 同档：%s，依据 %s）' % (_scalar(match.get('matched_spec')),
                                                _scalar(match.get('app_flavor_ref')),
                                                _scalar(match.get('app_group_label')),basis)


def _interaction_lines(module):
    """Interaction notices carried by arrangement modules (flavor/volume), each on its own line."""
    module=_dict(module)
    lines=[]
    for key,label in (('flavor_interaction','规格交互'),('volume_interaction','磁盘类型交互')):
        text=module.get(key)
        if text is None:continue
        lines.append('%s：%s' % (label,_wrap(_scalar(text),88)))
    return lines


def _baseline_rows(baseline):
    rows=[]
    for key,value in _dict(baseline).items():
        if key=='flavor_match' and isinstance(value,dict):
            rows.append(['规格匹配',_flavor_match_text(value)])
            continue
        if key=='volume' and isinstance(value,dict) and value.get('type_basis') is not None:
            rows.append(['volume','%s（%s）｜ %s GB' % (_scalar(value.get('type')),
                                                        _scalar(value.get('type_basis')),
                                                        _scalar(value.get('size')))])
            continue
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
    groups_block=_flavor_groups_block('实例规格分组',fields.get('flavor_ref'))
    if groups_block is not None:blocks.append(groups_block)
    volume_block=_volume_options_block(fields.get('volume.type'))
    if volume_block is not None:blocks.append(volume_block)
    reminder=_list(result.get('top_level_reminder'))
    if reminder:
        blocks.append(block('提醒',[str(item) for item in reminder]))
    return blocks


def _module_supabase(module):
    if module.get('status')=='fixed':
        parts=[table(['字段','基线'],_baseline_rows(module.get('baseline')))]
    else:
        parts=[str(module.get('hint') or '-')]
    parts.extend(_interaction_lines(module))
    return block('模块一：Supabase 基本信息','\n'.join(parts))


def _module_instance(module):
    if 'candidates_page' in module or 'candidates' in module:
        parts=[_candidate_table(module)]
    elif module.get('status')=='fixed':
        parts=[table(['字段','基线'],_baseline_rows(module.get('baseline')))]
        instance=module.get('instance')
        if isinstance(instance,dict) and 'basic' in instance:
            parts.extend(_db_instance_blocks(instance))
    else:
        parts=[str(module.get('hint') or '-')]
    parts.extend(_interaction_lines(module))
    return block('模块二：托管实例','\n\n'.join(parts))


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
    blocks=[block('Supabase 基本信息（AZ %s）' % az,table(['字段','推荐','说明'],basics_rows))]
    groups_block=_flavor_groups_block('应用规格分组',options.get('flavor_ref'))
    if groups_block is not None:blocks.append(groups_block)
    blocks.append(block('安全组推荐策略',table(['组','方向','端口','说明'],sg_rows)))
    return '\n\n'.join(blocks)


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
    the optional OBS integration module, the EIP purchase baseline, the step-numbered
    creation flow and post-creation flow."""
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
    obs=modules.get('obs_integration')
    if isinstance(obs,dict) and obs:
        blocks.append(_module_obs(obs))
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


def _wrap(text,columns):
    """Wrap to the display width without truncating; embedded newlines are kept."""
    if text is None:return ''
    if not isinstance(text,str):text=str(text)
    if columns<1:return text
    wrapped=[]
    for line in text.split('\n'):
        current='';used=0
        for char in line:
            step=2 if unicodedata.east_asian_width(char) in ('W','F') else 1
            if used+step>columns and current:
                wrapped.append(current);current='';used=0
            current+=char;used+=step
        wrapped.append(current)
    return '\n'.join(wrapped)


def _bucket_spec_rows(spec,hint=None):
    spec=_dict(spec)
    if hint is None:hint=spec.get('storage_component_hint')
    rows=[[key,_scalar(spec.get(key))] for key in
          ('bucket_name','storage_class','bucket_type','redundancy','block_public_access',
           'region','enterprise_project')]
    if isinstance(hint,dict) and hint:
        rows.append(['ak_sk',_scalar(hint.get('ak_sk'))])
        rows.append(['挂载',_scalar(hint.get('bucket'))])
    return rows


def _module_obs(module):
    module=_dict(module)
    acquisition=_dict(module.get('acquisition'))
    recommended=acquisition.get('recommended')
    lines=[]
    for option in _list(acquisition.get('options')):
        option=_dict(option)
        badge='（推荐/默认）' if option.get('key')==recommended or option.get('recommended') else ''
        lines.append('- %s：%s%s' % (_scalar(option.get('name')),_scalar(option.get('note')),badge))
    lines.append(table(['项','值'],_bucket_spec_rows(module.get('new_bucket_spec'))))
    credential=_dict(module.get('credential'))
    if credential.get('temporary'):
        lines.append('凭证提示：%s' % _scalar(credential.get('notice')))
    return block('OBS 桶对接（大文件存储场景）',lines)


def _render_storage_options(result):
    result=_dict(result)
    reuse=_dict(result.get('reuse'))
    new_bucket=_dict(result.get('new_bucket'))
    plan_lines=['- 复用已有桶：%s' % _scalar(reuse.get('note')),
                '- 新建桶（推荐、默认）：%s' % _scalar(new_bucket.get('note'))]
    credential=_dict(result.get('credential'))
    credential_rows=[['凭证类型','临时凭证（含 SecurityToken）' if credential.get('temporary') else '长期 AK/SK'],
                     ['detail',_scalar(credential.get('detail'))]]
    if credential.get('notice') is not None:
        credential_rows.append(['notice',_scalar(credential.get('notice'))])
    bucket_rows=[[_dict(bucket).get('name'),_dict(bucket).get('location'),
                  _dict(bucket).get('public_status'),_dict(bucket).get('risk_note')]
                 for bucket in _list(reuse.get('buckets'))]
    bucket_table=table(['桶名','区域','公共状态','风险提示'],bucket_rows)
    read_test=_dict(reuse.get('read_test'))
    if read_test.get('passed') is False:
        bucket_table='%s\n读测试未通过：%s' % (bucket_table,_scalar(read_test.get('detail')))
    blocks=[block('OBS 存储方案（大文件/图片/视频承载）',plan_lines),
            block('凭证模式',table(['项','值'],credential_rows)),
            block('可复用桶（私有优先）',bucket_table),
            block('新桶完整参数配置（推荐）',
                  table(['项','值'],_bucket_spec_rows(new_bucket.get('spec')))),
            block('storage_component 对应',_wrap(result.get('storage_component_note'),90) or '-')]
    return '\n\n'.join(blocks)


def _render_storage_bucket(result):
    result=_dict(result)
    spec=_dict(result.get('spec') or result.get('bucket'))
    blocks=[block('新桶参数规格',
                  table(['项','值'],_bucket_spec_rows(spec,result.get('storage_component_hint'))))]
    status=result.get('status')
    if status=='ok':
        status_text='已创建：%s' % _clip(result.get('note'),70)
    elif status=='confirmation_required':
        status_text='待确认（预览返回 plan_id）'
    else:
        status_text=_scalar(status)
    blocks.append(block('状态',status_text))
    warnings=_list(result.get('warnings'))
    if warnings:
        blocks.append(block('注意',[str(item) for item in warnings]))
    return '\n\n'.join(blocks)


def render_storage(result):
    """discover_supabase_storage -> the reuse-vs-new scheme, credential mode,
    reusable-bucket table and new-bucket spec; create_supabase_new_obs -> the
    new-bucket spec, creation status and warnings."""
    result=_dict(result)
    if result.get('mode')=='storage_options':
        return _render_storage_options(result)
    return _render_storage_bucket(result)


def _creation_request_rows(request):
    rows=[]
    for key,value in _dict(request).items():
        if isinstance(value,(dict,list)):
            text=_wrap(json.dumps(value,ensure_ascii=False),60)
            lines=text.split('\n') if text else ['-']
        else:
            lines=[_scalar(value)]
        for index,line in enumerate(lines):
            rows.append([key if index==0 else '',line])
    return rows


def _creation_plan_body(plan):
    plan=_dict(plan)
    application=_dict(plan.get('application_group'))
    ingress=_dict(application.get('ingress'))
    egress=_dict(plan.get('egress') or application.get('egress'))
    rows=[['应用组','入',ingress.get('port'),ingress.get('cidr')],
          ['应用组','出',egress.get('port'),egress.get('cidr')]]
    database=plan.get('database_group')
    if isinstance(database,dict):
        db_ingress=_dict(database.get('ingress'))
        rows.append(['数据库组','入',db_ingress.get('port'),db_ingress.get('cidr')])
    body=table(['组','方向','端口','网段'],rows)
    if isinstance(database,str) and database:
        body='%s\n数据库组：%s'%(body,database)
    return body


def _creation_groups_body(security_groups):
    security_groups=_dict(security_groups)
    database_id=security_groups.get('database_group_id')
    database_note=security_groups.get('database_group')
    id_rows=[['应用组',security_groups.get('application_group_id')]]
    if database_id is not None:
        id_rows.append(['数据库组',database_id])
        ids=table(['组','ID'],id_rows)
    elif isinstance(database_note,str) and database_note:
        ids='%s\n数据库组：%s'%(table(['组','ID'],id_rows),database_note)
    else:
        id_rows.append(['数据库组',None])
        ids=table(['组','ID'],id_rows)
    rule_rows=[[_dict(rule).get('group'),_dict(rule).get('direction'),_dict(rule).get('port'),
                _dict(rule).get('cidr')] for rule in _list(security_groups.get('rules'))]
    return '%s\n\n%s'%(ids,table(['组','方向','端口','网段'],rule_rows))


def _creation_workflow_lines(workflow):
    workflow=_dict(workflow)
    track=_dict(workflow.get('track'))
    head='跟踪：%s'%_scalar(track.get('tool'))
    if track.get('args') is not None:
        head='%s %s'%(head,json.dumps(track.get('args'),ensure_ascii=False))
    lines=[_wrap(head,90)]
    if workflow.get('reminder') is not None:
        lines.append(str(workflow.get('reminder')))
    return lines


def _creation_eip_lines(after_completion):
    after=_dict(after_completion)
    lines=[]
    for index,entry in enumerate(_list(after.get('eip_automation')),1):
        entry=_dict(entry)
        if entry.get('args') is not None:
            detail=_clip(json.dumps(entry.get('args'),ensure_ascii=False),70)
        else:
            detail=_clip(entry.get('action'),70)
        lines.append('%s. %s %s'%(index,_scalar(entry.get('tool')),detail))
    if after.get('note') is not None:
        lines.append(str(after.get('note')))
    return lines


def _creation_preview_blocks(result):
    result=_dict(result)
    scenario=result.get('scenario')
    if scenario is None:scenario='-'
    summary=table(['项','值'],[[key,result.get(key)] for key in ('scenario','status','plan_id')])
    blocks=[block('创建任务预览（场景 %s）'%scenario,summary),
            block('请求体（脱敏）',table(['字段','值'],_creation_request_rows(result.get('request')))),
            block('将自动创建的安全组',_creation_plan_body(result.get('security_group_plan')))]
    warnings=_list(result.get('warnings'))
    if warnings:
        blocks.append(block('注意',[str(item) for item in warnings]))
    return blocks


def _creation_submitted_blocks(result):
    result=_dict(result)
    scenario=result.get('scenario')
    if scenario is None:scenario='-'
    order_id=result.get('order_id')
    if order_id is not None and result.get('status')=='order_created':
        order_shown='%s（控制台/订单工具支付后生效）'%order_id
    else:
        order_shown=order_id
    summary_rows=[[key,result.get(key)] for key in
                  ('status','job_id','application_id','instance_id','instance_job_id')]
    summary_rows.append(['order_id',order_shown])
    workflow=_dict(result.get('workflow'))
    return [block('创建任务已下发（场景 %s）'%scenario,table(['项','值'],summary_rows)),
            block('自动创建的安全组',_creation_groups_body(result.get('security_groups'))),
            block('工作流',_creation_workflow_lines(workflow)),
            block('创建完成后：EIP 自动化',_creation_eip_lines(workflow.get('after_completion')))]


def render_creation_flow(result):
    """create_supabase_with_new_instance / create_supabase_link_exist_instance ->
    the confirmation preview (summary, sanitized request body, planned security
    groups, warnings) or the submitted summary (job ids, created security groups,
    tracking workflow, post-completion EIP automation)."""
    result=_dict(result)
    if result.get('status')=='confirmation_required':
        return '\n\n'.join(_creation_preview_blocks(result))
    return '\n\n'.join(_creation_submitted_blocks(result))
