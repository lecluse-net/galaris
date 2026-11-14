"""Read adapters for persisted native workflows, without advertising old APIs."""

from typing import Any

_ID_FUNCTIONS = frozenset({
    "service_admin_get", "service_admin_update", "service_admin_impact", "service_admin_delete",
    "service_admin_global_params_set", "service_admin_conversation_set", "service_admin_mcp_test",
    "service_admin_function_list", "service_admin_function_get", "service_admin_function_set",
    "service_admin_catalog_refresh", "service_admin_connection_list", "service_admin_connection_get",
    "service_admin_connection_create", "agent_connection_list", "agent_connection_create",
})
_CODE_FUNCTIONS = frozenset({"process_admin_sync", "process_admin_create", "process_admin_update"})


def canonical_service_call(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    canonical = "service_admin_" + name.removeprefix("tool_admin_") if name.startswith("tool_admin_") else {
        "tools_list": "services_list", "agent_tool_list": "agent_service_list",
    }.get(name, name)
    values = dict(arguments)
    aliases = {"tool_id": "service_id"} if canonical in _ID_FUNCTIONS else {
        "tool_code": "service_code"} if canonical in _CODE_FUNCTIONS else {}
    for old, new in aliases.items():
        if old in values:
            if new in values and values[new] != values[old]:
                raise ValueError("Conflicting legacy and current service references")
            values[new] = values.pop(old)
    return canonical, values
