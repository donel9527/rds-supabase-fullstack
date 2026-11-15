from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.eip import EipService
from mcp_server_supabase.service.eip_bind import EipBindService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_eip(prefer_idle: bool = True, charge_mode: str = 'postPaid', bandwidth_size_mbps: int = 300, name: str | None = None, period_type: str | None = None, period_num: int | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Provision the public entry EIP for a Supabase application, idle-first. Purchase baseline: pay-per-use recommended (prepaid needs period_type month/year and period_num, and returns a console order), dedicated full-dynamic-BGP bandwidth (publicip.type=5_bgp, share_type PER) sized 5-1000M with 300M recommended. prefer_idle=true first lists unbound EIPs so the user picks one (returned directly, nothing created); with none idle, or prefer_idle=false, it previews (confirm=false) then creates via KooCLI - a newly created postPaid EIP is tagged USAGE_FOR=Supabase应用公网访问，自动创建的. The response carries a chart-rendered visual for user review."""
        result = await EipService().ensure_publicip(prefer_idle, charge_mode, bandwidth_size_mbps, name, period_type, period_num, confirm, plan_id)
        result['visual'] = visual.render_eip(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def bind_supabase_eip(instance_id: str, public_ip_id: str, public_ip: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Bind an EIP to a Supabase application through the RDS AttachEip API. Strict validation prevents mistaken and stray operations: instance_id must be this environment's Supabase application ID (in32 suffix, then verified to exist in the application list), public_ip_id a canonical UUID, public_ip a valid IPv4 address. Preview with confirm=false; submit once with confirm=true plus the returned plan_id. After binding, sync api_external_url via update_supabase_auth_config and probe the address."""
        result = await EipBindService().bind_public_ip(instance_id, public_ip_id, public_ip, confirm, plan_id)
        rows = [[result.get('instance_id'), (result.get('eip') or {}).get('public_ip'),
                 (result.get('eip') or {}).get('public_ip_id'), result.get('status')]]
        result['visual'] = visual.block('EIP 绑定', visual.table(['实例 ID（in32）', 'EIP 地址', 'EIP ID', '状态'], rows))
        return result
