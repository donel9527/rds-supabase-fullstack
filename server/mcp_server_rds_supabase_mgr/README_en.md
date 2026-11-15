# Huawei Cloud RDS Supabase MCP Server

[中文](README.md)

## Version

Current version: `0.4.0a49` (development prerelease); Python `3.10+`;
MCP Python SDK `2.x`; 48 tools.

## Overview

This server wraps the full lifecycle management of Huawei Cloud RDS Supabase
applications as MCP tools, covering creation arrangement and scenario-based
creation (two managed-instance sources), network and security-group
specification, EIP provisioning and binding, SSL certificate query and
purchase, OBS storage integration,
authentication and login configuration, API key delivery, prepaid orders,
application start/stop/restart, and
change and deletion. It serves AgentArts and other MCP clients; the REST-token
and SDK credential modes, over stdio and Streamable HTTP, share one tool set,
one set of safety guardrails, and one output protocol. It is read-only by
default: every write runs a preview/confirm two-phase flow, and sensitive
fields travel through a local request file, never through conversation.
Discovery and arrangement results carry chart-rendered output (visual) for
direct inspection. The companion skill
`skills/huaweicloud-supabase/rds-supabase-mgr-mcp` provides scenario-based
operational guidance. This server covers the control plane only and performs
no SQL or data operations; the data plane is a separate service,
`server/mcp_server_rds_supabase`, delivered independently and interchangeable
with neither.

## Quick start

Prepare Python 3.10+, [uv](https://docs.astral.sh/uv/), and Huawei Cloud
credentials. The minimal configuration is three variables:
`HUAWEICLOUD_ACCESS_KEY`, `HUAWEICLOUD_SECRET_KEY`, and `HUAWEICLOUD_REGION`
(pair with `SUPABASE_TRANSPORT=sdk_core` to enable SDK signing); the project
ID is discovered through IAM and the RDS endpoint is derived from the region.
Stay read-only on first contact:

```bash
export HUAWEICLOUD_ACCESS_KEY="<AK>"
export HUAWEICLOUD_SECRET_KEY="<SK>"
export HUAWEICLOUD_REGION="<region, e.g. cn-north-4>"
export SUPABASE_TRANSPORT="sdk_core"
export HUAWEICLOUD_MCP_READ_ONLY="true"
uvx --from "git+https://github.com/huaweicloud/rds-supabase-fullstack#subdirectory=server/mcp_server_rds_supabase_mgr" \
  mcp-huaweicloud-rds-supabase-mgr
```

Generic stdio client configuration (token mode; AK/SK mode see
[examples/mcp-sdk.example.json](examples/mcp-sdk.example.json)):

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
        "HUAWEICLOUD_AUTH_TOKEN": "<service token>",
        "HUAWEICLOUD_MCP_READ_ONLY": "true",
        "SUPABASE_ENABLE_WRITES": "false"
      }
    }
  }
}
```

Once connected, first call `get_supabase_capabilities` to verify the endpoint,
permissions, and project, then run `plan_supabase_creation_arrangement` to
produce the creation arrangement baseline. Full installation, credential
modes, and the security-group prerequisites are covered below.

## Category

Cloud resource management / application lifecycle orchestration /
database hosting.

## Features

- **Arrangement and discovery**: scenario-based creation arrangement
  baseline — two managed-instance sources, three mandatory parameter modules plus
  the OBS bucket integration (a key optional module that must be confirmed before
  creation), two independent intent modules (SSL configuration and public access
  via EIP), and a step-numbered creation flow; four discovery tool
  families (application, instance, network, security group) that consolidate
  parameters live with recommendations.
- **Scenario-based creation**: `create_supabase_with_new_instance`
  (recommended) and `create_supabase_link_exist_instance` execute resource
  preparation strictly per the arrangement — dedicated security groups and
  the OBS bucket auto-created, parameters backfilled and injected, one
  submission; application/instance identifiers and workflow IDs echoed.
- **Network and security groups**: VPC/subnet placement (free-IP preference
  and default recommendation), dedicated group creation and rules, tag
  protection (AUTO_CREATE/USE_FOR), three-way ingress source choice
  (auto-detect / open / custom).
- **EIP**: idle-first provisioning (pay-per-use recommended, dedicated
  full-dynamic BGP 5-1000M with 300M recommended, auto-tagged); binding with
  triple validation (in32 application ID, ownership, format) via the RDS
  AttachEip API.
- **SSL certificates**: account certificate inventory (`list_ssl_certificates`,
  the SCM global service), two-phase certificate purchase and application
  (`purchase_supabase_ssl_cert`: free-tier DV_SSL_CERT_BASIC recommended,
  paid tiers produce pending-payment orders, pure-EIP public-IP certificates
  support file validation only), and the SSL switch.
- **OBS storage**: two acquisition options (reuse / create-new, new
  recommended) with the full new-bucket specification (private / standard /
  multi-AZ / block-public-access); temporary-credential detection and a read
  test.
- **Authentication and login**: sign-up toggles, Auth URLs, email/GitHub
  login, confirmation templates; application password change.
- **Key delivery**: key metadata, reset, and delivery through a protected
  local file — key values never enter conversation.
- **Orders**: prepaid order query, balance payment, and cancellation, with
  amount and currency verified item by item.
- **Application lifecycle**: start (does not start the managed instance),
  stop (does not stop the managed instance, which keeps billing), and
  restart (brief interruption, off-peak recommended); status-guardrail
  checks, asynchronous tasks tracked to a terminal state via
  `show_operation_job_status`.
- **Change and deletion**: SSL, EIP, and storage-integration changes;
  application deletion (optional managed-instance cascade) and standalone
  managed-instance teardown; task query and bounded waiting.
- **Safety and experience**: read-only mode with risk grading, sensitive-field
  redaction, JSONL audit, chart-rendered output, and four-layer
  wrong-deletion verification for delete-class tools.

## Business scenarios

### Scenario 1: Pre-creation preparation

Pre-creation preparation is completed in one call of
`plan_supabase_creation_arrangement`; it plans only and creates no resource. It first presents the two managed-instance
sources and requires a definitive conclusion from the user: a new instance is
the recommended default, attaching an existing instance the alternative. It
then consolidates the key parameter modules live - three mandatory modules and
one key optional module:

- **Supabase basics**: name suggestion and naming rules, version, deployment
  mode, and flavor (all saleable flavors selectable or custom, general 2U4G
  recommended), from `discover_supabase_create_basic_options`.
- **Managed instance**: the new-instance source returns per-field
  recommendations for engine version, flavor, and storage via
  `discover_db_instance_for_create` — the application flavor and the instance
  flavor are asked in two separate interactions: instance flavors are grouped
  by group_type into ten categories with all saleable flavors shown and the
  application's flavor recommended by default, and storage types display
  their Chinese name, official note, and live compatible flavor types for
  selection; the attach source lists attachable instances paginated (20 per
  page) with version, deployment type, port, availability zone, creation
  time, and current action (action lock) — instances being restarted,
  upgraded, or changed must be excluded to avoid task conflicts.
- **Network control**: VPC/subnet placement and the two-group security-group
  specification — application group 8443 ingress three-way choice plus 5432
  egress, database group 5432 ingress, all CIDRs from the chosen subnet, from
  `discover_network_for_create`.
- **OBS bucket storage integration (key optional)**: whether large-file
  storage applies (images, videos, large files) must be answered explicitly —
  it cannot be enabled after creation; once confirmed, the module carries the
  reuse/new choice, the complete new-bucket specification, and the temporary-
  credential notice, submitted once with the creation request.

The arrangement also emits two independent intent modules: **public access (EIP)**
carries the purchase baseline (pay-per-use, dedicated full-dynamic BGP bandwidth
5-1000M, 300M recommended), the binding, and the `api_external_url` sync steps;
**SSL configuration** carries the three certificate acquisition paths — reuse an
existing certificate (`list_ssl_certificates` inventory), purchase a new one
(`purchase_supabase_ssl_cert`, recommended; free-tier DV_SSL_CERT_BASIC, paid
tiers produce pending-payment orders), or import your own. Pure-EIP public-IP
certificates support file validation only. The output
is a step-numbered creation flow plus a post-creation action list, to be
followed 1:1 during creation.

### Scenario 2: Full application creation flow

Both managed-instance sources share one discipline: intents first, parameters
consolidated through the arrangement, sensitive fields only in the local
request file, and a preview/confirm two-phase submission. The creation tool
completes the resource preparation automatically (dedicated security groups
and, when storage is enabled, the OBS bucket) and backfills every prepared
identifier into the request before one successful submission.

#### New-instance scenario (recommended, `create_supabase_with_new_instance`)

1. Confirm the intents: managed-instance source is a new instance; large-file
   storage or not (cannot be enabled after creation), public access or not,
   HTTPS or not.
2. Produce the arrangement baseline (Scenario 1); `az_code` triggers live
   discovery, and with no VPC the default recommendation applies with the
   network created per `default_create`.
3. Assemble the local request file: all parameters and sensitive fields
   (application password, database password, storage AK/SK) go into the file
   only, never into conversation.
4. Preview (`request_ref`, `public_access_cidr`, `confirm=false`): resolves
   the three-way ingress choice and returns a `plan_id`.
5. Confirm and submit (`confirm=true` + `plan_id`): the application group and
   the database group are created automatically; with storage enabled, the
   OBS bucket is ensured to exist (existing reused, missing created, short
   uuid appended on global-name collision); everything is backfilled and
   injected before one submission.
6. application_id/instance_id and both workflow IDs are echoed; keep
   querying via `show_supabase_creation_progress`: roughly 20-30 minutes
   overall, the instance becomes ready first and only then does the
   application task start; prepaid resources begin only after the order is
   paid per Scenario 5.
7. Verify readiness with `show_supabase_application`; then proceed as needed
   with public access (Scenario 3), SSL (three certificate paths: reuse /
   purchase / import your own), login configuration, and access
   information delivery.

#### Existing-instance attach scenario (`create_supabase_link_exist_instance`)

1. Confirm the intents as above, with the managed-instance source being an
   existing instance.
2. The arrangement lists the attachable candidates paginated at 20 per page
   with version, deployment type, port, availability zones, creation time and
   current action locks - after excluding instances mid-restart, upgrade or
   change, the user picks the `instance_id` and backfills the arrangement.
3. Assemble the local request file: `manage_type=existed_instance` and
   `existing_instance{instance_id, database_name:"root", database_pwd}`;
   the database password goes into the file only.
4. Preview and submit: the application group is created automatically (8443
   ingress with the three-way choice plus 5432 egress to the instance's
   subnet CIDR) while the instance's own security group stays untouched;
   with storage enabled the OBS bucket is ensured likewise; backfilled and
   injected before one submission.
5. application_id and the application workflow ID are echoed (no instance
   task); track to readiness via `show_supabase_creation_progress`.
6. Verification and post-creation actions match the new-instance scenario.

### Scenario 3: EIP creation and binding

**Provisioning**: `create_supabase_eip` is idle-first
(`prefer_idle=true`) — it first lists unbound EIPs for the user to pick,
and the selection binds directly with nothing created; with no idle EIP, it
creates per the baseline: pay-per-use purchase (prepaid returns a console
order), full-dynamic BGP (`publicip.type=5_bgp`), dedicated bandwidth
(`share_type=PER`) 5-1000M with 300M recommended, auto-tagged USAGE_FOR.

**Binding**: `bind_supabase_eip` runs triple validation — `instance_id` must
be an in32-suffixed Supabase application ID within this environment's
application list, `public_ip_id` a canonical UUID, and `public_ip` a valid
IPv4 — and only then binds via the RDS AttachEip API.

After a successful binding, `update_supabase_auth_config` must sync
`api_external_url` (email links and OAuth callbacks depend on it), followed
by a liveness check.

When HTTPS is needed, SSL certificates are obtained through this server — no
console purchase required: `list_ssl_certificates` inventories existing
account certificates (the SCM global service) for reuse; and
`purchase_supabase_ssl_cert` purchases and applies in two phases — free-tier
DV_SSL_CERT_BASIC recommended, paid tiers producing pending-payment orders,
pure-EIP public-IP certificates supporting file validation only. Once the
`cert_id` is at hand, enable it via `change_supabase_ssl`.

### Scenario 4: Application deletion (with the managed PG instance)

`delete_supabase_application`'s `delete_managed_instance` is mandatory:
`false` deletes only the application, with the managed instance retained and
still billing; `true` deletes both concurrently — instance deletion is
irreversible, cascade applies to pay-per-use only, and prepaid instances must
be unsubscribed in the console first. Four verification layers run before
deletion: instance ownership, live re-check of the cloud `managed_instance`
state, no other application mounting the instance, and prepaid interception.
Submission returns two job IDs; track them to a terminal state with
`wait_operation_job_complete` and re-verify the resources.

The managed instance can also be torn down standalone via
`delete_supabase_managed_instance` while the application lives, under the
same four verification layers. Auto-created security groups are cleaned up
via `delete_supabase_security_group` behind the tag gate: only groups bearing
the `AUTO_CREATE=true`/`USE_FOR=Supabase` tag pair and free of references
may be deleted.

### Scenario 5: Purchase modes

The RDS Supabase application is free during public beta; charges arise only
from the managed database instance. The purchase mode is set in
`managed_instance.charge_info` of the creation request.

#### Billing boundary (application free, instance charged)

- **The application itself**: free during public beta, no charge.
- **The managed database instance**: the only billing subject - pay-per-use
  bills actual usage, prepaid bills the ordered period.
- A creation that returns `order_id` means a prepaid order was created and no
  resource provisioned yet; an unpaid order does not mean the instance is
  provisioned - resources are built only once a creation task (`job_id`)
  appears.

#### Purchase-mode choice (pay-per-use strongly recommended)

- **Pay-per-use (postPaid, strongly recommended)**: `charge_info` carries
  `charge_mode` only; start and stop at any time, controllable cost during
  trial and change periods, billing stops when the instance is deleted.
- **Prepaid (prePaid)**: `period_type` is the string `month` (1-9 months) or
  `year` (1-3 years); creation returns an order and resources are built only
  after payment through the order tools; suited to long-term stable runs.
- Obtain the user's explicit approval of the purchase mode and cost before
  submitting.

#### Prepaid order payment

1. Once the creation returns `order_id`, first query the order status,
   amounts, currency and lines with `get_supabase_order(order_id)` (20 lines
   by default, `marker` pagination); `amount_after_discount` is the
   post-discount amount excluding coupons and cards, and amounts must be read
   together with the returned currency and unit.
2. After verifying and obtaining the user's approval of the exact amount and
   currency, call `pay_supabase_order(order_id, expected_amount, currency,
   confirm=true)`: `expected_amount` must equal both `official_amount` and
   `amount_after_discount` - a difference means a discount or coupon exists,
   and the tool rejects the payment to avoid losing it; such orders are
   handled in the billing center. For managed accounts the final charge
   follows the bill.
3. One confirmation, one submission, no automatic retry; the result carries
   `payment_submitted` and `payment_verified`, and the order status and
   payment time are re-checked after payment. Timeouts may leave the outcome
   unknown (`payment_submitted=false`): query the same order first and never
   pay automatically again.
4. Once the payment completes and the order provisions, a creation task
   appears - track and verify per Scenario 2.

#### Prepaid order cancellation

1. To abandon an unpaid order: confirm it accurately with `get_supabase_order`
   first, then `cancel_supabase_order(order_id, confirm=true)`.
2. The service re-checks the cloud-side pending-payment state, product scope
   and every order line; only unpaid orders qualify; cancellation is
   permanent; already-cancelled orders return an idempotent result.
3. The result carries `cancellation_verified`; when false, keep querying with
   `get_supabase_order` instead of blindly resubmitting. Paid resources must
   go through the console unsubscription workflow, which this tool does not
   handle.

## Available tools

Every write tool runs a two-phase confirmation: a preview returns the changes
and a plan identifier first, and only an explicit confirmation submits. Tools
that carry passwords or credentials accept no plaintext — secrets are
pre-provisioned into a local request file and referenced by alias.

| Tool | Scenario | Risk | API doc |
|---|---|---|---|
| `get_supabase_capabilities` | View the scenarios and boundaries this service manages | READ | - |
| `list_supabase_applications` | Browse applications with pagination, filtering, and sorting | READ | [ListSupabaseApplications](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplications) |
| `show_supabase_application` | Inspect an application's full configuration: flavor/network/SSL/storage | READ | [ShowSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ShowSupabaseApplication) |
| `list_supabase_api_keys` | View API key types and statuses; key values never returned | READ | [ListSupabaseApplicationApiKeys](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplicationApiKeys) |
| `reset_supabase_api_key` | Reset a key against leakage or rotation; old key invalidated | DANGEROUS | [ResetSupabaseApplicationApiKey](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ResetSupabaseApplicationApiKey) |
| `deliver_supabase_api_key` | Write a key value to a protected local file for secure delivery | DANGEROUS | [ShowSupabaseApplicationApiKeyValue](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ShowSupabaseApplicationApiKeyValue) |
| `show_supabase_auth_config` | View the auth baseline: sign-up toggles/providers/mail templates | READ | [ShowSupabaseApplicationAuthConfig](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ShowSupabaseApplicationAuthConfig) |
| `update_supabase_auth_flags` | Toggle user sign-up and anonymous access | WRITE | [ModifySupabaseApplicationAuthConfig](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationAuthConfig) |
| `update_supabase_auth_config` | Configure GitHub/SMTP login, callback URLs, and mail templates | WRITE | [ModifySupabaseApplicationAuthConfig](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationAuthConfig) |
| `update_supabase_storage` | Integrate or change the OBS storage bucket | WRITE | [ModifySupabaseApplicationStorage](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationStorage) |
| `discover_supabase_storage` | OBS acquisition two options (reuse/new-recommended) and credential detection | READ | `KooCLI OBS ls` |
| `discover_supabase_create_basic_options` | Application creation-basics discovery with recommendations; application flavors grouped by flavor type with all saleable flavors shown | READ | [ListSupabaseApplicationFlavors](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplicationFlavors) |
| `plan_supabase_creation_arrangement` | End-to-end creation arrangement baseline: three-module parameter consolidation and flow design; application and instance flavors asked separately, instance defaulting to the application's flavor; SSL and public-access EIP as independent configuration modules | READ | live composite (read-only queries of the three discovery tools) |
| `list_supabase_flavors_with_azs` | Query application flavors and the AZs each supports | READ | [ListSupabaseApplicationFlavors](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseApplicationFlavors) |
| `list_supabase_manageable_instances` | Query existing PostgreSQL instances available for attachment | READ | [ListSupabaseManageableInstances](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListSupabaseManageableInstances) |
| `list_db_instance_engine_versions` | Query PostgreSQL engine versions for managed instances | READ | [ListDatastores](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListDatastores) |
| `list_db_instance_flavors_with_azs` | Query managed-instance flavors with per-AZ sale status | READ | [ListFlavors](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListFlavors) |
| `list_db_instance_storage_types` | Query managed-instance storage types (by version and mode) | READ | [ListStorageTypes](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListStorageTypes) |
| `discover_db_instance_for_create` | Managed-instance source discovery per scenario (with action-lock candidate list); instance flavors grouped by group_type with all saleable flavors, storage types with Chinese names and live compatible flavor types | READ | composite query (ListDatastores/ListFlavors/ListStorageTypes) + ListManageableInstances |
| `discover_network_for_create` | Network placement and security-group specification | READ | [ListVpcs](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ListVpcs) + [ListSubnets](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ListSubnets) |
| `create_supabase_with_new_instance` | (Recommended) end-to-end creation for the new-instance scenario: security groups/OBS auto-prepared and backfilled, one submission | WRITE | [CreateSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=CreateSupabaseApplication) |
| `create_supabase_link_exist_instance` | Creation for the attach-existing scenario: application group auto-created, database group untouched | WRITE | [CreateSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=CreateSupabaseApplication) |
| `delete_supabase_application` | Application deletion; delete_managed_instance mandatory (instance cascade optional) | DANGEROUS | [DeleteSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=DeleteSupabaseApplication) |
| `delete_supabase_managed_instance` | Standalone managed-instance teardown, four-layer verification | DANGEROUS | [DeleteInstance](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=DeleteInstance) |
| `start_supabase_application` | Start a stopped Supabase application, asynchronous task tracked via `show_operation_job_status`; the managed instance is not started automatically and may fail if unhealthy | DANGEROUS | [StartSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StartSupabaseApplication) |
| `stop_supabase_application` | Stop a Supabase application, unavailable while stopped, asynchronous task tracked; the managed instance is not stopped (still billing), off-peak recommended | DANGEROUS | [StopSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=StopSupabaseApplication) |
| `restart_supabase_application` | Restart a running (normal) Supabase application, asynchronous task tracked; internal components restart with a brief service interruption and memory cache cleared; stopped applications must start first | DANGEROUS | [RestartSupabaseApplication](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=RestartSupabaseApplication) |
| `get_supabase_order` | Query prepaid order status, amounts, currency, and line items | READ | [ShowCustomerOrderDetails](https://console.huaweicloud.com/apiexplorer/#/openapi/BSS/doc?api=ShowCustomerOrderDetails) |
| `pay_supabase_order` | Balance-pay a pending order after amount/currency verification | DANGEROUS | [PayOrders](https://console.huaweicloud.com/apiexplorer/#/openapi/BSS/doc?api=PayOrders) |
| `cancel_supabase_order` | Cancel an unneeded pending-payment order | DANGEROUS | [CancelCustomerOrder](https://console.huaweicloud.com/apiexplorer/#/openapi/BSS/doc?api=CancelCustomerOrder) |
| `change_supabase_ssl` | Enable or disable SSL-encrypted transport for the application | WRITE | [SwitchSupabaseApplicationSsl](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=SwitchSupabaseApplicationSsl) |
| `plan_supabase_ssl` | Pre-switch planning: certificate requirements and impact assessment | READ | - |
| `list_ssl_certificates` | Inventory the account's existing SSL certificates (SCM global service); cert_id feeds the SSL change | READ | - |
| `purchase_supabase_ssl_cert` | Two-phase SCM SSL certificate purchase, with optional simultaneous application | DANGEROUS | - |
| `create_supabase_eip` | EIP provisioning (idle-first): pay-per-use + full-dynamic BGP + 300M baseline | WRITE | [CreatePublicip](https://console.huaweicloud.com/apiexplorer/#/openapi/EIP/doc?api=CreatePublicip) |
| `bind_supabase_eip` | EIP binding: triple validation (in32/ownership/format) | WRITE | [AttachEip](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=AttachEip) |
| `create_supabase_new_obs` | Create a private OBS bucket (standard/multi-AZ/block-public-access) | WRITE | `KooCLI OBS mb` |
| `change_supabase_eip` | Bind or unbind an EIP to open or close public access | WRITE | [SwitchSupabaseApplicationEipBind](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=SwitchSupabaseApplicationEipBind) |
| `change_supabase_application_password` | Change the application password via the local request file | DANGEROUS | [ModifySupabaseApplicationPassword](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ModifySupabaseApplicationPassword) |
| `list_supabase_security_groups` | Browse the security-group list | READ | [ListSecurityGroups](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ListSecurityGroups) |
| `show_supabase_security_group` | Inspect a security group and all its rules | READ | [ShowSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=ShowSecurityGroup) |
| `create_supabase_security_group` | Create a dedicated security group, auto-tagged with origin and purpose | WRITE | [CreateSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=CreateSecurityGroup) |
| `add_supabase_security_group_rule` | Add an inbound or outbound access rule | DANGEROUS | [CreateSecurityGroupRule](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=CreateSecurityGroupRule) |
| `delete_supabase_security_group_rule` | Remove a specific access rule to narrow the exposed surface | DANGEROUS | [DeleteSecurityGroupRule](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=DeleteSecurityGroupRule) |
| `delete_supabase_security_group` | Delete a security group; flow-created and unreferenced only | DANGEROUS | [DeleteSecurityGroup](https://console.huaweicloud.com/apiexplorer/#/openapi/VPC/doc?api=DeleteSecurityGroup) |
| `show_operation_job_status` | Query the current status of a submitted operation task | READ | [ListJobInfo](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListJobInfo) |
| `show_supabase_creation_progress` | Analyze application creation progress across all phases | READ | - |
| `wait_operation_job_complete` | Poll an operation task to a terminal state within a bounded timeout | READ | [ListJobInfo](https://console.huaweicloud.com/apiexplorer/#/openapi/RDS/doc?api=ListJobInfo) |

The full API reference is at the
[Huawei Cloud RDS API docs](https://support.huaweicloud.com/api-rds/rds_01_0002.html);
some Supabase APIs are newer than the published catalog — when API Explorer
lacks one, this server's actual behavior is authoritative.

## Usage guide

Starting, stopping, and restarting an application are asynchronous
operations: once accepted with a `job_id`, track it to a terminal state with
`show_operation_job_status` and re-read the application; stopping does not
stop the managed database instance (it keeps billing) and starting does not
start the instance; restarting briefly interrupts the service — prefer
off-peak windows.

### Prerequisites

1. Python 3.10+; [uv](https://docs.astral.sh/uv/) when using uvx.
2. Huawei Cloud credentials with the minimal required permissions
   (see [Permission recommendations](#permission-recommendations)).
3. For security-group tools: KooCLI installed locally with the privacy
   agreement accepted (see [KooCLI integration](#koocli-integration)).

### Installation

**uvx direct run (recommended; the git repository is the only canonical
source):**

```bash
uvx --from "git+https://github.com/huaweicloud/rds-supabase-fullstack#subdirectory=server/mcp_server_rds_supabase_mgr" \
  mcp-huaweicloud-rds-supabase-mgr
```

The server is not published to PyPI; same-named third-party packages on
PyPI are not this server and must not be installed.

**Clone for development:**

```bash
git clone https://github.com/huaweicloud/rds-supabase-fullstack.git
cd rds-supabase-fullstack/server/mcp_server_rds_supabase_mgr
uv sync
uv run mcp-huaweicloud-rds-supabase-mgr          # stdio (default)
uv run mcp-huaweicloud-rds-supabase-mgr -t streamable-http
```

`mcp-huaweicloud-rds-supabase-mgr` is the canonical entry; the legacy entry
`mcp_server_supabase` is kept transitionally and is equivalent. For
slow-network uvx startup timeouts, see the
[skill install reference](../../skills/huaweicloud-supabase/rds-supabase-mgr-mcp/references/install.md).

### Diagnostics CLI

```bash
uv run python -m mcp_server_supabase.diagnostics check       # config and dependency check only
uv run python -m mcp_server_supabase.diagnostics offline     # offline stdio self-check
# Auto-discover project and candidate RDS endpoints from credentials (REST token or AK/SK):
uv run python -m mcp_server_supabase.diagnostics discover
uv run python -m mcp_server_supabase.diagnostics discover --probe   # add read-only reachability probing
# Real read-only checks, only in an authorized test environment:
uv run python -m mcp_server_supabase.diagnostics readonly --allow-cloud-read
```

`discover` queries IAM for the project list and derives candidate endpoints
per region, listing `suggested_env` for selection; an explicitly configured
`SUPABASE_RDS_ENDPOINT` wins. Reachability does not imply permissions or
production acceptance. The diagnostics CLI submits no cloud writes and its
summaries contain no resource values or credentials.

## Configuration

### Environment variables

Pick one credential mode: **REST token mode** (default,
`HUAWEICLOUD_AUTH_TOKEN`) or **sdk_core mode** (`SUPABASE_TRANSPORT=sdk_core`
+ AK/SK). Credentials are injected by a trusted host environment, never as
tool parameters.

| Variable | Required | Description | Default |
|---|---|---|---|
| `SUPABASE_RDS_ENDPOINT` | no | Native RDS HTTPS origin (no path/query/userinfo; not the Console or a /rest proxy). When absent, derived from `HUAWEICLOUD_REGION` as `https://rds.<region>.myhuaweicloud.com`; also derivable via `diagnostics discover` | derived per region |
| `HUAWEICLOUD_PROJECT_ID` | no | Target project ID; discovered via IAM from `HUAWEICLOUD_REGION` when absent (AK/SK with project-list permission required; sub-project accounts should set it explicitly) | IAM discovery |
| `HUAWEICLOUD_AUTH_TOKEN` | REST mode | Pre-provisioned service token, read per request | - |
| `SUPABASE_TRANSPORT` | no | Set `sdk_core` to enable Huawei SDK Core signing | REST token |
| `HUAWEICLOUD_ACCESS_KEY` | sdk_core mode | Account AK | - |
| `HUAWEICLOUD_SECRET_KEY` | sdk_core mode | Account SK | - |
| `HUAWEICLOUD_SECURITY_TOKEN` | no | STS temporary-credential token | - |
| `HUAWEICLOUD_REGION` | no | Region: shared by the security-group tools and RDS endpoint derivation; sub-project resolution stays with the hcloud profile | - |
| `HCLOUD_BIN` | no | Explicit KooCLI binary path override | auto-located |
| `SUPABASE_ENABLE_WRITES` | no | Cloud-write switch; must be `true` for cloud writes | `false` |
| `HUAWEICLOUD_MCP_READ_ONLY` | no | `true` intercepts all WRITE/DANGEROUS tools | `false` |
| `SUPABASE_STATE_FILE` | no | Local execution-record (SQLite) path; keep one record across restarts | user state dir |
| `SUPABASE_REQUESTS_FILE` | no | Local sensitive-request reference registry (operator-provisioned) | - |
| `REQUESTS_CA_BUNDLE` | no | Custom trusted CA bundle (PEM file) | - |
| `HUAWEICLOUD_MCP_PROTECTED_IDS` | no | Guardrail: protected resource IDs (comma-separated, hit = block) | empty |
| `HUAWEICLOUD_MCP_PROTECTED_NAMES` | no | Guardrail: protected resource names (comma-separated, hit = block) | empty |
| `HUAWEICLOUD_MCP_PROTECTED_TAGS` | no | Guardrail: protected tags (comma-separated `k` or `k=v`) | empty |
| `HUAWEICLOUD_MCP_GUARDRAILS_CONFIG` | no | Path to a `guardrails.yaml` rules file | empty |
| `HUAWEICLOUD_MCP_AUDIT_FILE` | no | Audit JSONL file path (audit always on; defaults to stderr) | empty |
| `MCP_SERVER_PORT` | no | streamable-http port | `8000` |
| `MCP_SERVER_HOST` | no | streamable-http bind address | `0.0.0.0` |

### Safety guardrails

Every write tool runs a preview/confirm two-phase flow: `confirm=false`
persists a ten-minute plan and returns a `plan_id`; confirmation resubmits
identical parameters with `confirm=true` + `plan_id`. Any change to
parameters, project, endpoint, or credentials requires a fresh preview. The
SQLite execution record (`SUPABASE_STATE_FILE`) registers every plan and
execution state: on a timeout or unknown outcome, verify directly against
the operation task and the target resource; no submitted plan may be
resubmitted, preventing double execution.

Passwords and credentials for SMTP, GitHub, and OBS never enter conversation;
the operator pre-provisions them into the local request registry
(`SUPABASE_REQUESTS_FILE`) and tools reference them by alias only,
accepting no plaintext. The cloud-write switch (`SUPABASE_ENABLE_WRITES`,
default off) and the read-only interception (`HUAWEICLOUD_MCP_READ_ONLY`)
act independently, and neither can be modified by the agent itself. A
`completed` job means the cloud API accepted the request only; re-read the
resource to confirm the business outcome.

Protection lists are configured via `HUAWEICLOUD_MCP_PROTECTED_*`
environment variables or `guardrails.yaml`, matching by tool name, risk
level, resource ID, name regex, or tag with block/confirm/warn actions.
Guardrails match at the parameter level: protected attributes that exist
only on the cloud side and never appear in tool arguments cannot match —
configure the protection lists proactively.

Example `guardrails.yaml`:

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
    message: Production Supabase applications are protected; contact ops.
```

### KooCLI integration

The six security-group tools (list/detail, create group, add/remove rules,
delete group) already embed the KooCLI capability and work out of the box:
the native RDS origin does not proxy the VPC API, so the tools call the VPC
v3 operations through the local KooCLI (`hcloud`) internally, with credential
injection, result parsing, preview confirmation, origin tagging, and
wrong-deletion protection. Principle: prefer these tools; fall back to raw
KooCLI commands only where they do not cover the need.

| Scenario | Use |
|---|---|
| Every routine security-group operation (list/detail, create group, add/remove rules, delete group) | This service's tools |
| Opening 0.0.0.0/0 world-wide ingress (tools refuse by design; requires explicit user confirmation) | Raw KooCLI commands |
| Edge operations the tools deliberately do not support (e.g. address-group management) | Raw KooCLI commands |

Operations-troubleshooting notes:

- **Prerequisite**: hcloud installed locally with its first-run privacy
  agreement accepted; installation is covered in
  [section 4 of the skill INSTALL.md](../../skills/huaweicloud-supabase/rds-supabase-mgr-mcp/INSTALL.md).
- **Binary location**: `HCLOUD_BIN` environment variable → fixed install
  directories → PATH, re-resolved on every call; no session restart needed
  after installation.
- **Credential injection**: injected per command only when both
  `HUAWEICLOUD_ACCESS_KEY` and `HUAWEICLOUD_SECRET_KEY` are set; otherwise
  the hcloud profile is used. REST token mode requires a local hcloud
  profile (`hcloud configure init`), or these tools report missing
  credentials.
- **Region and project**: region comes from `HUAWEICLOUD_REGION`; the
  project is resolved by KooCLI as the region default project — sub-project
  accounts must configure `--cli-project-id` in the hcloud profile.
- **Error passthrough**: VPC backend error_code/error_msg/request_id pass
  through verbatim; an unaccepted privacy agreement, a missing binary, and
  timeouts each map to a dedicated error code with remediation guidance.
- **Origin tagging**: every created group is auto-tagged AUTO_CREATE=true
  and USE_FOR=Supabase; whole-group deletion verifies the tag pair and
  rejects every group not created by this flow.

## Running with UVX

UVX stdio configuration for AgentArts and other clients:

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
        "HUAWEICLOUD_AUTH_TOKEN": "<service token>",
        "HUAWEICLOUD_MCP_READ_ONLY": "true",
        "SUPABASE_ENABLE_WRITES": "false"
      }
    }
  }
}
```

AgentArts supports UVX stdio and Streamable HTTP. Remote mode startup:

```bash
mcp-huaweicloud-rds-supabase-mgr -t streamable-http
```

It listens on `0.0.0.0:8000` by default with the endpoint at `/mcp`; front it
with HTTPS and client authentication in production. The server is not
published to PyPI, so UVX always pulls from the git repository
(see [Installation](#installation)).

## Examples

### Workflow 1: create a reachable application from scratch

1. Call `plan_supabase_creation_arrangement(manage_type, az_code, ...)` with
   the managed-source decision and intents (including the `needs_storage`
   answer) to get the end-to-end arrangement baseline: consolidated
   three-module parameters, the two independent modules (public access via EIP
   and SSL configuration), the OBS bucket plan,
   and the step-numbered creation flow.
2. Execute step by step per the arrangement: network ready (create the
   defaults per `default_create` when recommended) -> storage ready
   (`discover_supabase_storage` to decide reuse or new,
   `create_supabase_new_obs` when creating) -> the local request file (root
   password, storage credentials, and other secrets).
3. Submit with the creation tool matching the managed source (security
   groups are auto-created and injected by the tool — no manual
   `security_group_id`): `create_supabase_with_new_instance(request_ref,
   confirm=false)` for a new instance (recommended), or
   `create_supabase_link_exist_instance(request_ref, confirm=false)` to
   attach an existing one. Preview, show the redacted parameters to the
   user, then submit identical parameters with `confirm=true` + `plan_id`.
4. Track the returned workflow IDs with `show_supabase_creation_progress`
   (or `show_operation_job_status` / bounded `wait_operation_job_complete`)
   to a terminal state.
5. Re-read `show_supabase_application`; if public access is not open, run
   the Scenario 3 EIP provisioning and binding and sync `api_external_url`,
   then deliver access information via `list_supabase_api_keys` +
   `deliver_supabase_api_key`.

### Workflow 2: open security-group ports for an application

1. Preview and confirm `create_supabase_security_group` — a dedicated group
   with a purpose description.
2. Add the 8443 ingress rule (source CIDR) and the 5432 egress rule
   (`direction='egress'`) with `add_supabase_security_group_rule`, each
   previewed then confirmed.
3. Re-read with `show_supabase_security_group` and verify direction and
   port.
4. To revoke, use `delete_supabase_security_group_rule` (after verifying
   the group is not shared); retire the whole group with
   `delete_supabase_security_group` (after verifying no instance/NIC
   references).

Every write may execute asynchronously. A successful MCP call means the
cloud API accepted the request, not that the change has completed.

## Client compatibility

| Client | Transport | Notes |
|---|---|---|
| opencode | stdio | Project-level `opencode.json`, `mcp.servers.*` structure; connects automatically on save |
| Claude Code | stdio | Project-level `.mcp.json`; approve once in-session |
| Claude Desktop / Cursor / Trae | stdio | `command`/`args`/`env` configuration |
| CodeArts | stdio | Project-level `mcp_settings.json` (Settings → MCP tools); editing an entry needs a manual restart |
| Remote mode | Streamable HTTP | `mcp-huaweicloud-rds-supabase-mgr -t streamable-http`, endpoint `/mcp`; front it with HTTPS and authentication in production |

No legacy SSE transport is provided.

## Permission recommendations

- **Read-only discovery**: RDS application/flavor/instance queries plus IAM
  project listing; VPC, subnet, AZ, and EIP queries for creation planning
  run through KooCLI and follow the hcloud profile permissions.
- **Write operations**: grant only the RDS application create/change
  permissions and VPC security-group write permissions matching the tools
  actually enabled.
- **Dangerous operations**: deletions, password changes, and key resets
  should use a separate identity or temporary authorization, combined with
  `HUAWEICLOUD_MCP_PROTECTED_*` lists and confirmation rules.
- Never configure long-lived administrator credentials to an MCP client for
  convenience; prefer temporary security credentials in production.

## Development, testing, and release

```bash
uv sync --all-groups
uv run ruff check src tests
uv run pytest                       # no cloud access by default; 80% coverage gate
uv run python tests/smoke_stdio.py  # offline stdio smoke test
```

Live validation must only run in a dedicated test account; when creating
billable resources, always clean up on failure paths and confirm deletion
jobs reach a terminal state. Before release, check wheel metadata, a fresh
Python 3.10 installation, and the MCP tool list.

## Contributing and support

Contribution workflow, security reporting, and version history live in the
repository-root `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md`. Use
GitHub Issues for general questions; credential leaks and security issues
must never be filed in public issues.

## Further documentation

- [User guide](docs/USER_GUIDE.md) — installation, verification, and the
  natural-language operation workflow
- [Tool contracts](docs/TOOL_CONTRACTS.md) — the authoritative input/output
  and confirmation semantics
- [Recovery rules](docs/RECOVERY.md) and
  [reconciliation contract](docs/RECONCILIATION.md) — failure routing and
  Auth plan reconciliation
- [Local secret I/O](docs/LOCAL_REQUESTS.md) — the sensitive-request
  reference mechanism
- [SDK mode](docs/SDK.md), [migration notes](docs/MIGRATION.md)
- [docs/legacy/](docs/legacy/) — archived offline Windows delivery process

## License

MIT
