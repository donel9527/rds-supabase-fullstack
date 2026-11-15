"""Managed-database-instance lifecycle: the target is always resolved live from
the application's managed_instance binding; bare instance ids are never accepted,
so independent database instances cannot be touched by mistake. These native RDS
endpoints answer 200 with a job_id (not 202)."""
import os
import re
from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails import assert_not_protected
from mcp_server_supabase.client.rest import segment
from mcp_server_supabase.failures import RecoveryError
from mcp_server_supabase.service.operations import _DEFINITE_REJECTIONS, _JOB_FOLLOW_UP

_SIMPLIFIED_FIELDS = ("id", "name", "engine_name", "engine_version", "instance_status",
                      "frozen", "type", "pay_model", "spec_code", "availability_zone_ids",
                      "read_only_instances", "current_actions", "volume_type", "volume_size",
                      "enterprise_project_id")
_INSTANCE_STATUS_NOTES = {"normal": "正常", "abnormal": "异常", "creating": "创建中",
                          "createfail": "创建失败", "data_disk_full": "磁盘满",
                          "deleted": "已删除", "shutdown": "已停止（关机）"}
_INSTANCE_LIFECYCLE_WARNINGS = {
    "stop": ["停止后虚拟机（VM）停止收费，但 EIP、存储、备份继续正常计费。",
             "实例默认停止十五天；十五天内未手动开启，将于十五天后的下一个可维护时间段自动启动。",
             "已停止实例被删除后不进入回收站。",
             "停止后可能因资源不足导致开启失败。",
             "仅支持停止存储类型为超高IO、SSD云盘或极速型SSD 的按需实例（专属云不支持）。",
             "停止主实例会同时停止其只读实例，不支持单独停止只读实例。",
             "创建、重启、扩容、变更规格、恢复、修改端口等状态不能停止。",
             "建议在业务低峰期执行停止操作。"],
    "start": ["开启主实例会同时开启其只读实例。",
              "仅支持开启状态为已停止（shutdown）的实例。",
              "按需实例可能因资源不足导致开启失败，失败时请联系客服处理。"],
    "restart": ["重启过程中实例不可用，请谨慎操作。",
                "创建、扩容、变更规格、备份、恢复、修改端口或冻结状态下不能重启。",
                "建议在业务低峰期执行重启操作。"],
}


async def _resolve_managed(service, application_id):
    _, target = await service.client.request("GET", service.app(application_id))
    if not isinstance(target, dict) or target.get("id") != application_id:
        raise McpToolError("MCP_NOT_FOUND", "Application not found",
                           hint="Discover the application id first, then preview again.")
    managed = target.get("managed_instance")
    if not isinstance(managed, dict) or not managed.get("id"):
        raise McpToolError("MCP_GUARDRAIL_BLOCKED", "该应用没有可验证的托管实例",
                           hint="仅支持操作本应用绑定的托管实例；独立数据库实例不适用。")
    return target, segment(managed["id"])


async def _probe_instance(service, instance_id):
    _, data = await service.client.request("POST", "/v3/{project}/simplified-instances",
                                            body={"instance_ids": [instance_id]})
    rows = data.get("instances") if isinstance(data, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or rows[0].get("id") != instance_id):
        raise McpToolError("MCP_NOT_FOUND", "托管实例在实例清单中不可见",
                           hint="实例可能已被删除或不可达；回查控制台确认后再操作，不要盲目重试。")
    return rows[0]


def _action_request(action, instance_id):
    base = "/v3/{project}/instances/" + instance_id
    if action == "stop":
        return base + "/action/shutdown", {}
    if action == "start":
        return base + "/action/startup", {}
    return base + "/action", {"restart": {}}


async def show(service, application_id):
    """Read the application's managed instance through the simplified-instance view."""
    application_id = segment(application_id)
    target, instance_id = await _resolve_managed(service, application_id)
    row = await _probe_instance(service, instance_id)
    entry = {key: row.get(key) for key in _SIMPLIFIED_FIELDS}
    return {"application_id": application_id, "application_status": target.get("status"),
            "instance": entry,
            "status_note": _INSTANCE_STATUS_NOTES.get(entry["instance_status"], "未知状态"),
            "note": "此实例为该应用绑定的托管数据库实例，仅支持通过本应用的绑定关系查询与操作。"
                    "停止后虚拟机（VM）停止收费，但 EIP、存储、备份继续正常计费；"
                    "实例默认停止十五天，十五天内未手动开启将于十五天后的下一个可维护时间段自动启动。"}


async def lifecycle(service, application_id, action, confirm=False, plan_id=None):
    """Stop, start or restart the managed database instance of one Supabase
    application (asynchronous job).

    The instance is resolved live from the application's managed_instance
    binding on every call - preview and confirm both - and only single-instance
    operations are supported. State guardrails, per official contract: stop and
    restart require instance_status == normal with no current_actions; start
    requires instance_status == shutdown and not frozen; restart additionally
    rejects frozen instances.
    """
    application_id = segment(application_id)
    if action not in _INSTANCE_LIFECYCLE_WARNINGS:
        raise McpToolError("MCP_INVALID_ARGS", "Unsupported managed-instance lifecycle action",
                           hint="action must be one of stop, start, restart.")
    if confirm and (os.getenv("SUPABASE_ENABLE_WRITES") != "true" or os.getenv("HUAWEICLOUD_MCP_READ_ONLY", "false").lower() == "true"):
        raise McpToolError("MCP_READ_ONLY", "Writes are disabled")
    target, instance_id = await _resolve_managed(service, application_id)
    row = await _probe_instance(service, instance_id)
    status = row.get("instance_status")
    frozen = row.get("frozen") is True
    if action in ("stop", "restart") and row.get("current_actions"):
        raise McpToolError("MCP_GUARDRAIL_BLOCKED", "实例有进行中操作，须等待其完成后再执行生命周期操作",
                           hint="用 show_operation_job_status 查询进行中任务，终态后重新 preview。")
    if action == "stop":
        if status == "shutdown":
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "实例已在停止状态，无需停止",
                               hint="如需开启请使用 start_supabase_managed_instance。")
        if status != "normal":
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "仅运行中（normal）的实例可停止；创建、重启、扩容、变更规格、恢复、修改端口等状态不能停止",
                               hint="先用 show_supabase_managed_instance 回查实例状态，确认后再操作。")
    elif action == "start":
        if frozen:
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "实例处于冻结状态，不能开启",
                               hint="解除冻结后再执行开启操作。")
        if status == "normal":
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "实例已在运行，无需开启",
                               hint="开启仅适用于已停止（shutdown）的实例。")
        if status != "shutdown":
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "仅已停止（shutdown）的实例可开启",
                               hint="先用 show_supabase_managed_instance 回查实例状态，确认后再操作。")
    else:
        if frozen:
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "实例处于冻结状态，不能重启",
                               hint="解除冻结后再执行重启操作。")
        if status == "shutdown":
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "仅运行中（normal）的实例可重启，已停止的实例须先启动",
                               hint="先启动：使用 start_supabase_managed_instance 开启实例后再重启。")
        if status != "normal":
            raise McpToolError("MCP_GUARDRAIL_BLOCKED", "仅运行中（normal）的实例可重启",
                               hint="先用 show_supabase_managed_instance 回查实例状态，确认后再操作。")
    path, body = _action_request(action, instance_id)
    warnings = _INSTANCE_LIFECYCLE_WARNINGS[action]
    digest = service.intent_digest("POST", path, body)
    if not confirm:
        return {"status": "confirmation_required", "execution": "not_executed",
                "application_id": application_id, "instance_id": instance_id,
                "instance_status": status, "impact": list(warnings),
                "resource_path": path, **service.plans.issue(digest)}
    assert_not_protected(target)
    assert_not_protected({"id": instance_id, "name": target.get("managed_instance", {}).get("name")})
    service.plans.claim(plan_id, digest)
    unknown = RecoveryError("MCP_SDK_ERROR", "Managed-instance lifecycle change result unknown", "submission_unknown",
                            "Query the operation task and the instance directly; do not resubmit - previews and the recorded intent are single-use.", plan_id)
    try:
        http_status, data = await service.client.request("POST", path, body=body)
    except RecoveryError as error:
        if error.recovery.get("category") in _DEFINITE_REJECTIONS:
            service.plans.finish(plan_id, "failed"); raise
        service.plans.finish(plan_id, "unknown"); raise unknown from None
    except McpToolError:
        service.plans.finish(plan_id, "failed"); raise
    except BaseException:
        service.plans.finish(plan_id, "unknown"); raise unknown from None
    try:
        job_id = data.get("job_id") if isinstance(data, dict) else None
        if http_status not in (200, 202) or not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError()
        service.plans.finish(plan_id, "accepted", job_id)
        return {"status": "accepted", "job_id": job_id, "complete": False,
                "application_id": application_id, "instance_id": instance_id, "action": action,
                "notices": {"warnings": list(warnings)}, "job_follow_up": _JOB_FOLLOW_UP,
                "plan_id": plan_id}
    except BaseException:
        service.plans.finish(plan_id, "unknown"); raise unknown from None
