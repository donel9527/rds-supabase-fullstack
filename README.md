# huaweicloud-mcp

> **语言切换：** [English](./README_en.md) | 中文

华为云 MCP Server 共享仓库：为华为云服务提供场景化的 MCP 工具与配套 Agent Skills，
支持本地（stdio）与远程（streamable-http）部署，统一安全护栏与输出协议。

## MCP Server 列表

### 管理与治理

- **[RFS MCP](server/mcp_server_rfs/README.md)**：资源编排服务——HCL 模板一键部署为资源栈、
  执行计划干跑预览、失败部署根因诊断、安全下线。
- **[RC MCP](server/mcp_server_rc/README.md)**：资源中心——全局资源检索与分组管理、资源关系
  查询、ResourceQL 高级查询。

### 数据库

- **[RDS Supabase 管理面 MCP](server/mcp_server_rds_supabase_mgr/README.md)**（`mcp-huaweicloud-rds-supabase-mgr`）：华为云 RDS Supabase
  应用全生命周期管控——创建编排与参数基线（托管实例两种来源、规格分组发现、网络与安全组
  规划）、场景化创建（资源自动准备回填、一次提交）、EIP 采购绑定、SCM SSL 证书购买、
  OBS 存储对接、认证与登录配置、API Key 受控交付、包周期订单、应用与托管实例启停重启、
  安全组换绑、日常变更与删除收尾；53 个工具全部预览/确认两段式，任务统一跟踪。
- **[RDS Supabase 数据面 MCP](server/mcp_server_rds_supabase/README_zh.md)**（`mcp-server-huaweicloud-rds-supabase`）：RDS PostgreSQL 上
  自建 Supabase 栈的库内操作——表结构与数据查询、RLS 策略、SQL 执行（init.sql 迁移
  部署）、GoTrue 用户管理、存储桶配置、advisors 诊断。与管理面分开交付、互不替换，
  共用仓库核心库（libs/huaweicloud_mcp_core）与独立 uv 锁，支持 Docker 部署。

## Agent Skills

`skills/` 目录提供按 Agent Skills 开放标准编写的技能，两条安装通道任选：

```bash
npx skills add huaweicloud/rds-supabase-fullstack --skill <技能名>   # 主路径（Node.js ≥ 22.20）
# 或按各技能 INSTALL.md 的 git 克隆 / ZIP 归档方式
```

### RDS Supabase 技能族（七个）

围绕 RDS Supabase 平台的应用全生命周期，各技能单一职责、可独立安装：

| 技能 | 定位 |
|---|---|
| [rds-supabase-mgr-mcp](skills/huaweicloud-supabase/rds-supabase-mgr-mcp/SKILL.md) | 管理面 MCP 操作指引——十大场景工作流、参数契约速查与安全纪律 |
| [rds-supabase-mcp](skills/huaweicloud-supabase/rds-supabase-mcp/SKILL.md) | 数据面 MCP 使用技能——安装配置、工具用法与 init.sql 五步部署 |
| [rds-supabase-usage](skills/huaweicloud-supabase/rds-supabase-usage/SKILL.md) | 平台应用开发——客户端集成、认证排查、Data API 诊断、计算选型 |
| [rds-supabase-postgres-best-practices](skills/huaweicloud-supabase/rds-supabase-postgres-best-practices/SKILL.md) | Postgres 规则库——按症状直达规则，含 RDS 部署专属规则 |
| [rds-supabase-web-build](skills/huaweicloud-supabase/rds-supabase-web-build/SKILL.md) | 全栈总指挥——一句话触发八步流水线（资源→数据面→后端→前端→托管→上线） |
| [rds-supabase-frontend](skills/huaweicloud-supabase/rds-supabase-frontend/SKILL.md) | 静态前端部署——公开读 OBS 桶、版本发布、回退与真实入口验收 |
| [rds-supabase-function-graph](skills/huaweicloud-supabase/rds-supabase-function-graph/SKILL.md) | FunctionGraph 云函数——外部对接与高安全处理的服务端承载与验证 |

### 仓库工程

- **[huaweicloud-mcp-dev](skills/huaweicloud-mcp-dev/SKILL.md)**：本仓库 MCP 服务器开发指南——
  三层架构、工具风险分级与护栏、新服务接入流程。

## 核心能力（所有服务共享）

- 简化认证：`HUAWEICLOUD_ACCESS_KEY / SECRET_KEY / REGION`，project_id 经 IAM 自动解析
- 安全护栏：风险分级（READ/WRITE/DANGEROUS）、DANGEROUS 二次确认、资源保护名单、
  输出脱敏、结构化审计（默认开启）
- 输出治理：结构化 JSON + token 预算（默认 20 条、字段白名单、超长截断）
- 只读模式：`HUAWEICLOUD_MCP_READ_ONLY=true` 一键拦截全部写操作

## 快速开始

```bash
cd server/mcp_server_rfs
uv sync
export HUAWEICLOUD_ACCESS_KEY=... HUAWEICLOUD_SECRET_KEY=... HUAWEICLOUD_REGION=cn-north-4
uv run mcp_server_rfs
```

## 开发者文档

完整开发指南见 [docs/development/](docs/development/README.md)，按功能特性拆为 10 篇：核心包逐模块 API、
工具场景化方法论、service/client 层、护栏、输出错误、三层测试、从零建服务实战、
工程化与发布。参考实现：`server/mcp_server_rfs/`；脚手架：`docs/development/template/`。

## 新服务接入

参见 [docs/08-new-service-walkthrough.md](docs/development/08-new-service-walkthrough.md)：
提 issue → 复制脚手架模板 → 三层开发 → 自测 → 双语 README → PR 审查。

## License

MIT
