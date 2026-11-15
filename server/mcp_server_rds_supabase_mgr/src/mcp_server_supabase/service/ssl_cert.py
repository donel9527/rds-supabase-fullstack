"""SCM SSL certificate inventory and purchase via KooCLI (hcloud SCM), pinned to cn-north-4."""
import os
import re
import time
from huaweicloud_mcp_core.errors import McpToolError
from mcp_server_supabase.client.koocli import KoocliClient
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.plans import PlanStore, fingerprint

SCM_REGION='cn-north-4'
CERT_BRANDS=('GEOTRUST','GLOBALSIGN','SYMANTEC','CFCA','TRUSTASIA','VTRUS')
CERT_TYPES=('DV_SSL_CERT','DV_SSL_CERT_BASIC','EV_SSL_CERT','EV_SSL_CERT_PRO','OV_SSL_CERT','OV_SSL_CERT_PRO')
FREE_TYPES=('DV_SSL_CERT_BASIC',)
DOMAIN_TYPES=('SINGLE_DOMAIN','MULTI_DOMAIN','WILDCARD')
DOMAIN_METHODS=('DNS','File','Email')
CERT_FIELDS=('id','name','domain','sans','type','brand','status','expire_time','domain_type','domain_count','enterprise_project_id')
LIST_NOTE=('证书为账号级 SCM 资源（全局服务，SCM 通道固定 region=cn-north-4）；'
           'status 按实况透传（PAID=已购待申请、ISSUED=已签发等）；'
           'change_supabase_ssl 的 cert_id 即此 id')
UNLOCATED_NOTE='证书已购但未能自动定位 certificate_id，请用 list_ssl_certificates 查询后经控制台或后续版本工具完成申请'


class SslCertService:
    """SCM SSL certificates via KooCLI (hcloud SCM): account-level inventory and guarded
    purchase. SCM is a global service with a narrow KooCLI region list, so every call runs
    through a dedicated client pinned to cn-north-4 regardless of the ambient region."""

    def __init__(self,koocli=None,plans=None):
        self.koocli=koocli or KoocliClient(region=SCM_REGION)
        self.plans=plans or PlanStore()

    def intent_digest(self,method,path,body):
        """Fingerprint a certificate purchase intent against this KooCLI credential, mirroring Eip."""
        return fingerprint({'endpoint':'hcloud:'+SCM_REGION,'credential':self.koocli.token,
                            'method':method,'path':path,'body':body})

    @staticmethod
    def _view(row):
        """Whitelist one certificate row; every field tolerates absence."""
        if not isinstance(row,dict):row={}
        return {field:row.get(field) for field in CERT_FIELDS}

    @classmethod
    def _limited(cls,data,depth=3):
        """Bound an unknown response to at most 20 keys per level of scalars."""
        if not isinstance(data,dict):
            return None if data is None else str(data)[:200]
        keep={}
        for key,value in list(data.items())[:20]:
            if depth>0 and isinstance(value,dict):
                keep[key]=cls._limited(value,depth-1)
            elif depth>0 and isinstance(value,list):
                keep[key]=[cls._limited(item,depth-1) if isinstance(item,dict) else item
                           for item in value[:10]
                           if isinstance(item,(dict,str,int,float,bool)) or item is None]
            elif isinstance(value,(str,int,float,bool)) or value is None:
                keep[key]=value
            else:
                keep[key]=str(value)[:120]
        return keep

    @classmethod
    def _find_first(cls,data,keys,depth=3):
        """Best-effort identifier extraction from an unknown response shape."""
        if not isinstance(data,dict) or depth<0:return None
        for key in keys:
            value=data.get(key)
            if isinstance(value,str) and value:return value
            if isinstance(value,int) and not isinstance(value,bool) and value:return str(value)
        for value in data.values():
            found=None
            if isinstance(value,dict):found=cls._find_first(value,keys,depth-1)
            elif isinstance(value,list):
                for item in value[:10]:
                    if isinstance(item,dict):found=cls._find_first(item,keys,depth-1)
                    if found:break
            if found:return found
        return None

    async def list_certificates(self,limit=50):
        """List the account's SCM certificates, whitelist-projected with a fixed note."""
        if type(limit) is not int or not 1<=limit<=100:
            raise McpToolError('MCP_INVALID_ARGS','limit must be an integer between 1 and 100')
        data=await self.koocli.call('SCM','ListCertificates',{'limit':limit})
        rows=data.get('certificates') if isinstance(data,dict) else None
        if not isinstance(rows,list):
            raise McpToolError('MCP_SDK_ERROR','SCM certificate list unreadable')
        certificates=[self._view(row) for row in rows]
        return {'data':{'certificates':certificates},'total':len(certificates),'note':LIST_NOTE}

    async def _locate_paid_cert(self,apply_domain):
        """One bounded attempt to locate the just-purchased PAID certificate by domain, newest by id."""
        try:
            data=await self.koocli.call('SCM','ListCertificates',{'limit':100})
        except McpToolError:
            return None
        rows=data.get('certificates') if isinstance(data,dict) else None
        if not isinstance(rows,list):return None
        now=time.time();candidates=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('status')!='PAID':continue
            expire=row.get('expire_time')
            if isinstance(expire,(int,float)) and not isinstance(expire,bool):
                stamp=expire/1000 if expire>10**11 else expire
                if stamp<now:continue
            domain=str(row.get('domain') or '')
            raw_sans=row.get('sans')
            if isinstance(raw_sans,(list,tuple)):
                sans={str(item).strip() for item in raw_sans}
            else:
                sans={item.strip() for item in str(raw_sans or '').split(',')}
            if apply_domain and apply_domain!=domain and apply_domain not in sans:continue
            candidates.append(row)
        if not candidates:return None
        def rank(row):
            digits=re.sub(r'\D','',str(row.get('id') or ''))
            return int(digits) if digits else 0
        return max(candidates,key=rank).get('id')

    @staticmethod
    def _billing_note(cert_type,is_auto_pay,order_id):
        """Compose the post-purchase billing lead line from tier, auto-pay mode and order id."""
        if cert_type in FREE_TYPES:
            lead='免费档（DV_SSL_CERT_BASIC）无订单费用'
        elif is_auto_pay:
            lead='付费档已自动扣款'
        else:
            lead='付费档已生成待支付订单，须在控制台/费用中心支付后交付'
        if order_id:lead+='；订单号 '+str(order_id)
        return lead

    async def purchase_cert(self,cert_brand,cert_type,domain_type,effective_time,
                            order_number=1,domain_numbers=1,is_auto_pay=False,
                            apply_domain=None,domain_method=None,applicant_name=None,
                            applicant_email=None,applicant_phone=None,confirm=False,plan_id=None):
        """Preview or execute a guarded SCM certificate purchase, optionally chaining the apply."""
        if cert_brand not in CERT_BRANDS:
            raise McpToolError('MCP_INVALID_ARGS','cert_brand must be one of '+','.join(CERT_BRANDS))
        if cert_type not in CERT_TYPES:
            raise McpToolError('MCP_INVALID_ARGS','cert_type must be one of '+','.join(CERT_TYPES))
        if domain_type not in DOMAIN_TYPES:
            raise McpToolError('MCP_INVALID_ARGS','domain_type must be one of '+','.join(DOMAIN_TYPES))
        if type(effective_time) is not int or not 1<=effective_time<=10:
            raise McpToolError('MCP_INVALID_ARGS','effective_time must be an integer between 1 and 10 (years)')
        if type(order_number) is not int or not 1<=order_number<=100:
            raise McpToolError('MCP_INVALID_ARGS','order_number must be an integer between 1 and 100')
        if type(domain_numbers) is not int or not 1<=domain_numbers<=100:
            raise McpToolError('MCP_INVALID_ARGS','domain_numbers must be an integer between 1 and 100')
        if domain_type in ('SINGLE_DOMAIN','WILDCARD') and domain_numbers!=1:
            raise McpToolError('MCP_INVALID_ARGS','domain_numbers must be 1 for SINGLE_DOMAIN or WILDCARD')
        if domain_type=='MULTI_DOMAIN' and not 2<=domain_numbers<=100:
            raise McpToolError('MCP_INVALID_ARGS','domain_numbers must be between 2 and 100 for MULTI_DOMAIN')
        if type(is_auto_pay) is not bool:
            raise McpToolError('MCP_INVALID_ARGS','is_auto_pay must be a boolean')
        block=(apply_domain,domain_method,applicant_name,applicant_email,applicant_phone)
        names=('apply_domain','domain_method','applicant_name','applicant_email','applicant_phone')
        missing=[name for name,value in zip(names,block) if value is None]
        if missing and len(missing)<len(names):
            raise McpToolError('MCP_INVALID_ARGS','apply block is partial; missing: '+','.join(missing))
        wants_apply=not missing
        if wants_apply:
            if not isinstance(apply_domain,str) or not apply_domain.strip():
                raise McpToolError('MCP_INVALID_ARGS','apply_domain must be a non-empty string')
            if domain_method not in DOMAIN_METHODS:
                raise McpToolError('MCP_INVALID_ARGS','domain_method must be one of '+','.join(DOMAIN_METHODS))
            if not isinstance(applicant_name,str) or not applicant_name.strip():
                raise McpToolError('MCP_INVALID_ARGS','applicant_name must be a non-empty string')
            if not isinstance(applicant_email,str) or '@' not in applicant_email:
                raise McpToolError('MCP_INVALID_ARGS','applicant_email must contain @')
            if not isinstance(applicant_phone,str) or not applicant_phone.strip() or not re.search(r'\d',applicant_phone):
                raise McpToolError('MCP_INVALID_ARGS','applicant_phone must be a non-empty string containing digits')
        body={'cert_brand':cert_brand,'cert_type':cert_type,'domain_type':domain_type,
              'effective_time':effective_time,'order_number':order_number,
              'domain_numbers':domain_numbers,'is_auto_pay':is_auto_pay,
              'apply':{'apply_domain':apply_domain,'domain_method':domain_method,
                       'applicant_name':applicant_name,'applicant_email':applicant_email,
                       'applicant_phone':applicant_phone} if wants_apply else None}
        digest=self.intent_digest('POST','scm:certificates/subscribe',body)
        if not confirm:
            apply_view=None if not wants_apply else {
                'apply_domain':apply_domain,'domain_method':domain_method,
                'applicant_name':applicant_name,'applicant_email':applicant_email,
                'applicant_phone':applicant_phone,
                'note':'域名验证：DNS 在解析商添加 TXT 记录、File 在网站根目录放置验证文件、Email 由 CA 发送验证邮件；公网 IP 证书仅支持 File'}
            return {'status':'preview','execution':'not_executed',
                    'params':{'cert_brand':cert_brand,'cert_type':cert_type,'domain_type':domain_type,
                              'effective_time':effective_time,'order_number':order_number,
                              'domain_numbers':domain_numbers,'is_auto_pay':is_auto_pay},
                    'billing':{'免费档':'DV_SSL_CERT_BASIC 免订单费',
                               '付费档':'按 品牌×类型×年限×张数 计费',
                               '支付':'is_auto_pay=true 自动扣款；false 生成待支付订单，须控制台/费用中心支付后交付'},
                    'apply':apply_view,
                    'impact':['购买产生计费（免费档除外），is_auto_pay=false 的待支付订单逾期未付自动取消',
                              '证书为账号级 SCM 资源，须完成申请（提交域名与申请人信息）才能签发',
                              '申请需域名验证（DNS/File/Email），公网 IP 证书仅支持 File'],
                    **self.plans.issue(digest)}
        if os.getenv('SUPABASE_ENABLE_WRITES')!='true' or os.getenv('HUAWEICLOUD_MCP_READ_ONLY','false').lower()=='true':
            raise McpToolError('MCP_READ_ONLY','Writes are disabled')
        self.plans.claim(plan_id,digest)
        try:
            data=await self.koocli.call('SCM','SubscribeCertificate',
                                        {'agree_privacy_protection':True,'cert_brand':cert_brand,
                                         'cert_type':cert_type,'domain_type':domain_type,
                                         'domain_numbers':domain_numbers,'effective_time':effective_time,
                                         'order_number':order_number,'is_auto_pay':is_auto_pay})
        except BaseException:
            self.plans.finish(plan_id,'unknown')
            raise RecoveryError('MCP_SDK_ERROR','SCM subscribe result unknown','submission_unknown',
                                'Inspect the plan and the SCM certificate list; never blindly repeat a purchase.',plan_id) from None
        self.plans.finish(plan_id,'accepted')
        order_id=self._find_first(data,('order_id','orderId'))
        certificate_id=self._find_first(data,('certificate_id','cert_id','id'))
        billing_note=self._billing_note(cert_type,is_auto_pay,order_id)
        result={'status':'subscribed','subscribe_response':self._limited(data),
                'order_id':order_id,'certificate_id':certificate_id,
                'apply':{'attempted':False,
                         'reason':'未提供申请块：证书已购，待提交申请（可经控制台或后续版本工具完成）'},
                'note':billing_note+'；证书为账号级 SCM 资源，须完成申请（提交域名与申请人信息）才能签发',
                'plan_id':plan_id}
        if not wants_apply:return result
        if not certificate_id:
            certificate_id=await self._locate_paid_cert(apply_domain)
        if not certificate_id:
            result['status']='subscribed_apply_unlocated'
            result['apply']={'attempted':False,'reason':UNLOCATED_NOTE}
            result['note']=billing_note+'；'+UNLOCATED_NOTE
            return result
        result['certificate_id']=certificate_id
        try:
            applied=await self.koocli.call('SCM','ApplyCertificate',
                                           {'certificate_id':certificate_id,'agree_privacy_protection':True,
                                            'domain':apply_domain,'domain_method':domain_method,
                                            'applicant_name':applicant_name,'applicant_email':applicant_email,
                                            'applicant_phone':applicant_phone})
        except Exception as exc:
            message=str(exc)[:200] or exc.__class__.__name__
            result['status']='subscribed_apply_failed'
            result['apply']={'attempted':True,'certificate_id':certificate_id,'error':message}
            result['note']=billing_note+'；证书已购买成功，但申请提交失败，可经控制台重试申请'
            return result
        result['status']='subscribed_and_applied'
        result['apply']={'attempted':True,'certificate_id':certificate_id,'response':self._limited(applied)}
        result['note']=billing_note+'；申请已提交，等待 CA 完成域名验证后签发；签发后经 change_supabase_ssl（cert_id=证书 id）为应用启用'
        return result
