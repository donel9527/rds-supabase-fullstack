from huaweicloud_mcp_core.security import ToolRisk, guard
from mcp_server_supabase import visual
from mcp_server_supabase.service.instance_catalog import InstanceCatalog, NetworkDiscovery, BasicOptionsDiscovery
from mcp_server_supabase.service.instance_lifecycle import lifecycle as managed_instance_lifecycle
from mcp_server_supabase.service.instance_lifecycle import show as show_managed_instance
from mcp_server_supabase.service.operations import Operations


def register(server):
    service = Operations()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_applications(limit: int = 10, offset: int = 0,
                                         name: str | None = None,
                                         application_id: str | None = None,
                                         sort_key: str = 'created_time',
                                         sort_dir: str = 'desc') -> dict:
        """Paginated query of all RDS Supabase applications in the current project,
        with sorting and filtering. Use it to locate a target or an available application.

        Args: limit 1-100 (default 10), offset >= 0 for pagination.
        name: optional fuzzy-match filter on the application name.
        application_id: optional exact identifier filter (1-128 [A-Za-z0-9_-]).
        sort_key: name/status/mode/created_time/updated_time (default created_time).
        sort_dir: asc/desc (default desc).
        type is fixed to supabase server-side and cannot be overridden.
        Returns: data containing total_count and bounded sanitized records with the
        mandatory fields id/name/public_ip/port/flavor_ref/mode/created_time plus
        nullable remark/updated_time; other non-secret fields (flavor_id, vcpus, ram,
        private_ip, traffic_vip, availability_zone, az_details, managed_instance,
        current_actions, ...) pass through bounded. direct_eip is normalized to
        public_ip; epoch-millisecond timestamps become RFC 3339 UTC. Verify identity
        before selecting a target.
        """
        return await service.read("applications", limit=limit, offset=offset, name=name,
                                  application_id=application_id, sort_key=sort_key,
                                  sort_dir=sort_dir)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_application(application_id: str) -> dict:
        """Query RDS Supabase application details; use it for status, SSL, IP address
        and other specifics, and to assemble the complete access address from the result.

        Args: application_id from application discovery.
        Returns: a normalized detail object. Access-address assembly: scheme from
        enable_ssl (true->https, false->http), host from public_ip (direct_eip,
        public; null when no EIP is bound) or private_ip/traffic_vip (internal),
        port from port. Mandatory fields id/name/mode/status/port/enable_ssl/
        private_ip/created_time fail closed when missing; epoch-millisecond
        timestamps become RFC 3339 UTC; nested objects (spec_flavor, data_volume,
        nodes, dnat, az_details, managed_instance, storage_component) pass
        through bounded; secrets excluded. Status is not proof of completion.
        """
        return await service.read("application", application_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_api_keys(application_id: str, limit: int = 10, offset: int = 0,
                                    status: str | None = None, key_type: str | None = None,
                                    sort_key: str = 'created_time', sort_dir: str = 'desc',
                                    key_id: str | None = None) -> dict:
        """List the API keys of an RDS Supabase application: id-bearing metadata
        records for service_role, anon, publishable and secret keys. Plaintext
        values are never returned.

        Args: application_id from application discovery; limit 1-100, offset >= 0.
        status: normal/creating/createfail/deleted. key_type: publishable/secret/anon/service_role.
        sort_key: name/status/type/created_user/updated_user/created_time/updated_time.
        sort_dir: asc/desc. key_id: optional exact identifier filter.
        Returns: data containing total_count and bounded whitelisted records —
        id/name/status/type are mandatory, created_time/updated_time/remark are
        nullable with timestamps as RFC 3339 UTC. Unknown fields are dropped,
        not passed through; use deliver_supabase_api_key to obtain one key value
        into a protected local file.
        """
        return await service.read("keys", application_id, limit, offset, status=status,
                                  key_type=key_type, sort_key=sort_key, sort_dir=sort_dir, key_id=key_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_auth_config(application_id: str) -> dict:
        """Query the Auth configuration of an RDS Supabase application: user registration
        settings, access control, identity providers (email and GitHub) and email
        template configuration.

        Args: application_id from application discovery.
        Returns: the normalized configuration object — registration flags
        (enable_account_sign_up, enable_anonymous_users), URLs (api_external_url,
        site_url, allow_redirect_urls), provider sections (github_oauth_provider;
        email_oauth_provider with smtp_config) and email_template_config
        (confirmation, invite, recovery, email_change, magic_link,
        reauthentication). Mandatory fields fail closed when missing; secrets
        (SMTP credentials, OAuth client secrets) are excluded at any depth while
        identifiers (oauth_client_id, smtp_user) remain; empty strings mean not
        configured. Baseline for update_supabase_auth_config previews and
        accepted-plan reconciliation.
        """
        return await service.read("auth", application_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_operation_job_status(job_id: str) -> dict:
        """Query the current status of one submitted operation task, such as creation, deletion, SSL or EIP changes. The raw status is evidence only - a completed task still requires re-reading the resource to verify the business outcome."""
        return await service.job(job_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def wait_operation_job_complete(job_id: str, max_attempts: int = 3, interval_seconds: int = 2) -> dict:
        """Poll one operation task within a bounded timeout until it reaches a terminal state, for waiting on task completion. Observes only - it never submits, replays or cancels anything."""
        return await service.wait_job(job_id, max_attempts, interval_seconds)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def change_supabase_ssl(application_id: str, enable_ssl: bool, cert_id: str | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Preview or submit SSL change. Disabling requires null certificate. Writes require explicit server opt-in. 任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.mutate(application_id, "ssl", {"enable_ssl":enable_ssl,"cert_id":cert_id}, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def change_supabase_eip(application_id: str, is_bind: bool, public_ip_id: str | None = None, public_ip_address: str | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Preview or submit EIP binding change. Binding requires ID and IPv4; review public exposure and billing. 任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.mutate(application_id, "eip", {"is_bind":is_bind,"public_ip_id":public_ip_id,"public_ip_address":public_ip_address}, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_application(application_id: str, delete_managed_instance: bool | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Delete one RDS Supabase application, and on the user's explicit choice its managed PostgreSQL instance too.

        The instance choice is mandatory and cannot be defaulted: ask the user first.
        False deletes only the application - the instance is retained and keeps billing.
        True submits both deletions together and returns two job ids; the instance deletion
        is irreversible (all data destroyed, pay-per-use only). All managed-instance
        guardrails run before anything is submitted. 任务受理后用 show_operation_job_status(job_id) 查询任务状态（双任务时两个 job 分别查询）。
        """
        return await service.delete_application(application_id, delete_managed_instance, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def delete_supabase_managed_instance(application_id: str, instance_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Remove the PostgreSQL instance managed by one RDS Supabase application during teardown. The instance must be that application's own managed_instance (verified live) and referenced by no other application; deletion is irreversible. Pay-per-use only - yearly/monthly instances must be unsubscribed in the console. Confirm before applying. 任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.delete_managed_instance(application_id, instance_id, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def start_supabase_application(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """启动一个已停止的 RDS Supabase 应用（异步任务）。仅可对已停止的应用操作；启动不会自动启动托管数据库实例，托管实例状态须正常否则可能启动失败。两段式：preview（confirm=false）回读应用当前状态、返回影响说明并签发 plan_id；confirm=true+plan_id 一次提交。任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.lifecycle(application_id, "start", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def stop_supabase_application(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """停止一个运行中的 RDS Supabase 应用（异步任务）。仅运行中（normal）的应用可停止；停止不会停止托管数据库实例（实例保留并继续计费）；停止期间应用功能不可用，建议业务低峰期操作。两段式：preview（confirm=false）回读应用当前状态、返回影响说明并签发 plan_id；confirm=true+plan_id 一次提交。任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.lifecycle(application_id, "stop", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def restart_supabase_application(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """重启一个运行中的 RDS Supabase 应用（异步任务）。仅运行中（normal）的应用可重启，已停止的应用须先启动，异常状态可能重启失败；重启内部组件服务、期间短暂服务中断（状态显示为“重启中”）并自动释放内存缓存，建议低峰操作。两段式：preview（confirm=false）回读应用当前状态、返回影响说明并签发 plan_id；confirm=true+plan_id 一次提交。任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.lifecycle(application_id, "restart", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_managed_instance(application_id: str) -> dict:
        """查询一个 RDS Supabase 应用绑定的托管数据库实例详情（简化实例视图）。实例目标始终解析自该应用的 managed_instance 字段，不接受裸 instance_id，独立数据库实例不适用，仅支持单实例查询。返回白名单字段（id/name/engine_name/engine_version/instance_status/frozen/type/pay_model/spec_code/availability_zone_ids/read_only_instances/current_actions/volume_type/volume_size/enterprise_project_id）与状态中文语义；停止后虚拟机（VM）停止收费但 EIP、存储、备份继续计费；实例默认停止十五天，十五天内未手动开启将于十五天后的下一个可维护时间段自动启动。"""
        result = await show_managed_instance(service, application_id)
        row = result["instance"]
        result["visual"] = visual.block("托管实例详情", visual.table(
            ["实例 ID", "名称", "引擎", "状态", "规格", "磁盘", "可用区", "进行中动作"],
            [[row.get("id"), row.get("name"),
              (row.get("engine_name") or "-") + " " + (row.get("engine_version") or ""),
              result["status_note"], row.get("spec_code"),
              (row.get("volume_type") or "-") + (" " + str(row["volume_size"]) + "GB" if row.get("volume_size") is not None else ""),
              ",".join(row.get("availability_zone_ids") or []) or "-",
              ",".join(str(item) for item in (row.get("current_actions") or [])) or "-"]]))
        return result

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def stop_supabase_managed_instance(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """停止一个 RDS Supabase 应用托管的数据库实例（异步任务）。实例目标始终解析自该应用的 managed_instance 字段，不接受裸 instance_id，杜绝误操作其他独立数据库实例，仅支持单实例操作。官方约束：仅支持停止存储类型为超高IO/SSD云盘/极速型SSD 的按需实例（专属云不支持）；仅运行中（normal）且无进行中操作的实例可停止，创建、重启、扩容、变更规格、恢复、修改端口等状态不能停止；停止主实例会同时停止只读实例；停止后虚拟机（VM）停止收费，但 EIP、存储、备份继续计费；已停止实例删除后不进回收站；实例默认停止十五天，十五天内未手动开启将于十五天后的下一个可维护时间段自动启动；停止后可能因资源不足导致开启失败，建议业务低峰期操作。两段式：preview（confirm=false）回读实例状态、返回影响说明并签发 plan_id；confirm=true+plan_id 一次提交。任务受理后用 show_operation_job_status(job_id) 查询任务状态直至终态。"""
        return await managed_instance_lifecycle(service, application_id, "stop", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def start_supabase_managed_instance(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """启动一个 RDS Supabase 应用托管的、已停止的数据库实例（异步任务）。实例目标始终解析自该应用的 managed_instance 字段，不接受裸 instance_id，仅支持单实例操作。官方约束：仅支持开启状态为已停止（shutdown）且未冻结的实例；开启主实例会同时开启其只读实例；按需实例可能因资源不足导致开启失败，失败时联系客服处理。两段式：preview（confirm=false）回读实例状态、返回影响说明并签发 plan_id；confirm=true+plan_id 一次提交。任务受理后用 show_operation_job_status(job_id) 查询任务状态直至终态。"""
        return await managed_instance_lifecycle(service, application_id, "start", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def restart_supabase_managed_instance(application_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """重启一个 RDS Supabase 应用托管的数据库实例（异步任务）。实例目标始终解析自该应用的 managed_instance 字段，不接受裸 instance_id，仅支持单实例操作。官方约束：仅运行中（normal）、无进行中操作且未冻结的实例可重启，已停止的实例须先启动；创建、扩容、变更规格、备份、恢复、修改端口或冻结状态下不能重启；重启过程中实例不可用，请谨慎操作，建议业务低峰期执行。两段式：preview（confirm=false）回读实例状态、返回影响说明并签发 plan_id；confirm=true+plan_id 一次提交。任务受理后用 show_operation_job_status(job_id) 查询任务状态直至终态。"""
        return await managed_instance_lifecycle(service, application_id, "restart", confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def reset_supabase_api_key(application_id: str, key_id: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Preview or reset a key. Existing clients can lose access; does not retrieve the new secret. 任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        return await service.mutate(application_id, "reset_key", {"key_id":key_id}, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def update_supabase_auth_flags(application_id: str, enable_account_sign_up: bool | None = None, enable_anonymous_users: bool | None = None, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Update only supplied registration flags. Omitted flags remain unchanged; review anonymous access. 任务受理后用 show_operation_job_status(job_id) 查询任务状态。"""
        body = {k:v for k,v in {"enable_account_sign_up":enable_account_sign_up,"enable_anonymous_users":enable_anonymous_users}.items() if v is not None}
        return await service.mutate(application_id, "auth_flags", body, confirm, plan_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def change_supabase_application_password(application_id: str, request_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Change only the Supabase application password using an operator-provisioned local request alias.
        Never pass a password in tool arguments. Backend password policy remains authoritative.
        Preview first; explicit confirmation and the unchanged plan are required to submit once.
        任务受理后用 show_operation_job_status(job_id) 查询任务状态。
        """
        return await service.mutate_reference(application_id,'password',request_ref,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def update_supabase_auth_config(application_id: str, request_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Partially update supported Auth URLs/providers/confirmation template via a protected local alias.
        Omitted fields stay unchanged. Provider disabling may clear nested configuration.
        Unknown fields, null clears and unsupported templates are rejected. No secrets in tool input.
        任务受理后用 show_operation_job_status(job_id) 查询任务状态。
        """
        return await service.mutate_reference(application_id,'auth_config',request_ref,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.WRITE)
    async def update_supabase_storage(application_id: str, request_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """Configure Storage using a protected local alias: first enable requires full bucket/AK/SK.
        Omitted SK retains the current value only when Storage is already enabled with the same AK. Disabling requires empty/omitted secret fields.
        Review OBS cost and access effects; accepted job is not business completion.
        任务受理后用 show_operation_job_status(job_id) 查询任务状态。
        """
        return await service.mutate_reference(application_id,'storage',request_ref,confirm,plan_id)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_flavors_with_azs(az_code: str, mode: str) -> dict:
        """Query Supabase application flavors in an explicit AZ and Single/Ha mode, each flavor carrying the AZ list it supports - use this both for flavor sizing and as the availability-zone list for AZ selection. No defaults or price claims."""
        return await service.creation_candidates('flavors',az_code,mode)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_supabase_manageable_instances() -> dict:
        """Query PG candidates for application_type=supabase. Candidate presence is not full creation readiness."""
        return await service.creation_candidates('manageable')

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def show_supabase_creation_progress(application_id: str, application_job_id: str,
                                              instance_job_id: str | None = None,
                                              instance_id: str | None = None) -> dict:
        """Analyze the end-to-end creation progress of one application from the ids returned by the scenario creation tools.

        Existing-instance scenario: pass application_id and application_job_id only. New-instance
        scenario: also pass instance_job_id and instance_id - the instance task is checked first,
        and the application task is only queried once the instance has succeeded, because the
        application is created after the instance is ready. Returns one phase verdict:
        instance_creating, application_creating, succeeded, or failed with the failed stage.
        """
        return await service.creation_progress(application_id, application_job_id, instance_job_id, instance_id)

    @server.tool()
    @guard(risk=ToolRisk.DANGEROUS)
    async def deliver_supabase_api_key(application_id: str, key_id: str, delivery_ref: str, confirm: bool = False, plan_id: str | None = None) -> dict:
        """After explicit confirmation, deliver one selected normal key to an operator-configured protected local file.
        No key value or arbitrary path in arguments/output. Operator ACL and trusted manual opening are required.
        Never read the delivered file using an Agent tool. Copying is a trusted client action, not a cloud API.
        """
        return await service.deliver_key(application_id,key_id,delivery_ref,confirm,plan_id)

    catalog = InstanceCatalog()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_db_instance_engine_versions() -> dict:
        """Query PostgreSQL engine versions available for managed instances, for the create-with-new-instance scenario. Use the highest version unless the user needs an older one."""
        return await catalog.list_engine_versions()

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_db_instance_flavors_with_azs(version_name: str | None = None) -> dict:
        """Query PostgreSQL instance flavors for the create-with-new-instance scenario; each flavor carries its AZ sale status, doubling as the AZ availability source. Filter by major version (e.g. 17) or omit for all."""
        return await catalog.list_flavors(version_name)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def list_db_instance_storage_types(version_name: str, ha_mode: str) -> dict:
        """Query storage types available for a managed PostgreSQL instance in the create-with-new-instance scenario, filtered by engine version and deployment mode (single/ha)."""
        return await catalog.list_storage_types(version_name, ha_mode)

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_supabase_create_basic_options(az_code: str) -> dict:
        """Discover and pre-fill the Supabase application's own creation basics for one availability zone: available versions, Single/Ha support (live-probed), saleable application flavors with per-AZ status, defaults for name/password/storage, and the security-group strategy.

        Covers the top-level application fields only. Network placement and the concrete
        security-group plan come from discover_network_for_create; managed-instance fields come
        from discover_db_instance_for_create. The strategy here is guidance only: application
        group 8443 ingress (source options: default 0.0.0.0/0, current-device CIDR, custom) plus
        egress opening the managed instance's port (default 5432); the database group is created
        for new instances and left untouched for existing ones. Guidance only - nothing is
        created here.
        """
        result = await BasicOptionsDiscovery().discover(az_code)
        result['visual'] = visual.render_basic_options(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_network_for_create(scenario: str, availability_zone: str | None = None, instance_id: str | None = None, detect_access_ip: bool = False) -> dict:
        """Discover the network placement and the security-group plan for create_supabase_application, by instance source (scenario, same values as manage_type).

        newly_instance: walks VPCs/subnets through KooCLI for sufficient free IPs (>=2 preferred,
        >=1 fallback, default_vpc/default_subnet recommendation when the region has none) and,
        with the chosen subnet CIDR, states both groups' creation configuration: application
        group - 8443 ingress (source options: default 0.0.0.0/0, current-device CIDR via
        detect_access_ip=true, or custom; /0 rules go through KooCLI) plus 5432 egress, without
        which the app cannot be logged into or cannot reach the database; database group - 5432
        ingress from the subnet CIDR (egress default allow-all), without which Supabase is
        unusable. existed_instance: instance_id required; takes VPC/subnet from that attachable
        instance, leaves the instance's security group untouched, same application-group rules.
        All rule CIDRs are the chosen VPC subnet's CIDR. Specification only - nothing is
        created here; the later creation follows the returned apply_steps strictly
        (create_supabase_security_group / add_supabase_security_group_rule, KooCLI for /0 rules).
        """
        network = NetworkDiscovery()
        result = await network.discover_network_for_create(scenario, availability_zone, instance_id, detect_access_ip)
        result['visual'] = visual.render_network(result)
        return result

    @server.tool()
    @guard(risk=ToolRisk.READ)
    async def discover_db_instance_for_create(scenario: str, mode: str | None = None, instance_id: str | None = None) -> dict:
        """Discover what the managed-instance step of create_supabase_application needs, by instance source (scenario, same values as manage_type).

        newly_instance: engine versions, instance flavors with per-AZ sale status, mode-filtered
        storage types (Single/Ha), and a recommended value for every managed_instance field.
        existed_instance: the attachable PG candidates (same source as
        list_supabase_manageable_instances); pass instance_id to get that instance's basic,
        configuration and network information for the attach decision. Network placement and
        security-group planning belong to discover_network_for_create. Read-only: nothing
        is created or changed here.
        """
        result = await catalog.discover_db_instance_for_create(scenario, mode, instance_id)
        result['visual'] = visual.render_db_instance(result)
        return result
