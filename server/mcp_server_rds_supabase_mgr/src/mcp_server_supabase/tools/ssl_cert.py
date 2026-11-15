from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.ssl_cert import SslCertService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_ssl_certificates(limit: int = 50) -> dict:
        """查询账号下 SCM SSL 证书清单（状态与域名维度）。证书为账号级资源，SCM 为全局服务、region 固定 cn-north-4；返回的 cert_id 即 change_supabase_ssl 的入参。响应含 visual 图表。"""
        result = await SslCertService().list_certificates(limit)
        result['visual'] = visual.render_ssl_certificates(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def purchase_supabase_ssl_cert(cert_brand: str, cert_type: str, domain_type: str, effective_time: int, order_number: int = 1, domain_numbers: int = 1, is_auto_pay: bool = False, apply_domain: str | None = None, domain_method: str | None = None, applicant_name: str | None = None, applicant_email: str | None = None, applicant_phone: str | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """购买一张 SCM SSL 证书，两段式提交，可同请求提交证书申请。免费档 DV_SSL_CERT_BASIC 推荐；纯 EIP 公网 IP 证书仅支持文件验证。响应含订单与申请状态、visual 图表。"""
        result = await SslCertService().purchase_cert(cert_brand, cert_type, domain_type, effective_time, order_number, domain_numbers, is_auto_pay, apply_domain, domain_method, applicant_name, applicant_email, applicant_phone, confirm, plan_id)
        result['visual'] = visual.render_ssl_purchase(result)
        return result
