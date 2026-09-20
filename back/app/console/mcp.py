"""Native MCP tools for persistent SSH command execution."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.tools.mcp_loader import McpToolContext, mcp_tool
from app.tools.contracts import current_tool_execution

from .console_service import ConsoleRunResource


def _resource(ctx: McpToolContext) -> ConsoleRunResource:
    resource = ctx.resource("console")
    if not isinstance(resource, ConsoleRunResource):
        raise RuntimeError("The SSH console resource is unavailable for this run")
    return resource


def _result(value: Any) -> dict[str, Any]:
    if getattr(value, "status", None) == "outcome_unknown":
        raise RuntimeError("Console operation lost its supervisor without a terminal receipt; do not replay it")
    return value.model_dump(mode="json")


@mcp_tool(
    "console",
    name="console_status",
    effect_policy="read",
    concurrency_policy="safe",
    description="Check the configured SSH console, home, SFTP, and enhanced session support.",
    requires=("console_execution",),
)
async def console_status(ctx: McpToolContext) -> dict[str, Any]:
    return _result(await _resource(ctx).execution.status())


@mcp_tool(
    "console",
    name="console_exec",
    description=(
        "Execute a shell command on the agent's persistent SSH machine and wait for completion. "
        "Use for short bounded steps. Run long tests/builds separately with console_start, "
        "then console_poll the same run_id until terminal. "
        "cwd is relative to the Unix home, ~/..., or an absolute path inside that home."
    ),
    requires=("console_execution",),
)
async def console_exec(
    ctx: McpToolContext,
    command: str,
    cwd: str = ".",
    timeout_s: float | None = None,
) -> dict[str, Any]:
    execution = current_tool_execution()
    if execution is not None:
        return _result(await _resource(ctx).execution.exec_operation(
            command, operation_id=execution.operation_id, task_id=ctx.task_id,
            cwd=cwd, timeout_s=timeout_s,
        ))
    return _result(
        await _resource(ctx).execution.exec(command, cwd=cwd, timeout_s=timeout_s)
    )


@mcp_tool(
    "console",
    name="console_start",
    description=(
        "Start a durable command through galaris-exec v2 and return its run_id. "
        "Check console_status.operation_recovery_available first. Use for long tests/builds, "
        "separately from file edits or publication. Poll this run_id; do not start a duplicate."
    ),
    requires=("console_execution",),
)
async def console_start(
    ctx: McpToolContext,
    command: str,
    cwd: str = ".",
) -> dict[str, Any]:
    execution = current_tool_execution()
    return _result(
        await _resource(ctx).execution.start(
            command, cwd=cwd, task_id=ctx.task_id,
            operation_id=execution.operation_id if execution is not None else None,
        )
    )


@mcp_tool(
    "console",
    name="console_poll",
    effect_policy="idempotent",
    description="Read new bounded output from a durable console run starting at cursor.",
    requires=("console_execution",),
)
async def console_poll(
    ctx: McpToolContext,
    run_id: UUID,
    cursor: int = 0,
) -> dict[str, Any]:
    return _result(await _resource(ctx).execution.poll(run_id, cursor=cursor))


@mcp_tool(
    "console",
    name="console_write",
    description="Write UTF-8 data to the stdin of a durable console run.",
    requires=("console_execution",),
)
async def console_write(
    ctx: McpToolContext,
    run_id: UUID,
    data: str,
) -> dict[str, Any]:
    return _result(await _resource(ctx).execution.write(run_id, data))


@mcp_tool(
    "console",
    name="console_stop",
    effect_policy="idempotent",
    description="Stop the complete process group of a durable console run.",
    requires=("console_execution",),
)
async def console_stop(ctx: McpToolContext, run_id: UUID) -> dict[str, Any]:
    return _result(await _resource(ctx).execution.stop(run_id))
