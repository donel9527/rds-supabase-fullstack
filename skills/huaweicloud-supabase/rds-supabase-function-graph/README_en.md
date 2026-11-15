English | [中文](README.md)

# rds-supabase-function-graph (RDS Supabase FunctionGraph Cloud Function Skill)

Carries **server-side business logic that does not fit into Postgres RPCs** for RDS Supabase web apps: transaction notifications, integration with external systems, complex domain logic, and high-security, privacy-sensitive processing. Generate zero-dependency Node.js functions → deploy them to Huawei Cloud FunctionGraph via KooCLI (`hcloud`) → expose HTTPS endpoints through a shared-edition APIG trigger → **verify Supabase GoTrue JWTs inside the function** → `fgs-gate.py` mechanically verifies security facts such as "unauthenticated requests must be rejected".

The skill is self-contained: all cloud operations go through KooCLI, with no dependency on any MCP server.

For execution logic, see [SKILL.md](SKILL.md).

## Workflow

| Stage | Coverage |
|---|---|
| Environment check | KooCLI installation and authentication verification, region/PROJECT_ID, command-surface self-calibration (live `--help` output is authoritative) |
| Logic decomposition | decision-matrix classification (items a Postgres RPC can carry fall back to a database implementation), item-by-item confirmation of the function list (trigger type / secret requirements / idempotency requirements) |
| Code generation | zero-dependency Node.js 18 boilerplate (JWT verification / CORS / idempotency / REST / error contract + local event replay) |
| Deployment | OBS private artifacts + APIG trigger (atomic KooCLI commands) |
| Security verification & release | machine-verified unauthenticated → 401 / bad JWT → 401 / valid JWT → 200 / exact-origin CORS, plus version and alias pinning |
| Frontend integration | fetch wrapper contract (self-contained in SKILL.md) + idempotent-replay E2E |

Prerequisites: KooCLI (hcloud) installed and authenticated; an existing, working RDS Supabase application (the user provides the access address); an available OBS bucket.

## Frontend Secure Call Chain (v1 · Shared-Edition APIG Route)

```
Frontend (GoTrue JWT)
  ↘ APIG trigger (auth=none, the sole v1 entry form)
      ↘ Inside the function: JWT verification (FGS_JWT_SECRET) → exact-origin CORS → idempotency → unified error contract
```

Secrets live only in function environment variables (`--cli-json-file` is assembled by the user; the agent never sees plaintext). For upgrade paths (dedicated APIG authorizer / DEW CSMS / direct VPC connection), see the appendix in `references/secret-management.md`.

## Installation

See [INSTALL.md](INSTALL.md).

## Usage

After installation, simply converse as usual. Example trigger phrase:

> Add a transaction-notification cloud function to my blog site: after an order is placed, notify the fulfillment system asynchronously, with idempotency to guard against replays.

## Assets

- `references/`: workflow-stages (playbook), project-state (functions.json contract), routing-matrix (decision matrix), cli-commands (command chains), secret-management (secret discipline)
- `template/`: zero-dependency Node.js 18 boilerplate (JWT verification / CORS / idempotency / REST / error contract + local event replay)
- `scripts/fgs-gate.py`: standalone verification gate · `tests/`: 21-case pytest suite

## License

See the [SKILL.md](SKILL.md) frontmatter.
