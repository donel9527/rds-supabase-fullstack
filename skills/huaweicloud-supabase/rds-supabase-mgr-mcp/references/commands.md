# 工具全表（58 个 MCP 工具）

> 何时读：核对工具名、用途与风险分级时读本表；场景内用法见 SKILL.md 各场景章节与[场景手册](scenarios.md)。风险以运行时声明为准；全部写工具执行预览/确认双段，敏感字段只经 `request_ref` 别名引用。


58 个工具按六组列出；风险以运行时声明为准。全部写工具执行预览/确认双段，敏感字段只经 `request_ref` 别名引用。

**编排与发现（READ）**

| 工具 | 用途 | 风险 |
|---|---|---|
| `plan_supabase_creation_arrangement` | 端到端创建编排与参数基线 | READ |
| `discover_supabase_create_basic_options` | 应用要素发现，规格分组展示 | READ |
| `discover_db_instance_for_create` | 实例来源发现，规格分组展示 | READ |
| `discover_network_for_create` | 网络选址与安全组规格 | READ |
| `discover_supabase_storage` | OBS 获取两选择与凭证检测 | READ |
| `list_ssl_certificates` | 盘点已有 SSL 证书 | READ |
| `list_supabase_flavors_with_azs` | 查应用规格与可用区售卖 | READ |
| `list_db_instance_engine_versions` | 查托管实例引擎版本 | READ |
| `list_db_instance_flavors_with_azs` | 查实例规格与可用区售卖 | READ |
| `list_db_instance_storage_types` | 查磁盘类型与兼容规格 | READ |
| `list_supabase_manageable_instances` | 查可挂载的 PG 实例 | READ |
| `plan_supabase_ssl` | SSL 切换前规划评估 | READ |
| `get_supabase_capabilities` | 查看服务能力与操作边界 | READ |

**创建（DANGEROUS）**

| 工具 | 用途 | 风险 |
|---|---|---|
| `create_supabase_with_new_instance` | 新建实例场景创建（推荐） | DANGEROUS |
| `create_supabase_link_exist_instance` | 挂载已有实例创建应用 | DANGEROUS |
| `create_supabase_eip` | EIP 空闲优先采购（按需计费固定；计费方式 bandwidth/traffic 与带宽大小均由用户决策，收费项） | DANGEROUS |
| `create_supabase_new_obs` | 新建私有 OBS 桶 | DANGEROUS |

**绑定与变更（含安全组工具：`list_supabase_security_groups`、`show_supabase_security_group`、`create_supabase_security_group`、`add_supabase_security_group_rule`、`delete_supabase_security_group_rule`、`delete_supabase_security_group`、`change_supabase_security_group`）**

| 工具 | 用途 | 风险 |
|---|---|---|
| `bind_supabase_eip` | EIP 首次绑定（应用级 public-eip） | DANGEROUS |
| `change_supabase_eip` | 绑定或解绑 EIP | WRITE |
| `change_supabase_ssl` | 开关应用 SSL | WRITE |
| `purchase_supabase_ssl_cert` | 两段式购买并申请证书 | DANGEROUS |
| `change_supabase_application_password` | 改应用登录密码，不涉实例 | DANGEROUS |
| `update_supabase_storage` | 对接或轮换 OBS 存储 | WRITE |
| `update_supabase_auth_flags` | 开关注册与匿名访问 | WRITE |
| `update_supabase_auth_config` | 配置邮箱/GitHub 登录与模板 | WRITE |
| `reset_supabase_api_key` | 重置 Key，旧 Key 渐进失效 | DANGEROUS |
| `start_supabase_application` | 启动已停止的应用 | DANGEROUS |
| `stop_supabase_application` | 停止应用，实例继续计费 | DANGEROUS |
| `restart_supabase_application` | 重启运行中的应用 | DANGEROUS |
| `stop_supabase_managed_instance` | 停托管实例，VM 停计费 | DANGEROUS |
| `start_supabase_managed_instance` | 开启已停止的托管实例 | DANGEROUS |
| `restart_supabase_managed_instance` | 重启托管实例，低峰执行 | DANGEROUS |
| `list_supabase_security_groups` | 浏览安全组列表 | READ |
| `show_supabase_security_group` | 查安全组详情与规则 | READ |
| `create_supabase_security_group` | 建专用组并打双标签 | WRITE |
| `add_supabase_security_group_rule` | 新增规则，拒收全 0 入 | DANGEROUS |
| `delete_supabase_security_group_rule` | 删规则收窄开放面 | DANGEROUS |
| `delete_supabase_security_group` | 删组，标签门防误删 | DANGEROUS |
| `change_supabase_security_group` | 换绑安全组，多组全量替换 | DANGEROUS |

**查询与跟踪（READ）**

| 工具 | 用途 | 风险 |
|---|---|---|
| `list_supabase_applications` | 分页浏览应用，可过滤排序 | READ |
| `show_supabase_application` | 查应用详情与接入素材 | READ |
| `show_supabase_managed_instance` | 查托管实例详情与状态 | READ |
| `show_supabase_creation_progress` | 跟踪应用创建全阶段 | READ |
| `show_supabase_auth_config` | 查认证配置基线 | READ |
| `list_supabase_api_keys` | 查 Key 元数据，不返回值 | READ |
| `show_operation_job_status` | 查询异步任务状态 | READ |
| `wait_operation_job_complete` | 有界轮询任务至终态 | READ |
| `get_supabase_order` | 查订单状态金额与明细 | READ |

**交付（受控）**

| 工具 | 用途 | 风险 |
|---|---|---|
| `deliver_supabase_api_key` | Key 值落受保护本地文件 | 受控 |

**订单与删除（DANGEROUS）**

| 工具 | 用途 | 风险 |
|---|---|---|
| `pay_supabase_order` | 核对后余额支付订单 | DANGEROUS |
| `cancel_supabase_order` | 取消待支付订单 | DANGEROUS |
| `delete_supabase_application` | 删应用，实例去留必选；状态不限（正常/已停止/已移除均可删），仅拦进行中操作；级联删实例仅限按需（包周期整体拒绝，改 false 后控制台退订） | DANGEROUS |
| `delete_supabase_managed_instance` | 单独拆除托管实例（仅按需；包周期走控制台退订） | DANGEROUS |
| `delete_supabase_eip` | 删 EIP（KooCLI DeletePublicip），应用删除后按需清理；引用中拦截、绑定中须先解绑、删除即停保有费 | DANGEROUS |
| `clean_supabase_obs_ws` | 清空并删除桶根目录下应用 ID 子文件夹（不动桶与其他目录；存活应用 ID 拦截） | DANGEROUS |
| `delete_supabase_obs` | 删 OBS 桶（KooCLI obsutil）；引用中拦截、非空拦截（先清各应用目录）、桶不存在幂等返回 | DANGEROUS |
| `show_supabase_residuals` | 残留盘点（资源记录圈定+实时核对，场景十一入口）；保留桶高危计费提醒、实例保留时数据库组不可删 | READ |
| `cleanup_supabase_residuals` | 一键清理四类残留（四个必选布尔开关、单计划逐项守卫复检、被拦项跳过如实报告） | DANGEROUS |
