English | [中文](README.md)

# rds-supabase-mcp (Huawei Cloud RDS Supabase Data Plane Skill)

The **data plane management skill** for Huawei Cloud RDS Supabase: once the instance is ready, all platform operations go through this skill — writing and five-step deployment of init.sql migration scripts (table creation, grants, RLS policies, functions), database structure and data queries, login-user management, storage configuration, row-level security (RLS) and security advisor checks, and connection and execution-plan troubleshooting.

The skill runs on the companion data plane MCP server `mcp-server-huaweicloud-rds-supabase` (38 tools, Apache-2.0, an improved Python implementation based on HenkDz/selfhosted-supabase-mcp). Core changes over the original: `execute_sql` uses an in-database hardened function (callable only by service_role, with a read-only statement whitelist); the direct database connection channel is removed — SQL runs via PostgREST RPC and user management goes through the GoTrue admin API; tools are risk-classified and support read-only mode, interception and secondary-confirmation rules, call auditing, and sensitive-value masking.

In the backend development mode, backend code is organized as init.sql migration scripts and deployed via `execute_sql` as database-layer definitions (table structures, grants, RLS policies, functions); the frontend consumes them directly through REST APIs, so the application side needs no self-built backend service.

See [SKILL.md](SKILL.md) for the execution logic.

## Capabilities Overview

### Core Workflows

| Workflow | What it covers |
|---|---|
| Instance onboarding | Once the instance is ready, dynamically connect the MCP server with three configuration items; verify with `get_project_url` / `list_tables` |
| Deploy backend definitions (five steps) | init.sql → ① pre-check (verify current state) → ② review (four mandatory checks: repeatable execution, destructive statements, RLS coverage, least privilege) → ③ deploy (whole batch in a single transaction, automatic rollback on failure) → ④ grant exposure (GRANT + `NOTIFY pgrst, 'reload schema'`) → ⑤ query confirmation (the actually queried state is authoritative) |
| SQL troubleshooting | `execute_sql` with `read_only=true` (the database layer allows only SELECT, WITH, VALUES, TABLE, EXPLAIN) |
| Security checks | Work through `get_advisors` (security/performance) item by item; re-verify with `get_rls_status` / `list_rls_policies` |
| User management | list/get/create/update/delete_auth_user (official admin API; password hashing and email confirmation are handled by GoTrue) |

### Tool Groups (38)

| Group | Representative tools |
|---|---|
| SQL execution | execute_sql (whole batch in a single transaction, automatic rollback on failure, read_only whitelist) |
| Structure queries | list_tables, list_table_columns, list_indexes, list_constraints, get_function_definition, etc. |
| Security checks | get_rls_status, list_rls_policies, get_advisors |
| Runtime troubleshooting | get_database_connections, get_database_stats, get_logs, explain_query |
| Extensions | list_extensions, list_available_extensions |
| User management | list/get/create/update/delete_auth_user |
| Storage & platform | get/update_storage_config, verify_jwt_secret, get_project_url, list_cron_jobs, get_cron_job_history, vector indexes and statistics |

Unavailable tools (4): `list_storage_buckets`, `list_storage_objects`, `list_realtime_publications`, `generate_typescript_types` — this deployment form has removed the direct database connection channel, so calling them returns a clear error explanation. See [references/related-tools.md](references/related-tools.md) for the full list.

### Security Guardrails

- Two layers of read-only: the `read_only` parameter of `execute_sql` restricts the statement types of a single call; `HUAWEICLOUD_MCP_READ_ONLY=true` intercepts all write tools at the server layer
- Risk classification (READ / WRITE / DANGEROUS lanes) with protected lists, plus interception and secondary-confirmation rules (`HUAWEICLOUD_MCP_GUARDRAILS_CONFIG`, etc.)
- Every call is recorded to an audit log (stderr, persistable via `HUAWEICLOUD_MCP_AUDIT_FILE`); values matching secret patterns in the output are masked automatically
- Full environment variable table: [references/mcp-installation-guide.md](references/mcp-installation-guide.md)

## Installation

Quick install: `npx skills add huaweicloud/rds-supabase-fullstack --skill rds-supabase-mcp` (Node.js >= 22.20; see [INSTALL.md](INSTALL.md) for details).


See [INSTALL.md](INSTALL.md).

## Usage

After installation, simply develop in normal conversation — the Agent loads the skill automatically when a scenario matches (init.sql writing and deployment, structure and data queries, user management, RLS checks, connection troubleshooting). Example trigger phrases:

> The instance is connected. Build the backend for my blog: a posts table, a categories table, RLS policies and grants — write them into init.sql and deploy.

> Check the current database's security advisors, and whether RLS coverage on public-facing tables is complete.

## License

Skill: MIT. Companion server `mcp-server-huaweicloud-rds-supabase`: Apache-2.0, derived from HenkDz/selfhosted-supabase-mcp (TypeScript; for the MIT derivation chain see the repository NOTICE).
