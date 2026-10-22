"""Stable configuration read port consumed by connection resolution."""

from typing import Any
from uuid import UUID
from collections.abc import Collection
from .schemas import Tool
from .runtime_principals import RuntimePrincipal, register_runtime_principal_port
from .mcp_authorization import bind_native_action
from .authorization import authorization_policy as agent_authorization_policy
from .secrets import public_connection_schema as public_connection_schema
from .secrets import resolve_connection_references as resolve_connection_references
from .authorization_views import (
    AuthorizationReview as AuthorizationReview,
    authorization_reviews as authorization_reviews,
    pending_authorization_ids as pending_authorization_ids,
    prepared_authorization_links as prepared_authorization_links,
)
from .admin_network import diagnostic_client as mcp_http_client


from .rest_contracts import RestAuth, RestConfig, RestError, RestRequest, RestResponse
from .rest import execute_rest_request


async def has_active_admin_function(agent_id: int, function: str) -> bool:
    from app.connection.facade import has_active_tool_function

    return await has_active_tool_function(agent_id, "agent_admin", function)


async def get_tool_by_id(tool_id: int) -> Tool | None:
    from . import tool_service

    return await tool_service.get_tool_by_id(tool_id)


async def get_tools_by_ids(tool_ids: Collection[int]) -> dict[int, Tool]:
    from . import tool_service

    return await tool_service.get_tools_by_ids(tool_ids)


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
    runtime_authorizations_ready,
)
from .runtime_authorization import (
    register_runtime_authorization_configuration as register_runtime_authorization_configuration,
    register_runtime_dispatch_guard as register_runtime_dispatch_guard,
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
    "mcp_http_client",
    "resolve_connection_references",
    "RestAuth",
    "RestConfig",
    "RestError",
    "RestRequest",
    "RestResponse",
    "execute_rest_request",
    "execute_workflow_tool",
    "register_runtime_authorization_configuration",
    "register_runtime_dispatch_guard",
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
    "runtime_authorizations_ready",
    "AuthorizationAction",
    "AuthorizationRequired",
    "AuthorizationClosed",
    "AuthorizationReview",
    "authorization_reviews",
    "pending_authorization_ids",
    "prepared_authorization_links",
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
    "get_tools_by_ids",
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


async def execute_workflow_tool(
    *,
    agent_id: int,
    task_id: UUID | None,
    tool_name: str,
    arguments: dict[str, Any],
    operation_id: UUID,
    continuation: str | None = None,
) -> dict[str, Any]:
    """Declared native operations keep their connection, scope and approval checks."""
    from .mcp_loader import execute_native_mcp_tool, load_mcp_tools, build_agent_mcp
    from .contracts import ToolExecutionContext, tool_execution, EXECUTION_META_KEY
    from .authorization import AUTHORIZATION_META_KEY
    from fastmcp.tools import ToolResult
    from fastmcp import Client
    from pydantic import BaseModel

    if task_id is None:
        raise ValueError("A Tool activity requires an admitted execution Task")
    evidence = ToolExecutionContext(
        operation_id, tool_name, authorization_continuation=continuation
    )
    definition = next((item for item in load_mcp_tools() if item.name == tool_name), None)
    native = definition is not None
    read_only = definition is not None and definition.effect_policy == "read"
    with tool_execution(evidence):
        if native:
            try:
                result = await execute_native_mcp_tool(
                    agent_id,
                    runtime="internal",
                    task_id=task_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            except PermissionError:
                if evidence.entered:
                    raise
                return {"status": "rejected", "error": "The Tool is not authorized for this agent"}
        else:
            # External APIs use their declared MCP connection. Credentials stay
            # inside the shared loader and its live authorization middleware.
            server = await build_agent_mcp(agent_id, runtime="internal", task_id=task_id)
            async with Client(server) as client:
                remote = await client.call_tool(
                    tool_name,
                    arguments,
                    raise_on_error=False,
                    meta={
                        EXECUTION_META_KEY: {"operation_id": str(operation_id)},
                        **(
                            {AUTHORIZATION_META_KEY: {"continuation": continuation}}
                            if continuation
                            else {}
                        ),
                    },
                )
                result = ToolResult(
                    content=remote.content,
                    structured_content=remote.structured_content,
                    is_error=remote.is_error,
                    meta=remote.meta,
                )
    if isinstance(result, ToolResult):
        authorization = (result.meta or {}).get(AUTHORIZATION_META_KEY)
        if authorization:
            return {
                "authorization": authorization,
                "status": "waiting" if authorization.get("status") == "pending" else "rejected",
            }
        if result.is_error:
            if native and (evidence.outcome == "rejected" or read_only):
                return {
                    "status": "rejected",
                    "error": "The Tool rejected this activity before dispatch",
                }
            raise ValueError("The Tool rejected this activity")
        return {
            "status": "completed",
            "output": result.structured_content
            or {"content": [block.model_dump(mode="json") for block in result.content]},
        }
    if native and (
        evidence.outcome == "rejected" or (read_only and evidence.outcome != "returned")
    ):
        return {"status": "rejected", "error": str(result)}
    if native and evidence.outcome != "returned":
        raise ValueError("Tool effect outcome is unknown; reconcile it before retrying")
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")
    return {
        "status": "completed",
        "output": result if isinstance(result, dict) else {"value": result},
    }
