from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.obs import ObsService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_supabase_storage(app_name: str | None = None) -> dict:
        """查询 OBS 存储接入选项（复用既有桶或新建桶两选择）。检测临时凭证并提示需持久 AK/SK；含当前凭证读测试，新建桶方案附固定私有规格。响应含 visual 图表。"""
        result = await ObsService().discover_storage(app_name)
        result['visual'] = visual.render_storage(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_new_obs(app_name: str, redundancy: str = 'multi_az', confirm: bool = False, plan_id: str | None = None) -> dict:
        """为 Supabase 应用新建私有 OBS 桶，两段式提交。规格固定：私有类型、标准存储、阻止公共访问、默认多 AZ；桶名由应用名派生，重名自动加短 uuid 重试。响应含 visual 图表。"""
        result = await ObsService().create_bucket(app_name, redundancy, confirm, plan_id)
        result['visual'] = visual.render_storage(result)
        return result
