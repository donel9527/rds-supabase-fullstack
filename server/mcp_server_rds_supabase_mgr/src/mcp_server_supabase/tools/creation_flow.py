from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.creation_flow import CreationFlowService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_with_new_instance(request_ref: str, public_access_cidr: str = 'auto', confirm: bool = False, plan_id: str | None = None) -> dict:
        """Create the application together with its managed PG instance - the recommended scenario, strictly executing the arrangement's newly_instance resource preparation.

        Resource preparation is automatic: two dedicated security groups are provisioned
        (application group - 8443 ingress with public_access_cidr choosing auto (detected
        device CIDR, default), open (0.0.0.0/0 via KooCLI) or a custom bounded CIDR, plus
        5432 egress to the chosen subnet; database group - 5432 ingress from that subnet),
        an OBS bucket is ensured when the request enables storage (existing kept, missing
        created per the fixed private/standard/multi-AZ/block-public-access rules, renamed
        and backfilled on collision), and every prepared identifier is backfilled into the
        request before one submission - no manual security_group_id, one-shot success.
        All parameters and secrets live in the protected local request file (request_ref).
        Preview with confirm=false; submit once with confirm=true plus the returned plan_id.
        The response echoes the application/instance identifiers and workflow ids, reminds
        the caller to track creation status, and carries the EIP automation follow-ups for
        after completion. The response is chart-rendered.
        """
        result = await CreationFlowService().with_new_instance(request_ref, public_access_cidr, confirm, plan_id)
        result['visual'] = visual.render_creation_flow(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_link_exist_instance(request_ref: str, public_access_cidr: str = 'auto', confirm: bool = False, plan_id: str | None = None) -> dict:
        """Attach an existing PG instance to a new application - the existed_instance scenario, strictly executing the arrangement's resource preparation.

        The attachable instance is verified, one dedicated application security group is
        provisioned (8443 ingress with public_access_cidr choices plus 5432 egress to the
        instance's subnet) and injected; the instance's own security group stays untouched.
        An OBS bucket is ensured when the request enables storage (existing kept, missing
        created per the fixed rules, renamed and backfilled on collision). Prepared
        identifiers are backfilled before one submission. Parameters and secrets live in
        the protected local request file. Preview with confirm=false; submit once with
        confirm=true plus the returned plan_id. The response echoes the application
        identifiers and workflow ids with tracking and EIP automation follow-ups, and is
        chart-rendered.
        """
        result = await CreationFlowService().link_exist_instance(request_ref, public_access_cidr, confirm, plan_id)
        result['visual'] = visual.render_creation_flow(result)
        return result
