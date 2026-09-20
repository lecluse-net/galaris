"""Native MCP tools for creating, starting, inspecting, and stopping tasks."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import String, cast, func, select, true

from app.agent.contracts import ExecutionEffort, ExecutionResult, ForcedRoute
from app.agent.models import Agent
from app.task.models import Task, TaskAmendment, TaskAttempt, TaskStatus
from app.task.schemas import Task as TaskSchema, TaskCreate
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.database import get_db
from core.i18n import default_language, is_supported, render_prompt, t
from core.util import as_dict, visible_text
from .access import agent_task_filter, require_agent_task_access

_OBJECTIVES_LIMIT = 4_000
_FEEDBACK_LIMIT = 8_000
_FAILURE_REASON_LIMIT = 1_000
_EXECUTION_CONTEXT_KEYS = (
    "run_id",
    "runtime_run_id",
    "runtime_status",
    "driver_code",
    "effort",
    "execution_strategy",
    "model_code",
    "model_name",
    "budget_exhausted",
)
_ACTIVE_STATUSES = (
    TaskStatus.CREATE,
    TaskStatus.DISPATCH,
    TaskStatus.BRIEFING,
    TaskStatus.EXEC,
    TaskStatus.PLAN,
)
_TERMINAL_STATUSES = (TaskStatus.SUCCESS, TaskStatus.ERROR)
_STOP_FEEDBACK_LIMIT = 1_000
_INSPECTION_LIMIT_MAX = 100
_TASK_RESOURCE_PREFIX = "galaris://task/"


def _task_resource_uri(task_id: str | UUID) -> str:
    raw = str(task_id).strip()
    return raw if raw.startswith(_TASK_RESOURCE_PREFIX) else f"{_TASK_RESOURCE_PREFIX}{raw}"


def _task_selector(task_id: str | UUID) -> str | UUID:
    if isinstance(task_id, UUID):
        return task_id
    raw = str(task_id).strip()
    return raw.removeprefix(_TASK_RESOURCE_PREFIX)


def _task_language(task: Task | None) -> str:
    """Return a task's durable language or the configured default."""

    data = as_dict(task.data) if task is not None else {}
    raw = str(data.get("language") or "").strip().lower()
    return raw if is_supported(raw) else default_language()


def _message(key: str, language: str, **values: Any) -> str:
    """Render an MCP task message in a supported language."""

    return render_prompt(t(f"task_mcp.{key}", language), **values)


@mcp_tool(
    "galaris",
    name="task_get",
    description=(
        "Return a compact operational view of a task with its canonical resource URI, target "
        "agent, requester, objective, feedback, actionable terminal diagnostics, progress, "
        "amendment eligibility, and explicit "
        "waits such as the colleague, question, and deadline. Accept a canonical "
        "galaris://task/ URI, a full UUID, or a unique UUID prefix."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def mcp_get_task(
    ctx: McpToolContext,
    task_id: str,
) -> dict[str, Any]:
    """Return the main attributes of a task."""

    language = await context_language(ctx)
    task = await _resolve_task(task_id, language=language)
    if task is None:
        raise ValueError(_message("task_not_found", language, task_id=task_id))
    await require_agent_task_access(task, ctx.agent_id)
    return await get_task(task_id, language=language)


async def mcp_task(ctx: McpToolContext, task_id: str) -> str:
    """Return the complete JSON representation of a task."""

    language = await context_language(ctx)
    task = await _resolve_task(task_id, language=language)
    if task is None:
        raise ValueError(_message("task_not_found", language, task_id=task_id))
    await require_agent_task_access(task, ctx.agent_id)
    payload = await inspect_task(task_id, language=language)
    return json.dumps(payload, ensure_ascii=False)


async def mcp_tasks(
    ctx: McpToolContext,
    date_debut: datetime,
    date_fin: datetime,
    limit: int = 20,
) -> str:
    """Return task previews in an inclusive datetime range as JSON text."""

    payload = await inspect_tasks(date_debut, date_fin, limit=limit, actor_agent_id=ctx.agent_id)
    return json.dumps(payload, ensure_ascii=False)


async def mcp_list_running_tasks(
    ctx: McpToolContext,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List active root tasks, excluding the current task and its plan root."""

    return await list_running_tasks(ctx, limit=limit)


async def mcp_list_paused_tasks(
    ctx: McpToolContext,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List paused root tasks."""

    return await list_paused_tasks(ctx, limit=limit)


@mcp_tool(
    "galaris",
    name="task_stop",
    description=(
        "Permanently stop an active root task and its unfinished descendants. The current task, "
        "its ancestors, and child-task targets are rejected. Find the exact canonical Task URI "
        "with file_search on galaris://task/ first."
    ),
)
async def mcp_stop_task(
    ctx: McpToolContext,
    task_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Permanently stop another active root task."""

    return await stop_task(ctx, task_id=task_id, reason=reason)


@mcp_tool(
    "galaris",
    name="task_run",
    description=(
        "Create a child task delegated to a peer and return its canonical galaris://task/ URI. Never target your own "
        "agent_id; perform that work directly. Write `objective` as a rich-text HTML fragment with a direct instruction to the "
        "recipient. Your task waits and resumes automatically with the child result. Use this "
        "for delegated work; use messenger_send_message_to_user for conversation. `effort` may "
        "be auto, standard, or high. `mode` may be auto, exec, or plan."
    ),
)
async def mcp_run_task(
    ctx: McpToolContext,
    agent_id: int,
    label: str,
    objective: str,
    effort: str | None = None,
    mode: str | None = None,
) -> str:
    """Create an AI task for an agent and return its canonical resource URI."""
    from app.task.runner import go_next

    if agent_id == ctx.agent_id:
        language = await _context_language(ctx)
        raise ValueError(_message("self_delegation", language))
    blocked = await _delegation_blocked_message(ctx.task_id)
    if blocked is not None:
        raise ValueError(blocked)
    if not await _delegation_target_exists(agent_id):
        language = await _context_language(ctx)
        raise ValueError(
            _message("agent_not_found", language, agent_id=agent_id)
        )
    from app.agent import require_agent_contact
    from app.tools import has_galaris_admin_access
    if not await has_galaris_admin_access(ctx.agent_id):
        await require_agent_contact(ctx.agent_id, peer_agent_id=agent_id)
    task_id = await run_task(
        requester_agent_id=ctx.agent_id,
        agent_id=agent_id,
        label=label,
        objective=objective,
        effort=effort,
        mode=mode,
        source_task_id=ctx.task_id,
    )
    # Put the child in the fast queue. Its creator enters the ``child`` wait state when the
    # current run returns, and the child starts as soon as the agent slot becomes available.
    go_next(UUID(task_id), fast=True)
    return _task_resource_uri(task_id)


async def _delegation_target_exists(agent_id: int) -> bool:
    """Check the current public Agent surface before creating a delegated Task."""

    from app.agent import get_agent_record

    return await get_agent_record(agent_id) is not None


def _agent_payload(agent: Any | None) -> dict[str, Any] | None:
    if agent is None:
        return None
    if isinstance(agent, dict):
        agent_dict = as_dict(agent)
        return {
            "id": agent_dict.get("id"),
            "first_name": agent_dict.get("first_name"),
            "last_name": agent_dict.get("last_name"),
            "code": agent_dict.get("code"),
            "job_title": agent_dict.get("job_title"),
        }
    return {
        "id": agent.id,
        "first_name": agent.first_name,
        "last_name": agent.last_name,
        "code": agent.code,
        "job_title": agent.job_title,
    }


def _isoformat_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _bounded_text(value: object, *, limit: int = _FAILURE_REASON_LIMIT) -> str | None:
    """Return a non-empty bounded diagnostic string."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:limit] or None


def _execution_context(task: Task, execution_result: ExecutionResult | None) -> dict[str, Any]:
    """Build a bounded runtime summary without copying prompts or model output."""

    metadata = execution_result.metadata if execution_result is not None else {}
    context: dict[str, Any] = {
        key: metadata[key]
        for key in _EXECUTION_CONTEXT_KEYS
        if key in metadata and isinstance(metadata[key], (str, int, float, bool))
    }
    dispatch = task.get_dispatch_result()
    if "driver_code" not in context and dispatch is not None and dispatch.driver_code:
        context["driver_code"] = dispatch.driver_code
    if "effort" not in context:
        context["effort"] = task.effort or "standard"
    if dispatch is not None:
        context["route"] = dispatch.decision.route
    if execution_result is not None:
        context["success"] = execution_result.success
        context["tools_used"] = list(dict.fromkeys(execution_result.tools_used))
    return context


def _failed_execution_message(
    execution_result: ExecutionResult | None,
) -> tuple[str | None, str | None]:
    """Return the last explicit failed event from a terminal execution trace."""

    if execution_result is None:
        return None, None
    for message in reversed(execution_result.messages):
        if message.success:
            continue
        reason = _bounded_text(message.content)
        if reason is None:
            continue
        source = (
            f"execution_tool:{message.tool_name}"
            if message.type == "tool" and message.tool_name
            else "execution_message"
        )
        return reason, source
    return None, None


_GENERIC_ATTEMPT_FAILURES = {
    "Attempt ended with an unsuccessful execution result.",
    "The action returned a failed result.",
    "L’action a renvoyé un résultat en échec.",
}


def _actionable_attempt_failure(value: str | None) -> str | None:
    """Keep the terminal scheduler cause unless it is only a generic wrapper."""

    return value if value is not None and value not in _GENERIC_ATTEMPT_FAILURES else None


async def _terminal_error_diagnostics(
    task: Task,
    execution_result: ExecutionResult | None,
) -> dict[str, Any]:
    """Load the last durable attempt and LLM call for an erroneous Task."""

    from app.llm import LLMCall, llm_call_service

    db = get_db()
    attempt = await db.scalar(
        select(TaskAttempt)
        .where(TaskAttempt.task_id == task.id)
        .order_by(TaskAttempt.attempt_number.desc())
        .limit(1)
    )
    llm_call = await db.scalar(
        select(LLMCall)
        .where(
            LLMCall.task_id == task.id,
            *llm_call_service.task_owned_call_predicates(),
        )
        .order_by(LLMCall.started_at.desc(), LLMCall.id.desc())
        .limit(1)
    )

    attempt_payload = (
        {
            "id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "phase": attempt.phase,
            "status": attempt.status,
            "retryable": attempt.retryable,
            "error": _bounded_text(attempt.error),
            "started_at": _isoformat_or_none(attempt.started_at),
            "finished_at": _isoformat_or_none(attempt.finished_at),
        }
        if attempt is not None
        else None
    )
    llm_call_payload = (
        {
            "id": str(llm_call.id),
            "status": llm_call.status,
            "provider": llm_call.provider_name,
            "model": llm_call.effective_model or llm_call.requested_model,
            "finish_reason": llm_call.finish_reason,
            "error": _bounded_text(llm_call.error),
            "started_at": _isoformat_or_none(llm_call.started_at),
            "completed_at": _isoformat_or_none(llm_call.completed_at),
            "duration": llm_call.duration,
        }
        if llm_call is not None
        else None
    )

    metadata = execution_result.metadata if execution_result is not None else {}
    structured_reason = _bounded_text(metadata.get("failure_reason"))
    message_reason, message_source = _failed_execution_message(execution_result)
    llm_reason = _bounded_text(llm_call.error) if llm_call is not None else None
    attempt_reason = _bounded_text(attempt.error) if attempt is not None else None
    actionable_attempt_reason = _actionable_attempt_failure(attempt_reason)
    task_reason = _bounded_text(task.last_error)
    terminal_result_reason = (
        _bounded_text(execution_result.result)
        if execution_result is not None and not execution_result.success
        else None
    )
    reason_candidates = (
        (structured_reason, "execution_metadata"),
        (actionable_attempt_reason, "attempt"),
        (message_reason, message_source),
        (llm_reason, "llm_call"),
        (attempt_reason, "attempt"),
        (task_reason, "task"),
        (terminal_result_reason, "execution_result"),
    )
    failure_reason: str | None = None
    failure_source: str | None = None
    for candidate, source in reason_candidates:
        if candidate is not None:
            failure_reason = candidate
            failure_source = source
            break

    return {
        "failure_code": _bounded_text(metadata.get("failure_code")),
        "failure_reason": failure_reason,
        "failure_source": failure_source,
        "last_error": task_reason,
        "attempt_count": task.attempt_count,
        "latest_attempt": attempt_payload,
        "latest_llm_call": llm_call_payload,
        "execution_context": _execution_context(task, execution_result),
    }


async def get_task(
    task_id: str | UUID,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Return the main attributes of a task."""
    started_at = time.perf_counter()
    lang = language if is_supported(language) else default_language()
    task = await _get_task_light(task_id, language=lang)
    if task is None:
        raise ValueError(_message("task_not_found", lang, task_id=task_id))

    agent_id = task.get("agent_id")
    requester_agent_id = task.get("requester_agent_id")
    agent_ids = [
        value for value in (agent_id, requester_agent_id)
        if value is not None
    ]
    agents = await _get_agents_light(agent_ids)

    agent_payload = _agent_payload(agents.get(agent_id) if agent_id is not None else None)
    requester_payload = _agent_payload(
        agents.get(requester_agent_id) if requester_agent_id is not None else None
    )
    status = task.get("status")
    objectives = task.get("objectives")
    feedback = task.get("feedback")
    objectives_chars = task.get("objectives_chars") or 0
    feedback_chars = task.get("feedback_chars") or 0
    task_uuid = task["id"]

    # Detailed progress is available only for a planned task.
    from app.agent import get_plan_progress

    progress = await get_plan_progress(
        task_uuid if isinstance(task_uuid, UUID) else UUID(str(task_uuid))
    )
    resolved_task = await _resolve_task(task_uuid, language=lang)
    if resolved_task is None:
        raise ValueError(_message("task_not_found", lang, task_id=task_id))
    from app.task.operational_state import inspect_operational_state

    operational = await inspect_operational_state(resolved_task)
    from .activity_snapshot import activity_snapshots

    activity = (await activity_snapshots([resolved_task]))[0]
    execution_result = resolved_task.get_execution_result()
    diagnostics = (
        await _terminal_error_diagnostics(resolved_task, execution_result)
        if resolved_task.status == TaskStatus.ERROR
        else {
            "failure_code": None,
            "failure_reason": None,
            "failure_source": None,
            "last_error": _bounded_text(resolved_task.last_error),
            "attempt_count": resolved_task.attempt_count,
            "latest_attempt": None,
            "latest_llm_call": None,
            "execution_context": _execution_context(resolved_task, execution_result),
        }
    )

    logger.info(
        "MCP get_task: read id={} status={} feedback_chars={} progress={} duration={:.3f}s",
        task_uuid,
        status.value if isinstance(status, TaskStatus) else status,
        feedback_chars,
        f"{progress['percent']}%" if progress else "-",
        time.perf_counter() - started_at,
    )
    return {
        "id": str(task_uuid),
        "resource_uri": _task_resource_uri(task_uuid),
        "progress": progress,
        "label": task.get("label"),
        "agent_id": agent_id,
        "agent": agent_payload,
        "requester_agent_id": requester_agent_id,
        "requester_agent": requester_payload,
        "sender_agent": requester_payload,
        "ai": task.get("ai"),
        "status": status.value if isinstance(status, TaskStatus) else str(status),
        "outcome": _task_outcome(resolved_task),
        "paused": bool(task.get("paused")),
        "objectives": objectives,
        "objectives_chars": objectives_chars,
        "objectives_truncated": objectives_chars > _OBJECTIVES_LIMIT,
        "feedback": feedback,
        "feedback_chars": feedback_chars,
        "feedback_truncated": feedback_chars > _FEEDBACK_LIMIT,
        **diagnostics,
        "latest_attempt": diagnostics["latest_attempt"] or activity.latest_attempt,
        **operational,
        "activity": activity.model_dump(mode="json"),
    }


def _inspection_window(
    date_debut: datetime,
    date_fin: datetime,
    limit: int,
) -> tuple[datetime, datetime, int]:
    """Validate an inclusive MCP inspection range and its result limit."""
    if date_debut.tzinfo is None or date_debut.utcoffset() is None:
        raise ValueError("date_debut must include a timezone offset")
    if date_fin.tzinfo is None or date_fin.utcoffset() is None:
        raise ValueError("date_fin must include a timezone offset")
    if date_debut > date_fin:
        raise ValueError("date_debut must be earlier than or equal to date_fin")
    if limit < 1 or limit > _INSPECTION_LIMIT_MAX:
        raise ValueError(f"limit must be between 1 and {_INSPECTION_LIMIT_MAX}")
    return date_debut, date_fin, limit


def _user_payload(user: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the non-sensitive identity fields of a dashboard user."""
    if user is None:
        return None
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "display_name": user.get("display_name"),
    }


async def _get_users_light(user_ids: list[int | None]) -> dict[int, dict[str, Any]]:
    """Load non-sensitive user identity fields in one query."""
    from core.user.models import User

    ids = {value for value in user_ids if value is not None}
    if not ids:
        return {}
    result = await get_db().execute(
        select(
            User.id.label("id"),
            User.email.label("email"),
            User.display_name.label("display_name"),
        ).where(User.id.in_(ids))
    )
    return {int(row["id"]): dict(row) for row in result.mappings().all()}


async def inspect_task(
    task_id: str | UUID,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Build the complete, JSON-compatible inspection payload for one task."""
    from app.llm import LLMCall, llm_call_service

    lang = language if is_supported(language) else default_language()
    task = await _resolve_task(task_id, language=lang)
    if task is None:
        raise ValueError(_message("task_not_found", lang, task_id=task_id))

    db = get_db()
    children_result = await db.execute(
        Task.histo_filter(
            select(Task)
            .where(Task.parent_id == task.id)
            .order_by(Task.created_at.asc(), Task.id.asc())
        )
    )
    from app.task.operational_state import inspect_operational_state, operational_snapshot

    child_tasks = list(children_result.scalars().all())
    children: list[dict[str, Any]] = []
    for child in child_tasks:
        children.append({
            "id": str(child.id),
            "resource_uri": _task_resource_uri(child.id),
            "label": child.label,
            "objective": child.objective,
            "status": child.status.value,
            "outcome": _task_outcome(child),
            "paused": child.paused,
            "agent_id": child.agent_id,
            "created_at": _isoformat_or_none(child.created_at),
            **(await inspect_operational_state(child)),
        })

    llm_result = await db.execute(
        select(LLMCall.id)
        .where(
            LLMCall.task_id == task.id,
            *llm_call_service.task_owned_call_predicates(),
        )
        .order_by(LLMCall.started_at.asc(), LLMCall.id.asc())
    )
    llm_call_ids = [str(value) for value in llm_result.scalars().all()]

    attempts_result = await db.execute(
        select(TaskAttempt)
        .where(TaskAttempt.task_id == task.id)
        .order_by(TaskAttempt.attempt_number.asc())
    )
    attempts = [
        {
            "id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "phase": attempt.phase,
            "status": attempt.status,
            "worker_id": attempt.worker_id,
            "lease_token": str(attempt.lease_token),
            "started_at": _isoformat_or_none(attempt.started_at),
            "finished_at": _isoformat_or_none(attempt.finished_at),
            "retryable": attempt.retryable,
            "error": attempt.error,
            "cost": attempt.cost,
            "data": attempt.data,
        }
        for attempt in attempts_result.scalars().all()
    ]
    amendment_rows = (
        await db.scalars(
            select(TaskAmendment)
            .where(TaskAmendment.task_id == task.id)
            .order_by(TaskAmendment.created_at.asc(), TaskAmendment.id.asc())
        )
    ).all()
    amendments = [
        {
            "id": str(amendment.id),
            "source_kind": amendment.source_kind,
            "source_id": amendment.source_id,
            "disposition": amendment.disposition,
            "instruction": amendment.instruction,
            "reason": amendment.reason,
            "created_at": _isoformat_or_none(amendment.created_at),
            "applied_at": _isoformat_or_none(amendment.applied_at),
        }
        for amendment in amendment_rows
    ]

    agents = await _get_agents_light([task.agent_id, task.requester_agent_id])
    users = await _get_users_light([task.created_by, task.updated_by, task.deleted_by])
    agent = _agent_payload(agents.get(task.agent_id)) if task.agent_id is not None else None
    requester = (
        _agent_payload(agents.get(task.requester_agent_id))
        if task.requester_agent_id is not None
        else None
    )

    from app.agent import get_plan_progress

    payload = TaskSchema.model_validate(task).model_dump(mode="json")
    payload.update({
        "resource_uri": _task_resource_uri(task.id),
        "outcome": _task_outcome(task),
        "agent": agent,
        "owner": agent,
        "requester_agent": requester,
        "creator_user": _user_payload(users.get(task.created_by)) if task.created_by else None,
        "updater_user": _user_payload(users.get(task.updated_by)) if task.updated_by else None,
        "progress": await get_plan_progress(task.id),
        "lease_token": str(task.lease_token) if task.lease_token is not None else None,
        "lease_owner": task.lease_owner,
        "lease_expires_at": _isoformat_or_none(task.lease_expires_at),
        "next_attempt_at": _isoformat_or_none(task.next_attempt_at),
        "attempt_count": task.attempt_count,
        "consecutive_failures": task.consecutive_failures,
        "last_error": task.last_error,
        "cancel_requested": task.cancel_requested,
        "attempts": attempts,
        "amendments": amendments,
        "subtasks": children,
        "llm_calls": llm_call_ids,
        **operational_snapshot(task, child_tasks),
    })
    return payload


def _task_outcome(task: Task) -> str:
    """Expose a skipped plan leaf without falsifying its durable Task phase."""
    data = task.data if isinstance(task.data, dict) else {}
    return "SKIPPED" if data.get("plan_skipped") is True else task.status.value


async def inspect_tasks(
    date_debut: datetime,
    date_fin: datetime,
    *,
    limit: int = 20,
    actor_agent_id: int | None = None,
) -> list[dict[str, Any]]:
    """List recent task previews in an inclusive datetime range."""
    start, end, safe_limit = _inspection_window(date_debut, date_fin, limit)
    result = await get_db().execute(
        select(
            Task.id.label("id"),
            Task.label.label("label"),
            Task.objective.label("objective"),
            Task.agent_id.label("agent_id"),
            Task.created_at.label("created_at"),
            Agent.first_name.label("owner_first_name"),
            Agent.last_name.label("owner_last_name"),
            Agent.code.label("owner_code"),
            Agent.job_title.label("owner_job_title"),
        )
        .select_from(Task)
        .outerjoin(Agent, Agent.id == Task.agent_id)
        .where(
            Task.deleted_at.is_(None),
            await agent_task_filter(actor_agent_id) if actor_agent_id is not None else true(),
            Task.created_at >= start,
            Task.created_at <= end,
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(safe_limit)
    )
    items: list[dict[str, Any]] = []
    for row in result.mappings().all():
        agent_id = row["agent_id"]
        owner = None
        if agent_id is not None:
            owner = {
                "id": agent_id,
                "first_name": row["owner_first_name"],
                "last_name": row["owner_last_name"],
                "code": row["owner_code"],
                "job_title": row["owner_job_title"],
            }
        items.append({
            "id": str(row["id"]),
            "resource_uri": _task_resource_uri(row["id"]),
            "label": row["label"],
            "objective": visible_text(str(row["objective"] or ""))[:_OBJECTIVES_LIMIT],
            "owner": owner,
            "created_at": _isoformat_or_none(row["created_at"]),
        })
    return items


async def list_running_tasks(
    ctx: McpToolContext,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return active root tasks except the current task and current root."""
    db = get_db()
    current_root_id = await _current_root_id(ctx)
    safe_limit = max(1, min(int(limit or 20), 100))

    query = (
        select(
            Task.id.label("id"),
            Task.label.label("label"),
            Task.agent_id.label("agent_id"),
            Task.requester_agent_id.label("requester_agent_id"),
            Task.status.label("status"),
            Task.paused.label("paused"),
            Task.created_at.label("created_at"),
            Task.updated_at.label("updated_at"),
            func.substr(Task.objective, 1, 500).label("objectives"),
            func.length(Task.objective).label("objectives_chars"),
        )
        .where(Task.parent_id.is_(None))
        .where(Task.status.in_(_ACTIVE_STATUSES))
        .where(await agent_task_filter(ctx.agent_id, manage=True))
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .limit(safe_limit)
    )
    if current_root_id is not None:
        query = query.where(Task.id != current_root_id)
    result = await db.execute(Task.histo_filter(query))
    rows = [dict(row) for row in result.mappings().all()]

    items: list[dict[str, Any]] = []
    for row in rows:
        status = row.get("status")
        task_id = row["id"]
        from app.agent import get_plan_progress

        progress = await get_plan_progress(
            task_id if isinstance(task_id, UUID) else UUID(str(task_id))
        )
        resolved_task = await _resolve_task(task_id)
        if resolved_task is None:
            continue
        from app.task.operational_state import inspect_operational_state

        operational = await inspect_operational_state(resolved_task)
        items.append({
            "id": str(task_id),
            "resource_uri": _task_resource_uri(task_id),
            "progress": progress,
            "label": row.get("label"),
            "agent_id": row.get("agent_id"),
            "requester_agent_id": row.get("requester_agent_id"),
            "status": status.value if isinstance(status, TaskStatus) else str(status),
            "paused": bool(row.get("paused")),
            "objectives": row.get("objectives"),
            "objectives_truncated": (row.get("objectives_chars") or 0) > 500,
            "created_at": _isoformat_or_none(row.get("created_at")),
            "updated_at": _isoformat_or_none(row.get("updated_at")),
            **operational,
        })
    return items


async def list_paused_tasks(
    ctx: McpToolContext,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return root tasks explicitly paused by a human."""
    db = get_db()
    current_root_id = await _current_root_id(ctx)
    safe_limit = max(1, min(int(limit or 20), 100))

    query = (
        select(
            Task.id.label("id"),
            Task.label.label("label"),
            Task.agent_id.label("agent_id"),
            Task.requester_agent_id.label("requester_agent_id"),
            Task.status.label("status"),
            Task.data.label("data"),
            Task.created_at.label("created_at"),
            Task.updated_at.label("updated_at"),
            func.substr(Task.objective, 1, 500).label("objectives"),
            func.length(Task.objective).label("objectives_chars"),
        )
        .where(Task.parent_id.is_(None))
        .where(Task.paused.is_(True))
        .where(await agent_task_filter(ctx.agent_id, manage=True))
        .where(Task.status.not_in(_TERMINAL_STATUSES))
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .limit(safe_limit)
    )
    if current_root_id is not None:
        query = query.where(Task.id != current_root_id)
    result = await db.execute(Task.histo_filter(query))
    rows = [dict(row) for row in result.mappings().all()]

    from app.task import task_service

    items: list[dict[str, Any]] = []
    for row in rows:
        # Only human-held tasks belong here. Internal dependency waits cannot be resumed by an
        # agent and are therefore excluded.
        data = as_dict(row.get("data"))
        reasons: Any = data.get("pause_reasons")
        if not isinstance(reasons, list) or task_service.PAUSE_USER not in reasons:
            continue
        status = row.get("status")
        task_id = row["id"]
        from app.agent import get_plan_progress

        progress = await get_plan_progress(
            task_id if isinstance(task_id, UUID) else UUID(str(task_id))
        )
        items.append({
            "id": str(task_id),
            "resource_uri": _task_resource_uri(task_id),
            "progress": progress,
            "label": row.get("label"),
            "agent_id": row.get("agent_id"),
            "requester_agent_id": row.get("requester_agent_id"),
            "status": status.value if isinstance(status, TaskStatus) else str(status),
            "paused": True,
            "objectives": row.get("objectives"),
            "objectives_truncated": (row.get("objectives_chars") or 0) > 500,
            "created_at": _isoformat_or_none(row.get("created_at")),
            "updated_at": _isoformat_or_none(row.get("updated_at")),
        })
    return items


async def stop_task(
    ctx: McpToolContext,
    *,
    task_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Stop an active root task and all unfinished descendants."""
    language = await _context_language(ctx)
    target = await _resolve_task(task_id, language=language)
    if target is None:
        raise ValueError(
            _message("task_not_found", language, task_id=task_id)
        )
    await require_agent_task_access(target, ctx.agent_id, manage=True)
    if target.parent_id is not None:
        raise ValueError(
            _message("root_only", await _context_language(ctx, fallback=target))
        )

    current_root_id = await _current_root_id(ctx)
    if current_root_id is not None and target.id == current_root_id:
        raise ValueError(
            _message("self_stop", await _context_language(ctx, fallback=target))
        )

    if target.status in _TERMINAL_STATUSES:
        return {
            "stopped": False,
            "id": str(target.id),
            "resource_uri": _task_resource_uri(target.id),
            "status": target.status.value,
            "message": _message("already_terminal", _task_language(target)),
        }

    stopper = f"agent {ctx.agent_id}"
    clean_reason = " ".join(str(reason or "").strip().split())
    if len(clean_reason) > _STOP_FEEDBACK_LIMIT:
        clean_reason = clean_reason[: _STOP_FEEDBACK_LIMIT - 3].rstrip() + "..."
    target_language = _task_language(target)
    feedback = _message("stopped_by", target_language, stopper=stopper)
    if clean_reason:
        feedback = _message(
            "stopped_by_with_reason",
            target_language,
            stopper=stopper,
            reason=clean_reason,
        )

    stopped_ids = await _stop_task_tree(target, feedback)
    from app.task import scheduler

    cancelled = [str(tid) for tid in stopped_ids if scheduler.cancel(tid)]
    scheduler.wake()

    return {
        "stopped": True,
        "id": str(target.id),
        "resource_uri": _task_resource_uri(target.id),
        "stopped_task_ids": [str(tid) for tid in stopped_ids],
        "stopped_task_uris": [_task_resource_uri(tid) for tid in stopped_ids],
        "cancelled_running_task_ids": cancelled,
        "message": _message(
            "stopped_count",
            await _context_language(ctx, fallback=target),
            count=len(stopped_ids),
        ),
    }


def _task_light_select() -> Any:
    return (
        select(
            Task.id.label("id"),
            Task.label.label("label"),
            Task.agent_id.label("agent_id"),
            Task.requester_agent_id.label("requester_agent_id"),
            Task.ai.label("ai"),
            Task.status.label("status"),
            Task.paused.label("paused"),
            func.substr(Task.objective, 1, _OBJECTIVES_LIMIT).label("objectives"),
            func.length(Task.objective).label("objectives_chars"),
            func.substr(Task.feedback, 1, _FEEDBACK_LIMIT).label("feedback"),
            func.length(Task.feedback).label("feedback_chars"),
        )
        .select_from(Task)
        .where(Task.deleted_at.is_(None))
    )


async def _get_task_light(
    task_id: str | UUID,
    *,
    language: str | None = None,
) -> dict[str, Any] | None:
    db = get_db()
    selector = _task_selector(task_id)
    raw_id = str(selector).strip()
    try:
        task_uuid = selector if isinstance(selector, UUID) else UUID(raw_id)
    except ValueError:
        lang = language if is_supported(language) else default_language()
        if len(raw_id) < 8:
            raise ValueError(_message("invalid_uuid", lang, task_id=task_id)) from None
        query = (
            _task_light_select()
            .where(cast(Task.id, String).ilike(f"{raw_id}%"))
            .limit(2)
        )
        result = await db.execute(query)
        matches = [dict(row) for row in result.mappings().all()]
        if len(matches) > 1:
            raise ValueError(_message(
                "ambiguous_uuid_prefix", lang, task_id=task_id
            )) from None
        task = matches[0] if matches else None
        if task is not None:
            logger.info("MCP get_task: prefix {} resolved to {}", task_id, task["id"])
        return task

    result = await db.execute(_task_light_select().where(Task.id == task_uuid))
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _resolve_task(
    task_id: str | UUID,
    *,
    language: str | None = None,
) -> Task | None:
    """Resolve a task by canonical URI, full UUID, or unique UUID prefix."""
    db = get_db()
    selector = _task_selector(task_id)
    raw_id = str(selector).strip()
    try:
        task_uuid = selector if isinstance(selector, UUID) else UUID(raw_id)
    except ValueError:
        lang = language if is_supported(language) else default_language()
        if len(raw_id) < 8:
            raise ValueError(_message("invalid_uuid", lang, task_id=task_id)) from None
        query = (
            select(Task)
            .where(cast(Task.id, String).ilike(f"{raw_id}%"))
            .limit(2)
        )
        result = await db.execute(Task.histo_filter(query))
        matches = list(result.scalars().all())
        if len(matches) > 1:
            raise ValueError(_message(
                "ambiguous_uuid_prefix", lang, task_id=task_id
            )) from None
        return matches[0] if matches else None

    result = await db.execute(Task.histo_filter(select(Task).where(Task.id == task_uuid)))
    return result.scalar_one_or_none()


async def _root_id_for_task(task: Task) -> UUID:
    """Walk from a task to its root."""
    root = task
    seen: set[UUID] = {root.id}
    while root.parent_id is not None and root.parent_id not in seen:
        parent = await _resolve_task(root.parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        root = parent
    return root.id


async def _infer_current_task(ctx: McpToolContext) -> Task | None:
    """Hermes HTTP fallback: return this agent's most recent active task."""
    db = get_db()
    query = (
        select(Task)
        .where(Task.agent_id == ctx.agent_id)
        .where(Task.status.in_((TaskStatus.DISPATCH, TaskStatus.BRIEFING, TaskStatus.EXEC, TaskStatus.PLAN)))
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .limit(1)
    )
    result = await db.execute(Task.histo_filter(query))
    return result.scalar_one_or_none()


async def _current_root_id(ctx: McpToolContext) -> UUID | None:
    current: Task | None = None
    if ctx.task_id is not None:
        current = await _resolve_task(ctx.task_id)
    if current is None:
        current = await _infer_current_task(ctx)
    if current is None:
        return None
    return await _root_id_for_task(current)


async def _context_language(
    ctx: McpToolContext,
    *,
    fallback: Task | None = None,
) -> str:
    """Return the durable language associated with an MCP call."""

    try:
        current: Task | None = None
        if ctx.task_id is not None:
            current = await _resolve_task(ctx.task_id)
        if current is None:
            current = await _infer_current_task(ctx)
        return _task_language(current or fallback)
    except RuntimeError:
        # Some direct callers and unit tests intentionally run without a bound DB context.
        return _task_language(fallback)


async def _children(parent_id: UUID) -> list[Task]:
    db = get_db()
    result = await db.execute(
        Task.histo_filter(
            select(Task)
            .where(Task.parent_id == parent_id)
            .order_by(Task.created_at.asc())
        )
    )
    return list(result.scalars().all())


async def _stop_task_tree(root: Task, feedback: str) -> list[UUID]:
    """Mark a root and its unfinished descendants as ERROR."""
    from app.task import task_service
    stopped: list[UUID] = []
    queue: list[Task] = [root]
    while queue:
        task = queue.pop(0)
        queue.extend(await _children(task.id))
        if task.status in _TERMINAL_STATUSES:
            continue
        from app.task.workflow import TaskEvent, transition

        transition(task, TaskEvent.FAIL)
        task_service.clear_pauses(task)
        task.feedback = feedback
        task.set_execution_result(
            ExecutionResult(
                prompt=task.objective or "",
                result=feedback,
                success=False,
                cost=0.0,
            )
        )
        await task_service.save(task)
        stopped.append(task.id)
    return stopped


async def _get_agents_light(agent_ids: Any) -> dict[int, dict[str, Any]]:
    ids = {int(agent_id) for agent_id in agent_ids if agent_id is not None}
    if not ids:
        return {}
    db = get_db()
    result = await db.execute(
        select(
            Agent.id.label("id"),
            Agent.first_name.label("first_name"),
            Agent.last_name.label("last_name"),
            Agent.code.label("code"),
            Agent.job_title.label("job_title"),
        ).where(Agent.id.in_(ids))
    )
    return {int(row["id"]): dict(row) for row in result.mappings().all()}


def _parse_forced_effort(effort: Optional[str]) -> Optional[ExecutionEffort]:
    """Parse an explicit effort; automatic or unknown values return ``None``."""
    value = str(effort or "").strip().lower()
    if value == "standard":
        return "standard"
    if value == "high":
        return "high"
    return None


def _parse_forced_route(mode: Optional[str]) -> Optional[ForcedRoute]:
    """Parse an explicit route; automatic or unknown values return ``None``."""
    value = str(mode or "").strip().lower()
    if value == "exec":
        return "EXEC"
    if value == "plan":
        return "PLAN"
    if value == "briefing":
        return "BRIEFING"
    return None


async def run_task(
    requester_agent_id: int,
    agent_id: int,
    label: str,
    objective: str,
    effort: Optional[str] = None,
    mode: Optional[str] = None,
    source_task_id: Optional[UUID] = None,
) -> str:
    """Create an AI task, store its requester, and return its UUID without inline execution."""
    task_id = await create_task(
        requester_agent_id=requester_agent_id,
        agent_id=agent_id,
        label=label,
        objective=objective,
        effort=effort,
        mode=mode,
        source_task_id=source_task_id,
    )
    return str(task_id)


async def _delegation_blocked_message(source_task_id: Optional[UUID]) -> Optional[str]:
    """Return a delegation rejection message, or ``None`` when delegation is allowed.

    A human-held task cannot create children, and the collaboration round limit prevents an
    unbounded delegation loop.
    """
    if source_task_id is None:
        return None
    from app.task import collab, task_service
    from core.params import runtime_settings

    parent = await task_service.get_by_id(source_task_id)
    if parent is None:
        return None
    if task_service.is_held_by_user(parent):
        return _message("paused_delegation", _task_language(parent))
    if collab.collab_rounds(parent) >= runtime_settings.TASK_ASK_AGENT_MAX_ROUNDS:
        return _message("round_limit", _task_language(parent))
    return None


async def create_task(
    requester_agent_id: int,
    agent_id: int,
    label: str,
    objective: str,
    effort: Optional[str] = None,
    mode: Optional[str] = None,
    source_task_id: Optional[UUID] = None,
) -> UUID:
    """Add an AI task to the current session and return its UUID.

    ``auto_approve`` is never set here because an agent-created task cannot approve itself or
    bypass approval through a peer. Only a human may grant it through the API or UI, after which
    ancestor resolution applies it to eligible descendants. ``source_task_id`` records the
    causal continuation and lets source lineage establish the parent.
    """
    from app.task import task_service

    task_id = uuid4()
    forced_effort = _parse_forced_effort(effort)
    task_data = TaskCreate(
        agent_id=agent_id,
        requester_agent_id=requester_agent_id,
        label=label,
        objective=objective,
        status=TaskStatus.CREATE,
        ai=True,
        cost=0.0,
        effort=forced_effort or "standard",
        forced_effort=forced_effort,
        forced_route=_parse_forced_route(mode),
    )
    await task_service.apply_source_lineage(task_data, source_task_id)
    db = get_db()
    task = Task(id=task_id, **task_data.model_dump(exclude={"messages"}))
    await task_service.apply_requester_lineage(task)
    await task_service.apply_topic_lineage(task, db=db)
    db.add(task)
    logger.info("MCP task create: task added to session id={}", task_id)
    return task_id
