"""Security-group set (native SetSecurityGroup, full replacement) for one of
three targets: the Supabase application itself, the application's managed
instance (resolved live from the managed_instance binding - bare instance ids
are never accepted), or an attachable PG instance (candidate-list membership
enforced, for pre-creation security-group preparation in the attach scenario).
The endpoint answers 200 with workflowId - not job_id - queryable through
show_operation_job_status."""
import os
import re
from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails import assert_not_protected
from mcp_server_supabase.client.rest import segment
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.instance_catalog import _manageable_rows
from mcp_server_supabase.service.instance_lifecycle import _probe_instance, _resolve_managed
from mcp_server_supabase.service.operations import _DEFINITE_REJECTIONS, _JOB_FOLLOW_UP

_TARGETS = ("application", "managed_instance", "attachable_instance")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_IMPACT = [
    "全量替换语义：所给清单将整体替换现有安全组——需保留的既有组必须一并列入；替换后 8443/5432 放行缺失将导致应用不可访问。",
    "官方约束：实例在创建、数据库升级、变更规格、创建用户、删除用户状态下不能设置安全组。",
    "替换期间实例连接可能出现短暂中断。",
    "错误的安全组清单可能导致应用失联（应用不可登录、无法访问数据库）。",
]


def _group_id(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise McpToolError("MCP_INVALID_ARGS", "安全组 ID 必须是 UUID 格式",
                           hint="用 list_supabase_security_groups 查询安全组 ID 后回填。")
    return value


def _group_ids(security_group_ids):
    if not isinstance(security_group_ids, list) or not security_group_ids:
        raise McpToolError("MCP_INVALID_ARGS", "security_group_ids 必须是非空的安全组 UUID 清单",
                           hint="提供至少一个安全组 UUID；需保留的既有组必须一并列入。")
    return [_group_id(item) for item in security_group_ids]


def _guard_application(detail):
    if detail.get("current_actions"):
        raise McpToolError("MCP_GUARDRAIL_BLOCKED", "应用有进行中操作，须等待其完成后再修改安全组",
                           hint="用 show_operation_job_status 查询进行中任务，终态后重新 preview。")
    if detail.get("status") != "normal":
        raise McpToolError("MCP_GUARDRAIL_BLOCKED", "仅运行中（normal）的应用可修改安全组",
                           hint="先用 show_supabase_application 回查应用状态，确认后再操作。")


def _guard_instance(row):
    if row.get("current_actions"):
        raise McpToolError("MCP_GUARDRAIL_BLOCKED", "实例有进行中操作，须等待其完成后再修改安全组",
                           hint="用 show_operation_job_status 查询进行中任务，终态后重新 preview。")
    if row.get("instance_status") != "normal":
        raise McpToolError("MCP_GUARDRAIL_BLOCKED",
                           "仅运行中（normal）的实例可设置安全组；创建、数据库升级、变更规格、创建用户、删除用户状态下不能设置",
                           hint="先回查实例状态（show_supabase_managed_instance 或控制台），确认后再操作。")


async def _resolve_target(service, target, application_id, instance_id):
    if target == "application":
        application_id = segment(application_id)
        _, detail = await service.client.request("GET", service.app(application_id))
        if not isinstance(detail, dict) or detail.get("id") != application_id:
            raise McpToolError("MCP_NOT_FOUND", "Application not found",
                               hint="Discover the application id first, then preview again.")
        _guard_application(detail)
        return detail, application_id, detail.get("security_group_id")
    if target == "managed_instance":
        detail, resolved = await _resolve_managed(service, application_id)
        row = await _probe_instance(service, resolved)
        _guard_instance(row)
        return detail, resolved, (detail.get("managed_instance") or {}).get("security_group_id")
    instance_id = segment(instance_id)
    rows = await _manageable_rows(service)
    match = next((row for row in rows if row.get("id") == instance_id), None)
    if match is None:
        raise McpToolError("MCP_GUARDRAIL_BLOCKED",
                           "instance_id 不在本环境可挂载到 Supabase 应用的 PG 实例候选清单中",
                           hint="仅支持本环境可挂载到 Supabase 应用的 PG 实例——为挂载场景做前置安全组准备；"
                                "先用 list_supabase_manageable_instances 查看候选。")
    row = await _probe_instance(service, instance_id)
    _guard_instance(row)
    return match, instance_id, match.get("security_group_id")


async def change(service, target, security_group_ids, application_id=None, instance_id=None,
                 confirm=False, plan_id=None):
    """Set the security groups (full replacement) of one of three targets: the
    Supabase application itself, the application's managed instance (resolved
    live from the managed_instance binding - never a bare instance id), or an
    attachable PG instance (enforced against the attachable-candidate list, for
    pre-creation security-group preparation). Two-phase confirmation; acceptance
    is a workflowId tracked through show_operation_job_status.
    """
    if target not in _TARGETS:
        raise McpToolError("MCP_INVALID_ARGS", "Unsupported security-group target",
                           hint="target must be one of application, managed_instance, attachable_instance.")
    if application_id is not None and instance_id is not None:
        raise McpToolError("MCP_INVALID_ARGS", "application_id 与 instance_id 不得同时提供",
                           hint="一次只操作一个目标：application/managed_instance 模式给 application_id，"
                                "attachable_instance 模式给 instance_id。")
    if target in ("application", "managed_instance"):
        if application_id is None:
            raise McpToolError("MCP_INVALID_ARGS", "target=%s 需要 application_id" % target,
                               hint="提供该应用的 application_id。")
        if instance_id is not None:
            raise McpToolError("MCP_INVALID_ARGS", "target=%s 不接受 instance_id" % target,
                               hint="该模式的目标由 application_id 解析；独立实例目标仅限 "
                                    "attachable_instance 模式。")
    else:
        if application_id is not None:
            raise McpToolError("MCP_INVALID_ARGS", "target=attachable_instance 不接受 application_id",
                               hint="该模式服务于挂载已有实例的前置安全组准备；应用与其托管实例目标"
                                    "请使用 target=application 或 managed_instance。")
        if instance_id is None:
            raise McpToolError("MCP_INVALID_ARGS", "target=attachable_instance 需要 instance_id",
                               hint="提供待挂载 PG 实例的 instance_id。")
    security_group_ids = _group_ids(security_group_ids)
    if confirm and (os.getenv("SUPABASE_ENABLE_WRITES") != "true" or os.getenv("HUAWEICLOUD_MCP_READ_ONLY", "false").lower() == "true"):
        raise McpToolError("MCP_READ_ONLY", "Writes are disabled")
    context, target_id, current = await _resolve_target(service, target, application_id, instance_id)
    path = "/v3/{project}/instances/" + target_id + "/security-group"
    body = {"security_group_id": ",".join(security_group_ids)}
    digest = service.intent_digest("PUT", path, body)
    if not confirm:
        preview = {"status": "confirmation_required", "execution": "not_executed",
                   "target": target, "target_id": target_id,
                   "current_security_group_id": current,
                   "security_group_ids": list(security_group_ids),
                   "impact": list(_IMPACT), "resource_path": path}
        if current is None:
            preview["current_security_group_note"] = "当前安全组未知（目标详情未返回该字段）；全量替换语义不受影响——所给清单即最终清单。"
        preview.update(service.plans.issue(digest))
        return preview
    if target == "managed_instance":
        assert_not_protected(context)
        assert_not_protected({"id": target_id, "name": (context.get("managed_instance") or {}).get("name")})
    elif target == "application":
        assert_not_protected(context)
    else:
        assert_not_protected({"id": target_id, "name": context.get("name")})
    service.plans.claim(plan_id, digest)
    unknown = RecoveryError("MCP_SDK_ERROR", "Security-group set result unknown", "submission_unknown",
                            "Query the operation task and the target directly; do not resubmit - previews and the recorded intent are single-use.", plan_id)
    try:
        http_status, data = await service.client.request("PUT", path, body=body)
    except RecoveryError as error:
        if error.recovery.get("category") in _DEFINITE_REJECTIONS:
            service.plans.finish(plan_id, "failed"); raise
        service.plans.finish(plan_id, "unknown"); raise unknown from None
    except McpToolError:
        service.plans.finish(plan_id, "failed"); raise
    except BaseException:
        service.plans.finish(plan_id, "unknown"); raise unknown from None
    try:
        job_id, source = None, None
        if isinstance(data, dict):
            for key in ("workflowId", "job_id"):
                value = data.get(key)
                if isinstance(value, str):
                    job_id, source = value, key
                    break
        if http_status not in (200, 202) or not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError()
        service.plans.finish(plan_id, "accepted", job_id)
        # Resource-ledger rebind (advisory): the new set becomes the application's
        # binding; previously bound auto-created groups left out of the replacement
        # become detached residuals.
        record_warnings = []
        if getattr(service, "ledger", None) is not None:
            try:
                rows = service.ledger.rows(application_id, "security_group") if application_id else []
                current = {row["resource_id"] for row in rows}
                for group_id in security_group_ids:
                    warning = service.ledger.bind_safe(
                        "security_group", group_id, application_id,
                        detail={"role": "application" if target == "application" else target,
                                "binding": "change_supabase_security_group"})
                    if warning: record_warnings.append(warning)
                if application_id:
                    for row in rows:
                        if row["resource_id"] not in set(security_group_ids) and row["auto_created"]:
                            try:
                                service.ledger.detach("security_group", row["resource_id"])
                            except Exception:  # noqa: BLE001 - advisory persistence
                                pass
            except Exception as error:  # noqa: BLE001 - advisory persistence must not fail a finished change
                record_warnings.append("资源记录写入失败（安全组换绑）：%s" % error)
        response = {"status": "accepted", "job_id": job_id, "job_id_source": source,
                "complete": False, "target": target, "target_id": target_id,
                "security_group_ids": list(security_group_ids),
                "notices": {"warnings": list(_IMPACT)}, "job_follow_up": _JOB_FOLLOW_UP,
                "plan_id": plan_id}
        if record_warnings:
            response["record_warnings"] = record_warnings
        return response
    except BaseException:
        service.plans.finish(plan_id, "unknown"); raise unknown from None
