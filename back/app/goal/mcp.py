"""Self-service Goal access and restricted Goal-management MCP tools."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool

from . import goal_service
from .models import GoalStatus
from .referrer_wait import ask_human_referrer
from .schemas import (
    GoalCommand,
    GoalCreate,
    GoalDetail,
    GoalMessengerReferrerInput,
    GoalScheduleWindow,
    GoalUpdate,
)


_GOAL_MANAGEMENT_TOOL_CODE = "goal_management"


def _goal_id(value: str) -> UUID:
    """Parse an exact Goal UUID from a model-provided string."""

    try:
        return UUID(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid Goal UUID: {value}") from exc


def _goal_payload(goal: Any) -> dict[str, Any]:
    """Return JSON-safe Goal data from a Pydantic response model."""

    return dict(goal.model_dump(mode="json"))


async def _has_goal_management_access(ctx: McpToolContext) -> bool:
    """Treat one active Goal-management connection as the live admin witness."""

    from app.connection import connection_service

    return await connection_service.has_active_tool_connection(
        agent_id=ctx.agent_id,
        tool_code=_GOAL_MANAGEMENT_TOOL_CODE,
    )


async def _require_goal_management_access(ctx: McpToolContext) -> None:
    """Reject an administrative call unless its live admin witness still exists."""

    if not await _has_goal_management_access(ctx):
        raise PermissionError(
            "An active goal_management connection is required for Goal administration."
        )


async def _goal_owner_scope(ctx: McpToolContext) -> int | None:
    """Return an exact owner filter, or no filter for a live Goal administrator."""

    if await _has_goal_management_access(ctx):
        return None
    return ctx.agent_id


async def _goal_visible_to_caller(
    ctx: McpToolContext,
    goal_id: UUID,
) -> GoalDetail:
    """Load a Goal owned by the caller, or any Goal for an administrator."""

    goal = await goal_service.get_detail(
        goal_id,
        owner_agent_id=await _goal_owner_scope(ctx),
    )
    if goal is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return goal


async def _goal_list_agent_scope(
    ctx: McpToolContext,
    requested_agent_id: int | None,
) -> int | None:
    """Resolve the owner filter allowed for a self-service or administrative list."""

    if requested_agent_id is not None and requested_agent_id <= 0:
        raise ValueError("agent_id must be greater than zero")
    if requested_agent_id == ctx.agent_id:
        return ctx.agent_id
    if await _has_goal_management_access(ctx):
        return requested_agent_id
    if requested_agent_id is None:
        return ctx.agent_id
    raise ValueError("goal_list can only list Goals owned by the current agent")


async def _goal_management_command(
    ctx: McpToolContext,
    operation: str,
    goal_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Authorize and apply one revision-safe administrative lifecycle command."""

    await _require_goal_management_access(ctx)
    identifier = _goal_id(goal_id)
    command = GoalCommand(expected_revision=expected_revision)
    method = getattr(goal_service, operation)
    result = await method(identifier, command)
    if result is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return _goal_payload(result)


@mcp_tool(
    "galaris",
    name="goal_ask_referrer",
    description=(
        "Ask the configured human Messenger referrer of the current agent's own Goal a "
        "question and wait for their answer. Use only when an answer or decision is required; use "
        "messenger_send_message_to_user for non-blocking progress updates. The question is "
        "correlated durably, the current Task waits, automatic reminders are sent every 24 "
        "hours up to the Goal's configured limit, and the Goal pauses if no answer arrives."
    ),
)
async def mcp_goal_ask_referrer(ctx: McpToolContext, question: str) -> str:
    """Ask and wait for the selected human referrer of the current Goal."""

    if ctx.task_id is None:
        raise ValueError("goal_ask_referrer requires a running Goal Task.")

    language = await context_language(ctx)
    return await ask_human_referrer(
        task_id=ctx.task_id,
        agent_id=ctx.agent_id,
        question=question,
        language=language,
    )


@mcp_tool(
    "goal_management",
    name="goal_create",
    description=(
        "Assign a new long-running Goal to an agent. The owner agent performs the work and "
        "the selected Messenger contact supervises it as its human contact. The "
        "description must be a rich-text HTML fragment; title stays plain text. The "
        "first cycle is scheduled immediately when active is true. An enabled schedule adds "
        "a Goal-specific restriction inside the global Goal time window."
    ),
)
async def mcp_goal_create(
    ctx: McpToolContext,
    agent_id: int,
    referrer_connection_id: int,
    referrer_user_id: str,
    referrer_display_name: str,
    title: str,
    description: str,
    cycle_delay_seconds: int = 3600,
    referrer_max_reminders: int = 1,
    schedule_enabled: bool = False,
    schedule: list[GoalScheduleWindow] | None = None,
    active: bool = True,
) -> dict[str, Any]:
    """Create an agent-owned Goal with an explicit human referrer."""

    await _require_goal_management_access(ctx)
    data = GoalCreate(
        title=title,
        description=description,
        agent_id=agent_id,
        referrer=GoalMessengerReferrerInput(
            type="MESSENGER",
            connection_id=referrer_connection_id,
            user_id=referrer_user_id,
            display_name=referrer_display_name,
        ),
        cycle_delay_seconds=cycle_delay_seconds,
        referrer_max_reminders=referrer_max_reminders,
        schedule_enabled=schedule_enabled,
        schedule=schedule or [],
        active=active,
    )
    return _goal_payload(await goal_service.create(data))


async def mcp_goal_list(
    ctx: McpToolContext,
    agent_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """List caller-visible Goals with optional owner, status, and text filters."""


    if offset < 0:
        raise ValueError("offset must be greater than or equal to zero")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    goal_status: GoalStatus | None = None
    if status is not None:
        try:
            goal_status = GoalStatus(status.strip().upper())
        except ValueError as exc:
            raise ValueError(
                "status must be ACTIVE, PAUSED, COMPLETED, or ERROR"
            ) from exc
    scoped_agent_id = await _goal_list_agent_scope(ctx, agent_id)
    page = await goal_service.list_page(
        skip=offset,
        limit=limit,
        agent_id=scoped_agent_id,
        status=goal_status,
        search=search,
    )
    return dict(page.model_dump(mode="json"))


async def mcp_goal_get(
    ctx: McpToolContext,
    goal_id: str,
) -> dict[str, Any]:
    """Return one Goal after applying self-service or administrative visibility."""


    identifier = _goal_id(goal_id)
    goal = await _goal_visible_to_caller(ctx, identifier)
    return _goal_payload(goal)


async def mcp_goal_get_suivi(
    ctx: McpToolContext,
    goal_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return a bounded newest-first cycle list for one visible Goal."""


    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    identifier = _goal_id(goal_id)
    cycles = await goal_service.list_cycles(
        identifier,
        page=1,
        page_size=limit,
        owner_agent_id=await _goal_owner_scope(ctx),
    )
    if cycles is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return [dict(cycle.model_dump(mode="json")) for cycle in cycles.items]


@mcp_tool(
    "galaris",
    name="goal_update_suivi",
    description=(
        "Replace the tracking HTML of one visible Goal using the revision returned by "
        "file_read on galaris://goal/<uuid>. By default only the current agent's Goals can "
        "be updated; goal_management grants access to every Goal."
    ),
)
async def mcp_goal_update_suivi(
    ctx: McpToolContext,
    goal_id: str,
    expected_revision: int,
    tracking_content: str,
) -> dict[str, Any]:
    """Replace Goal tracking HTML with optimistic concurrency control."""


    identifier = _goal_id(goal_id)
    data = GoalUpdate(
        expected_revision=expected_revision,
        tracking_content=tracking_content,
    )
    result = await goal_service.update(
        identifier,
        data,
        owner_agent_id=await _goal_owner_scope(ctx),
    )
    if result is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return _goal_payload(result)


@mcp_tool(
    "goal_management",
    name="goal_update",
    description=(
        "Update a Goal using the revision read from galaris://goal/<uuid>. Any omitted field is "
        "preserved. description must be a rich-text HTML fragment; title stays plain text. "
        "The owner assignment can only change before the first cycle; a supplied referrer is "
        "always a human Galaris user. An enabled schedule can only further restrict the global "
        "Goal time window."
    ),
)
async def mcp_goal_update(
    ctx: McpToolContext,
    goal_id: str,
    expected_revision: int,
    title: str | None = None,
    description: str | None = None,
    agent_id: int | None = None,
    referrer_connection_id: int | None = None,
    referrer_user_id: str | None = None,
    referrer_display_name: str | None = None,
    cycle_delay_seconds: int | None = None,
    referrer_max_reminders: int | None = None,
    schedule_enabled: bool | None = None,
    schedule: list[GoalScheduleWindow] | None = None,
) -> dict[str, Any]:
    """Update selected Goal fields with optimistic concurrency control."""


    await _require_goal_management_access(ctx)
    values: dict[str, Any] = {"expected_revision": expected_revision}
    for key, value in (
        ("title", title),
        ("description", description),
        ("agent_id", agent_id),
        ("cycle_delay_seconds", cycle_delay_seconds),
        ("referrer_max_reminders", referrer_max_reminders),
        ("schedule_enabled", schedule_enabled),
        ("schedule", schedule),
    ):
        if value is not None:
            values[key] = value
    referrer_values = (
        referrer_connection_id,
        referrer_user_id,
        referrer_display_name,
    )
    if any(value is not None for value in referrer_values):
        if not all(value is not None for value in referrer_values):
            raise ValueError(
                "referrer_connection_id, referrer_user_id and "
                "referrer_display_name must be supplied together"
            )
        assert referrer_connection_id is not None
        assert referrer_user_id is not None
        assert referrer_display_name is not None
        values["referrer"] = GoalMessengerReferrerInput(
            type="MESSENGER",
            connection_id=referrer_connection_id,
            user_id=referrer_user_id,
            display_name=referrer_display_name,
        )
    if len(values) == 1:
        raise ValueError("At least one Goal field must be supplied")
    data = GoalUpdate(**values)
    result = await goal_service.update(_goal_id(goal_id), data)
    if result is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return _goal_payload(result)


@mcp_tool(
    "goal_management",
    name="goal_pause",
    description="Pause a Goal using the revision read from galaris://goal/<uuid>.",
)
async def mcp_goal_pause(
    ctx: McpToolContext,
    goal_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Pause an active or errored Goal."""


    return await _goal_management_command(
        ctx,
        "pause",
        goal_id,
        expected_revision,
    )


@mcp_tool(
    "goal_management",
    name="goal_resume",
    description=(
        "Resume a paused or errored Goal, or restart a completed Goal while preserving "
        "its history, using the revision read from galaris://goal/<uuid>."
    ),
)
async def mcp_goal_resume(
    ctx: McpToolContext,
    goal_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Resume or restart Goal scheduling and any pending referrer wait."""


    return await _goal_management_command(
        ctx,
        "resume",
        goal_id,
        expected_revision,
    )


@mcp_tool(
    "goal_management",
    name="goal_complete",
    description=(
        "Mark a Goal completed and stop future cycles, using the revision read from "
        "galaris://goal/<uuid>."
    ),
)
async def mcp_goal_complete(
    ctx: McpToolContext,
    goal_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Complete a Goal manually."""


    return await _goal_management_command(
        ctx,
        "complete",
        goal_id,
        expected_revision,
    )


@mcp_tool(
    "galaris",
    name="goal_run_now",
    description=(
        "Schedule a Goal cycle immediately, using the revision read from "
        "galaris://goal/<uuid>. This also "
        "reactivates a paused or errored Goal when its referrer is available. By default only the "
        "current agent's Goals can be launched; goal_management grants access to every Goal."
    ),
)
async def mcp_goal_run_now(
    ctx: McpToolContext,
    goal_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Run a Goal as soon as its owner agent is available."""


    identifier = _goal_id(goal_id)
    command = GoalCommand(expected_revision=expected_revision)
    result = await goal_service.run_now(
        identifier,
        command,
        owner_agent_id=await _goal_owner_scope(ctx),
    )
    if result is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return _goal_payload(result)


@mcp_tool(
    "goal_management",
    name="goal_delete",
    description=(
        "Soft-delete a Goal. A Goal with an unfinished execution cycle cannot be deleted; "
        "complete or wait for it first."
    ),
)
async def mcp_goal_delete(
    ctx: McpToolContext,
    goal_id: str,
) -> dict[str, Any]:
    """Soft-delete a Goal when no cycle is running."""


    identifier = _goal_id(goal_id)
    await _require_goal_management_access(ctx)
    deleted = await goal_service.delete(identifier)
    if not deleted:
        raise ValueError(f"Goal not found: {goal_id}")
    return {"goal_id": str(identifier), "deleted": True}
