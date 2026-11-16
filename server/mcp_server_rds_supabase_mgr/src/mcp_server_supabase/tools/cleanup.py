from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase.service.cleanup import CleanupService


def register(server):
    service = CleanupService()

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_eip(public_ip_id: str, public_ip: str | None = None,
                                  confirm: bool = False, plan_id: str | None = None) -> dict:
        """删除 EIP（KooCLI EIP DeletePublicip），用于 Supabase 应用删除后的关联 EIP 资源清理，供业务方按需显式使用或自动联动触发。两段式提交：提交前实读 EIP 校验身份，可选地址交叉核对；全量扫描应用清单，仍被存活应用公网地址引用的 EIP 拦截；已绑定资源的 EIP 由后端拒绝（先解绑再删）。删除不可逆且立即停止 IP 保有费。"""
        return await service.delete_eip(public_ip_id, public_ip, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_obs(bucket: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """删除 OBS 桶（KooCLI 内嵌 obsutil rm），用于 Supabase 应用删除后的关联 OBS 桶资源清理，供业务方按需显式使用或自动联动触发。两段式提交：桶不存在直接返回 already_absent；全量扫描应用清单，仍被存活应用 storage_component 引用的桶拦截；非空桶拦截（防误删共享桶）——先用 clean_supabase_obs_ws 清理各应用数据目录、其余对象人工核对后再删。删除不可逆。"""
        return await service.delete_bucket(bucket, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def clean_supabase_obs_ws(bucket: str, application_id: str,
                                    confirm: bool = False, plan_id: str | None = None) -> dict:
        """清理 OBS 桶中 Supabase 应用的数据目录（仅数据空间，不删桶），用于应用删除后的关联资源清理，供业务方按需显式使用或自动联动触发。删除范围严格限定为桶根目录下名称等于应用 ID 的目录（obs://<bucket>/<application_id>/），桶与其他任何目录不受影响；删除前缀仅由通过校验的桶名与 in32 规范应用 ID 构造。仍存活应用的 ID 会被拦截（先删应用再清目录）。目录不存在或为空返回 already_clean。"""
        return await service.clean_workspace(bucket, application_id, confirm, plan_id)
