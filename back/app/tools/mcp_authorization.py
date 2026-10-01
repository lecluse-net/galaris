"""Bind native function calls to their concrete live Tool connection."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from uuid import UUID, uuid4

from app.connection import facade as connections
from app.connection import Connection

from .authorization import AuthorizationAction, claim_action, restore_prepared_callback, tool_authorization_configuration
from dataclasses import replace
from .contracts import current_tool_execution, ToolCallRejectedError
from .schemas import Tool

if TYPE_CHECKING:
    from .mcp_loader import McpToolContext, McpToolDefinition


def authorization_context_key(task_id: UUID | None, resources: dict[str, Any]) -> str:
    if explicit := resources.get("authorization_context"):
        return str(explicit)
    if task_id:
        return f"task:{task_id}"
    if turn := resources.get("conversation_turn"):
        if session := turn.messaging_context.get("voice_session_id"):
            return f"voice:{session}:round:{turn.round_id}"
        return f"round:{turn.round_id}"
    return f"principal:{resources.get('mcp_principal') or 'internal'}"


async def bind_native_action(ctx: McpToolContext, definition: McpToolDefinition, arguments: dict[str, Any]) -> AuthorizationAction:
    from .mcp_loader import native_tool_codes_for_tool
    from .tool_service import get_tool_by_id

    candidates: list[tuple[Connection, Tool]] = []
    # Administrative connection_id arguments describe the target being edited,
    # not the Tool connection that grants the administrative capability.
    requested_connection = ctx.resource("source_connection_id")
    if requested_connection is None and definition.tool_code == "messenger":
        requested_connection = arguments.get("connection_id") or ctx.resource("connection_id")
    turn = ctx.resource("conversation_turn")
    if requested_connection is None and turn is not None and definition.tool_code == "messenger":
        requested_connection = turn.messaging_context.get("connection_id")
    for connection in await connections.get_connections_by_agent(ctx.agent_id):
        if not connection.active:
            continue
        tool = await get_tool_by_id(connection.tool_id)
        if tool is not None and definition.tool_code in native_tool_codes_for_tool(tool):
            candidates.append((connection, tool))
    if requested_connection is not None:
        candidates = [pair for pair in candidates if pair[0].id == requested_connection]
    if len(candidates) != 1:
        raise ToolCallRejectedError("The exact Tool connection for this action must be resolved before authorization")
    connection, tool = candidates[0]
    _, params = await connections.get_params_as_dict(connection.id)
    preflight: dict[str, Any] = {}
    resolved = await connections.resolve_function(connection, definition.name)
    if definition.authorization_preflight is not None and resolved["effective_state"] == "ask":
        preflight = await definition.authorization_preflight(ctx, arguments)
    execution = current_tool_execution()
    action = AuthorizationAction(
        agent_id=ctx.agent_id, runtime=ctx.runtime,
        context_key=authorization_context_key(ctx.task_id, ctx.resources),
        runtime_grant_id=UUID(str(ctx.resource("runtime_grant_id"))) if ctx.resource("runtime_grant_id") else None,
        callback_key=str(execution.operation_id if execution is not None else uuid4()),
        name=definition.name, arguments=arguments,
        configuration={"tool": tool_authorization_configuration(tool), "params": params,
                       "classification": definition.approval, "reason": definition.approval_reason,
                       **({"precondition": preflight} if preflight else {})},
        tool_id=connection.tool_id, connection_id=connection.id,
        preview=f"{tool.label}: {definition.name}",
        continuation=execution.authorization_continuation if execution else None,
    )
    if definition.authorization_boundary == "prepared" and action.continuation:
        callback = restore_prepared_callback(action)
        action = replace(action, callback_key=callback)
        if execution is not None:
            execution.operation_id = UUID(callback)
    return action


async def authorize_native_call(ctx: McpToolContext, definition: McpToolDefinition, arguments: dict[str, Any]) -> UUID | None:
    return await claim_action(await bind_native_action(ctx, definition, arguments))
