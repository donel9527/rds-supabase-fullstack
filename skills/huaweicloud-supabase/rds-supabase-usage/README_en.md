English | [中文](README.md)

# rds-supabase-usage (Huawei Cloud RDS Supabase Application Development Skill)

An application development skill for the self-hosted Supabase stack running on Huawei Cloud RDS PostgreSQL (Kong gateway, PostgREST Data API, GoTrue auth, Storage, Realtime, pgvector). It covers six task categories: supabase-js / @supabase/ssr client libraries and framework integration with Next.js, React, SvelteKit, Astro, and Remix; authentication and session troubleshooting (sign-in and sign-out, JWT, cookies, getSession/getUser, RLS-related errors); schema changes and init.sql deployment discipline; REST/Data API anomalies (permission denied, schema cache, 42501, timeouts, tables not visible); Storage and Realtime failures; vector search and server-side compute selection.

The skill also binds the Agent to development discipline: component versions are authoritative only as measured inside the deployment, every change must be verified, error recovery must not loop, and faults are located layer by layer (database → service containers → console logs).

For execution logic, see [SKILL.md](SKILL.md).

## Capability Overview

| Area | Coverage |
|---|---|
| Client integration | integration patterns for supabase-js / @supabase/ssr, session management across server/client components, environment variables and secret boundaries |
| Auth & sessions | sign-in/sign-out flows, JWT claims freshness, permission boundaries between `user_metadata` and `app_metadata`, session invalidation handling for token revocation and user deletion |
| Data API | the two-layer table exposure mechanism (GRANT determines visibility; RLS determines the row set), PostgREST error semantics, Kong gateway timeout characteristics |
| Schema deployment | change scripts managed in a Git directory, whole-batch single-transaction deployment via MCP `execute_sql`, key points of the five-step process (pre-check / review / deploy / grant & exposure / query confirmation) |
| Troubleshooting | symptom-to-layer triage table (42501, empty results, prepared-statement errors, slow queries, service-level errors) |
| Vector search | pgvector index inspection tools and index-type selection (HNSW/IVF/GIN) |
| Server-side compute | selection and boundaries of FunctionGraph / Postgres RPC / pg_cron / pg_net |

## Installation

Quick install: `npx skills add huaweicloud/rds-supabase-fullstack --skill rds-supabase-usage` (Node.js >= 22.20; see [INSTALL.md](INSTALL.md) for details).


See [INSTALL.md](INSTALL.md).

## Usage

After installation, simply carry on development conversations as usual; the Agent loads the skill automatically when a scenario matches (client integration, auth issues, Data API anomalies, platform debugging). Example trigger phrases:

> My Next.js app signs in with supabase-js, but getSession returns no user afterwards. Help me troubleshoot.

> My REST API query returns 42501 permission denied, but the data definitely exists. How should I handle it?

> Add RLS policies to my existing tables so that frontend users can only see their own data.

## License

MIT. Derived from [supabase/agent-skills](https://github.com/supabase/agent-skills) (commit `c9be0e9`, MIT), adapted for self-hosted Huawei Cloud RDS Supabase deployments.
