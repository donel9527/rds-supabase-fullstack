# 华为云 RDS Supabase MCP Server

[English](README_en.md)

## 版本

当前版本：`0.4.0a52`（开发预发行版）；Python `3.10+`；MCP Python SDK `2.x`；53 个工具。

## 概述

该服务把华为云 RDS Supabase 应用的全生命周期管理能力封装为 MCP 工具，覆盖创建编排与场景化创建（托管实例两种来源）、网络与安全组规格、EIP 采购与绑定、SSL 证书查询与购买、OBS 存储对接、认证与登录配置、API Key 交付、包周期订单、应用启停与重启（应用与托管实例两层）、安全组绑定修改、SSL/密码/安全组规则等日常变更以及变更与删除，供 AgentArts 及其他 MCP 客户端调用；REST Token 与 SDK 两种凭据模式、stdio 与 Streamable HTTP 两种传输共用同一套工具、安全护栏与输出协议。默认只读：写操作一律以预览/确认双段执行，敏感字段经本地请求文件承载，不进入对话。发现与编排结果附图表化输出（visual），供直接查阅。配套技能 `skills/huaweicloud-supabase/rds-supabase-mgr-mcp` 提供场景化操作指引。本服务仅覆盖管理面（control plane），不执行 SQL 与数据操作；数据面由独立服务 `server/mcp_server_rds_supabase` 承担，两者分开交付、互不替换。

## 快速开始

准备 Python 3.10+、[uv](https://docs.astral.sh/uv/) 与华为云凭证。最小配置为三个变量：`HUAWEICLOUD_ACCESS_KEY`、`HUAWEICLOUD_SECRET_KEY` 与 `HUAWEICLOUD_REGION`（搭配 `SUPABASE_TRANSPORT=sdk_core` 启用 SDK 签名模式）；项目 ID 经 IAM 自动发现，RDS 服务入口按区域自动推导。首次接入建议保持只读：

```bash
export HUAWEICLOUD_ACCESS_KEY="<AK>"
export HUAWEICLOUD_SECRET_KEY="<SK>"
export HUAWEICLOUD_REGION="<区域，例如 cn-north-4>"
export SUPABASE_TRANSPORT="sdk_core"
export HUAWEICLOUD_MCP_READ_ONLY="true"
uvx --from "git+https://github.com/huaweicloud/rds-supabase-fullstack#subdirectory=server/mcp_server_rds_supabase_mgr" \
  mcp-huaweicloud-rds-supabase-mgr
```

通用 stdio 客户端配置（Token 模式；AK/SK 模式见
[examples/mcp-sdk.example.json](examples/mcp-sdk.example.json)）：

```json
{
  "mcpServers": {
    "rds-supabase-mgr-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/huaweicloud/rds-supabase-fullstack#subdirectory=server/mcp_server_rds_supabase_mgr",
        "mcp-huaweicloud-rds-supabase-mgr"
      ],
      "env": {
        "HUAWEICLOUD_AUTH_TOKEN": "<服务 Token>",
        "HUAWEICLOUD_MCP_READ_ONLY": "true",
        "SUPABASE_ENABLE_WRITES": "false"
      }
    }
  }
}
```

连接后先调用 `get_supabase_capabilities` 验证端点、权限与项目，再以
`plan_supabase_creation_arrangement` 生成创建编排基线。完整安装方式、凭据模式与
安全组前置条件见后文。

## 分类

云资源管理 / 应用生命周期编排 / 数据库托管。

## 功能

- **编排与发现**：场景化创建编排基线——托管实例两种来源、三大必选参数模块与 OBS 桶存储
  对接（关键可选，创建前必须确认）、SSL 配置与公网访问（EIP）两个独立模块与步骤化创建
  流程；应用与实例规格分开单独询问，全部可售规格按规格类型（group_type 十大类）分组
  展示、实例默认推荐与应用同规格、磁盘类型带中文名与实时兼容清单；应用、实例、网络与
  安全组四类发现工具，参数实时固化并给出推荐。
- **场景化创建**：`create_supabase_with_new_instance`（推荐）与
  `create_supabase_link_exist_instance` 严格按编排执行资源准备——专用安全组与
  OBS 桶自动创建、参数回填注入、一次提交；回显应用/实例标识与工作流 ID。
- **网络与安全组**：VPC/子网选址（空闲 IP 优选与默认推荐）、专用组建组与规则、
  标签防护（AUTO_CREATE/USE_FOR）、入方向来源三选一（自动探测/全开放/自定义）；
  安全组换绑（`change_supabase_security_group`）——应用、托管实例与待挂载实例
  三目标，多组全量替换（未列入即摘除），托管与可挂载目标强校验。
- **EIP**：空闲优先采购（按需推荐、全动态 BGP 独享带宽 5-1000M、推荐 300M、
  自动打标）；绑定三重校验（in32 应用 ID、归属、格式），经 RDS AttachEip 执行。
- **SSL 证书**：账号已有证书盘点（`list_ssl_certificates`，SCM 全局服务）、两段式
  证书购买与申请（`purchase_supabase_ssl_cert`：免费档 DV_SSL_CERT_BASIC 推荐、
  付费档生成待支付订单、纯 EIP 公网 IP 证书仅文件验证）、SSL 开关变更。
- **OBS 存储**：获取两选择（复用/新建，新建为推荐）与新桶完整规格（私有/标准/
  多AZ/阻止公共访问）；临时凭证检测与读测试。
- **认证与登录**：注册开关、Auth URL、邮箱/GitHub 登录、确认模板；应用密码变更
  （仅应用登录密码，托管实例 root 密码不在本工具范围）。
- **密钥交付**：Key 元数据查询、重置、受保护本地文件交付，密钥值不进入对话。
- **订单**：包周期订单查询、余额支付与取消，金额币种逐项核对。
- **应用启停与重启**：启动（不自动拉起托管实例）、停止（不停托管实例、继续计费）与重启（短暂中断、建议低峰）；状态护栏校验，异步任务经 `show_operation_job_status` 跟踪至终态。
- **托管实例生命周期**：`show_supabase_managed_instance` 查询托管实例详情（引擎/版本/状态/规格/磁盘/可用区/进行中动作，附计费与十五天自动启动说明）；启停/重启均以 `application_id` 入参，目标实例强制解析自该应用的 `managed_instance` 字段，不接受裸 `instance_id`，杜绝误操作独立数据库实例；停止仅超高IO/SSD云盘/极速型SSD 的**按需**实例可受理（专属云不支持），VM 停止计费但 EIP/存储/备份继续计费，默认停止十五天、十五天内未开启将于可维护时段自动启动；重启期间实例不可用；先启实例再启应用是正确顺序；异步任务经 `show_operation_job_status` 跟踪至终态。
- **变更与删除**：SSL、EIP 与存储对接变更；应用删除（可选级联托管实例）与托管
  实例单独拆除；任务查询与有界等待。
- **安全与体验**：只读模式与风险分级、敏感字段脱敏、JSONL 审计、图表化输出、
  删除类四层防误校验。

## 业务场景

### 场景一：创建前置准备

创建前置准备由 `plan_supabase_creation_arrangement` 一次完成，仅做规划，不创建任何
资源。它先明确呈现托管实例的两种来源，并要求用户给出确定性结论：新建实例为推荐
与默认，挂载已有实例为备选。随后将关键参数模块实时固化——三大必选模块与一个关键可选模块：

- **Supabase 基本信息**：名称建议与命名规则、版本、部署模式与规格（全部可售规格
  供选择或自定义，推荐通用型 2U4G），来自 `discover_supabase_create_basic_options`。
- **托管实例**：新建来源经 `discover_db_instance_for_create` 返回引擎版本、规格与
  磁盘类型的逐字段推荐——应用规格与实例规格分两次交互单独询问：实例规格按
  group_type 十大类分组展示全部可售规格，默认推荐与应用同规格；磁盘类型明确展示
  中文名、官方说明与实时兼容规格类型供选择。挂载来源分页（每页 20 条）列出可托管
  实例，版本、部署类型、端口、可用区、创建时间与当前操作（action 锁）齐全——正在
  重启、升级或变更的实例须排除，以免任务冲突。
- **网络控制**：VPC/子网选址与双组安全组规格——应用组 8443 入方向三选一加 5432
  出方向、数据库组 5432 入方向，网段均为所选子网 CIDR，来自
  `discover_network_for_create`。
- **OBS 桶存储对接（关键可选）**：是否大文件存储场景（图片/视频/大文件）须经用户
  明确答复——创建后不可再启用；确认启用时输出复用/新建两选择、新桶完整规格与
  临时凭证提示，随创建请求一次提交。

编排同时输出两个意图独立模块：**公网访问（EIP）** 给出购买基线（按需购买、全动态 BGP
独享带宽 5-1000M、推荐 300M）与绑定、`api_external_url` 同步步骤；**SSL 配置** 给出
证书获取三路径——复用已有证书（`list_ssl_certificates` 盘点）、购买新证书
（`purchase_supabase_ssl_cert`，推荐，免费档 DV_SSL_CERT_BASIC、付费档生成待支付订单）、
导入自有证书。纯 EIP 公网 IP 证书仅支持文件验证。输出为步骤编号的创建流程与创建后动作
清单，供创建阶段 1:1 严格执行。

### 场景二：应用创建全流程

两个托管实例来源共用同一套纪律：意图先行、参数经编排固化、敏感字段只入本地
请求文件、预览确认双段提交。创建工具自动完成资源准备（专用安全组、启用存储
时的 OBS 桶）并将结果回填注入请求体，一次提交成功。

#### 新建实例场景（推荐，`create_supabase_with_new_instance`）

1. 意图确认：托管来源取新建实例；是否大文件存储（创建后不可再启用）、是否
   公网访问、是否 HTTPS。
2. 编排基线（场景一）固化必选模块参数与 OBS 对接方案（若启用存储）；`az_code` 触发实时发现，无 VPC 时采纳
   默认推荐并按 `default_create` 建网。
3. 组装本地请求文件：全部参数与敏感字段（应用密码、数据库密码、存储 AK/SK）
   只入文件，不进对话。
4. 预览（`request_ref`、`public_access_cidr`、`confirm=false`）：解析入方向
   三选一并返回 `plan_id`。
5. 确认提交（`confirm=true` + `plan_id`）：自动创建应用组与数据库组两个专用
   安全组；启用存储时确保 OBS 桶存在（已有复用、缺失新建、全局重名自动加短
   uuid）；全部回填注入后一次提交。
6. 回显 `application_id`/`instance_id` 与双工作流 ID，经
   `show_supabase_creation_progress` 持续查询：整体约 20-30 分钟，实例先就绪、
   应用任务才开始；预付费按场景六支付订单后才开始建资源。
7. `show_supabase_application` 验证就绪，随后按需执行公网开通（场景三）、SSL
   （证书三路径：复用/购买/导入自有）、登录配置与接入信息交付。

#### 已有实例挂载场景（`create_supabase_link_exist_instance`）

1. 意图确认同上，托管来源取已有实例。
2. 编排基线分页（每页 20 条）列出可托管候选，版本、部署类型、端口、可用区、
   创建时间与当前操作（action 锁）齐全——排除正在重启、升级或变更的实例后，
   由用户选定 `instance_id` 回填编排。
3. 组装本地请求文件：`manage_type=existed_instance` 与
   `existing_instance{instance_id, database_name:"root", database_pwd}`，数据库
   密码只入文件。
4. 预览与确认提交：自动创建应用组（8443 入方向三选一、5432 出方向指向实例
   子网 CIDR），实例自身安全组不动；启用存储时同样确保 OBS 桶；回填注入后
   一次提交。
5. 回显 `application_id` 与应用工作流 ID（无实例任务），经
   `show_supabase_creation_progress` 跟踪至就绪。
6. 验证与创建后动作与新建实例场景一致。

### 场景三：EIP 创建与绑定

**采购**：`create_supabase_eip` 空闲优先（`prefer_idle=true`）——先列出未绑定 EIP
供用户选定，选定后直接用于绑定、不新建；无空闲时按基线新建：按需购买（包周期返回
控制台订单）、全动态 BGP（`publicip.type=5_bgp`）、独享带宽（`share_type=PER`）
5-1000M、推荐 300M，并自动打标 USAGE_FOR。

**绑定**：`bind_supabase_eip` 执行三重校验——`instance_id` 必须为 in32 结尾的
Supabase 应用 ID 且在本环境应用列表内、`public_ip_id` 为规范 UUID、`public_ip`
为合法 IPv4——全部通过后经 RDS AttachEip 绑定。

绑定成功后必须经 `update_supabase_auth_config` 同步 `api_external_url`（邮箱链接与
OAuth 回调依赖该地址），并探活验证。

需要 HTTPS 时，SSL 证书可经本服务获取，无需到控制台购买：`list_ssl_certificates`
盘点账号已有证书（SCM 全局服务）供复用；`purchase_supabase_ssl_cert` 两段式购买并
申请——免费档 DV_SSL_CERT_BASIC 推荐，付费档生成待支付订单，纯 EIP 公网 IP 证书
仅支持文件验证；取得 `cert_id` 后经 `change_supabase_ssl` 开启。

### 场景四：应用与托管实例运维管理

上线后的日常运维——应用启停与重启、托管实例详情/启停/重启、安全组换绑、应用改密、
Key 重置与 SSL 开关——共用统一节奏：**操作前核对**（`show_supabase_application`
或 `show_supabase_managed_instance` 确认目标状态与进行中动作，状态护栏不满足即拦截
并如实转述）→ **两段式提交**（`confirm=false` 预览取 `plan_id`，确认后一次提交）→
**任务跟踪**（受理返回 `job_id`/`workflowId`，经 `show_operation_job_status` 跟踪至
终态）→ **回查**（只读工具确认业务结果）。启停与重启短暂影响可用性，建议低峰执行。

#### 应用启停与重启

`start_supabase_application` 仅停止态可受理，且不自动拉起托管实例（实例状态异常
可能启动失败）；`stop_supabase_application` 仅运行态可受理，停止期间应用功能不可用，
不停托管实例、实例继续计费；`restart_supabase_application` 仅运行态可受理，重启内部
组件、短暂服务中断并释放内存缓存，已停止应用须先启动。

#### 托管实例详情与启停重启

`show_supabase_managed_instance` 与启停重启三工具均以 `application_id` 入参，目标
实例强制解析自应用的 `managed_instance` 字段——不接受裸 `instance_id`，杜绝误操作
独立数据库实例。详情查询返回引擎/版本/instance_status 语义/规格/磁盘/可用区/进行中
动作，附计费与十五天自动启动说明。停止仅 normal 且无进行中操作、仅超高IO/SSD云盘/
极速型SSD 的按需实例可停（专属云不支持）：VM 停止计费，EIP/存储/备份继续计费，十五
天内未开启将于可维护时段自动启动，已停止实例删除不进回收站，主实例连带只读实例；
启动仅 shutdown 可受理、可能因资源不足失败；重启仅 normal 未冻结且无进行中操作，
重启期间实例不可用。**先启实例、再启应用**是正确顺序——启动应用不会自动拉起实例。

#### 安全组换绑

`change_supabase_security_group` 支持三目标（应用自身/托管实例/挂载已有实例场景的
待挂载实例），按**多组全量替换**执行——清单即最终清单，未列入的既有组被摘除，须保留
的组一并列入；摘掉承载 8443/5432 放行的组会导致应用不可访问。实例处于创建、数据库
升级、变更规格、创建/删除用户状态时不能设置。本工具决定目标绑哪些组；组内规则增删
仍走 `add_supabase_security_group_rule` / `delete_supabase_security_group_rule`。
受理返回 workflowId，经 `show_operation_job_status` 跟踪至终态。

#### 应用密码修改与 Key 重置

`change_supabase_application_password` 仅修改**应用登录密码**（dashboard 用户
supabase）；托管实例 root 登录密码不在本工具范围，实例密码经控制台实例管理修改；
修改后旧密码会话失效；新密码经本地请求文件承载，不进对话。`reset_supabase_api_key`
重置指定 Key（异步）：旧 Key 逐渐失效、新 Key 是一条新记录，新值经
`deliver_supabase_api_key` 重新交付，提前告知下游会断。

#### SSL 开关

`change_supabase_ssl` 开启需证书 ID（获取三路径见场景三），关闭必须不带证书；切换会
闪断，建议低峰执行，生效后提醒同步回调地址协议。EIP 绑定/解绑、存储桶轮换与注册
开关等其余日常变更同样按上述统一节奏执行。

### 场景五：应用删除（关联 PG 实例）

`delete_supabase_application` 的 `delete_managed_instance` 为必选项：`false` 仅删
应用，托管实例保留并继续计费；`true` 应用与实例并发双删——实例删除不可逆，仅
pay-per-use 可级联，预付费须先在控制台退订。删除前执行四层校验：实例归属、云端
`managed_instance` 现状复核、实例未被其他应用挂载、预付费拦截。提交后返回双任务
ID，经 `wait_operation_job_complete` 跟踪到终态并复查资源。

托管实例亦可经 `delete_supabase_managed_instance` 在应用存续时单独拆除，同样执行
四层校验。自动创建的安全组经 `delete_supabase_security_group` 按标签门清理：仅
允许删除带 `AUTO_CREATE=true`/`USE_FOR=Supabase` 双标签且无引用的安全组。

### 场景六：购买方式

RDS Supabase 应用公测期间免费，费用仅产生于托管实例；购买方式在创建请求
`managed_instance.charge_info` 中确定。

#### 计费边界（应用免费，实例计费）

- **应用本身**：公测期免费，不产生任何费用。
- **托管实例**：唯一计费主体——按需按实际使用计费，包周期按订购时长计费。
- 创建返回 `order_id` 表示包周期订单已创建、资源尚未开通；待支付订单不代表
  实例已开通，出现创建任务（`job_id`）才开始建资源。

#### 购买方式选择（强烈建议按需）

- **按需（postPaid，强烈建议）**：`charge_info` 仅携带 `charge_mode`；随用随停，
  试运行与变更期成本可控，删除实例即停止计费。
- **包周期（prePaid）**：`period_type` 为字符串 `month`（时长 1-9 个月）或
  `year`（1-3 年）；创建返回订单，经订单工具支付后才开始建资源；适合长期
  稳定运行。
- 提交前先取得用户对购买方式与费用的明确授权。

#### 包周期订单支付

1. 创建返回 `order_id` 后，先 `get_supabase_order(order_id)` 查询订单状态、
   金额、币种与明细（默认 20 条，`marker` 分页）；`amount_after_discount` 为
   优惠后、不含券与卡的金额，金额须结合返回币种与度量单位解释。
2. 核对并取得用户对准确金额与币种的授权后，调用
   `pay_supabase_order(order_id, expected_amount, currency, confirm=true)`：
   `expected_amount` 必须同时等于 `official_amount` 与 `amount_after_discount`——
   两者不同即为存在折扣或券，工具拒绝支付以防丢失优惠，此类订单请在费用中心
   处理；托管账户的最终扣款以账单为准。
3. 单次确认单次提交，不自动重试；返回 `payment_submitted` 与
   `payment_verified`，支付后复查订单状态与支付时间确认到账。超时等异常可能
   使提交结果未知（`payment_submitted=false`）：先查询同一订单，不自动再次付款。
4. 支付完成、订单开通后出现创建任务，再按场景二跟踪创建进度并验证。

#### 包周期订单取消

1. 弃用未支付订单：先 `get_supabase_order` 确认订单准确，再
   `cancel_supabase_order(order_id, confirm=true)`。
2. 服务重新核验云端待支付状态、产品范围与全部明细，仅未支付订单可取消；取消
   不可逆；已取消订单返回幂等结果。
3. 返回 `cancellation_verified`；为 false 时继续用 `get_supabase_order` 查询，
   不盲目重复提交。已支付资源须走控制台退订流程，本工具不受理。

## 可用工具

全部写工具执行两阶段确认：先以预览模式返回变更内容与计划编号，经确认后才真正提交。
涉及密码、凭据等秘密的工具不接收明文，秘密由操作方预先写入本地请求文件，工具仅凭
别名引用。

| 工具 | 场景 | 风险 | API 文档 |
|---|---|---|---|
| `get_supabase_capabilities` | 查看服务能力与操作边界 | READ | - |
| `list_supabase_applications` | 分页浏览应用，可过滤排序 | READ | [ListSupabaseApplications](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplications) |
| `show_supabase_application` | 查应用详情与接入素材 | READ | [ShowSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ShowSupabaseApplication) |
| `list_supabase_api_keys` | 查 Key 元数据，不返回值 | READ | [ListSupabaseApplicationApiKeys](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplicationApiKeys) |
| `reset_supabase_api_key` | 重置 Key，旧 Key 渐进失效 | DANGEROUS | [ResetSupabaseApplicationApiKey](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ResetSupabaseApplicationApiKey) |
| `deliver_supabase_api_key` | Key 值落受保护本地文件 | DANGEROUS | [ShowSupabaseApplicationApiKeyValue](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ShowSupabaseApplicationApiKeyValue) |
| `show_supabase_auth_config` | 查认证配置基线 | READ | [ShowSupabaseApplicationAuthConfig](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ShowSupabaseApplicationAuthConfig) |
| `update_supabase_auth_flags` | 开关注册与匿名访问 | WRITE | [ModifySupabaseApplicationAuthConfig](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationAuthConfig) |
| `update_supabase_auth_config` | 配置邮箱/GitHub 登录与模板 | WRITE | [ModifySupabaseApplicationAuthConfig](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationAuthConfig) |
| `update_supabase_storage` | 对接或轮换 OBS 存储 | WRITE | [ModifySupabaseApplicationStorage](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationStorage) |
| `discover_supabase_storage` | OBS 获取两选择与凭证检测 | READ | `KooCLI OBS ls` |
| `discover_supabase_create_basic_options` | 应用要素发现，规格分组展示 | READ | [ListSupabaseApplicationFlavors](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplicationFlavors) |
| `plan_supabase_creation_arrangement` | 端到端创建编排与参数基线 | READ | 实时组合（发现工具的只读查询） |
| `list_supabase_flavors_with_azs` | 查应用规格与可用区售卖 | READ | [ListSupabaseApplicationFlavors](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplicationFlavors) |
| `list_supabase_manageable_instances` | 查可挂载的 PG 实例 | READ | [ListSupabaseManageableInstances](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseManageableInstances) |
| `list_db_instance_engine_versions` | 查托管实例引擎版本 | READ | [ListDatastores](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListDatastores) |
| `list_db_instance_flavors_with_azs` | 查实例规格与可用区售卖 | READ | [ListFlavors](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListFlavors) |
| `list_db_instance_storage_types` | 查磁盘类型与兼容规格 | READ | [ListStorageTypes](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListStorageTypes) |
| `discover_db_instance_for_create` | 实例来源发现，规格分组展示 | READ | 组合查询（ListDatastores/ListFlavors/ListStorageTypes）+ ListManageableInstances |
| `discover_network_for_create` | 网络选址与安全组规格 | READ | [ListVpcs](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ListVpcs) + [ListSubnets](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ListSubnets) |
| `create_supabase_with_new_instance` | 新建实例场景创建（推荐） | WRITE | [CreateSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=CreateSupabaseApplication) |
| `create_supabase_link_exist_instance` | 挂载已有实例创建应用 | WRITE | [CreateSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=CreateSupabaseApplication) |
| `delete_supabase_application` | 删应用，实例去留必选 | DANGEROUS | [DeleteSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=DeleteSupabaseApplication) |
| `delete_supabase_managed_instance` | 单独拆除托管实例 | DANGEROUS | [DeleteInstance](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=DeleteInstance) |
| `start_supabase_application` | 启动已停止的应用 | DANGEROUS | [StartSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StartSupabaseApplication) |
| `stop_supabase_application` | 停止应用，实例继续计费 | DANGEROUS | [StopSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StopSupabaseApplication) |
| `restart_supabase_application` | 重启运行中的应用 | DANGEROUS | [RestartSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=RestartSupabaseApplication) |
| `show_supabase_managed_instance` | 查托管实例详情与状态 | READ | [ListSimplifiedInstances](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSimplifiedInstances) |
| `stop_supabase_managed_instance` | 停托管实例，VM 停计费 | DANGEROUS | [StopInstance](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StopInstance) |
| `start_supabase_managed_instance` | 开启已停止的托管实例 | DANGEROUS | [StartupInstance](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StartupInstance) |
| `restart_supabase_managed_instance` | 重启托管实例，低峰执行 | DANGEROUS | [StartInstanceRestartAction](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StartInstanceRestartAction) |
| `get_supabase_order` | 查订单状态金额与明细 | READ | [ShowCustomerOrderDetails](https://console.huaweicloud.com/apiexplorer/#/openapi/BSS/doc?api=ShowCustomerOrderDetails) |
| `pay_supabase_order` | 核对后余额支付订单 | DANGEROUS | [PayOrders](https://console.huaweicloud.com/apiexplorer/#/openapi/BSS/doc?api=PayOrders) |
| `cancel_supabase_order` | 取消待支付订单 | DANGEROUS | [CancelCustomerOrder](https://console.huaweicloud.com/apiexplorer/#/openapi/BSS/doc?api=CancelCustomerOrder) |
| `change_supabase_ssl` | 开关应用 SSL | WRITE | [SwitchSupabaseApplicationSsl](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=SwitchSupabaseApplicationSsl) |
| `plan_supabase_ssl` | SSL 切换前规划评估 | READ | - |
| `list_ssl_certificates` | 盘点已有 SSL 证书 | READ | - |
| `purchase_supabase_ssl_cert` | 两段式购买并申请证书 | DANGEROUS | - |
| `create_supabase_eip` | EIP 空闲优先采购 | WRITE | [CreatePublicip](https://console.huaweicloud.com/apiexplorer/#/openapi/EIP/doc?api=CreatePublicip) |
| `bind_supabase_eip` | EIP 三重校验绑定 | WRITE | [AttachEip](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=AttachEip) |
| `create_supabase_new_obs` | 新建私有 OBS 桶 | WRITE | `KooCLI OBS mb` |
| `change_supabase_eip` | 绑定或解绑 EIP | WRITE | [SwitchSupabaseApplicationEipBind](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=SwitchSupabaseApplicationEipBind) |
| `change_supabase_application_password` | 改应用登录密码，不涉实例 | DANGEROUS | [ModifySupabaseApplicationPassword](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationPassword) |
| `list_supabase_security_groups` | 浏览安全组列表 | READ | [ListSecurityGroups](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ListSecurityGroups) |
| `show_supabase_security_group` | 查安全组详情与规则 | READ | [ShowSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ShowSecurityGroup) |
| `create_supabase_security_group` | 建专用组并打双标签 | WRITE | [CreateSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=CreateSecurityGroup) |
| `add_supabase_security_group_rule` | 新增规则，拒收全 0 入 | DANGEROUS | [CreateSecurityGroupRule](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=CreateSecurityGroupRule) |
| `delete_supabase_security_group_rule` | 删规则收窄开放面 | DANGEROUS | [DeleteSecurityGroupRule](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=DeleteSecurityGroupRule) |
| `delete_supabase_security_group` | 删组，标签门防误删 | DANGEROUS | [DeleteSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=DeleteSecurityGroup) |
| `change_supabase_security_group` | 换绑安全组，多组全量替换 | DANGEROUS | [SetSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=SetSecurityGroup) |
| `show_operation_job_status` | 查询异步任务状态 | READ | [ListJobInfo](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListJobInfo) |
| `show_supabase_creation_progress` | 跟踪应用创建全阶段 | READ | - |
| `wait_operation_job_complete` | 有界轮询任务至终态 | READ | [ListJobInfo](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListJobInfo) |

完整 API 参考见[华为云 RDS API 文档](https://support.huaweicloud.com/api-rds/rds_01_0002.html)；
部分 Supabase 接口晚于已发布目录——当 API Explorer 缺少某接口时，以本服务实际行为为准。

## 使用指南

应用的启动、停止与重启均为异步操作：受理返回 `job_id` 后用 `show_operation_job_status` 跟踪至终态再回查应用；停止不会停止托管实例（实例继续计费），启动不自动拉起实例；重启短暂中断，建议低峰期执行。

托管实例的停止与重启同为异步操作，同样以 `show_operation_job_status` 跟踪至终态、以 `show_supabase_managed_instance` 回查实例状态：目标实例强制解析自该应用的 `managed_instance` 字段（不接受裸 `instance_id`，杜绝误操作独立数据库实例）；仅超高IO/SSD云盘/极速型SSD 的按需实例可停止（专属云不支持），VM 停止计费但 EIP/存储/备份继续计费，默认停止十五天、十五天内未开启将于可维护时段自动启动；停止主实例同时停止只读实例，重启亦同步作用于只读实例；停止/重启期间实例不可用，应用功能将受影响（应用仍会产生请求失败）；可能因资源不足开启失败。**先启实例再启应用**是正确顺序——启动应用不会自动拉起托管实例。

### 前置条件

1. Python 3.10+；使用 uvx 时安装 [uv](https://docs.astral.sh/uv/)。
2. 具有所需最小权限的华为云凭证（见[权限建议](#权限建议)）。
3. 使用安全组工具时：本机安装 KooCLI 并完成隐私协议（见
   [KooCLI 协同](#koocli-协同)）。

### 安装

**uvx 直接运行（推荐，git 仓库为唯一规范来源）：**

```bash
uvx --from "git+https://github.com/huaweicloud/rds-supabase-fullstack#subdirectory=server/mcp_server_rds_supabase_mgr" \
  mcp-huaweicloud-rds-supabase-mgr
```

服务未发布到 PyPI；PyPI 上的同名第三方包不是本服务，禁止安装。

**克隆开发：**

```bash
git clone https://github.com/huaweicloud/rds-supabase-fullstack.git
cd rds-supabase-fullstack/server/mcp_server_rds_supabase_mgr
uv sync
uv run mcp-huaweicloud-rds-supabase-mgr          # stdio（默认）
uv run mcp-huaweicloud-rds-supabase-mgr -t streamable-http
```

`mcp-huaweicloud-rds-supabase-mgr` 为规范入口；旧入口 `mcp_server_supabase` 保留
过渡，两者等价。慢网络下 uvx 启动超时的处置见
[技能安装手册](../../skills/huaweicloud-supabase/rds-supabase-mgr-mcp/references/install.md)。

### 诊断 CLI

```bash
uv run python -m mcp_server_supabase.diagnostics check       # 只检查配置格式与依赖
uv run python -m mcp_server_supabase.diagnostics offline     # 离线 stdio 自检
# 从凭据自动发现项目与候选 RDS 入口（REST token 或 AK/SK 二选一）：
uv run python -m mcp_server_supabase.diagnostics discover
uv run python -m mcp_server_supabase.diagnostics discover --probe   # 追加只读可达性探测
# 仅在已授权测试环境执行真实只读检查：
uv run python -m mcp_server_supabase.diagnostics readonly --allow-cloud-read
```

`discover` 联调 IAM 查询项目清单，按区域推导候选入口并列出 `suggested_env`
供勾选；显式配置的 `SUPABASE_RDS_ENDPOINT` 优先。探测可达不等于权限与生产验收。
诊断 CLI 不提交云写操作，摘要不含资源值与凭据。

## 配置

### 环境变量

凭据模式二选一：**REST token 模式**（默认，`HUAWEICLOUD_AUTH_TOKEN`）或
**sdk_core 模式**（`SUPABASE_TRANSPORT=sdk_core` + AK/SK）。凭据经可信宿主环境
注入，不作为工具参数。

| 变量 | 必填 | 说明 | 默认值 |
|---|---|---|---|
| `SUPABASE_RDS_ENDPOINT` | 否 | 原生 RDS HTTPS 服务入口（不含路径/查询/用户信息；非 Console 或 /rest 代理）。缺省时由 `HUAWEICLOUD_REGION` 推导标准区域入口 `https://rds.<region>.myhuaweicloud.com`；也可由 `diagnostics discover` 从凭据推导生成 | 按区域推导 |
| `HUAWEICLOUD_PROJECT_ID` | 否 | 目标项目 ID；缺省时通过 IAM 按 `HUAWEICLOUD_REGION` 自动发现（需 AK/SK 具备项目列表权限；子项目账号请显式配置） | IAM 发现 |
| `HUAWEICLOUD_AUTH_TOKEN` | REST 模式必填 | 外部预置的服务 Token，每次请求读取 | - |
| `SUPABASE_TRANSPORT` | 否 | 设为 `sdk_core` 启用华为 SDK Core 签名模式 | REST token |
| `HUAWEICLOUD_ACCESS_KEY` | sdk_core 模式必填 | 账号 AK | - |
| `HUAWEICLOUD_SECRET_KEY` | sdk_core 模式必填 | 账号 SK | - |
| `HUAWEICLOUD_SECURITY_TOKEN` | 否 | STS 临时凭据 token | - |
| `HUAWEICLOUD_REGION` | 否 | 区域：安全组工具与 RDS 服务入口推导共用；子项目解析由 hcloud profile 处理 | - |
| `HCLOUD_BIN` | 否 | KooCLI 二进制路径覆盖（固定目录与 PATH 之外的显式指定） | 自动定位 |
| `SUPABASE_ENABLE_WRITES` | 否 | 云写开关；`true` 才能执行云侧写操作 | `false` |
| `HUAWEICLOUD_MCP_READ_ONLY` | 否 | `true` 拦截所有 WRITE/DANGEROUS 工具 | `false` |
| `SUPABASE_STATE_FILE` | 否 | 本地执行记录（SQLite）路径；跨重启保持同一记录 | 用户本地状态目录 |
| `SUPABASE_REQUESTS_FILE` | 否 | 敏感请求本地引用注册表（操作方预置） | - |
| `REQUESTS_CA_BUNDLE` | 否 | 自定义可信 CA（PEM 文件） | - |
| `HUAWEICLOUD_MCP_PROTECTED_IDS` | 否 | 护栏：受保护资源 ID（逗号分隔，命中即 block） | 空 |
| `HUAWEICLOUD_MCP_PROTECTED_NAMES` | 否 | 护栏：受保护资源名称（逗号分隔，命中即 block） | 空 |
| `HUAWEICLOUD_MCP_PROTECTED_TAGS` | 否 | 护栏：受保护标签（逗号分隔 `k` 或 `k=v`） | 空 |
| `HUAWEICLOUD_MCP_GUARDRAILS_CONFIG` | 否 | 复杂规则文件 `guardrails.yaml` 路径 | 空 |
| `HUAWEICLOUD_MCP_AUDIT_FILE` | 否 | 审计 JSONL 文件路径（审计始终开启，默认写 stderr） | 空 |
| `MCP_SERVER_PORT` | 否 | streamable-http 端口 | `8000` |
| `MCP_SERVER_HOST` | 否 | streamable-http 绑定地址 | `0.0.0.0` |

### 安全护栏

全部写工具执行预览/确认双段：`confirm=false` 先持久化十分钟计划并返回 `plan_id`，
复核后以相同参数 `confirm=true` + `plan_id` 提交；参数、项目、服务地址或凭据任一
变更都须重新预览确认。SQLite 本地执行记录（`SUPABASE_STATE_FILE`）登记每笔计划与
执行状态：提交超时或结果未知时直接查询操作任务与目标资源核对，任何已提交的计划
不得重复提交，防止重复执行。

密码、SMTP、GitHub、OBS 等敏感字段不进入对话，由操作方预先写入本地请求注册表
（`SUPABASE_REQUESTS_FILE`），工具仅凭别名引用，不接受明文。云写开关
（`SUPABASE_ENABLE_WRITES`，默认关闭）与只读拦截（`HUAWEICLOUD_MCP_READ_ONLY`）
独立生效，均不可由 Agent 自行修改。任务 `completed` 仅表示云 API 受理，业务结果
须回查资源确认。

保护名单经 `HUAWEICLOUD_MCP_PROTECTED_*` 环境变量或 `guardrails.yaml` 配置，可按
工具名、风险级别、资源 ID、名称正则与标签执行 block/confirm/warn。护栏为参数级
匹配：仅存在于云侧而未出现在工具参数中的保护属性无法命中，建议主动配置保护名单。

`guardrails.yaml` 示例：

```yaml
version: 1
rules:
  - id: protect-prod-supabase
    match:
      tools: ["delete_supabase_application"]
      risks: [DANGEROUS]
      resources:
        name_patterns: ["^prod-"]
    action: block
    message: 生产 Supabase 应用受保护，请联系运维。
```

### KooCLI 协同

安全组 VPC 六个工具（查列表/详情、建组、加规则、删规则、删组）已内置 KooCLI
能力，开箱即用：原生 RDS 入口不代理 VPC API，工具内部经本机 KooCLI（`hcloud`）调用
VPC v3 操作，自动完成凭据注入与结果解析，并提供预览确认、来源标签与误删防护。
更换目标绑定的安全组走 `change_supabase_security_group`（RDS SetSecurityGroup，不经
KooCLI）：多组全量替换——清单即最终清单，未列入的既有组被摘除，须保留的组一并列入，
替换后 8443/5432 放行缺失会导致应用不可访问；组内规则的增删仍走既有规则工具。
使用原则：优先用本服务工具，工具未覆盖的场景再用 KooCLI 原生命令。

| 场景 | 用什么 |
|---|---|
| 安全组全部常规操作（查列表/详情、建组、加/删规则、删组、换绑绑定） | 本服务工具 |
| 放行 0.0.0.0/0 全网入方向（工具按设计拒绝，需用户明确确认） | KooCLI 原生命令 |
| 工具明确不支持的边缘操作（如地址组管理） | KooCLI 原生命令 |

运维排障要点：

- **前置条件**：本机安装 hcloud 并接受首次运行隐私协议，安装方法见技能
  [INSTALL.md 第四节](../../skills/huaweicloud-supabase/rds-supabase-mgr-mcp/INSTALL.md)。
- **二进制定位**：`HCLOUD_BIN` 环境变量 → 固定安装目录 → PATH，每次调用重新定位，
  安装后无需重启会话。
- **凭据注入**：`HUAWEICLOUD_ACCESS_KEY` 与 `HUAWEICLOUD_SECRET_KEY` 同时存在时
  按命令注入，否则回落 hcloud profile；REST Token 模式须本机配置 hcloud profile
  （`hcloud configure init`），否则安全组工具报凭据缺失。
- **区域与项目**：区域取 `HUAWEICLOUD_REGION`；项目由 KooCLI 按区域默认项目解析，
  子项目账号须在 profile 配置 `--cli-project-id`。
- **错误透传**：VPC 后端 error_code/error_msg/request_id 原样透传；隐私协议未接受、
  二进制缺失、超时各有专用错误码与处置指引。
- **来源标记**：建组自动打 `AUTO_CREATE=true` 与 `USE_FOR=Supabase` 双标签；整组
  删除校验双标签匹配，非本流程创建的安全组一律拒绝。

## 使用 UVX 运行

AgentArts 及其他客户端的 UVX stdio 配置：

```json
{
  "mcpServers": {
    "rds-supabase-mgr-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/huaweicloud/rds-supabase-fullstack#subdirectory=server/mcp_server_rds_supabase_mgr",
        "mcp-huaweicloud-rds-supabase-mgr"
      ],
      "env": {
        "HUAWEICLOUD_AUTH_TOKEN": "<服务 Token>",
        "HUAWEICLOUD_MCP_READ_ONLY": "true",
        "SUPABASE_ENABLE_WRITES": "false"
      }
    }
  }
}
```

AgentArts 支持 UVX stdio 与 Streamable HTTP。远程模式启动命令：

```bash
mcp-huaweicloud-rds-supabase-mgr -t streamable-http
```

默认监听 `0.0.0.0:8000`，端点为 `/mcp`；生产部署应在前置网关配置 HTTPS 与客户端
鉴权。服务未发布到 PyPI，UVX 始终经 git 仓库拉取（见[安装](#安装)）。

## 示例

### 工作流一：从零创建一个能访问的应用

1. 调用 `plan_supabase_creation_arrangement(manage_type, az_code, ...)`，按托管
   来源决策与意图（含 `needs_storage` 存储答复）取得端到端编排基线：必选模块参数
   固化、公网访问（EIP）与 SSL 配置两个独立模块、OBS 桶对接方案与步骤编号的创建
   流程。
2. 按编排逐步执行：网络就绪（默认推荐场景按 `default_create` 建网）→ 存储就绪
   （`discover_supabase_storage` 定复用或新建，新建桶走 `create_supabase_new_obs`）
   → 本地请求文件（含 root 密码、存储凭据等秘密）。
3. 按托管来源二选一提交（安全组由创建工具自动创建注入，无需手填
   `security_group_id`）：新建实例（推荐）走
   `create_supabase_with_new_instance(request_ref, confirm=false)`，挂载已有实例走
   `create_supabase_link_exist_instance(request_ref, confirm=false)`。预览 → 脱敏
   参数交用户核对 → 相同参数 `confirm=true` + `plan_id` 提交。
4. 用返回的工作流 ID 调用 `show_supabase_creation_progress`（或
   `show_operation_job_status` / `wait_operation_job_complete` 有界等待）到终态。
5. 回查 `show_supabase_application`：公网未开通时按场景三执行 EIP 采购与绑定并
   同步 `api_external_url`，再以 `list_supabase_api_keys` +
   `deliver_supabase_api_key` 交付接入信息。

### 工作流二：给应用开安全组端口

1. `create_supabase_security_group` 预览 → 确认，创建带用途描述的专用组。
2. `add_supabase_security_group_rule` 加 8443 入方向（来源网段）与 5432 出方向
   （`direction='egress'`），各自预览 → 确认。
3. `show_supabase_security_group` 回读规则，核对方向与端口。
4. 需要收回时 `delete_supabase_security_group_rule`（先核对该组未被共用）；
   整组下线走 `delete_supabase_security_group`（删前核对无实例/NIC 引用）。

所有写接口都可能异步执行。MCP 调用成功只表示云 API 已受理，不表示资源变更已经
完成。

## 客户端兼容性

| 客户端 | 接入方式 | 说明 |
|---|---|---|
| opencode | stdio | 项目级 `opencode.json`，`mcp.servers.*` 结构；保存即自动连接 |
| Claude Code | stdio | 项目级 `.mcp.json`；会话内批准一次即连 |
| Claude Desktop / Cursor / Trae | stdio | `command`/`args`/`env` 配置 |
| CodeArts | stdio | 项目级 `mcp_settings.json`（设置 → MCP 工具）；改既有条目需手动重启 |
| 远程模式 | Streamable HTTP | `mcp-huaweicloud-rds-supabase-mgr -t streamable-http`，端点 `/mcp`；生产部署应前置网关配置 HTTPS 与鉴权 |

不提供旧版 SSE 传输。

## 权限建议

- **只读发现**：RDS 应用/规格/可托管实例查询 + IAM 项目查询；创建选型所需的
  VPC、子网、可用区、EIP 查询经 KooCLI，权限随 KooCLI profile。
- **写操作**：只增加实际启用工具对应的 RDS 应用创建/变更权限与 VPC 安全组写权限。
- **危险操作**：删除类、改密、Key 重置建议使用单独身份或临时授权，并配合
  `HUAWEICLOUD_MCP_PROTECTED_*` 保护名单与确认规则。
- 不要为方便而把长期管理员凭证配置到 MCP 客户端；生产环境建议使用临时安全凭证。

## 开发、测试和发布

```bash
uv sync --all-groups
uv run ruff check src tests
uv run pytest                       # 默认不访问云上资源，80% 覆盖率门槛
uv run python tests/smoke_stdio.py  # 离线 stdio 冒烟
```

Live 验证只能在专用测试账号中显式启用；创建计费资源时必须在失败路径也执行清理，
并确认删除任务到达终态。发布前检查 wheel 元数据、全新 Python 3.10 环境安装与
MCP 工具列表。

## 贡献和支持

贡献流程、安全报告方式和版本变更分别见仓库根目录的 `CONTRIBUTING.md`、
`SECURITY.md` 和 `CHANGELOG.md`。普通问题可使用 GitHub Issue；凭证泄露和安全
问题不得提交到公开 Issue。

## 深入文档

- [用户指南](docs/USER_GUIDE.md)——安装、验证与自然语言操作全流程
- [工具契约](docs/TOOL_CONTRACTS.md)——输入输出与确认语义的权威定义
- [恢复规则](docs/RECOVERY.md)、[核对契约](docs/RECONCILIATION.md)——异常分流与 Auth 计划核对
- [本地秘密输入输出](docs/LOCAL_REQUESTS.md)——敏感请求引用机制
- [SDK 模式](docs/SDK.md)、[迁移说明](docs/MIGRATION.md)
- [docs/legacy/](docs/legacy/)——已归档的 Windows 离线交付流程

## 许可证

MIT
