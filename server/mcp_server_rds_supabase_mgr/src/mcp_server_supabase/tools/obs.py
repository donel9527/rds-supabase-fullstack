from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.obs import ObsService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_supabase_storage(app_name: str | None = None) -> dict:
        """Present the OBS acquisition options once the storage need is confirmed: reuse an existing bucket (private buckets first, public ones flagged with anonymous-access risk) or create a new one (recommended and the default - fully isolated, safe).

        AK/SK prefer the environment credentials; temporary credentials (SecurityToken)
        are detected and the user is explicitly prompted for persistent AK/SK, which are
        the only kind that keeps the application accessing OBS after expiry. Includes an
        OBS read test with the current credentials and, for the new-bucket option, the
        complete parameter specification (name derived from the application, standard
        storage, private, multi-AZ default / single-AZ optional, public access blocked,
        region from the current project, default enterprise project).
        """
        result = await ObsService().discover_storage(app_name)
        result['visual'] = visual.render_storage(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_new_obs(app_name: str, redundancy: str = 'multi_az', confirm: bool = False, plan_id: str | None = None) -> dict:
        """Create a brand-new private OBS bucket for the Supabase application's storage needs (images, videos, large files) - the storage_component target - via KooCLI.

        The bucket name derives from the application/business name (sanitized, supabase-
        prefix) with a short-uuid suffix retried on collision; storage class fixed to
        standard, bucket type fixed to private; data redundancy is a parameter (multi_az
        default, single_az optional); public access is blocked (default on, fixed and
        not modifiable); region follows the current project automatically and the
        enterprise project defaults to default. Preview with confirm=false, submit once
        with confirm=true plus the returned plan_id. The response carries a
        chart-rendered visual.
        """
        result = await ObsService().create_bucket(app_name, redundancy, confirm, plan_id)
        result['visual'] = visual.render_storage(result)
        return result
