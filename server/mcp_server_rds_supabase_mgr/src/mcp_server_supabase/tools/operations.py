from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.instance_catalog import InstanceCatalog, NetworkDiscovery, BasicOptionsDiscovery
from mcp_server_supabase.service.instance_lifecycle import lifecycle as managed_instance_lifecycle
from mcp_server_supabase.service.instance_lifecycle import show as show_managed_instance
from mcp_server_supabase.service.operations import Operations
from mcp_server_supabase.service.ledger import ResourceLedger
from mcp_server_supabase.service.security_group_set import change as change_security_group


def register(server):
    service = Operations(ledger=ResourceLedger())

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_applications(limit: int = 10, offset: int = 0,
                                         name: str | None = None,
                                         application_id: str | None = None,
                                         sort_key: str = 'created_time',
                                         sort_dir: str = 'desc') -> dict:
        """查询当前项目全部 RDS Supabase 应用，分页返回（名称模糊、ID 精确过滤）。记录已脱敏且仅含本项目 Supabase 应用；选定目标前须核对应用身份。"""
        return await service.read("applications", limit=limit, offset=offset, name=name,
                                  application_id=application_id, sort_key=sort_key,
                                  sort_dir=sort_dir)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_application(application_id: str) -> dict:
        """查询单个 RDS Supabase 应用详情（状态、SSL、公网/私网地址）。按 in32 应用 ID 精确查询；状态字段不构成完成证明，业务结果须回读资源核实。"""
        return await service.read("application", application_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_api_keys(application_id: str, limit: int = 10, offset: int = 0,
                                    status: str | None = None, key_type: str | None = None,
                                    sort_key: str = 'created_time', sort_dir: str = 'desc',
                                    key_id: str | None = None) -> dict:
        """查询应用 API Key 的元数据列表（类型、状态、时间，可过滤排序）。仅返回含 id 的元数据记录，Key 明文永不返回；获取 Key 值须经 deliver_supabase_api_key 受控交付。"""
        return await service.read("keys", application_id, limit, offset, status=status,
                                  key_type=key_type, sort_key=sort_key, sort_dir=sort_dir, key_id=key_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_auth_config(application_id: str) -> dict:
        """查询应用 Auth 配置（注册开关、跳转 URL、邮箱与 GitHub 身份源、邮件模板）。敏感凭据在任何层级均不返回；结果作为 Auth 变更预览与核对基线。"""
        return await service.read("auth", application_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_operation_job_status(job_id: str) -> dict:
        """查询单个已提交操作任务的当前状态（创建、删除、SSL、EIP 等变更通用）。仅返回任务原始状态；任务成功不等于业务完成，还须回读资源核实结果。"""
        return await service.job(job_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def wait_operation_job_complete(job_id: str, max_attempts: int = 3, interval_seconds: int = 2) -> dict:
        """在有界超时内轮询单个操作任务直至终态，用于等待任务完成。仅观察不提交、不重放、不取消；超时未达终态不代表失败，可再次轮询。"""
        return await service.wait_job(job_id, max_attempts, interval_seconds)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def change_supabase_ssl(application_id: str, enable_ssl: bool, cert_id: str | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """变更 RDS Supabase 应用的 SSL 开关，两段式提交。开启须提供证书 ID，关闭须不带证书；写入需服务端显式开启。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await service.mutate(application_id, "ssl", {"enable_ssl":enable_ssl,"cert_id":cert_id}, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def change_supabase_eip(application_id: str, is_bind: bool, public_ip_id: str | None = None, public_ip_address: str | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """变更应用 EIP 绑定，两段式提交。绑定须同时提供 EIP ID 与 IPv4 地址，解绑不带二者；变更即影响公网暴露面。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await service.mutate(application_id, "eip", {"is_bind":is_bind,"public_ip_id":public_ip_id,"public_ip_address":public_ip_address}, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_application(application_id: str, delete_managed_instance: bool | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """删除 RDS Supabase 应用，两段式提交。delete_managed_instance 必选不可默认：false 仅删应用、托管实例保留并继续计费；true 双删且实例删除不可逆。双任务受理后须分别以 job_id 跟踪。"""
        return await service.delete_application(application_id, delete_managed_instance, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_managed_instance(application_id: str, instance_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """删除应用的托管实例，两段式提交。实例须为该应用自身的 managed_instance 且无其他应用引用，经四层校验；删除不可逆、数据全毁。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await service.delete_managed_instance(application_id, instance_id, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def start_supabase_application(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """启动一个已停止的 RDS Supabase 应用，两段式提交。仅停止态应用可启动，且不会自动启动托管实例。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await service.lifecycle(application_id, "start", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def stop_supabase_application(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """停止一个运行中的 RDS Supabase 应用，两段式提交。仅运行态应用可停止；不停托管实例，实例保留并继续计费。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await service.lifecycle(application_id, "stop", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def restart_supabase_application(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """重启一个运行中的 RDS Supabase 应用，两段式提交。仅运行态应用可重启，已停止须先启动；重启期间服务短暂中断。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await service.lifecycle(application_id, "restart", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_managed_instance(application_id: str) -> dict:
        """查询应用绑定的托管实例详情（状态、规格、磁盘、可用区、进行中动作）。目标强制解析自该应用的 managed_instance 字段，不接受裸 instance_id，独立实例不适用。"""
        result = await show_managed_instance(service, application_id)
        row = result["instance"]
        result["visual"] = visual.block("托管实例详情", visual.table(
            ["实例 ID", "名称", "引擎", "状态", "规格", "磁盘", "可用区", "进行中动作"],
            [[row.get("id"), row.get("name"),
              (row.get("engine_name") or "-") + " " + (row.get("engine_version") or ""),
              result["status_note"], row.get("spec_code"),
              (row.get("volume_type") or "-") + (" " + str(row["volume_size"]) + "GB" if row.get("volume_size") is not None else ""),
              ",".join(row.get("availability_zone_ids") or []) or "-",
              ",".join(str(item) for item in (row.get("current_actions") or [])) or "-"]]))
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def stop_supabase_managed_instance(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """停止应用的托管实例，两段式提交。目标强制解析自应用的 managed_instance，不接受裸 instance_id；仅运行态可停止，VM 停止计费而 EIP、存储、备份继续计费。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await managed_instance_lifecycle(service, application_id, "stop", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def start_supabase_managed_instance(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """启动应用的托管实例，两段式提交。目标强制解析自应用的 managed_instance，不接受裸 instance_id；仅已停止且未冻结的实例可启动。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await managed_instance_lifecycle(service, application_id, "start", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def restart_supabase_managed_instance(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """重启应用的托管实例，两段式提交。目标强制解析自应用的 managed_instance，不接受裸 instance_id；仅运行态且未冻结的实例可重启，重启期间实例不可用。异步任务，受理后须以 job_id 跟踪至终态。"""
        return await managed_instance_lifecycle(service, application_id, "restart", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def change_supabase_security_group(target: str, security_group_ids: list[str],
                                             application_id: str | None = None,
                                             instance_id: str | None = None,
                                             confirm: bool = False, plan_id: str | None = None) -> dict:
        """修改安全组绑定，两段式提交。三目标互斥：应用自身、托管实例（解析自应用 managed_instance）、待挂载实例；多组为全量替换语义，未列入的既有组将被摘除。受理返回 workflowId 工作流，须跟踪至终态。"""
        return await change_security_group(service, target, security_group_ids,
                                           application_id, instance_id, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def reset_supabase_api_key(application_id: str, key_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """重置一个 API Key，两段式提交。异步任务，受理后须以 job_id 跟踪；旧 Key 渐进失效、既有客户端可能失联，新 Key 值不经本工具返回，须另行受控交付。"""
        return await service.mutate(application_id, "reset_key", {"key_id":key_id}, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def update_supabase_auth_flags(application_id: str, enable_account_sign_up: bool | None = None, enable_anonymous_users: bool | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """更新应用 Auth 注册开关（账号注册、匿名访问），两段式提交。仅修改显式传入的开关，省略项保持不变；匿名访问开关影响公网暴露面，变更前须审慎确认。"""
        body = {k:v for k,v in {"enable_account_sign_up":enable_account_sign_up,"enable_anonymous_users":enable_anonymous_users}.items() if v is not None}
        return await service.mutate(application_id, "auth_flags", body, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def change_supabase_application_password(application_id: str, request_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """修改应用登录密码（dashboard 用户 supabase），两段式提交。范围限定：仅应用登录密码，托管实例 root 密码不在范围；新密码经本地请求文件提供，修改后旧密码立即失效。"""
        return await service.mutate_reference(application_id,'password',request_ref,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def update_supabase_auth_config(application_id: str, request_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """部分更新应用 Auth 配置（跳转 URL、邮箱与 GitHub 身份源、确认邮件模板），两段式提交。敏感字段一律经本地请求文件提供、不经工具参数；省略字段保持不变。"""
        return await service.mutate_reference(application_id,'auth_config',request_ref,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def update_supabase_storage(application_id: str, request_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """配置应用 OBS 存储对接，两段式提交。凭据经本地请求文件提供，首次启用须全量桶与 AK/SK；任务受理不等于对接完成，须跟踪并回读核实。"""
        return await service.mutate_reference(application_id,'storage',request_ref,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_flavors_with_azs(az_code: str, mode: str) -> dict:
        """查询指定可用区与 Single/Ha 模式下可售的 Supabase 应用规格（各规格附支持的可用区清单）。兼作可用区选择依据；不含默认值与价格信息。"""
        return await service.creation_candidates('flavors',az_code,mode)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_manageable_instances() -> dict:
        """查询本环境下可挂载到 Supabase 应用的 PG 实例候选清单。仅列候选，候选存在不代表创建就绪，能否挂载须按创建流程另行逐项校验。"""
        return await service.creation_candidates('manageable')

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_creation_progress(application_id: str, application_job_id: str,
                                              instance_job_id: str | None = None,
                                              instance_id: str | None = None) -> dict:
        """查询一次应用创建的端到端进度（实例与应用两阶段任务）。返回阶段判定：实例创建中、应用创建中、成功，或失败并指明失败阶段。"""
        return await service.creation_progress(application_id, application_job_id, instance_job_id, instance_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def deliver_supabase_api_key(application_id: str, key_id: str, delivery_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """将选定的 API Key 交付至运营方配置的受保护本地文件，两段式提交。红线：Key 值只写入该本地文件，永不进入对话、工具参数或输出；禁止用 Agent 工具读取交付文件。"""
        return await service.deliver_key(application_id,key_id,delivery_ref,confirm,plan_id)

    catalog = InstanceCatalog()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_db_instance_engine_versions() -> dict:
        """查询新建托管实例场景可用的 PostgreSQL 引擎版本清单。仅返回版本列表，规格与存储类型另行查询；无明确低版本需求时建议取最高版本。"""
        return await catalog.list_engine_versions()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_db_instance_flavors_with_azs(version_name: str | None = None) -> dict:
        """查询新建托管实例场景的 PostgreSQL 实例规格（可按主版本过滤）。各规格附可用区售卖状态，兼作可用区可用性来源。"""
        return await catalog.list_flavors(version_name)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_db_instance_storage_types(version_name: str, ha_mode: str) -> dict:
        """查询新建托管实例场景可用的存储类型，须按引擎版本与部署模式（Single/Ha）过滤。不同版本与模式下可用磁盘类型不同，须先取版本与规格再定存储。"""
        return await catalog.list_storage_types(version_name, ha_mode)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_supabase_create_basic_options(az_code: str) -> dict:
        """查询指定可用区的应用创建基础选项（引擎版本、Single/Ha 支持、可售规格、名称/密码/存储默认值、安全组策略）。仅覆盖应用自身字段，只做发现不创建任何资源。"""
        result = await BasicOptionsDiscovery().discover(az_code)
        result['visual'] = visual.render_basic_options(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_network_for_create(scenario: str, availability_zone: str | None = None, instance_id: str | None = None, detect_access_ip: bool = False) -> dict:
        """查询应用创建的网络选址与安全组规划（按新建/挂载实例场景）。输出应用组与数据库组的规则配置及后续执行步骤；仅规格说明，不创建任何资源。"""
        network = NetworkDiscovery()
        result = await network.discover_network_for_create(scenario, availability_zone, instance_id, detect_access_ip)
        result['visual'] = visual.render_network(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_db_instance_for_create(scenario: str, mode: str | None = None, instance_id: str | None = None) -> dict:
        """查询应用创建的托管实例取数需求（按新建/挂载场景）。新建返回版本、规格、存储类型与推荐值，挂载返回可挂载候选及实例详情；只读发现，不创建不变更。"""
        result = await catalog.discover_db_instance_for_create(scenario, mode, instance_id)
        result['visual'] = visual.render_db_instance(result)
        return result
