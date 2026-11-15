from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase.service.planning import PlanningService
from mcp_server_supabase import visual


def register(server):
    service = PlanningService()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def get_supabase_capabilities() -> dict[str, object]:
        """查询本 MCP 的能力范围声明（传输模式、执行策略、已实现操作与六大场景契约）。纯离线声明，不探测云状态；会话应最先调用以确认操作边界。"""
        return service.capabilities()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def plan_supabase_creation_arrangement(manage_type: str, az_code: str | None = None, mode: str | None = None, page: int = 1, instance_id: str | None = None, detect_access_ip: bool = False, needs_storage: bool | None = None, needs_public_access: bool | None = None, needs_ssl: bool | None = None, needs_email_login: bool | None = None, needs_github_login: bool | None = None) -> dict[str, object]:
        """规划 Supabase 应用端到端创建编排与参数基线（编排流程、网络、托管实例规格与意图分支），仅规划不创建资源。SSL 与公网 EIP 为独立配置模块，不在编排内。响应含 visual 图表。"""
        result = await service.arrangement(manage_type, az_code, mode, page, instance_id, detect_access_ip, needs_storage, needs_public_access, needs_ssl, needs_email_login, needs_github_login)
        if result.get('status') == 'arrangement_baseline':
            result['visual'] = visual.render_arrangement(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def plan_supabase_ssl(enable_ssl: bool = True) -> dict[str, object]:
        """规划 SSL 启停切换方案，不执行变更。纯本地规划、无云调用；返回规划状态与缺失契约，供 change_supabase_ssl 正式提交前核对。"""
        return await service.ssl(enable_ssl)
