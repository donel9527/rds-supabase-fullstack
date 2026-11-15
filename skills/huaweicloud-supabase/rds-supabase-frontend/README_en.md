English | [中文](README.md)

# rds-supabase-frontend (Huawei Cloud OBS Static Frontend Deployment Skill)

A **frontend deployment and Supabase integration skill** for Huawei Cloud OBS static hosting: create and deploy, update, roll back, and maintain OBS static frontends (two routes: `obs-domain`, where the entry domain points directly at the bucket, or `obs-cdn`, where the entry domain is served through a CDN pulling from the bucket as origin), integrate an existing Huawei Cloud RDS Supabase (the browser calls its HTTPS API directly, so end users need no Huawei Cloud account), and prepare build environments for these tasks. The skill preserves the project's existing framework, build environment, and OBS release workflow, and introduces no separate deployment CLI.

Core discipline: snapshot before acting (read-only checks of project records, OBS configuration, artifact manifests, and entry candidates; the snapshot determines the region, bucket, route, and this round's delta); repeated releases take the fast path (single-pass upload plus batch verification when a successful record already exists and artifact hashes match); release verification defers to real-URL content, MIME type, version, and browser acceptance; when the endpoint belongs to the internal cloud (`.ulanqab.huawei.com`), internal-cloud procedures apply automatically.

For execution logic, see [SKILL.md](SKILL.md).

## Capability Overview

| Area | Coverage |
|---|---|
| Hosting routes | `obs-domain` (entry domain pointing directly at the bucket; the default) / `obs-cdn` (entry domain served through a CDN pulling from the same public bucket) |
| Deploy & update | build artifacts uploaded to a public-read OBS bucket, website configuration, domain binding, batch-GET release verification, hash-level rollback |
| Supabase integration | frontend auth flows (authentication), API calls (supabase), region selection (regions) |
| Environment adaptation | build environment preparation (build-environment), internal-cloud procedures (internal-cloud), OBS releases (obs-release) |
| Framework adaptation | builds and artifact shapes for common frameworks (frameworks), plus examples (references/examples) |

## Installation

Quick install: `npx skills add huaweicloud/rds-supabase-fullstack --skill rds-supabase-frontend` (Node.js >= 22.20; see [INSTALL.md](INSTALL.md) for details).


See [INSTALL.md](INSTALL.md).

## Usage

After installation, simply converse as usual; the Agent loads the skill automatically when a scenario matches. Example trigger phrases:

> Deploy my Vite project to Huawei Cloud OBS, serve it on my own domain, and connect it to my existing RDS Supabase.

> A fix release of my frontend is out — update the live artifacts and verify them.

## License

MIT.
