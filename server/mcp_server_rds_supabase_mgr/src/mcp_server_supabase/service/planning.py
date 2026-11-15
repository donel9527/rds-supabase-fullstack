"""Offline planning only; no cloud operation or invented resource data."""
import os
from mcp_server_supabase.service.contracts import ssl_body
from mcp_server_supabase.client.base import OfflineClient, SupabaseClient

try:
    from mcp_server_supabase.service.instance_catalog import GROUP_TYPE_LABELS as _GROUP_TYPE_LABELS
except Exception:
    _GROUP_TYPE_LABELS = {"general": "通用型", "dedicated": "专属型", "bigmem": "大内存型", "arm": "鲲鹏型"}

SCENARIOS = {
    "create": "Creation via local reference available: existing PG (database_name fixed to root) or new PG (Single or Ha mode; postPaid or prepaid 1-9 months / 1-3 years - prepaid returns a console order); intent-driven phase planning via plan_supabase_creation; backend policy/live acceptance pending",
    "delete": "Application-only execution available; PG cascade remains unavailable",
    "access": "SSL/EIP/application-password adapters available; SCM certificate inventory (list_ssl_certificates) and two-phase purchase (purchase_supabase_ssl_cert) available; live validation pending",
    "security_group": "Native VPC group query/create and rule add/delete adapters available; shared-resource inventory and live validation pending",
    "apikey": "Metadata/reset and protected local-file key delivery available; automatic new-key correlation unavailable",
    "business_config": "Auth/SMTP/GitHub/confirmation-template/OBS adapters available; omitted SK requires enabled Storage and unchanged AK",
}


class PlanningService:
    PAGE_SIZE = 20

    def __init__(self, client: SupabaseClient | None = None, basics=None, catalog=None, network=None):
        self.client = client if client is not None else OfflineClient()
        self.basics = basics
        self.catalog = catalog
        self.network = network

    def _basics_service(self):
        if self.basics is None:
            from mcp_server_supabase.service.instance_catalog import BasicOptionsDiscovery
            self.basics = BasicOptionsDiscovery()
        return self.basics

    def _catalog_service(self):
        if self.catalog is None:
            from mcp_server_supabase.service.instance_catalog import InstanceCatalog
            self.catalog = InstanceCatalog()
        return self.catalog

    def _network_service(self):
        if self.network is None:
            from mcp_server_supabase.service.instance_catalog import NetworkDiscovery
            self.network = NetworkDiscovery()
        return self.network

    def capabilities(self) -> dict[str, object]:
        return {"mode": "configured_" + os.getenv("SUPABASE_TRANSPORT", "rest"), "generated_supabase_sdk": False, "input_policy": "reject_unknown_fields", "local_plan_cancellation": "prepared_only", "cloud_execution": "configured_subset", "implemented_operations": ["application queries", "key metadata", "auth query", "job query", "bounded job observation", "accepted Auth plan reconciliation", "SSL", "EIP", "application lifecycle (start/stop/restart)", "managed-instance lifecycle (stop/start/restart) and simplified detail query", "application-only deletion", "key reset", "registration flags", "local request references", "application password", "Auth providers and confirmation template", "OBS full-credential update", "VPC group query/create", "VPC rule add/delete", "security-group set for application/managed/attachable instance", "creation candidate queries", "Single and Ha creation (postPaid or prepaid order)", "protected local key delivery"], "scenarios": SCENARIOS.copy()}

    @staticmethod
    def _candidate_view(row):
        """Complete, lock-aware rendering of one attachable instance: basic identity fields
        never omitted, current action locks surfaced so busy instances can be excluded."""
        nodes=row.get("nodes") if isinstance(row.get("nodes"),list) else []
        azs=[node.get("availability_zone") for node in nodes
             if isinstance(node,dict) and node.get("availability_zone")]
        azs=azs or ([row["availability_zone"]] if row.get("availability_zone") else [])
        datastore=row.get("datastore") if isinstance(row.get("datastore"),dict) else {}
        ha=row.get("ha") if isinstance(row.get("ha"),dict) else {}
        actions=row.get("current_actions") or row.get("actions") or row.get("action_status")
        if not isinstance(actions,list):
            actions=[actions] if actions else []
        created=row.get("created") or row.get("created_at") or row.get("create_time")
        return {"id":row.get("id"),"name":row.get("name"),"status":row.get("status"),
                "datastore_version":datastore.get("version"),
                "deployment_type":row.get("instance_mode") or ha.get("mode"),
                "port":row.get("port"),"availability_zones":azs,"created":created,
                "current_actions":actions,
                "vpc_id":row.get("vpc_id"),"subnet_id":row.get("subnet_id"),
                "security_group_id":row.get("security_group_id")}

    @staticmethod
    def _flavor_entries(block):
        groups = block.get("groups") if isinstance(block, dict) else None
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            specs = group.get("specs")
            for spec in specs if isinstance(specs, list) else []:
                if isinstance(spec, dict) and spec.get("spec_code"):
                    yield group.get("group_type"), spec

    @staticmethod
    def _same_number(left, right):
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return str(left) == str(right)

    @staticmethod
    def _number_key(value):
        try:
            return (0, int(value), "")
        except (TypeError, ValueError):
            return (1, 0, str(value) if value is not None else "")

    async def arrangement(self, manage_type, az_code=None, mode=None, page=1, instance_id=None,
                          detect_access_ip=False, needs_storage=None, needs_public_access=None,
                          needs_ssl=None, needs_email_login=None, needs_github_login=None) -> dict[str, object]:
        """End-to-end creation arrangement: runs the three discovery tools live, consolidates
        their parameters into a fixed baseline, and emits a step-numbered creation flow for
        strict 1:1 execution. Planning only - nothing is created here."""
        if manage_type not in ("newly_instance", "existed_instance"):
            return {"error": {"code": "MCP_INVALID_ARGS",
                              "message": "manage_type must be the user's definitive conclusion",
                              "hint": "Present both routes and get an explicit answer first: newly_instance (recommended default - the managed PG is created together with the application) or existed_instance (attach an existing PG)"}}
        if type(page) is not int or not 1 <= page <= 500:
            return {"error": {"code": "MCP_INVALID_ARGS", "message": "page must be an integer from 1 to 500"}}

        # Module 1: Supabase basics (live via discover_supabase_create_basic_options)
        app_flavor = None
        module_basics = {"source_tool": "discover_supabase_create_basic_options", "status": "pending_decision",
                         "hint": "回填 az_code 重新生成本编排（可售 AZ 见 list_supabase_flavors_with_azs）",
                         "baseline": None}
        if az_code:
            result = await self._basics_service().discover(az_code)
            options = result.get("basic_options") or {}
            def _pick(field):
                block = options.get(field) if isinstance(options.get(field), dict) else {}
                return block.get("suggested") or block.get("recommended")
            module_basics = {"source_tool": "discover_supabase_create_basic_options", "status": "fixed",
                             "baseline": {"name": _pick("name"), "version": _pick("version"),
                                          "mode": _pick("mode"), "flavor_ref": _pick("flavor_ref"),
                                          "availability_zone": az_code,
                                          "storage_component": ({"enabled": True, "note": "桶名与持久 AK/SK 经本地请求文件"} if needs_storage is True
                                                                else ({"enabled": False} if needs_storage is False
                                                                      else "决策点：创建后不可再启用，创建前必须确认")),
                                          "password": "经本地请求文件提供（8-32 位三类字符，dashboard 登录用户 supabase）"},
                             "flavor_interaction": "应用规格单独询问：展示全部可售规格（按规格类型分组、含 vCPU/内存），供用户选择或自定义输入；推荐通用型 2U4G",
                             "probe_status": result.get("probe_status")}
            app_baseline_flavor = module_basics["baseline"]["flavor_ref"]
            if app_baseline_flavor:
                for group_type, spec in self._flavor_entries(options.get("flavor_ref")):
                    if spec.get("spec_code") == app_baseline_flavor:
                        if group_type:
                            app_flavor = {"spec_code": app_baseline_flavor, "group_type": group_type,
                                          "vcpus": spec.get("vcpus"), "ram": spec.get("ram")}
                        break

        # Module 2: managed instance (live via discover_db_instance_for_create)
        if manage_type == "newly_instance":
            instance_result = await self._catalog_service().discover_db_instance_for_create("newly_instance", mode or "Single")
            fields = instance_result.get("managed_instance_field_options") or {}
            def _rec(field):
                block = fields.get(field) if isinstance(fields.get(field), dict) else {}
                return block.get("recommended")
            az_values = (fields.get("availability_zone") or {}).get("values") or []
            flavor_baseline = _rec("flavor_ref")
            flavor_match = None
            if app_flavor is not None:
                same_group = [spec for group_type, spec in self._flavor_entries(fields.get("flavor_ref"))
                              if group_type == app_flavor["group_type"]]
                matched = None
                match_basis = None
                if same_group:
                    if app_flavor["vcpus"] is not None and app_flavor["ram"] is not None:
                        exact = sorted((spec for spec in same_group
                                        if str(spec.get("vcpus")) == str(app_flavor["vcpus"])
                                        and self._same_number(spec.get("ram"), app_flavor["ram"])),
                                       key=lambda spec: str(spec.get("spec_code")))
                        if exact:
                            matched = exact[0]
                            match_basis = "group_type+vcpus+ram"
                    if matched is None:
                        matched = sorted(same_group, key=lambda spec: (self._number_key(spec.get("vcpus")),
                                                                       self._number_key(spec.get("ram")),
                                                                       str(spec.get("spec_code"))))[0]
                        match_basis = "group_type"
                if matched is not None:
                    flavor_baseline = matched.get("spec_code")
                    flavor_match = {"app_flavor_ref": app_flavor["spec_code"],
                                    "app_group_type": app_flavor["group_type"],
                                    "app_group_label": _GROUP_TYPE_LABELS.get(app_flavor["group_type"], app_flavor["group_type"]),
                                    "matched_spec": matched.get("spec_code"),
                                    "match_basis": match_basis}
            volume_type = _rec("volume.type")
            volume_basis = None
            volume_block = fields.get("volume.type") if isinstance(fields.get("volume.type"), dict) else {}
            volume_options = volume_block.get("options")
            if app_flavor is not None and isinstance(volume_options, list) and volume_options:
                compatible = [entry for entry in volume_options if isinstance(entry, dict)
                              and (not entry.get("compatible_group_types")
                                   or (isinstance(entry.get("compatible_group_types"), list)
                                       and app_flavor["group_type"] in entry["compatible_group_types"]))]
                picked = None
                for preferred in ("ESSD", "CLOUDSSD", "GPSSD2"):
                    picked = next((entry for entry in compatible if str(entry.get("value")) == preferred), None)
                    if picked is not None:
                        break
                if picked is None and compatible:
                    picked = compatible[0]
                if picked is not None and picked.get("value") is not None:
                    volume_type = picked.get("value")
                    volume_basis = "与匹配规格（group_type=%s）实时兼容" % app_flavor["group_type"]
            module_instance = {"source_tool": "discover_db_instance_for_create", "status": "fixed",
                               "baseline": {"datastore": {"type": "PostgreSQL", "version": _rec("datastore.version")},
                                            "flavor_ref": flavor_baseline,
                                            "volume": {"type": volume_type, "size": _rec("volume.size") or 40},
                                            "charge_info": _rec("charge_info") or {"charge_mode": "postPaid"},
                                            "ha": {"mode": mode or "Single", "replication_mode": "async"},
                                            "availability_zone": az_code or (az_values[0] if az_values else None),
                                            "port": _rec("port") or 5432,
                                            "enterprise_project_id": _rec("enterprise_project_id") or "0",
                                            "security_group_id": "<建组后回填（模块3 apply_steps）>"},
                               "flavor_interaction": "实例规格与应用规格分开单独询问：按 group_type 分大类展示全部规格，默认推荐与 Supabase 应用相同的规格（同规格类型且同 vCPU/内存）",
                               "volume_interaction": "磁盘类型明确展示（中文名+官方说明+实时兼容规格类型）供用户选择，默认推荐与所选规格兼容的类型",
                               "field_options": fields,
                               "discovery_status": instance_result.get("discovery_status"),
                               "top_level_reminder": instance_result.get("top_level_reminder")}
            if flavor_match is not None:
                module_instance["baseline"]["flavor_match"] = flavor_match
            if volume_basis is not None:
                module_instance["baseline"]["volume"]["type_basis"] = volume_basis
        elif not instance_id:
            listing = await self._catalog_service().discover_db_instance_for_create("existed_instance")
            rows = listing.get("candidates") or []
            start_at = (page - 1) * self.PAGE_SIZE
            module_instance = {"source_tool": "discover_db_instance_for_create", "status": "instance_selection",
                               "pagination": {"page": page, "page_size": self.PAGE_SIZE,
                                              "total_count": len(rows),
                                              "total_pages": max(1, -(-len(rows) // self.PAGE_SIZE)),
                                              "note": "page 逐页取全量；源站单次最多返回 100 条"},
                               "candidates_page": [self._candidate_view(row) for row in rows[start_at:start_at + self.PAGE_SIZE]],
                               "action_lock": "current_actions 非空或 status 非 ACTIVE 表示实例正在执行重大操作（重启/升级/变更）——下发任务会冲突失败，必须排除该实例",
                               "hint": "排除带 action 锁的实例后选定一个，把 instance_id 回填本工具生成完整编排"}
        else:
            detail = await self._catalog_service().discover_db_instance_for_create("existed_instance", instance_id=instance_id)
            module_instance = {"source_tool": "discover_db_instance_for_create", "status": "fixed",
                              "instance": detail,
                              "baseline": {"existing_instance": {"instance_id": instance_id,
                                                                 "database_name": "root（固定，不可改）",
                                                                 "database_pwd": "经本地请求文件提供"}},
                              "note": "已有实例参数不可改；其安全组保持现状不动"}

        # Module 3: network control (live via discover_network_for_create)
        if manage_type == "newly_instance":
            network_result = await self._network_service().discover_network_for_create(
                "newly_instance", availability_zone=az_code, detect_access_ip=detect_access_ip)
            module_network = {"source_tool": "discover_network_for_create", "status": "fixed",
                              "placement": {k: network_result.get(k) for k in
                                            ("preference", "vpc_id", "vpc_name", "vpc_cidr", "subnet_id",
                                             "subnet_name", "subnet_cidr", "availability_zone",
                                             "available_ip_count", "basic_config_usage", "default_create")},
                              "security_group_plan": network_result.get("security_group_plan")}
        elif not instance_id:
            module_network = {"source_tool": "discover_network_for_create", "status": "pending_decision",
                              "hint": "先在模块2选定实例，再以 instance_id 生成网络编排"}
        else:
            network_result = await self._network_service().discover_network_for_create(
                "existed_instance", instance_id=instance_id, detect_access_ip=detect_access_ip)
            module_network = {"source_tool": "discover_network_for_create", "status": "fixed",
                              "placement": {k: network_result.get(k) for k in
                                            ("vpc_id", "subnet_id", "subnet_cidr", "basic_config_usage")},
                              "security_group_plan": network_result.get("security_group_plan"),
                              "note": "实例安全组不动；应用组按 plan 建组配规则"}

        module_obs = None
        if needs_storage is True:
            from mcp_server_supabase.service.obs import ObsService
            obs = ObsService()
            suggested = (module_basics.get("baseline") or {}).get("name") or "supabase-app"
            module_obs = {"source_tool": "discover_supabase_storage",
                          "acquisition": {"options": [
                              {"key": "reuse", "name": "复用已有桶", "note": "私有桶优先；公共桶提示匿名公开风险尽量不用；无可选则转新建"},
                              {"key": "new", "name": "新建桶", "note": "全新私有桶，完全隔离，安全可靠"}],
                              "recommended": "new"},
                          "new_bucket_spec": obs.new_bucket_spec(obs.bucket_name_for(suggested), "multi_az"),
                          "credential": obs.credential_mode(),
                          "note": "先调 discover_supabase_storage 确定获取方式；新建走 create_supabase_new_obs；storage_component（bucket + 持久 AK/SK 经本地请求文件）随创建请求一次提交"}

        # Public access (EIP) module
        module_public = None
        if needs_public_access is True:
            module_public = {"status": "planned",
                             "applies_when": "公网访问（needs_public_access；建议默认启用）",
                             "purchase_method": {"options": [{"charge_mode": "postPaid", "name": "按需购买",
                                                             "note": "随用随停，试运行与变更期成本可控"},
                                                            {"charge_mode": "prePaid", "name": "包周期",
                                                             "note": "订单支付与退订受合约约束，长期稳定运行再选"}],
                                                 "recommended": {"charge_mode": "postPaid", "name": "按需购买"}},
                             "bandwidth": {"share_type": "PER（独享带宽）",
                                           "type": "全动态 BGP（publicip.type=5_bgp）",
                                           "size_range_mbps": "5-1000", "recommended_size_mbps": 300},
                             "purchase": "优先空闲：create_supabase_eip(prefer_idle=true) 先列未绑定 EIP 供用户选定（直接用于绑定，不新建）；无空闲或 prefer_idle=false 则按基线新建（KooCLI EIP CreatePublicip，postPaid 自动打标 USAGE_FOR=Supabase应用公网访问，自动创建的）；也可控制台购买",
                             "bind": "bind_supabase_eip(instance_id, public_ip_id, public_ip)（in32 结尾应用 ID、归属、格式三重校验，RDS AttachEip）",
                             "post_bind": "绑定成功后必须 update_supabase_auth_config 同步 api_external_url（邮箱链接与 OAuth 回调都指向它）"}
        elif needs_public_access is False:
            module_public = {"status": "excluded", "delivery": "内网交付 private_ip；不购买 EIP、不开公网入方向"}

        # SSL configuration module
        module_ssl = None
        if needs_ssl is True:
            module_ssl = {"source_tools": ["list_ssl_certificates", "purchase_supabase_ssl_cert", "change_supabase_ssl"],
                          "status": "planned",
                          "acquisition": {"options": [
                              {"key": "reuse", "name": "复用已有证书",
                               "note": "list_ssl_certificates 盘点账号已有证书（账号级 SCM 资源），取其 id 作 change_supabase_ssl 的 cert_id"},
                              {"key": "purchase", "name": "MCP 工具购买+申请（推荐）",
                               "note": "purchase_supabase_ssl_cert 两段式：SCM 订阅+申请一次完成；推荐免费档 DV_SSL_CERT_BASIC（有域名时）；付费 DV/OV/EV 按需"},
                              {"key": "import_own", "name": "导入自有证书",
                               "note": "控制台/ImportCertificate 导入第三方证书后取 id"}],
                              "recommended": "purchase"},
                          "domain_note": "域名与 IP 前提：证书绑定域名；当前访问地址为 https://<EIP>:8443 形式时——纯 EIP 无域名可申请公网 IP 证书（仅文件 File 验证）；有域名则 DNS 验证最顺且华为云 DNS 可自动推送（auto_dns_auth）",
                          "enable_flow": ["change_supabase_ssl(application_id, enable_ssl=true, cert_id=证书 id) 两段式"],
                          "impact": ["SSL 切换短暂中断，低峰执行", "生效后 api_external_url 协议变 https，需复核邮箱链接与 OAuth 回调"]}
        elif needs_ssl is False:
            module_ssl = {"status": "excluded",
                          "note": "http 访问（enable_ssl=false），内网/试运行可接受；后续可经 change_supabase_ssl 开启（需证书）"}

        # Step-numbered creation flow - executed strictly, one by one
        sg_steps = (module_network.get("security_group_plan") or {}).get("apply_steps") or []
        flow = []
        def _step(phase, tool, action=None, args=None, returns=None, note=None):
            entry = {"step": len(flow) + 1, "phase": phase, "tool": tool}
            if action is not None: entry["action"] = action
            if args is not None: entry["args"] = args
            if returns is not None: entry["returns"] = returns
            if note is not None: entry["note"] = note
            flow.append(entry)
        if manage_type == "newly_instance":
            placement = module_network.get("placement") or {}
            if placement.get("preference") == "default_recommendation":
                _step("network_ready", "console/KooCLI",
                      action="区域无可用网络：按 default_create 建 default_vpc（192.168.0.0/16）与 default_subnet（192.168.0.0/24，AZ 与实例一致，网关 192.168.0.1），建好后重跑 discover_network_for_create 取真实 ID",
                      note="basic_config 的 vpc_id/subnet_id 以真实 ID 为准")
            else:
                _step("network_ready", "discover_network_for_create",
                      action="直接采用已选定的 VPC/子网填入 basic_config（vpc_id=%s, subnet_id=%s）" % (placement.get("vpc_id"), placement.get("subnet_id")))
        else:
            _step("instance_confirm", "discover_db_instance_for_create",
                  action=("已选定实例 %s；确认无 action 锁后继续" % instance_id) if instance_id
                        else "排除 current_actions 非空或 status 非 ACTIVE 的实例，选定一个后把 instance_id 回填本工具",
                  note="带 action 锁（重启/升级/变更中）的实例下发任务会冲突失败")
        # Security groups (and, when enabled, the OBS bucket) are provisioned automatically
        # by the scenario creation tool per module 3's specification - not manual steps.
        if needs_storage is True:
            _step("obs_integration", "discover_supabase_storage",
                  action="确定 OBS 获取方式：复用已有桶（私有优先）或新建（推荐、默认）",
                  note="临时凭证（SecurityToken）时须先取得长期 AK/SK 再对接")
        if manage_type == "newly_instance":
            _step("request_file", "本地请求文件",
                  action="按基线组装创建请求体：name/version/mode/flavor_ref/availability_zone（顶层与实例一致）+ basic_config{vpc_id,subnet_id} + managed_instance（模块2 baseline）+ storage_component%s；安全组与桶无需手填——创建工具自动创建并回填" % ("（bucket=复用桶名或目标桶名，AK/SK 经文件）" if needs_storage is True else "（enabled:false）" if needs_storage is False else "（决策点：创建后不可再启用）"),
                  note="敏感字段（应用密码/数据库密码/存储 AK/SK）只进文件，不进对话")
        else:
            _step("request_file", "本地请求文件",
                  action="按基线组装：name/version/mode/flavor_ref/availability_zone + basic_config{vpc_id,subnet_id}（模块3）+ manage_type=existed_instance + existing_instance{instance_id, database_name:'root', database_pwd}；安全组无需手填——创建工具自动创建并回填",
                  note="敏感字段只进文件，不进对话")
        create_tool = "create_supabase_with_new_instance" if manage_type == "newly_instance" else "create_supabase_link_exist_instance"
        _step("create_preview", create_tool,
              args={"request_ref": "<请求文件别名>", "public_access_cidr": "<auto/open/自定义 CIDR>", "confirm": False},
              note="预览返回 plan_id（10 分钟内有效）；预览即解析三选一入方向网段")
        _step("create_submit", create_tool,
              args={"request_ref": "<请求文件别名>", "public_access_cidr": "<同预览>", "confirm": True, "plan_id": "<预览返回>"},
              note="确认后自动执行：专用安全组建组与规则（模块3 规格）+ OBS 桶确保（启用存储时）+ 参数回填注入，一次提交；新建实例场景返回实例与应用双任务 ID")
        _step("progress", "show_supabase_creation_progress",
              args={"application_id": "<返回值>", "application_job_id": "<返回值>",
                    "instance_job_id": "<新建场景返回值，已有场景省略>",
                    "instance_id": "<新建场景返回值，已有场景省略>"},
              note="整体约 20-30 分钟；新建场景实例先就绪、应用任务才开始")
        _step("verify", "show_supabase_application",
              args={"application_id": "<application_id>"},
              note="status 就绪且无进行中任务")

        # Post-creation flow, conditioned on the intents
        post = []
        if needs_public_access is False:
            post.append({"tool": "show_supabase_application", "action": "内网交付 private_ip；不购买 EIP、不开公网入方向"})
        else:
            post.append({"tool": "create_supabase_eip",
                         "action": "按 public_access 模块执行：prefer_idle=true 优先空闲（用户选定其一，直接绑定不新建）；无空闲则按需新建（全动态 BGP、300M 独享、自动打标）",
                         "args": {"prefer_idle": True, "charge_mode": "postPaid", "bandwidth_size_mbps": 300}})
            post.append({"tool": "bind_supabase_eip",
                         "args": {"instance_id": "<应用 ID（in32 结尾）>", "public_ip_id": "<EIP ID>", "public_ip": "<EIP 地址>"},
                         "note": "预览确认后绑定；in32/归属/格式三重校验"})
            post.append({"tool": "update_supabase_auth_config", "action": "同步 api_external_url 为公网地址",
                         "note": "邮箱链接与 OAuth 回调依赖此地址"})
            post.append({"tool": "probe", "action": "探活访问地址（任意 HTTP 状态即可达）"})
        if needs_ssl is False:
            post.append({"tool": "-", "action": "http 访问（enable_ssl=false），内网/试运行可接受"})
        else:
            post.append({"tool": "list_ssl_certificates", "action": "盘点已有证书：有可用证书取其 id（复用路径）"})
            post.append({"tool": "purchase_supabase_ssl_cert",
                         "action": "无可用证书则购买+申请（推荐免费档 DV_SSL_CERT_BASIC；有域名 DNS 验证，纯 EIP 公网 IP 证书仅 File 验证；is_auto_pay=false 生成待支付订单须支付后生效）"})
            post.append({"tool": "change_supabase_ssl",
                         "args": {"application_id": "<id>", "enable_ssl": True, "cert_id": "<证书 id>"},
                         "note": "切换短暂中断，低峰执行；完成后复核 api_external_url 协议"})
        if needs_storage is True:
            post.append({"tool": "update_supabase_storage", "action": "存储凭据轮换/更新：桶名与持久 AK/SK 经本地请求文件（创建后 storage_component 已定型，仅凭据可轮换）"})
        if needs_email_login is True:
            post.append({"tool": "update_supabase_auth_config", "action": "邮箱登录：SMTP 非密字段对话收集、SMTP 密码入请求文件；真实邮件验证"})
        elif needs_email_login is None:
            post.append({"decision": "needs_email_login 是否启用邮箱登录（SMTP 后配置）"})
        if needs_github_login is True:
            post.append({"tool": "update_supabase_auth_config", "action": "GitHub 登录：用户建 OAuth App，client secret 入请求文件，回调与公网地址一致；真实登录验证"})
        elif needs_github_login is None:
            post.append({"decision": "needs_github_login 是否启用 GitHub 登录"})
        post.append({"tool": "list_supabase_api_keys",
                     "action": "接入信息交付：show_supabase_application 出信息卡；key 值经 deliver_supabase_api_key 只入受保护本地文件"})

        decision_points = []
        if az_code is None: decision_points.append("az_code：可售 AZ 待选（list_supabase_flavors_with_azs）")
        if needs_storage is None: decision_points.append("needs_storage：是否存在大文件存储场景（图片/视频/大文件）——创建后不可再启用，创建前必须确认")
        if needs_public_access is None: decision_points.append("needs_public_access：公网访问（建议启用）")
        if needs_ssl is None: decision_points.append("needs_ssl：https（证书可经 MCP 购买或复用已有）")

        return {"status": "arrangement_baseline", "execution": "not_executed", "manage_type": manage_type,
                "declaration": "本工具为编排规划与参数基线，不创建任何资源；实际创建严格按 creation_flow 逐步执行，不偏离目标与计划",
                "managed_instance_source": {"decision": manage_type,
                                            "options": [{"value": "newly_instance", "name": "新建实例", "recommended": True,
                                                         "note": "应用与托管 PG 一并创建，参数全链路可控，推荐且为默认"},
                                                        {"value": "existed_instance", "name": "已有实例",
                                                         "note": "挂载现有可托管 PG；实例参数不可改，其安全组不动"}],
                                            "requirement": "两种方式必须先向用户明确呈现并拿到确定性结论，本编排按该结论展开"},
                "step_modules": {**({"supabase_basics": module_basics,
                                    "managed_instance": module_instance,
                                    "network_control": module_network}),
                                **({"obs_integration": module_obs} if module_obs else {}),
                                **({"public_access": module_public} if module_public else {}),
                                **({"ssl_configuration": module_ssl} if module_ssl else {})},
                "creation_flow": flow,
                "post_creation_flow": post,
                "decision_points": decision_points,
                "security_notes": ["应用密码、数据库密码、存储 AK/SK、SMTP 密码、GitHub client secret 只进受保护本地请求文件，预览与对话均不回显",
                                   "API key 值只经 deliver_supabase_api_key 落受保护本地文件，不进对话",
                                   "全 0（0.0.0.0/0）入方向规则经 KooCLI 配置，需用户明确确认"],
                "missing": ["后端密码/版本/容量/售卖策略以服务端为准", "SSL 证书购买/申请经 purchase_supabase_ssl_cert（SCM，全局服务）", "EIP 采购经 create_supabase_eip（空闲优先）"]}

    async def ssl(self, enable_ssl: bool) -> dict[str, object]:
        if not enable_ssl:
            return {"status": "planning_only", "execution": "not_executed", "request_body": ssl_body(False), "missing": ["verified transport", "job terminal schema", "live state verification"]}
        return {"status": "planning_only", "execution": "not_executed",
                "steps": ["list_ssl_certificates 盘点已有证书", "select compatible certificate", "review SSL enable plan", "submit once after execution support exists", "verify application state"],
                "acquisition": "无可用证书已可经 purchase_supabase_ssl_cert 购买+申请（推荐免费档 DV_SSL_CERT_BASIC；有域名 DNS 验证，纯 EIP 公网 IP 证书仅 File 验证）；也可复用已有或导入自有证书",
                "certificates": await self.client.list_certificates(),
                "missing": ["response and SSL effective-state contract"]}
