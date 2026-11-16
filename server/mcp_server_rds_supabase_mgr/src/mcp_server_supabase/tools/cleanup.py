from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase.service.cleanup import CleanupService
from mcp_server_supabase.service.ledger import ResourceLedger


def register(server):
    service = CleanupService(ledger=ResourceLedger())

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
        """清理 OBS 桶中 Supabase 应用的数据目录（仅数据空间，不删桶），用于应用删除后的关联资源清理，供业务方按需显式使用或自动联动触发。删除对象是桶根目录下名称等于应用 ID 的子文件夹：先清空其全部内容，再删除该文件夹本身（桶与其他任何目录不受影响）；应用 ID 强制 in32 规范格式，删除范围不接受任何调用方路径片段。仍存活应用的 ID 会被拦截（先删应用再清目录）。目录不存在或为空返回 already_clean。"""
        return await service.clean_workspace(bucket, application_id, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_residuals(application_id: str) -> dict:
        """查询一个应用的关联资源残留清单（场景七入口）：资源记录圈定范围 + 云端实时核对——EIP（是否仍在、地址、流程自动创建与否及删除建议）、OBS 桶（是否存在、删除建议）与应用数据目录（对象数量、保留桶时的高危持续计费提醒）、安全组（应用组/数据库组、实例保留时数据库组不可删）、托管实例现状。附全量清理一键选项说明。资源记录无记录时如实拒绝猜测范围。"""
        return await service.residuals(application_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def cleanup_supabase_residuals(application_id: str,
                                         cleanup_eip: bool,
                                         cleanup_obs_bucket: bool,
                                         cleanup_obs_workspace: bool,
                                         cleanup_security_groups: bool,
                                         confirm: bool = False,
                                         plan_id: str | None = None) -> dict:
        """一键清理一个应用的关联资源（场景七）：四个类别开关均为必选布尔（全 True 即按残留清单一次清理全部，False 保留该类）。单次确认、单计划；执行时逐项守卫复检（引用中拦截、非空桶拦截、存活应用目录拦截、实例保留时数据库组自动跳过并说明），被拦与失败项如实逐项报告不中断其他类别；成功项资源记录回写。部分清理使用单项工具更合适。"""
        return await service.cleanup_all(application_id, cleanup_eip, cleanup_obs_bucket,
                                         cleanup_obs_workspace, cleanup_security_groups,
                                         confirm, plan_id)
