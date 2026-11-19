# 场景手册（执行详版）

SKILL.md 教链路；本文件存细节。每个场景给出"步骤/工具/参数/校验点"操作表与补充契约，执行复杂场景或排障时加载，不必全读。字段级秘密契约见 [本地请求与字段契约](local-requests.md)。

## 通用流程（十步）

理解要求 → 定位目标 → 查询必要状态 → 对照能力说明要求覆盖 → 展示方案 → 用户确认 → 执行一次 → 查询任务 → 回查资源 → 分层说明结果（受理/任务/资源/业务，未验证的项如实标注）。

先查工具列表与能力，按实际提供的工具契约调用，不编造工具名。

## 通用异常分支

| 事件 | 必须做 | 不得做 |
|---|---|---|
| 创建含未支持字段 | 说明是否必要、是否独立后置操作；必要条件未满足暂停 | 删除该要求后直接创建 |
| 用户调整范围 | 重做方案并确认，旧计划在可用时取消 | 继续用旧 plan_id |
| 预览后取消 | 预览不提交即作废（10 分钟过期），无需操作 | 宣称云端已撤销 |
| 已提交后取消 | 查询记录/任务，解释任务可能继续 | 调另一个写工具模拟取消 |
| 缺工具/未知契约 | 明确能力缺口及可完成部分 | 拼 HTTP 请求、借 Shell 执行 |
| 202 受理 | 报告已受理、保留 job/plan 标识 | 宣布完成 |
| 超时/结果不明 | 查本地执行记录和资源，停止重放 | 换身份/换目录绕过幂等 |
| 多步部分成功 | 列出已完成与剩余项，清理另行确认 | 删除用户原有资源 |
| 获取明文请求 | 仅在可信展示能力可用且获授权时执行 | 把明文注入普通对话 |
| SSL 切换 | 保留中断告警，提醒针对性检查 URL/OAuth/模板和登录 | 自动全量替换 http/https 或修改 SMTP host |
| Key 重置 | 分别核对任务和记录，新 Key 须可靠关联 | 假设最新列表记录就是新 Key |
| 配置保存成功 | 报告保存结果及未做的连接验证 | 宣称 SMTP/GitHub 登录一定可用 |

确认方案由客户端承接，MCP 只验证本地计划绑定。数据面交接只传非敏感目标及用户诉求，不附带管理 AK/SK 或 ApiKey 明文。

## 场景一：从零创建（新建实例）

### 意图四问（进入配置前必须问完，不得默认、不得替用户决定）

| 问题 | 答案的后果 |
|---|---|
| 数据库来源？新建还是用已有 PG？ | 新建实例（newly_instance，本场景，推荐）/ 挂载已有实例（existed_instance，见场景二） |
| 要传文件吗？（图片、视频、附件都算） | 要 → **创建前**按场景五定 OBS 方案（复用或新建也问用户）；桶名+AK/SK 进 `storage_component`——**强烈建议创建时当场启用**（事后可经场景五补开对接，但避免遗漏与流程拉长）。不要 → `storage_component` 写 `{"enabled":false}`（三字段全空），不能整个省略 |
| 要从公网访问吗？ | 要 → 创建后按场景四处理（EIP+安全组+`api_external_url` 同步）；不要 → 明确告知用户只能内网访问 |
| 要 HTTPS 吗？ | 要 → 先定证书获取三路径：复用已有证书（`list_ssl_certificates` 盘点，`cert_id` 直接用于 `change_supabase_ssl`）/ 购买新证书（`purchase_supabase_ssl_cert` 两段式，推荐；免费档 DV_SSL_CERT_BASIC，付费档生成待支付订单）/ 导入自有 SCM 证书；纯 EIP 公网 IP 无域名时证书仅支持文件验证。创建后切 SSL；不要 → 走 http |

答全后喂给 `plan_supabase_creation_arrangement(manage_type, az_code, ...)`。部署模式是否支持 Ha 不猜：`list_supabase_flavors_with_azs(az_code, mode="Ha")` 成功 → Single/Ha 都可选；被拒 → 该环境仅 Single，如实告知。

### 操作表

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 意图四问 | — | needs_storage/needs_public_access/needs_ssl 三态意图 | 四问全有明确答复；存储答复必须在创建前拿到 |
| 2. 编排基线 | `plan_supabase_creation_arrangement` | manage_type=newly_instance、az_code、意图参数 | 三必选模块已固化（应用与实例规格分开单独询问，实例默认推荐与应用同规格）、creation_flow 步骤编号齐全、decision_points 清空或已答复 |
| 3. 应用要素发现 | `discover_supabase_create_basic_options` | az_code | version 取当前最高（x.y.z 应用版本）；Ha 实时探测结果如实采纳；应用规格按规格类型分组展示全部可售（可选或自定义，推荐通用型 2U4G） |
| 4. 实例要素发现 | `discover_db_instance_for_create` | scenario=newly_instance、mode | 实例规格按 group_type 十大类分组展示全部可售规格，默认推荐与应用同规格；磁盘类型展示中文名与实时兼容规格类型；引擎版本、规格、磁盘类型均为实时推荐值 |
| 5. 网络选址 | `discover_network_for_create` | scenario=newly_instance | vpc_id/subnet_id 来自返回；无可用网络时按 default_create 建网后重跑一次取真实 ID |
| 6. 写请求文件 | 本地操作 | 见"创建请求体" | 秘密全部入文件；预览前过"预览前逐项核对清单" |
| 7. 预览 | `create_supabase_with_new_instance` | request_ref、public_access_cidr、confirm=false | 脱敏参数、双组安全组方案、obs_plan 交用户核对；plan_id 记录在案 |
| 8. 确认提交 | `create_supabase_with_new_instance` | 同参数 confirm=true + plan_id | 10 分钟内、参数未变；提交后自动建双安全组与 OBS 桶并回填 |
| 9. 跟踪 | `show_supabase_creation_progress` | application_id、application_job_id、instance_id、instance_job_id | 实例先就绪、应用任务才开始；约 20-30 分钟 |
| 10. 回查 | `show_supabase_application` | application_id | 状态 normal、无进行中操作、托管实例正常 |
| 11. 后续 | 场景四/五/六/七 | — | 公网、登录、交付按需执行 |

`public_access_cidr` 三选一：`auto`（探测当前设备出口 IP，失败提示改传自定义或 open）/ `open`（0.0.0.0/0，经 KooCLI，须用户明确确认）/ 自定义有界 CIDR（全 0 网段必须直接传 open，自定义必须严格有界）。

### 创建请求体（写入本地请求文件的完整字段）

真实可用的创建请求示例（新建实例；选主备时把 mode/ha 换成对应值；charge_info 固定按需）：

```json
{"name":"rds-supabase-5a55","basic_config":{"region":"cn-east-3","vpc_id":"<VPC ID>","subnet_id":"<子网 ID>","time_zone":"UTC+08:00"},"storage_component":{"enabled":false},"version":"1.0.0","mode":"Single","flavor_ref":"rds.supabase.n1.large.2","availability_zone":"cn-east-3a","password":"<本地生成的密码>","manage_type":"newly_instance","managed_instance":{"datastore":{"type":"PostgreSQL","version":"17.11.260901"},"ha":{"mode":"Single","replication_mode":"async"},"charge_info":{"charge_mode":"postPaid"},"flavor_ref":"rds.pg.n1.medium.2","volume":{"type":"ESSD","size":40},"availability_zone":"cn-east-3a","password":"<本地生成的密码>","port":5432}}

> **`security_group_id` 不得出现在请求文件**（顶层与 `managed_instance` 均同）：专用安全组由创建工具在确认后自动创建并注入（携带即拒绝，错误会提示删除字段；自备安全组请在创建完成后经 `change_supabase_security_group` 换绑）。历史版本曾要求手填，现已废止。
```

密码规则（应用密码与数据库密码同规则）：8-32 位，至少包含大写字母、小写字母、数字、特殊字符（`~!@#$%^*-_+=?,`）中的三种；本地生成时只从这些字符里取，生成后直接入文件。

- **公共必填**：name（4-64 字符，中文按 3 字节计，字母或中文开头）、basic_config{region, vpc_id, subnet_id, 可选 time_zone}、version（应用版本，取当前最高）、mode（Single/Ha，与用户确认）、flavor_ref（应用规格，形如 `rds.supabase.n1.large.2`）、availability_zone（Single 一个 AZ；Ha 两个不同 AZ，此处为主 AZ）、password（默认用户 supabase 的密码，兼 Dashboard 管理员登录密码）、storage_component、manage_type。
- **managed_instance 追加**：datastore{type=PostgreSQL, version=引擎版本}、ha{mode 与顶层一致，replication_mode: async/sync}、charge_info（**固定按需** `{"charge_mode":"postPaid"}`——托管实例仅支持按需计费，不支持包周期；计费规则：计费项=实例规格+存储空间（必选）+备份空间超出免费额度（存储容量 100%）部分，公网带宽/跨区域备份可选，按秒计费整点小时结算、自实例创建成功时间点起计费至删除 https://support.huaweicloud.com/price-rds-pg/rds_00_0005.html ）、flavor_ref（数据库规格，形如 `rds.pg.n1.medium.2`，与应用规格是两回事）、volume{type: 按 `list_db_instance_storage_types` 实时结果选择, size: 40-40000 GB}、availability_zone（与顶层主 AZ 一致）、password（规则同上，可与应用密码同值）、port（固定 5432，传或省略均可）、可选 enterprise_project_id（**仅企业项目账号需要**：取值来自 `discover_db_instance_for_create` 实时返回的企业项目列表，默认选中 default 项目；个人账号省略不填，省略时归属由服务端决定）、可选 configuration_id（参数模板 ID，取值来源 ListConfigurations，默认不传）。**security_group_id 不得携带**（数据库组由创建工具自动创建注入）。
- 不支持 tags 与未知字段——如实告知，不静默丢弃用户要求。主备是否可用以所选环境实际为准：后端拒绝时报错附 error_code/error_msg，如实转述。

### 预览前逐项核对清单

预览前把请求体逐项过一遍（秘密字段只核"已配置"，不回显值），有出入先改再预览；结论给用户看一眼。最常见的错误：version 填成 PG 版本、漏 ha、密码不合规、period_type 传数字。

| # | 字段 | 规则 | 参考值 |
|---|---|---|---|
| 1 | name | 4-64 字符，中文 3 字节，字母/中文开头 | rds-supabase-5a55 |
| 2 | basic_config | region/vpc_id/subnet_id 与环境一致；time_zone 整段 UTC-12:00~UTC+12:00，推荐 UTC+08:00 | cn-east-3 / … / UTC+08:00 |
| 3 | version | 应用版本，取当前最高 | "1.0.0"（不是 17.11.x） |
| 4 | mode | Single 或 Ha（与用户确认） | Single |
| 5 | flavor_ref | 应用规格 | rds.supabase.n1.large.2 |
| 6 | availability_zone | Single 一个 AZ；Ha 两个不同 AZ（此处主 AZ） | cn-east-3a |
| 7 | password | 8-32 位三类字符，本地生成 | （已配置） |
| 8 | storage_component | 不用存储 | {"enabled":false} |
| 9 | manage_type | 新建实例 | newly_instance |
| 10 | datastore | PostgreSQL + 引擎版本 | 17.11.260901 |
| 11 | ha | mode 与顶层 mode 一致 | {"mode":"Single","replication_mode":"async"} |
| 12 | charge_info | 固定按需：仅 `{"charge_mode":"postPaid"}`（不支持包周期） | postPaid |
| 13 | managed flavor_ref | 数据库规格（不等于应用规格）；按 group_type 十大类分组选择，默认推荐与应用同规格 | rds.pg.n1.medium.2 |
| 14 | volume | 环境支持的盘型（核对中文名与实时兼容规格类型） + 容量 | ESSD / 40 |
| 15 | managed availability_zone | 与顶层主 AZ 一致 | cn-east-3a |
| 16 | managed password | 规则同应用密码，可同值 | （已配置） |
| 17 | port | 5432 或省略 | 5432 |
| 18 | enterprise_project_id | 可选——仅企业项目账号填写；个人账号省略 | （企业项目账号：列表实时选择，默认 default 项目；个人账号：留空） |

### 提交与等待

提交返回 202 + job_id + application_id + instance_id + instance_job_id（应用在实例创建成功后才触发创建，实例就绪前查不到应用任务；**两个任务分别确认**）。等待节奏：`show_supabase_creation_progress` 综合编排查询顺序 → 提交后先查 1 次抓秒级失败 → 告知用户"预计 20-30 分钟"→ 每次用户回来问再查 1 次；单任务细节才用 `show_operation_job_status`。观察预算用完不等于云任务失败。

### 失败处置（创建）

| 失败 | 工具行为 | 处置 |
|---|---|---|
| 请求文件不安全/别名缺失 | MCP_INVALID_ARGS（区分"别名不存在"与"注册表不可用"） | 补别名或修权限（0600）/路径；禁止用 Shell 代填秘密 |
| 结构校验不过 | MCP_INVALID_ARGS（指明具体字段） | 按指明字段修正；不删用户要求后静默重试 |
| 预览超 10 分钟/参数变 | MCP_GUARDRAIL_BLOCKED | 重新预览确认 |
| 同意图有未完成执行 | MCP_GUARDRAIL_BLOCKED | 查记录核对，不新建计划绕过 |
| 响应含 order_id（防御性：固定按需后正常不出现；如出现按订单流程处理） | status=order_created，计划记 accepted | 按场景九订单流程处理：核对→授权→支付→按正常节奏查任务；放弃则取消 |
| 提交中断 | submission_unknown + plan_id | `show_operation_job_status` 查任务、回查资源；禁止重放 |
| 后端明确拒绝（4xx） | MCP_INVALID_ARGS 等，报错附后端 error_code/error_msg；计划标 failed | 如实转述；修正参数后重新预览再提交（failed 不阻塞重试，与结果不明不同） |
| 写开关未开/只读拦截 | MCP_READ_ONLY | 操作员同时核对两个变量并重启 |
| 任务 failed/状态识别不了 | next_action 指向人工 | 停止当前链路，交操作方 |
| 应用完成但数据库失败 | 两个任务独立返回 | 分别核对；部分成功不自动删资源 |

## 场景二：挂载已有实例创建

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 意图四问 | — | 同场景一 | 托管来源取已有实例 |
| 2. 候选清单 | `discover_db_instance_for_create`（或 `list_supabase_manageable_instances`） | scenario=existed_instance | 分页 20/页；`current_actions` 非空或状态非 ACTIVE 的实例必须排除；用户选定 instance_id |
| 3. 实例详情 | `discover_db_instance_for_create` | instance_id | 版本/部署类型/端口/可用区/网络信息回填编排 |
| 4. 写请求文件 | 本地操作 | manage_type=existed_instance、existing_instance{instance_id, database_name="root", database_pwd} | database_name 固定 root 不能改；root 密码只入文件（存量密码不受创建密码规则约束） |
| 5. 预览 | `create_supabase_link_exist_instance` | request_ref、public_access_cidr、confirm=false | 脱敏参数与应用组方案交用户核对 |
| 6. 确认提交 | 同上 | confirm=true + plan_id | 自动建应用组（8443 入方向三选一+5432 出方向指向实例子网 CIDR）；实例自身安全组不动 |
| 7. 跟踪 | `show_supabase_creation_progress` | application_id、application_job_id | 无实例任务；约 20-30 分钟 |
| 8. 回查 | `show_supabase_application` | application_id | managed_instance 指向所选实例 |

## 场景三：创建前置编排与参数基线

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 收集意图 | — | manage_type、az_code、mode、instance_id、detect_access_ip | 不确定的意图保持省略（开放决策点），不替用户决定 |
| 2. 生成基线 | `plan_supabase_creation_arrangement` | 三态意图参数 needs_* | planning_only，不创建任何资源；应用与实例规格分开单独询问，实例规格按 group_type 十大类分组展示全部可售、默认推荐与应用同规格，磁盘类型展示中文名与实时兼容规格类型 |
| 3. 追问决策点 | — | — | 按 decision_points 逐项追问到明确答复 |
| 4. 展示 | visual 输出 | — | 表格/流程图直接给用户；三大必选模块参数注明实时来源 |

基线输出结构：托管来源两决策 → 三必选模块（Supabase 基本信息/托管实例/网络控制，各注明所依赖的发现工具）→ OBS 关键可选模块（needs_storage 答复后给复用/新建两方案）→ SSL 配置与公网访问（EIP）两个独立模块（needs_ssl/needs_public_access 答复后输出：SSL 给证书获取三路径——复用 `list_ssl_certificates`/购买 `purchase_supabase_ssl_cert` 推荐/导入自有，免费档 DV_SSL_CERT_BASIC；公网给 EIP 购买基线：按需计费固定（不支持包周期）+全动态 BGP 独享带宽；计费方式（bandwidth 按带宽/traffic 按流量）与带宽大小均由用户决策（无默认），基线附收费标准（官方示例：bandwidth 6Mbps≈0.565 元/小时、traffic 0.64 元/GB、IP 保有费 0.02 元/小时；traffic 单 EIP 峰值上限 300Mbps））→ 步骤化 creation_flow → 创建后动作（SSL 分支 `list_ssl_certificates`→`purchase_supabase_ssl_cert`→`change_supabase_ssl`）→ decision_points → 秘密边界。实际创建 1:1 严格按 creation_flow 执行，不偏离目标与计划。

## 场景四：公网开通（EIP 采购与绑定）

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 采购 | `create_supabase_eip` | prefer_idle=true、billing_method=<bandwidth/traffic 用户按场景选>、bandwidth_size_mbps=<用户决策：bandwidth 5-1000 计费尺寸 / traffic 5-300 峰值限速> | 空闲优先：列出未绑定 EIP 供用户选定；无空闲按需新建（**计费方式与大小先问用户并展示收费标准再执行**——bandwidth 带宽费=峰值×时长不限流量[官方示例 6Mbps≈0.565 元/小时]、traffic 流量费按出云 GB[官方示例 0.64 元/GB，单 EIP 峰值上限 300Mbps]，另含 IP 保有费[未绑定时官方示例 0.02 元/小时]；全动态 BGP+独享+自动添加 USAGE_FOR 标签） |
| 2. 绑定 | `bind_supabase_eip` | instance_id、public_ip_id、public_ip | 三重校验全过：in32 结尾应用 ID 且真实存在（应用详情接口核对）、UUID 规范、IPv4 合法；仅未绑定应用的首次绑定，经应用级 public-eip 接口 |
| 3. 同步 URL | `update_supabase_auth_config` | 请求文件别名只含 api_external_url | 拼装的公网访问地址；预览→确认→查任务→回查 |
| 4. 探活 | 本地 curl | 访问地址 | 任何状态码都算网络可达；不通查安全组规则与 EIP |
| 5. HTTPS（可选） | `list_ssl_certificates` / `purchase_supabase_ssl_cert` → `change_supabase_ssl` | cert_id 即 `change_supabase_ssl` 入参 | 证书获取三路径：复用（盘点账号已有证书）/购买（推荐，免费档 DV_SSL_CERT_BASIC；付费档生成待支付订单）/导入自有；纯 EIP 公网 IP 无域名时仅文件验证；切换闪断低峰执行，生效后回调协议改 https |

绑定成功后必须同步 `api_external_url`：邮箱确认链接与 OAuth 回调都指向该地址，不同步则登录链路是断的。解绑（`change_supabase_eip` is_bind=false，不带绑定参数）不释放 EIP、不停计费；解绑后旧公网地址失效，与用户确认改回内网地址还是等重新绑定。新建 EIP 的标签（USAGE_FOR）由 `create_supabase_eip` 自动打，用于在控制台区分流程自动创建的 EIP。

## 场景五：OBS 存储对接

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 两选择 | `discover_supabase_storage` | app_name | 复用（私有优先，公共桶标注匿名公开风险）/ 新建（推荐）；附读测试与凭证检测 |
| 2. 新建桶 | `create_supabase_new_obs` | app_name、redundancy=multi_az/single_az | 私有桶、标准存储、阻止公共访问固定开启；重名自动追加 4 位短 uuid |
| 3. 创建对接 | 创建工具自动处理 | storage_component{enabled, bucket_name, ak, sk} | 创建工具确保桶存在（已有复用、缺失新建）并回填最终桶名；凭据必须持久 AK/SK |
| 4. 变更轮换 | `update_supabase_storage` | 请求文件别名 | 首次或换 AK 给全（桶名+AK+SK）；AK 未变换桶名可只带原 AK 省 SK；禁用三字段全空 |

临时凭证检测：环境使用 SecurityToken 临时凭证时，发现工具明确提示不可作 `storage_component` 凭据，引导经本地请求文件提供持久 AK/SK——避免凭证过期后应用无法访问 OBS。存储对接强烈建议创建时一次成型（业务确认需要就当场启用）——这是意图四问在创建前问清存储的原因；未启用的应用事后可经场景五 `update_supabase_storage` 补开对接（首次须全量凭据：桶名+AK/SK）。

## 场景六：认证、登录与增强

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 基线 | `show_supabase_auth_config` | application_id | 空串=未配置；作为更新对照基准 |
| 2. 开关 | `update_supabase_auth_flags` | enable_account_sign_up / enable_anonymous_users | 只改传入的开关；先评估匿名暴露面 |
| 3. 邮箱登录 | `update_supabase_auth_config` | 请求文件别名（smtp_config 等） | SMTP 密码只入文件；端口常见 465/587；确认邮件模板是唯一可自定义模板 |
| 4. GitHub 登录 | `update_supabase_auth_config` | 请求文件别名（github_oauth_provider） | Client ID 非秘密可对话收；Client Secret 只入文件；回调地址与 GitHub App 一致；`https` 回调前提是应用已开 SSL（证书获取三路径见场景一四问④） |
| 5. 回查 | `show_supabase_auth_config` | application_id | 配置生效；空串仍未配置 |

字段级契约（顶层八选一、值不得为空、省略=不变、关闭只传开关）见 [本地请求与字段契约](local-requests.md)。验证分级：保存成功（任务+回查）不等于业务可用——真实发信、真实登录才算。

## 场景七：接入信息与密钥交付

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 地址素材 | `show_supabase_application` | application_id | 协议←enable_ssl、主机←public_ip（公网）/private_ip·traffic_vip（内网）、端口←port |
| 2. Key 元数据 | `list_supabase_api_keys` | application_id | 四类（secret/publishable/service_role/anon）只返回记录不返回值 |
| 3. 交付 | `deliver_supabase_api_key` | application_id、key_id、delivery_ref | 每类 Key 一个别名一个**新文件**（同别名二次交付失败）；需写开关；交付前用户逐个确认 |
| 4. 信息卡 | — | — | 按输出格式输出；验证状态如实标注 |

输入契约：已核验的 application_id（状态 normal 且无进行中操作）+ 用户对每个 Key 值查看的明确授权。失败处置：key 非 normal 或不唯一 → 护栏拒绝，刷新元数据重选；文件已存在 → 换别名；中途失败 → 操作员检查目标文件，不再拉取、不读内容。

## 场景八：日常变更

见 SKILL.md 速查表。变更后统一节奏：`show_operation_job_status` 查询任务至终态 → 回查资源 → 涉登录/存储的业务验证；所有返回 job_id 的操作类工具受理后必须跟踪至终态（应用创建除外，使用专用 `show_supabase_creation_progress`）。Key 重置后新值是新记录，不用旧 key_id 取值，按场景七重新交付。

### 应用启停与重启

| 操作 | 工具 | 校验点 |
|---|---|---|
| 启动应用 | `start_supabase_application` | 操作前 `show_supabase_application` 核对状态与 `current_actions`（状态护栏：start 仅停止态且无进行中操作）；启动应用不会自动启动托管实例，实例状态异常可能启动失败；异步返回 job_id，跟踪至终态后回查应用状态 |
| 停止应用 | `stop_supabase_application` | 操作前同上核对（状态护栏：stop 仅运行态 normal 且无进行中操作）；不停托管实例、实例继续计费，停止期间应用功能不可用；建议低峰执行；异步 job 跟踪至终态 |
| 重启应用 | `restart_supabase_application` | 操作前同上核对（状态护栏：restart 仅运行态 normal 且无进行中操作，已停止应用须先启动）；重启内部组件、短暂服务中断并释放内存缓存；建议低峰执行；异步 job 跟踪至终态 |

### 托管实例详情与启停重启

四个工具均以 `application_id` 入参，目标实例强制解析自该应用的 `managed_instance` 字段——**不接受裸 `instance_id`，杜绝误操作独立数据库实例**；无 `managed_instance` 的应用直接被拦截。异步任务用 `show_operation_job_status` 跟踪至终态，回查工具为 `show_supabase_managed_instance`。

| 操作 | 工具 | 校验点 |
|---|---|---|
| 查托管实例 | `show_supabase_managed_instance` | application_id；返回引擎/版本/instance_status（normal=正常、shutdown=已停止等）/规格/磁盘/可用区/进行中动作，附关键计费与十五天自动启动说明 |
| 停止托管实例 | `stop_supabase_managed_instance` | 操作前 `show_supabase_managed_instance` 核对 instance_status 与进行中动作（状态护栏：stop 仅 normal 且无进行中操作）；仅超高IO/SSD云盘/极速型SSD 的按需实例可停（专属云不支持）；VM 停止计费、EIP/存储/备份继续计费；默认停止十五天，十五天内未开启将于可维护时段自动启动；已停止实例删除不进回收站；停止主实例同时停止只读实例；停止期间应用功能不可用；异步 job 跟踪 |
| 启动托管实例 | `start_supabase_managed_instance` | 操作前核对 instance_status（状态护栏：start 仅 shutdown 可开启）；启动主实例同时启动只读实例；可能因资源不足开启失败；**顺序建议：先启实例再启应用**（启动应用不会自动启动实例）；异步 job 跟踪 |
| 重启托管实例 | `restart_supabase_managed_instance` | 操作前核对 instance_status、冻结状态与进行中动作（状态护栏：restart 仅 normal、未冻结且无进行中操作；创建/扩容/变更规格/备份/恢复/修改端口期间不能重启）；重启期间实例不可用、应用功能受影响；建议低峰执行；异步 job 跟踪 |

### 安全组绑定修改

`change_supabase_security_group`（DANGEROUS，两段式）经 RDS SetSecurityGroup 修改目标绑定的安全组，三目标模式互斥使用：

| 目标 | 入参 | 语义与校验 |
|---|---|---|
| `application` | `application_id` | 应用自身的安全组；仅运行态（normal）且无进行中操作可受理 |
| `managed_instance` | `application_id` | 应用托管实例——目标强制解析自该应用的 `managed_instance` 字段，不接受裸 `instance_id`；无托管实例直接拦截 |
| `attachable_instance` | `instance_id` | 挂载已有实例创建场景的前置安全组准备——实例必须在本环境可挂载候选清单内（`list_supabase_manageable_instances`），清单外直接拒绝 |

执行纪律：

- **多组全量替换**：`security_group_ids` 为非空安全组 UUID 清单，所给清单即最终清单——须保留的既有组必须一并列入，未列入的既有组被摘除；预览回读当前安全组并在 impact 明示替换语义与 8443/5432 失联风险（摘掉承载 8443 入方向或 5432 出方向的组，应用即不可访问）。
- **官方状态约束**：实例在创建、数据库升级、变更规格、创建用户、删除用户状态下不能设置；替换期间连接可能短暂中断。被拒如实转述，待任务终态后重新预览。
- **跟踪**：受理返回 workflowId，经 `show_operation_job_status` 查询至终态后回查目标绑定的安全组。
- **分工边界**：本工具换“绑哪些组”；组内规则的增删仍使用 `add_supabase_security_group_rule` / `delete_supabase_security_group_rule`。

### 应用密码修改

`change_supabase_application_password`（DANGEROUS，两段式）仅修改应用登录密码，新密码只经本地请求文件别名引用：

| 操作 | 工具 | 校验点 |
|---|---|---|
| 改应用密码 | `change_supabase_application_password` | 仅修改应用登录密码（dashboard 用户 supabase）；托管实例 root 登录密码不在本工具范围，实例密码经控制台实例管理修改；修改后旧密码会话失效；新密码明文不进对话 |

## 场景九：包周期订单

计费边界：RDS Supabase 应用公测期间免费，费用仅产生于托管实例；托管实例**固定按需计费**（创建请求 `managed_instance.charge_info` 仅 `{"charge_mode":"postPaid"}`，不支持包周期），创建不再返回 `order_id`。订单工具用于**控制台侧产生的包周期订单**（如存量实例）的核对、支付与取消。

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 核对 | `get_supabase_order` | order_id（limit 默认 20、marker 分页） | 状态、金额、币种、明细逐项给用户核对；amount_after_discount 为优惠后不含券卡 |
| 2. 支付 | `pay_supabase_order` | order_id、expected_amount、currency、confirm=true | expected_amount 须同时等于 official_amount 与 amount_after_discount（不同=有折扣，拒绝支付走费用中心）；单次提交不自动重试 |
| 3. 支付复核 | `get_supabase_order` | order_id | payment_submitted/payment_verified；订单状态与支付时间确认到账 |
| 4. 取消 | `cancel_supabase_order` | order_id、confirm=true | 仅未支付可取消；不可逆；cancellation_verified 为 false 继续查询不重提 |

异常处置：提交结果未知（payment_submitted=false）→ 先查询同一订单，不自动再次付款；已支付资源退订走控制台，本工具不受理；已取消订单再次取消返回幂等结果。

## 场景十：删除与收尾

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 预检 | `show_supabase_application` | application_id | 无进行中操作（**状态不限**：正常/已停止/已移除均可删除）；记录 public_ip/安全组 ID/托管实例 ID/桶名 |
| 2. 问实例去留 | — | delete_managed_instance 必选 | 不能默认：false 留实例留费；true 双删不可逆（**仅按需可级联**——包周期实例含挂载场景接入的，`true` 整体拒绝、改 false 删应用后控制台退订实例：费用中心→退订管理；计费模式无法核验同样失败关闭） |
| 3. 预览 | `delete_supabase_application` | application_id、delete_managed_instance、confirm=false | 不可逆影响与费用后果展示给用户 |
| 4. 提交跟踪 | `delete_supabase_application` → `show_operation_job_status` | confirm=true + plan_id | true 时返回 job_id + instance_job_id 双任务，分别跟踪至终态 |
| 5. 确认消失 | `list_supabase_applications` | application_id 精确查 | 应用不在列表；级联时实例确认消失（可回 `list_supabase_manageable_instances` 交叉复核） |
| 6. 残留处置 | 见下 | — | 输出残留清单与处置建议 |

四层校验（服务端自动执行，**均在提交前触发、应用保持可读**）：实例归属、云端 `managed_instance` 现状复核、实例未被其他应用挂载、**计费模式门禁**（包年/包月实例不支持 API 直删——级联与单独拆除均拦截，须控制台退订；charge_info 缺失失败关闭）。残留处置通道：**EIP 释放 `delete_supabase_eip`（KooCLI EIP DeletePublicip）**——提交前实读 EIP 校验身份（可带地址交叉核对）、全量扫描应用清单拦截仍被存活应用公网地址引用者、绑定中由后端拒绝（先 `change_supabase_eip` 置 is_bind=false 解绑）、删除即停 IP 保有费；**应用数据目录清理 `clean_supabase_obs_ws`（KooCLI obsutil）**——删除对象是桶根目录下名称等于应用 ID 的子文件夹：清空内容并删除文件夹本身，桶与其他任何目录不受影响（应用 ID 强制 in32 规范格式），仍存活应用 ID 拦截（先删应用再清目录），目录不存在或为空幂等返回 already_clean；**OBS 桶删除 `delete_supabase_obs`（KooCLI obsutil rm）**——仍被存活应用 storage_component 引用拦截、非空拦截（先用 clean_supabase_obs_ws 清各应用目录，其余对象人工核对）、桶不存在幂等返回 already_absent；三工具均供业务方按需显式使用或随删除流程联动触发。托管实例单独拆除 `delete_supabase_managed_instance`（应用 ID + managed_instance.id 双标识，**仅按需实例可直删、包周期须控制台退订**，数据不可恢复先确认导出）；安全组规则清理 `delete_supabase_security_group_rule`（先核对组未被共用）；整组下线 `delete_supabase_security_group`（标签门：仅 AUTO_CREATE=true/USE_FOR=Supabase 双标签且无引用；后端拒绝在用组）；本地 Key 文件与请求文件、项目 MCP 配置按需清理。

## 场景十一：资源清理与保留

| 步骤 | 工具 | 关键参数 | 校验点 |
|---|---|---|---|
| 1. 删应用 | 场景十 | delete_managed_instance 必选 | 新建实例场景建议同步删实例（避免残留） |
| 2. 盘点残留 | `show_supabase_residuals` | application_id | 资源记录圈定+实时核对：EIP（自动创建建议删/复用用户决策）、桶（同）、应用数据目录（对象数+保留桶高危计费提醒）、安全组（应用组/数据库组；实例保留时数据库组不可删）；资源记录无记录如实拒绝 |
| 3a. 一键清理 | `cleanup_supabase_residuals` | 四个类别开关（必选布尔）、confirm、plan_id | 单确认单计划；逐项守卫复检；被拦项跳过并如实报告；资源记录回写；复核重跑步骤 2 |
| 3b. 分项清理 | 单项工具 | — | EIP/桶必须显式确认；保留桶必须提醒清理存储（高危持续计费）；自动创建安全组建议删 |
| 4. 复核 | `show_supabase_residuals` | application_id | 残留清单归零或如实说明被拦原因 |

全流程保护机制（资源记录）：创建/复用/绑定/修改全程本地记录，清理精准圈定；详细流程见服务端 README 场景七。

## 排障补充

- **KooCLI 协同**：安全组 VPC 六个工具（查列表/详情、建组、增删规则、删组）内置 KooCLI（hcloud）能力，开箱即用；原生 RDS 入口不代理 VPC API。换绑安全组使用 `change_supabase_security_group`（RDS SetSecurityGroup，不经 KooCLI）。二进制定位：`HCLOUD_BIN` → 固定安装目录 → PATH，每次调用重新定位。凭据注入：AK/SK 环境变量同时存在时按命令注入，否则回落 hcloud profile；REST Token 模式须本机 `hcloud configure init`。区域取 `HUAWEICLOUD_REGION`；子项目账号在 profile 配 `--cli-project-id`。VPC 后端 error_code/error_msg/request_id 原样透传。
- **诊断 CLI**（克隆方式）：`uv run python -m mcp_server_supabase.diagnostics check`（配置与依赖）/ `offline`（stdio 自检）/ `discover`（从凭据发现项目与候选入口，`--probe` 追加只读探测）/ `readonly --allow-cloud-read`（授权环境真实只读检查）。诊断不提交云写操作，摘要不含资源值与凭据。
- **模式配错症状**：只填 AK/SK 不设 `SUPABASE_TRANSPORT=sdk_core`，服务端按 REST 模式启动并完全忽略 AK/SK，每次调用报 MCP_PERMISSION_DENIED；REST 模式缺 `HUAWEICLOUD_AUTH_TOKEN` 同样报错。
- **术语表**：plan_id——预览凭证，10 分钟有效、单次使用；request_ref——本地请求文件里含秘密配置的别名；job_id——云端异步任务编号；本地执行记录——每笔写操作在本机留下的结果记录（成功/失败/结果不明），出问题时核对用，永不删除；受理——服务端收到请求，不代表做完。
