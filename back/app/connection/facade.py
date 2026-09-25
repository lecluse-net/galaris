"""Stable connection-domain operations used by other modules."""

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
]
