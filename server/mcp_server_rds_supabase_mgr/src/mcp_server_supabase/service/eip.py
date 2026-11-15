"""Elastic-EIP purchase via KooCLI (hcloud EIP): idle-first reuse, else a dedicated 5_bgp EIP."""
import os
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.plans import PlanStore, fingerprint

EIP_PATH='/v3/{project}/eip/eips'
USAGE_TAG='Supabase应用公网访问，自动创建的'


class EipService:
    """EIP purchase via KooCLI (hcloud EIP service): idle-first selection or a new
    dedicated full-dynamic-BGP EIP. Baseline: pay-per-use recommended, bandwidth 5-1000M."""

    def __init__(self,koocli=None,plans=None):
        self.koocli=koocli or KoocliClient()
        self.plans=plans or PlanStore()

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

    async def ensure_publicip(self,prefer_idle=True,charge_mode='postPaid',bandwidth_size_mbps=300,
                              name=None,period_type=None,period_num=None,confirm=False,plan_id=None):
        """Return idle EIPs for reuse, preview the purchase, or execute it behind the plan ledger."""
        if charge_mode not in ('postPaid','prePaid'):
            raise McpToolError('MCP_INVALID_ARGS','charge_mode must be postPaid or prePaid')
        if type(bandwidth_size_mbps) is not int or not 5<=bandwidth_size_mbps<=1000:
            raise McpToolError('MCP_INVALID_ARGS','bandwidth_size_mbps must be an integer between 5 and 1000')
        if name is not None and (not isinstance(name,str) or len(name)>64):
            raise McpToolError('MCP_INVALID_ARGS','name must be a string of at most 64 characters')
        if charge_mode=='prePaid':
            if period_type not in ('month','year'):
                raise McpToolError('MCP_INVALID_ARGS','prePaid requires period_type month or year')
            if type(period_num) is not int:
                raise McpToolError('MCP_INVALID_ARGS','prePaid requires an integer period_num')
            if period_type=='month' and not 1<=period_num<=9:
                raise McpToolError('MCP_INVALID_ARGS','month period_num must be between 1 and 9')
            if period_type=='year' and not 1<=period_num<=3:
                raise McpToolError('MCP_INVALID_ARGS','year period_num must be between 1 and 3')
        if prefer_idle:
            idle=await self.list_idle_publicips()
            if idle['data']:
                return {'mode':'idle_selection','idle_eips':idle['data'],
                        'note':'存在空闲 EIP：请展示给用户选定其一，直接用于 bind_supabase_eip，无需新建'}
        digest=self.intent_digest('POST',EIP_PATH,
                                  {'charge_mode':charge_mode,'bandwidth_size_mbps':bandwidth_size_mbps,
                                   'publicip_type':'5_bgp','share_type':'PER','name':name})
        if not confirm:
            return {'mode':'confirmation_required','status':'confirmation_required','execution':'not_executed',
                    'charge_mode':charge_mode,
                    'eip':{'id':None,'public_ip_address':None,'alias':name,'status':None,
                           'bandwidth_size_mbps':bandwidth_size_mbps,'charge_mode':charge_mode,
                           'publicip_type':'5_bgp（全动态 BGP）','share_type':'PER（独享）'},
                    'recommendation':{'charge_mode':'按需购买（postPaid）推荐',
                                      'bandwidth':'全动态 BGP，5-1000M，推荐 300M'},
                    'warnings':['新购 EIP 立即计费','包周期需控制台支付订单后生效'],
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        self.plans.claim(plan_id,digest)
        operation='CreatePublicip'
        params={'publicip':{'type':'5_bgp','ip_version':4,'alias':name or 'supabase-app-eip'},
                'bandwidth':{'name':name or 'supabase-bandwidth','share_type':'PER',
                             'size':bandwidth_size_mbps,'charge_mode':'bandwidth'}}
        if charge_mode=='prePaid':
            operation='CreatePrePaidPublicip'
            params['extendParam']={'period_type':period_type,'period_num':period_num}
        try:
            data=await self.koocli.call('EIP',operation,params)
            nested=data.get('publicip') if isinstance(data,dict) else None
            row=nested if isinstance(nested,dict) else (data if isinstance(data,dict) else {})
            view=self._view(row)
            if isinstance(data,dict) and data.get('public_ip_address') and not view.get('public_ip_address'):
                view['public_ip_address']=data['public_ip_address']
            if charge_mode=='prePaid':
                order_id=None
                if isinstance(data,dict):
                    order_id=data.get('order_id')
                    inner=data.get('data')
                    if not order_id and isinstance(inner,dict):order_id=inner.get('order_id')
                self.plans.finish(plan_id,'accepted')
                return {'mode':'created','status':'order_created','eip':view,'order_id':order_id,
                        'plan_id':plan_id,'note':'包周期订单在控制台支付后生效'}
            if not view.get('id'):raise ValueError()
            await self.koocli.call('EIP','BatchCreatePublicipTags',
                                   {'action':'create','publicip_id':view['id'],
                                    'tags':[{'key':'USAGE_FOR','value':USAGE_TAG}]})
            self.plans.finish(plan_id,'accepted')
            return {'mode':'created','status':'created','eip':view,
                    'tag':'USAGE_FOR='+USAGE_TAG,'plan_id':plan_id}
        except BaseException:
            self.plans.finish(plan_id,'unknown')
            raise RecoveryError('MCP_SDK_ERROR','EIP write result unknown','submission_unknown',
                                'Inspect the plan and EIP resource; never blindly repeat a write.',plan_id) from None
