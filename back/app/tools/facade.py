"""Stable configuration read port consumed by connection resolution."""

from typing import Any
from .schemas import Tool
from .runtime_principals import RuntimePrincipal, register_runtime_principal_port
from .mcp_authorization import bind_native_action
from .authorization import authorization_policy as agent_authorization_policy
from .secrets import public_connection_schema as public_connection_schema


async def has_active_admin_function(agent_id: int, function: str) -> bool:
    from app.connection.facade import has_active_tool_function

    return await has_active_tool_function(agent_id, "agent_admin", function)


async def get_tool_by_id(tool_id: int) -> Tool | None:
    from . import tool_service

    return await tool_service.get_tool_by_id(tool_id)


async def get_tool(code: str) -> Tool | None:
    from . import tool_service

    return await tool_service.get_tool(code)


async def get_runtime_global_params(
    tool_id: int, *, decrypt_passwords: bool = True
) -> tuple[dict[str, Any], set[str]]:
    from . import tool_service

    return await tool_service.get_runtime_global_params(
        tool_id, decrypt_passwords=decrypt_passwords
    )


from .administration_lock import lock_tools, finish_write
from .admin_contracts import AdministrationContext, AdministrationError, HUMAN_ONLY_TOOL_CODES

from . import admin_service as administration
from .runtime_authorization import (
    issue_runtime_run_grant,
    resolve_runtime_run_grant,
    close_runtime_run_grant,
    renew_runtime_run_grant,
    revoke_runtime_run_grant,
)
from .runtime_authorization import (
    register_runtime_authorization_configuration as register_runtime_authorization_configuration,
)
from .authorization import fingerprint as authorization_fingerprint
from .authorization import (
    register_authorization_dispatch_guard as register_authorization_dispatch_guard,
    register_deferred_authorization_guard as register_deferred_authorization_guard,
    continued_deferred_dispatch as continued_deferred_dispatch,
    release_buffered_dispatch as release_buffered_dispatch,
    AuthorizationSuspended as AuthorizationSuspended,
    register_authorization_context_guard,
    authorization_context_snapshot,
    AuthorizationAction,
    AuthorizationRequired,
    AuthorizationClosed,
    claim_action,
    current_action_covers,
    authorized_request,
    answer_action,
    finish_action,
    authorization_status,
    AUTHORIZATION_META_KEY,
    register_authorization_waker,
    wake_authorization_context,
    current_prepared_authorization,
    claim_prepared_action,
    register_deferred_dispatch,
    claim_deferred_dispatch,
    canonical as canonical_authorization_snapshot,
    authorization_context_pending,
    invalidate_authorization_context,
)

__all__ = [
    "register_runtime_authorization_configuration",
    "authorization_fingerprint",
    "continued_deferred_dispatch",
    "release_buffered_dispatch",
    "AuthorizationSuspended",
    "register_deferred_authorization_guard",
    "authorized_request",
    "bind_native_action",
    "revoke_runtime_run_grant",
    "RuntimePrincipal",
    "register_runtime_principal_port",
    "agent_authorization_policy",
    "register_authorization_dispatch_guard",
    "register_authorization_context_guard",
    "authorization_context_snapshot",
    "issue_runtime_run_grant",
    "resolve_runtime_run_grant",
    "close_runtime_run_grant",
    "renew_runtime_run_grant",
    "AuthorizationAction",
    "AuthorizationRequired",
    "AuthorizationClosed",
    "claim_action",
    "answer_action",
    "finish_action",
    "authorization_status",
    "AUTHORIZATION_META_KEY",
    "register_authorization_waker",
    "wake_authorization_context",
    "current_prepared_authorization",
    "claim_prepared_action",
    "register_deferred_dispatch",
    "claim_deferred_dispatch",
    "canonical_authorization_snapshot",
    "authorization_context_pending",
    "invalidate_authorization_context",
    "current_action_covers",
    "get_tool_by_id",
    "get_tool",
    "get_runtime_global_params",
    "has_active_admin_function",
    "lock_tools",
    "finish_write",
    "AdministrationContext",
    "AdministrationError",
    "HUMAN_ONLY_TOOL_CODES",
    "administration",
]
