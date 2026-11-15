from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.ssl_cert import SslCertService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_ssl_certificates(limit: int = 50) -> dict:
        """查询账号下的 SCM SSL 证书清单，供挑选与核对启用证书用。证书为账号级资源、SCM 为全局服务，经 KooCLI 通道且 region 固定 cn-north-4；status 按实况透传（PAID=已购待申请、ISSUED=已签发等）；change_supabase_ssl 的 cert_id 即此 id；limit 每页 1-100，默认 50。"""
        result = await SslCertService().list_certificates(limit)
        result['visual'] = visual.render_ssl_certificates(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def purchase_supabase_ssl_cert(cert_brand: str, cert_type: str, domain_type: str, effective_time: int, order_number: int = 1, domain_numbers: int = 1, is_auto_pay: bool = False, apply_domain: str | None = None, domain_method: str | None = None, applicant_name: str | None = None, applicant_email: str | None = None, applicant_phone: str | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """购买一张 SCM SSL 证书（可同请求提交申请），经 KooCLI 通道且 region 固定 cn-north-4。必填 cert_brand/cert_type/domain_type/effective_time；domain_numbers 随 domain_type 校验（单域名/泛域名=1，多域名 2-100）；申请块（apply_domain+domain_method+申请人姓名/邮箱/电话）要么全空要么全给，domain_method 取 DNS/File/Email，公网 IP 证书仅支持 File；免费档 DV_SSL_CERT_BASIC 免订单费，付费档按 品牌×类型×年限×张数 计费，is_auto_pay=false 生成待支付订单须控制台/费用中心支付。preview（confirm=false）仅本地校验并签发 plan_id；confirm=true+plan_id 一次提交：先 SubscribeCertificate，带申请块时再凭提取或回查定位的 certificate_id 调 ApplyCertificate，定位不到不硬失败并明确说明后续动作。"""
        result = await SslCertService().purchase_cert(cert_brand, cert_type, domain_type, effective_time, order_number, domain_numbers, is_auto_pay, apply_domain, domain_method, applicant_name, applicant_email, applicant_phone, confirm, plan_id)
        result['visual'] = visual.render_ssl_purchase(result)
        return result
