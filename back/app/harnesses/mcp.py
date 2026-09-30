"""AgentAdmin Harness operations using the existing selection and lifecycle workflows."""

from typing import Any, Annotated
from uuid import UUID
from pydantic import Field

from app.agent import get_agent_task_blockers
from app.agent.facade import delegated_admin
from app.tools import McpToolContext, mcp_tool
from . import service, supervision
from .contracts import HarnessAction
from .facade import get_admin_harness
from .schemas import HarnessSelectionUpdate


@mcp_tool("agent_admin", name="agent_harness_get", description="Read a managed agent's selected Harness and public execution settings.", effect_policy="read", concurrency_policy="safe")
async def agent_harness_get(ctx: McpToolContext, agent_id: int) -> dict[str, object]:
    async with delegated_admin(ctx.agent_id, "agent_harness_get", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        return await get_admin_harness(agent_id)


@mcp_tool("agent_admin", name="agent_harness_set", description="Select an existing Harness, respecting open Tasks and previous runtime cleanup.", timeout_seconds=660)
async def agent_harness_set(ctx: McpToolContext, agent_id: int, harness_id: UUID) -> dict[str, object]:
    async with delegated_admin(ctx.agent_id, "agent_harness_set", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        _, cleanup = await service.install(agent_id, HarnessSelectionUpdate(harness_id=harness_id))
        cleaned = True
        if cleanup is not None:
            cleaned = await service.cleanup_runtime(cleanup)
        result = await get_admin_harness(agent_id)
        result["operation_status"] = ("error" if not cleaned or result["lifecycle_status"] == "error"
                                      else "completed" if result["lifecycle_status"] in {"ready", "absent"} else "in_progress")
        return result


@mcp_tool("agent_admin", name="agent_harness_reset", description="Return to the internal Harness using the existing cleanup workflow.", timeout_seconds=660, effect_policy="idempotent")
async def agent_harness_reset(ctx: McpToolContext, agent_id: int) -> dict[str, object]:
    async with delegated_admin(ctx.agent_id, "agent_harness_reset", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        _, cleanup = await service.select_internal(agent_id)
        cleaned = True
        if cleanup is not None:
            cleaned = await service.cleanup_runtime(cleanup)
        result = await get_admin_harness(agent_id)
        result["operation_status"] = "completed" if cleaned else "error"
        return result


@mcp_tool("agent_admin", name="agent_harness_status", description="Inspect lifecycle, observed runtime state and available actions.", effect_policy="read", concurrency_policy="safe")
async def agent_harness_status(ctx: McpToolContext, agent_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_harness_status", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        state = await supervision.status(agent_id)
        result = state.model_dump(mode="json")
        result.pop("last_error", None)
        result["resource_uri"] = f"galaris://agent/{agent_id}"
        return result


@mcp_tool("agent_admin", name="agent_harness_action", description="Perform an action supported by the current provider and runtime state.", timeout_seconds=660)
async def agent_harness_action(ctx: McpToolContext, agent_id: int, action: HarnessAction) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_harness_action", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        await supervision.validate_action(agent_id, action)
        await service.run_action(agent_id, action)
        return {"agent_id": agent_id, "resource_uri": f"galaris://agent/{agent_id}", "action": action,
                "operation_status": "in_progress" if action == "refresh" else "completed"}


@mcp_tool("agent_admin", name="agent_harness_logs", description="Read bounded Harness logs, with credentials and host paths redacted.", effect_policy="read", concurrency_policy="safe")
async def agent_harness_logs(ctx: McpToolContext, agent_id: int, lines: Annotated[int, Field(ge=1, le=5000)] = 300) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_harness_logs", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        from .sanitizer import redact_logs
        result = await supervision.logs(agent_id, lines)
        return {"agent_id": agent_id, "lines": redact_logs(result.lines)}


@mcp_tool("agent_admin", name="agent_harness_blockers", description="List Tasks blocking a Harness change, using full Task URIs. Does not terminate Tasks.", effect_policy="read", concurrency_policy="safe")
async def agent_harness_blockers(ctx: McpToolContext, agent_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_harness_blockers", "AGENT_EDIT", "TASK_EDIT") as grant:
        await grant.target(agent_id)
        blockers = await get_agent_task_blockers(agent_id)
        return {"agent_id": agent_id, "active_count": blockers.active_count,
                "active_tasks": [{"uri": f"galaris://task/{t.id}", "label": t.label} for t in blockers.active_tasks],
                "paused_tasks": [{"uri": f"galaris://task/{t.id}", "label": t.label} for t in blockers.paused_tasks]}
