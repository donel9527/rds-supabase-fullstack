"""Elastic-EIP purchase via KooCLI (hcloud EIP): idle-first reuse, else a dedicated 5_bgp EIP."""
import os
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.plans import PlanStore, fingerprint

EIP_PATH='/v3/{project}/eip/eips'
USAGE_TAG='Supabase应用公网访问，自动创建的'


def _error_label(error):
    """Bounded failure label for user-facing notes: the MCP error code when
    available, else the exception class name - never the raw message."""
    code=getattr(error,'code',None)
    return code if isinstance(code,str) else type(error).__name__


class EipService:
    """EIP purchase via KooCLI (hcloud EIP service): idle-first selection or a new
    dedicated full-dynamic-BGP EIP. Baseline: pay-per-use recommended, bandwidth 5-1000M."""

    def __init__(self,koocli=None,plans=None,ledger=None):
        self.koocli=koocli or KoocliClient()
        self.plans=plans or PlanStore()
        self.ledger=ledger   # None disables resource-ledger recording (tests / embedded use)

    def intent_digest(self,method,path,body):
        """Fingerprint a purchase intent against this KooCLI credential, mirroring Network."""
        return fingerprint({'endpoint':'hcloud:'+self.koocli.region,'credential':self.koocli.token,
                            'method':method,'path':path,'body':body})

    @staticmethod
    def _view(row):
        """Normalize origin rows and EIP rows into one contract; every field tolerates absence."""
        if not isinstance(row,dict):row={}
        publicip=row.get('publicip') or {}
        bandwidth=row.get('bandwidth') if isinstance(row.get('bandwidth'),dict) else {}
        return {'id':row.get('id'),
                'public_ip_address':row.get('public_ip_address') or row.get('publicip_address') or publicip.get('ip_address'),
                'alias':row.get('alias') or publicip.get('alias'),
                'status':row.get('status') or publicip.get('status'),
                'bandwidth_size_mbps':bandwidth.get('size') or row.get('bandwidth_size'),
                'charge_mode':bandwidth.get('charge_mode') or row.get('charge_mode'),
                'publicip_type':publicip.get('type') or row.get('type'),
                'share_type':bandwidth.get('share_type') or row.get('bandwidth_share_type')}

    async def list_idle_publicips(self):
        """List EIPs and keep only unbound ones for reuse before any purchase."""
        data=await self.koocli.call('EIP','ListPublicips',{'limit':100})
        rows=data.get('publicips') if isinstance(data,dict) else None
        if not isinstance(rows,list):
            raise McpToolError('MCP_SDK_ERROR','EIP list unreadable')
        idle=[self._view(row) for row in rows if isinstance(row,dict) and
              (row.get('status')=='FREE' or (row.get('status') is None and not row.get('associate_instance_id')))]
        return {'data':idle,'note':'空闲=未绑定（FREE）；选定其一可直接用于 bind_supabase_eip'}

    async def _existing_eip_ids(self):
        """Snapshot every visible EIP id before a creation submission - the
        reconciliation baseline. None (unreadable) degrades reconciliation to
        'unreadable'; submission itself proceeds (issue #24)."""
        try:
            data=await self.koocli.call('EIP','ListPublicips',{'limit':100})
            rows=data.get('publicips') if isinstance(data,dict) else None
            if not isinstance(rows,list):return None
            return {row.get('id') for row in rows if isinstance(row,dict)}
        except BaseException:
            return None

    async def _reconcile_creation(self,baseline,alias,charge_mode,size):
        """One bounded reconciliation read after an ambiguous CreatePublicip (issue #24).

        Attribution is by baseline difference: only ids absent from the
        pre-submission snapshot AND matching the submitted attributes (alias,
        charge mode, size) count as candidates - the fixed default alias
        'supabase-app-eip' collides across earlier auto-created EIPs, so
        attribute matching alone cannot attribute safely. Outcomes:
        created (exactly one new match) / absent (no new match) /
        ambiguous (several new matches - never auto-claimed) /
        unreadable (list failed or baseline unavailable)."""
        if baseline is None:
            return {'outcome':'unreadable','error':'baseline unavailable'}
        try:
            data=await self.koocli.call('EIP','ListPublicips',{'limit':100})
        except BaseException as error:
            return {'outcome':'unreadable','error':type(error).__name__}
        rows=data.get('publicips') if isinstance(data,dict) else None
        if not isinstance(rows,list):
            return {'outcome':'unreadable','error':'unrecognized list response'}
        candidates=[]
        for row in rows:
            if not isinstance(row,dict):continue
            view=self._view(row)
            if not view.get('id') or view['id'] in baseline:continue
            if view.get('alias')!=alias:continue
            if view.get('charge_mode')!=charge_mode:continue
            if view.get('bandwidth_size_mbps')!=size:continue
            candidates.append(view)
        if len(candidates)==1:return {'outcome':'created','eip':candidates[0]}
        if not candidates:return {'outcome':'absent'}
        return {'outcome':'ambiguous','candidates':sorted(str(c.get('id')) for c in candidates)}

    async def ensure_publicip(self,prefer_idle=True,billing_method=None,bandwidth_size_mbps=None,
                              name=None,confirm=False,plan_id=None):
        """Return idle EIPs for reuse, preview the on-demand purchase, or execute it behind the plan ledger."""
        # On-demand billing is fixed on this path: prepaid periods are not supported.
        if billing_method not in (None,'bandwidth','traffic'):
            raise McpToolError('MCP_INVALID_ARGS','billing_method must be bandwidth (按带宽计费) or traffic (按流量计费)')
        size_ceiling=300 if billing_method=='traffic' else 1000   # traffic-mode per-EIP peak cap (official rule)
        if bandwidth_size_mbps is not None and (type(bandwidth_size_mbps) is not int or not 5<=bandwidth_size_mbps<=size_ceiling):
            raise McpToolError('MCP_INVALID_ARGS',
                               'bandwidth_size_mbps must be an integer between 5 and %d%s'%(size_ceiling,
                                   ' (按流量计费单 EIP 带宽峰值上限 300Mbps，官方约束)' if billing_method=='traffic' else ''))
        if name is not None and (not isinstance(name,str) or len(name)>64):
            raise McpToolError('MCP_INVALID_ARGS','name must be a string of at most 64 characters')
        if prefer_idle:
            idle=await self.list_idle_publicips()
            if idle['data']:
                return {'mode':'idle_selection','idle_eips':idle['data'],
                        'note':'存在空闲 EIP：请展示给用户选定其一，直接用于 bind_supabase_eip，无需新建'}
        # The new-purchase branch only: billing method and bandwidth size are user decisions with no defaults.
        if billing_method is None:
            raise McpToolError('MCP_INVALID_ARGS','计费方式由用户根据场景选择（无默认）：bandwidth（按带宽计费——流量大或访问量稳定）/ traffic（按流量计费——流量低或访问量波动大）',
                               hint='按需计费固定（不支持包周期）；费用 = 带宽费/流量费 + 弹性公网IP保有费（未绑定云资源且未释放时收取）；计费方式适用场景见 https://support.huaweicloud.com/price-eip/eip_billing_0005.html')
        if bandwidth_size_mbps is None:
            raise McpToolError('MCP_INVALID_ARGS',
                              '带宽大小由用户决策（%s），无默认推荐——带宽为收费项，创建即持续计费直至释放'%(
                                  '5-300 Mbps 整数；按流量计费下带宽为峰值限速（单 EIP 上限 300Mbps）' if billing_method=='traffic'
                                  else '5-1000 Mbps 整数；按带宽计费下大小即计费尺寸'),
                               hint='收费标准见 https://support.huaweicloud.com/price-eip/eip_billing_0007.html 与官网价格详情；空闲复用路径（prefer_idle=true 且存在空闲 EIP）无需带宽参数')
        digest=self.intent_digest('POST',EIP_PATH,
                                  {'billing_method':billing_method,'bandwidth_size_mbps':bandwidth_size_mbps,
                                   'publicip_type':'5_bgp','share_type':'PER','name':name})
        if not confirm:
            method_note={'bandwidth':'按带宽计费——带宽费按带宽峰值×时长（不限流量），流量大或访问量稳定场景更优',
                         'traffic':'按流量计费——流量费按出云流量 GB 计费（入云不计），带宽仅作峰值限速，流量低或波动大场景更优'}[billing_method]
            unit_ref={'bandwidth':'阶梯计费：0-5M 统一单价、超 5M 按每 Mbps 计费；官方示例 6Mbps≈0.565 元/小时（随地域浮动，以价格详情为准）',
                      'traffic':'官方示例 0.64 元/GB（仅出云流量；随地域浮动，以价格详情为准）'}[billing_method]
            return {'mode':'confirmation_required','status':'confirmation_required','execution':'not_executed',
                    'billing_method':billing_method,
                    'eip':{'id':None,'public_ip_address':None,'alias':name,'status':None,
                           'bandwidth_size_mbps':bandwidth_size_mbps,'billing_method':billing_method,
                           'publicip_type':'5_bgp（全动态 BGP）','share_type':'PER（独享）'},
                    'billing':{'mode':'按需计费（固定，不支持包周期）——秒级计费按小时结算，自 EIP 创建起计费至释放',
                               'method':method_note,
                               'fee_components':'费用 = 带宽费/流量费 + 弹性公网IP保有费（未绑定云资源且未释放时收取，官方示例 0.02 元/小时）',
                               'unit_price_reference':unit_ref,
                               'price_source':'精确单价以官网价格详情为准：https://www.huaweicloud.com/pricing.html?tab=detail#/eip',
                               'traffic_limit':'单 EIP 带宽峰值上限 300Mbps；同账号同区域所有按流量 EIP 峰值总和 ≤5Gbps（2026-04 起官方约束）' if billing_method=='traffic' else None},
                    'warnings':['%s——已由用户确认（%s Mbps）'%(method_note,bandwidth_size_mbps),
                                '带宽/流量均为收费项：自 EIP 创建起持续计费直至释放'],
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        self.plans.claim(plan_id,digest)
        alias=name or 'supabase-app-eip'
        params={'publicip':{'type':'5_bgp','ip_version':4,'alias':alias},
                'bandwidth':{'name':name or 'supabase-bandwidth','share_type':'PER',
                             'size':bandwidth_size_mbps,'charge_mode':billing_method}}
        baseline=await self._existing_eip_ids()
        view=None
        reconciled=None
        try:
            data=await self.koocli.call('EIP','CreatePublicip',params)
            nested=data.get('publicip') if isinstance(data,dict) else None
            row=nested if isinstance(nested,dict) else (data if isinstance(data,dict) else {})
            view=self._view(row)
            if isinstance(data,dict) and data.get('public_ip_address') and not view.get('public_ip_address'):
                view['public_ip_address']=data['public_ip_address']
            if not view.get('id'):raise ValueError('unrecognized creation response')
        except BaseException as error:
            # Ambiguous submission (transport lost or response unparsable): the
            # cloud may still have created the EIP. Reconcile before returning
            # anything - never push a clarifiable result back to the caller (#24).
            outcome=await self._reconcile_creation(baseline,alias,billing_method,bandwidth_size_mbps)
            if outcome['outcome']=='created':
                view=outcome['eip']
                reconciled={'verified':True,
                            'note':'提交响应丢失（%s）：已按基线差集+参数匹配（别名/带宽/计费方式）实查确认 EIP 创建成功'%_error_label(error)}
            elif outcome['outcome']=='absent':
                self.plans.finish(plan_id,'failed')
                raise RecoveryError('MCP_SDK_ERROR','EIP creation verified absent after reconciliation','verified_absent',
                                    '实查核对未发现新建 EIP（大概率未创建）：重试须全新预览+新 plan_id；若担心列表滞后，重试前可稍候并用 list_idle_publicips 或控制台再核对一次。',plan_id) from None
            elif outcome['outcome']=='ambiguous':
                self.plans.finish(plan_id,'unknown')
                raise RecoveryError('MCP_SDK_ERROR','EIP creation ambiguous: multiple new candidates','ambiguous_candidates',
                                    '实查核对发现多个新 EIP 匹配本次参数（候选 ID：%s）——不可自动归属，请人工核对后处置，绝不重放。'%', '.join(outcome['candidates']),plan_id) from None
            else:
                self.plans.finish(plan_id,'unknown')
                raise RecoveryError('MCP_SDK_ERROR','EIP write result unknown','submission_unknown',
                                    '提交响应丢失（%s）且实查清单不可读（%s）：先实查 EIP 列表再决定下一步；绝不盲目重放。'%(
                                        _error_label(error),outcome.get('error','unreadable')),plan_id) from None
        # The USAGE_FOR tag is advisory (provenance also lives in the resource
        # ledger): a failed tag write degrades to a warning, never to an unknown
        # write result - the EIP itself is already created.
        tag_warning=None
        try:
            await self.koocli.call('EIP','BatchCreatePublicipTags',
                                   {'action':'create','publicip_id':view['id'],
                                    'tags':[{'key':'USAGE_FOR','value':USAGE_TAG}]})
        except BaseException as error:
            tag_warning='USAGE_FOR 标签写入失败（%s）：EIP 已创建；标签用于来源标识，可稍后经控制台或 hcloud 补写'%_error_label(error)
        self.plans.finish(plan_id,'accepted')
        result={'mode':'created','status':'created','eip':view,
                'tag':'USAGE_FOR='+USAGE_TAG,'plan_id':plan_id}
        if reconciled is not None:result['reconciliation']=reconciled
        if tag_warning:result['tag_warning']=tag_warning
        if self.ledger is not None:
            warning=self.ledger.record_safe('eip',view['id'],name=view.get('alias'),
                                            auto_created=True,
                                            detail={'address':view.get('public_ip_address'),
                                                    'billing_method':billing_method,
                                                    'bandwidth_size_mbps':bandwidth_size_mbps,
                                                    'charge_mode':view.get('charge_mode'),
                                                    'provenance':'create_supabase_eip'})
            if warning:result['record_warning']=warning
        return result
