from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.ledger import ResourceLedger
from mcp_server_supabase.service.creation_flow import CreationFlowService


def register(server):

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_with_new_instance(request_ref: str, public_access_cidr: str = 'auto', confirm: bool = False, plan_id: str | None = None) -> dict:
        """创建 Supabase 应用并新建托管 PostgreSQL 实例（推荐场景），两段式提交。安全组与 OBS 桶自动准备、标识回填后一次提交——请求文件不得携带 security_group_id（顶层与 managed_instance 均同，携带即拒绝并提示删除；自备安全组创建后经 change_supabase_security_group 换绑）；public_access_cidr 三选一定义 8443 入方向来源。响应含 workflow id 跟踪与 visual 图表。"""
        result = await CreationFlowService(ledger=ResourceLedger()).with_new_instance(request_ref, public_access_cidr, confirm, plan_id)
        result['visual'] = visual.render_creation_flow(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def create_supabase_link_exist_instance(request_ref: str, public_access_cidr: str = 'auto', confirm: bool = False, plan_id: str | None = None) -> dict:
        """挂载已有 PostgreSQL 实例并创建 Supabase 应用，两段式提交。自动准备应用安全组并注入，实例自身安全组不动；请求文件不得携带 security_group_id（携带即拒绝并提示删除）；准备标识回填后一次提交，参数与密钥均在本地请求文件。响应含 workflow id 与 visual 图表。"""
        result = await CreationFlowService(ledger=ResourceLedger()).link_exist_instance(request_ref, public_access_cidr, confirm, plan_id)
        result['visual'] = visual.render_creation_flow(result)
        return result
