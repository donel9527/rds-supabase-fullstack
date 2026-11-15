from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase.service.planning import PlanningService


def register(server):
    service = PlanningService()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def get_supabase_capabilities() -> dict[str, object]:
        """List the available capabilities of the RDS Supabase management MCP. Run first; returns an offline scope declaration (transport mode, execution policies, implemented operations, six scenario contracts), never cloud status."""
        return service.capabilities()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def plan_supabase_creation_arrangement(manage_type: str, az_code: str | None = None, mode: str | None = None, page: int = 1, instance_id: str | None = None, detect_access_ip: bool = False, needs_storage: bool | None = None, needs_public_access: bool | None = None, needs_ssl: bool | None = None, needs_email_login: bool | None = None, needs_github_login: bool | None = None) -> dict[str, object]:
        """Design the end-to-end, scenario-based arrangement for creating a Supabase application: an orchestration flow plus a consolidated parameter baseline, assembled live from the three discovery tools - Supabase basics (discover_supabase_create_basic_options), managed instance (discover_db_instance_for_create) and network control (discover_network_for_create).

        manage_type is the definitive user conclusion required up front: newly_instance (recommended and
        the default - the managed PG is created together with the application) or existed_instance
        (attach an existing PG; candidates are listed paginated at 20 per page with their current
        action locks so instances in a restart/upgrade/change can be excluded, and instance_id fixes
        that instance and its network). az_code enables the live basics module; mode shapes the new
        instance (Single recommended); detect_access_ip probes the current-device egress CIDR for the
        8443 ingress options. The arrangement carries the EIP purchase baseline (pay-per-use
        recommended; dedicated full-dynamic-BGP bandwidth 5-1000M, 300M recommended) and a
        step-numbered creation_flow plus post-creation flow to follow strictly 1:1. Optional intents
        (needs_storage/needs_public_access/needs_ssl/needs_email_login/needs_github_login): omitted =
        open decision point, true = plan the branch, false = plan the exclusion. Planning only -
        nothing is created here.
        """
        return await service.arrangement(manage_type, az_code, mode, page, instance_id, detect_access_ip, needs_storage, needs_public_access, needs_ssl, needs_email_login, needs_github_login)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def plan_supabase_ssl(enable_ssl: bool = True) -> dict[str, object]:
        """Plan SSL selection without cloud calls. Args: enable_ssl defaults true; false plans disabling. Returns planning status and missing contracts."""
        return await service.ssl(enable_ssl)
