# huaweicloud-mcp

> **Language:** English | [中文](./README.md)

Huawei Cloud MCP Server shared repository: scenario-based MCP tools and companion Agent Skills for Huawei Cloud services, supporting local (stdio) and remote (streamable-http) deployment, with unified security guardrails and output protocol.

## MCP Server List

### Management & Governance

- **[RFS MCP](server/mcp_server_rfs/README_en.md)**: Resource Formation Service — one-click HCL template deployment as stacks, dry-run preview for execution plans, root-cause diagnosis for failed deployments, secure decommissioning.
- **[RC MCP](server/mcp_server_rc/README_en.md)**: Resource Center — global resource search and group management, resource relationship queries, advanced ResourceQL queries.

### Database

- **[RDS Supabase Management-Plane MCP](server/mcp_server_rds_supabase_mgr/README_en.md)** (`mcp-huaweicloud-rds-supabase-mgr`): full-lifecycle control of Huawei Cloud RDS Supabase applications — creation arrangement and parameter baselines (two managed-instance sources, grouped flavor discovery, network and security-group planning), scenario-based creation (resources auto-prepared and backfilled, one submission), EIP provisioning and binding, SCM SSL certificate purchase, OBS storage integration, auth and login configuration, controlled API-key delivery, prepaid orders, application and managed-instance lifecycle, security-group rebinding, routine changes, and clean teardown; all 53 tools run preview/confirm two-phase with unified job tracking.
- **[RDS Supabase Data-Plane MCP](server/mcp_server_rds_supabase/README.md)** (`mcp-server-huaweicloud-rds-supabase`): in-database operations for the self-hosted Supabase stack on RDS PostgreSQL — schema and data inspection, RLS policies, SQL execution (init.sql migration deployment), GoTrue user management, storage bucket configuration, advisor diagnostics. Delivered separately from the management plane — neither replaces the other; consumes the repository-shared core library (libs/huaweicloud_mcp_core) with a standalone uv lock and Docker deployment.

## Agent Skills

The `skills/` directory provides skills authored to the Agent Skills open standard. Two installation channels:

```bash
npx skills add huaweicloud/rds-supabase-fullstack --skill <skill-name>   # primary (Node.js >= 22.20)
# or the git-clone / ZIP-archive methods in each skill's INSTALL.md
```

### RDS Supabase Skill Family (seven skills)

Covering the full application lifecycle on the RDS Supabase platform; each skill has a single responsibility and installs independently:

| Skill | Focus |
|---|---|
| [rds-supabase-mgr-mcp](skills/huaweicloud-supabase/rds-supabase-mgr-mcp/SKILL.md) | Management-plane MCP operations — ten-scenario workflows, parameter-contract quick reference, safety discipline |
| [rds-supabase-mcp](skills/huaweicloud-supabase/rds-supabase-mcp/SKILL.md) | Data-plane MCP usage — installation, tooling, and the five-step init.sql deployment |
| [rds-supabase-usage](skills/huaweicloud-supabase/rds-supabase-usage/SKILL.md) | Platform application development — client integration, auth troubleshooting, Data API diagnostics, compute routing |
| [rds-supabase-postgres-best-practices](skills/huaweicloud-supabase/rds-supabase-postgres-best-practices/SKILL.md) | Postgres rule library — symptom-to-rule index with RDS-deployment-specific rules |
| [rds-supabase-web-build](skills/huaweicloud-supabase/rds-supabase-web-build/SKILL.md) | Full-stack orchestrator — one sentence triggers the eight-stage pipeline (resources → data plane → backend → frontend → hosting → go-live) |
| [rds-supabase-frontend](skills/huaweicloud-supabase/rds-supabase-frontend/SKILL.md) | Static frontend deployment — public-read OBS bucket, versioned releases, rollbacks, production URL verification |
| [rds-supabase-function-graph](skills/huaweicloud-supabase/rds-supabase-function-graph/SKILL.md) | FunctionGraph cloud functions — server-side carrier and verification for external integrations and security-sensitive processing |

### Repository Engineering

- **[huaweicloud-mcp-dev](skills/huaweicloud-mcp-dev/SKILL.md)**: development guide for MCP servers in this repository — three-layer architecture, tool risk grading and guardrails, new-service onboarding.

## Core Capabilities (Shared Across All Services)

- Simplified authentication: `HUAWEICLOUD_ACCESS_KEY / SECRET_KEY / REGION`, project_id auto-resolved via IAM
- Security guardrails: risk classification (READ/WRITE/DANGEROUS), double confirmation for DANGEROUS operations, resource protection allowlist, output desensitization, structured auditing (enabled by default)
- Output governance: structured JSON + token budget (default 20 items, field allowlist, truncation for oversized content)
- Read-only mode: `HUAWEICLOUD_MCP_READ_ONLY=true` one-click interception of all write operations

## Quick Start

```bash
cd server/mcp_server_rfs
uv sync
export HUAWEICLOUD_ACCESS_KEY=... HUAWEICLOUD_SECRET_KEY=... HUAWEICLOUD_REGION=cn-north-4
uv run mcp_server_rfs
```

## Developer Documentation

The complete development guide is available at [docs/development/](docs/development/README.md), split into 10 feature-focused documents: core package modular API, tool scenario methodology, service/client layers, guardrails, output & errors, three-tier testing, hands-on service creation from scratch, engineering & release. Reference implementation: `server/mcp_server_rfs/`; scaffold: `docs/development/template/`.

## New Service Onboarding

See [docs/08-new-service-walkthrough.md](docs/development/08-new-service-walkthrough.md): open issue → copy scaffold template → three-tier development → self-test → bilingual README → PR review.

## License

MIT
