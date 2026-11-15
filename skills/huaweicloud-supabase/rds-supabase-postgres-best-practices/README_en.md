English | [中文](README.md)

# rds-supabase-postgres-best-practices (Postgres Best-Practices Rule Library)

A Postgres rules-library skill, derived from the general-purpose ruleset maintained by Supabase ("for Postgres running anywhere"), adapted for self-hosted Huawei Cloud RDS Supabase deployments (JWT claims identity resolution, the RDS parameter-template channel, extension availability, the PostgREST exposure surface), and extended with a new `rds-` prefixed category for deployment-specific rules. It contains 35 rule files across nine categories; every rule ships with Incorrect/Correct contrasts and quantified benefits.

Applicability commitment: **load this skill before writing or changing anything that lives in a Postgres database** — creating or altering tables, choosing column types, schema design, RLS policies, indexes, triggers, database functions, primary-key and UUID selection, bulk imports, and data restores. It applies equally to a single-column change and a single query. Diagnostic scenarios (slow queries, high CPU, timeouts, EXPLAIN plans, connection exhaustion, lock waits, deadlocks, table bloat, N+1, deep pagination, upsert races, slow JSONB queries, full-text search, scheduled jobs, cross-tenant data visibility) are equally covered.

See [SKILL.md](SKILL.md) for execution logic and the symptom index.

## Rule Categories

Ordered by descending impact; rule files live under `references/`:

| Priority | Category | Impact level | File prefix |
|---|---|---|---|
| 1 | Query performance (missing indexes, composite indexes, index-type selection, covering indexes, partial indexes) | CRITICAL | `query-` |
| 2 | Connection management (pooling, connection limits, prepared statements, idle timeouts) | CRITICAL | `conn-` |
| 3 | Security & RLS (multi-tenant isolation, RLS performance, least privilege) | CRITICAL | `security-` |
| 4 | Schema design (primary-key selection, constraints, column types, foreign-key indexes, identifier casing, partitioning) | HIGH | `schema-` |
| 5 | Concurrency & locks (short transactions, SKIP LOCKED, deadlock prevention, advisory locks) | MEDIUM-HIGH | `lock-` |
| 6 | Data access patterns (N+1, batch inserts, deep pagination, upsert) | MEDIUM | `data-` |
| 7 | Monitoring & diagnostics (pg_stat_statements, EXPLAIN, VACUUM/ANALYZE) | LOW-MEDIUM | `monitor-` |
| 8 | Advanced features (full-text search, JSONB indexing) | LOW | `advanced-` |
| 9 | Huawei Cloud RDS deployment specifics (JWT claims RLS, parameter templates, identity helper functions, scheduled jobs) | CRITICAL | `rds-` |

Usage: while performing SQL-related tasks, the agent locates the relevant rule file via the symptom and task index in SKILL.md, then revises the SQL according to the rule; you can also search directly with `grep -il "keyword" references/`. New rules must follow the format contract in `references/_contributing.md`. The library is agnostic about the database operation channel: SQL may be executed via the MCP `execute_sql` tool, psql, or the RDS console.

## Installation

Quick install: `npx skills add huaweicloud/rds-supabase-fullstack --skill rds-supabase-postgres-best-practices` (Node.js >= 22.20; see [INSTALL.md](INSTALL.md) for details).


See [INSTALL.md](INSTALL.md).

## Usage

After installation, simply continue normal development conversations — the agent loads the skill automatically before writing or modifying SQL, designing schemas, or troubleshooting performance issues. Example trigger phrases:

> Help me design an orders table: a million rows written per day, queried mostly by buyer and status.

> This join query keeps getting slower — optimize it and explain why.

> Write RLS policies for a multi-tenant table so users can only access their own tenant's data.

## License

MIT. Derived from [supabase/agent-skills](https://github.com/supabase/agent-skills) (commit `c9be0e9`, MIT), adapted and extended for Huawei Cloud RDS deployments.
