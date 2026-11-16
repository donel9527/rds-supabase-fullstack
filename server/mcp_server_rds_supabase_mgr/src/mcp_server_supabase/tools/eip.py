from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.eip import EipService
from mcp_server_supabase.service.eip_bind import EipBindService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_eip(prefer_idle: bool = True, charge_mode: str = 'postPaid', bandwidth_size_mbps: int | None = None, name: str | None = None, period_type: str | None = None, period_num: int | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """为 Supabase 应用采购公网入口 EIP，两段式提交。空闲优先：先列出未绑定 EIP 供选用（无需带宽参数），无空闲才新建；新建带宽大小由用户决策（5-1000 Mbps 整数，无默认推荐，缺失即拒）；采购基线为按需计费加全动态 BGP 独享带宽。响应含 visual 图表。"""
        result = await EipService().ensure_publicip(prefer_idle, charge_mode, bandwidth_size_mbps, name, period_type, period_num, confirm, plan_id)
        result['visual'] = visual.render_eip(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def bind_supabase_eip(instance_id: str, public_ip_id: str, public_ip: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """为 Supabase 应用绑定 EIP，两段式提交，经 RDS AttachEip 通道。三重校验：instance_id 须为本环境 in32 应用 ID 且真实存在、public_ip_id 为规范 UUID、public_ip 为合法 IPv4。"""
        result = await EipBindService().bind_public_ip(instance_id, public_ip_id, public_ip, confirm, plan_id)
        rows = [[result.get('instance_id'), (result.get('eip') or {}).get('public_ip'),
                 (result.get('eip') or {}).get('public_ip_id'), result.get('status')]]
        result['visual'] = visual.block('EIP 绑定', visual.table(['实例 ID（in32）', 'EIP 地址', 'EIP ID', '状态'], rows))
        return result
