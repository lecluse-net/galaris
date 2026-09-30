"""Stable connection-domain operations used by other modules."""

from . import admin_service as administration

from .connection_service import (
    function_state_label,
    get_connection,
    get_connections_by_agent,
    get_disabled_function_names,
    get_params_as_dict,
    has_active_tool_connection,
    has_active_tool_function,
    has_any_active_tool_connection,
    list_function_states,
    list_tool_function_states,
    resolve_function_enabled,
    validate_param_value,
    validate_params,
    get_connection_by_agent_tool,
    get_agent_ids_by_tool,
    get_or_create_connection,
    set_connection_active,
    delete_connection,
    get_params_for_api,
    set_params_bulk,
    delete_param,
    set_connection_function_state,
    set_tool_function_state,
    resolve_function,
)

__all__ = [
    "function_state_label",
    "get_connection",
    "get_connections_by_agent",
    "get_disabled_function_names",
    "get_params_as_dict",
    "has_active_tool_connection",
    "has_active_tool_function",
    "has_any_active_tool_connection",
    "list_function_states",
    "list_tool_function_states",
    "resolve_function_enabled",
    "admin_create", "admin_delete", "admin_get", "admin_set_active", "admin_params_set",
    "admin_param_delete", "admin_function_set", "admin_functions", "admin_list", "admin_tools",
    "admin_require_connection",
]
from .agent_admin_service import (
    create as admin_create, delete as admin_delete, projection as admin_get,
    set_active as admin_set_active, params_set as admin_params_set,
    param_delete as admin_param_delete, function_set as admin_function_set,
    functions as admin_functions, list_connections as admin_list,
    list_tools as admin_tools, require_connection as admin_require_connection,
)

__all__ += [
    "administration", "validate_param_value", "validate_params", "get_connection_by_agent_tool",
    "get_agent_ids_by_tool", "get_or_create_connection", "set_connection_active", "delete_connection",
    "get_params_for_api", "set_params_bulk", "delete_param", "set_connection_function_state",
    "set_tool_function_state", "resolve_function",
]
