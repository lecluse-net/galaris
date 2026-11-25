"""Read adapters for persisted native workflows, without advertising old APIs."""

from typing import Any

BUILTIN_TOOL_RENAMES = {
    "service": {
        f"service_admin_{action}": f"service_{action}"
        for action in (
            "list", "get", "create", "update", "impact", "delete", "global_params_set", "mcp_test",
            "function_list", "function_get", "function_set", "connection_list", "connection_get",
            "connection_create", "connection_update", "connection_delete", "connection_params_set",
            "connection_param_delete", "connection_test", "connection_function_list",
            "connection_function_set", "catalog_refresh",
        )
    },
    "process": {
        "conversation_process_start": "process_start_conversation",
        "conversation_process_prepare": "process_prepare",
        "conversation_process_pending": "process_pending",
        "conversation_process_respond": "process_respond",
    },
    "task": {
        "conversation_task_submit": "task_submit",
        "conversation_task_list": "task_list",
        "conversation_task_status": "task_status",
        "conversation_task_pause": "task_pause",
        "conversation_task_resume": "task_resume",
        "conversation_task_retry": "task_retry",
        "conversation_task_stop": "task_stop_conversation",
        "task_work_update": "task_update",
    },
}
_RENAMED_TOOLS = {old: new for names in BUILTIN_TOOL_RENAMES.values() for old, new in names.items()}
MERGED_TASK_TOOLS = {
    "task_retry": "task_resume",
    "task_submit": "task_run",
    "task_status": "task_get",
    "task_stop": "task_cancel",
    "task_stop_conversation": "task_cancel",
}
_ID_FUNCTIONS = frozenset({
    "service_get", "service_update", "service_impact", "service_delete",
    "service_global_params_set", "service_admin_conversation_set", "service_mcp_test",
    "service_function_list", "service_function_get", "service_function_set",
    "service_catalog_refresh", "service_connection_list", "service_connection_get",
    "service_connection_create", "agent_connection_list", "agent_connection_create",
})
_CODE_FUNCTIONS = frozenset({"process_admin_sync", "process_admin_create", "process_admin_update"})


def canonical_service_call(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    canonical = "service_admin_" + name.removeprefix("tool_admin_") if name.startswith("tool_admin_") else {
        "tools_list": "services_list", "agent_tool_list": "agent_service_list",
    }.get(name, name)
    canonical = _RENAMED_TOOLS.get(canonical, canonical)
    # The previous Chat-only actions cannot be replayed from a Process Task.
    if canonical == "task_stop":
        canonical = MERGED_TASK_TOOLS[canonical]
    values = dict(arguments)
    aliases = {"tool_id": "service_id"} if canonical in _ID_FUNCTIONS else {
        "tool_code": "service_code"} if canonical in _CODE_FUNCTIONS else {}
    for old, new in aliases.items():
        if old in values:
            if new in values and values[new] != values[old]:
                raise ValueError("Conflicting legacy and current service references")
            values[new] = values.pop(old)
    return canonical, values
