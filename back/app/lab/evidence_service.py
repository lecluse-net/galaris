"""Live evidence collection for one canonical Galaris task."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.agent import (
    list_driver_statuses,
    resolve_pipeline_policy,
    resolve_tool_profile,
)
from app.agent import agent_service
from app.llm import llm_call_service, llm_service
from app.process import process_service
from app.skill import skill_service
from app.task import Task, TaskStatus
from app.task.models import TaskAttempt
from app.tools import list_agent_mcp_tools
from core.database import get_db
from core.params import runtime_settings

from . import evaluation_service
from .schemas import EvidenceCoverage, LabTaskSummary

_MAX_RELATED_TASKS = 50
_MAX_LLM_CALLS = 200
_MAX_PROCESS_RUNS = 100
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "credential",
        "credentials",
        "access_token",
        "refresh_token",
        "auth_token",
        "bearer_token",
        "callback_token",
        "webhook_token",
        "client_secret",
        "private_key",
    }
)
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "passwd",
    "credential",
    "client_secret",
    "private_key",
)
_SECRET_KEY_SUFFIXES = (
    "_secret",
    "_token",
)
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]{12,}")
_RUNTIME_FIELDS = (
    "TASK_ACTION_MAX_ATTEMPTS",
    "TASK_NETWORK_MAX_ATTEMPTS",
    "TASK_ACTION_TIMEOUT_SECONDS",
    "TASK_TOOL_TIMEOUT_SECONDS",
    "TASK_PLAN_MAX_DEPTH",
    "TASK_PLAN_MAX_NODES",
    "TASK_PLAN_MAX_LEAVES",
    "TASK_AGENT_MAX_REQUESTS",
    "TASK_AGENT_MAX_TOOL_CALLS",
    "TASK_ASK_AGENT_TIMEOUT_SECONDS",
    "TASK_ASK_AGENT_MAX_ROUNDS",
)


@dataclass(frozen=True)
class TaskEvidenceBundle:
    summary: LabTaskSummary
    payload: dict[str, Any]
    coverage: EvidenceCoverage


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in cast(list[Any], value)]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in cast(tuple[Any, ...], value)]
    if isinstance(value, set):
        return [_jsonable(item) for item in cast(set[Any], value)]
    if isinstance(value, frozenset):
        return [_jsonable(item) for item in cast(frozenset[Any], value)]
    if isinstance(value, (datetime, UUID)):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if normalized in _SECRET_KEYS:
        return True
    if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
        return True
    return normalized.endswith(_SECRET_KEY_SUFFIXES)


def sanitize_evidence(value: Any, *, key: str = "") -> Any:
    """Remove credential-shaped values before evidence reaches an analysis model."""

    if _is_secret_key(key):
        return "[REDACTED]"
    normalized = _jsonable(value)
    if isinstance(normalized, dict):
        mapping = cast(dict[Any, Any], normalized)
        return {
            str(child_key): sanitize_evidence(child, key=str(child_key))
            for child_key, child in mapping.items()
        }
    if isinstance(normalized, list):
        return [
            sanitize_evidence(item, key=key)
            for item in cast(list[Any], normalized)
        ]
    if isinstance(normalized, str):
        return _BEARER_PATTERN.sub(r"\1[REDACTED]", normalized)
    return normalized


async def _task_rows(task_ids: set[UUID]) -> list[Task]:
    if not task_ids:
        return []
    query = (
        select(Task)
        .options(selectinload(Task.agent))
        .where(Task.id.in_(task_ids))
    )
    return list((await get_db().scalars(Task.histo_filter(query))).all())


async def _task_graph(task_id: UUID) -> tuple[Task, list[Task], bool]:
    root = await evaluation_service.get_task(task_id)
    if root is None:
        raise LookupError("task_not_found")

    known: dict[UUID, Task] = {root.id: root}
    truncated = False

    ancestor_ids = {
        value for value in (root.parent_id, root.source_task_id) if value is not None
    }
    while ancestor_ids and len(known) < _MAX_RELATED_TASKS:
        rows = await _task_rows(ancestor_ids - known.keys())
        if not rows:
            break
        for row in rows:
            known[row.id] = row
        ancestor_ids = {
            value
            for row in rows
            for value in (row.parent_id, row.source_task_id)
            if value is not None and value not in known
        }

    frontier = {root.id}
    while frontier and len(known) < _MAX_RELATED_TASKS:
        query = (
            select(Task)
            .options(selectinload(Task.agent))
            .where(
                or_(
                    Task.parent_id.in_(frontier),
                    Task.source_task_id.in_(frontier),
                )
            )
        )
        rows = list((await get_db().scalars(Task.histo_filter(query))).all())
        new_rows = [row for row in rows if row.id not in known]
        remaining = _MAX_RELATED_TASKS - len(known)
        if len(new_rows) > remaining:
            new_rows = new_rows[:remaining]
            truncated = True
        for row in new_rows:
            known[row.id] = row
        frontier = {row.id for row in new_rows}

    if len(known) >= _MAX_RELATED_TASKS and frontier:
        truncated = True
    related = [task for current_id, task in known.items() if current_id != root.id]
    related.sort(key=lambda task: (task.created_at or datetime.min, str(task.id)))
    return root, related, truncated


def _task_payload(task: Task, *, selected: bool) -> dict[str, Any]:
    status = task.status.value
    agent = task.agent
    return {
        "uri": f"galaris://task/{task.id}",
        "selected": selected,
        "revision": task.revision,
        "label": task.label,
        "objective": task.objective,
        "status": status,
        "paused": task.paused,
        "feedback": task.feedback,
        "last_error": task.last_error,
        "cost": task.cost,
        "effort": task.effort,
        "forced_route": task.forced_route,
        "forced_effort": task.forced_effort,
        "auto_approve": task.auto_approve,
        "attempt_count": task.attempt_count,
        "consecutive_failures": task.consecutive_failures,
        "cancel_requested": task.cancel_requested,
        "next_attempt_at": task.next_attempt_at,
        "lease_expires_at": task.lease_expires_at,
        "parent_uri": (
            f"galaris://task/{task.parent_id}" if task.parent_id is not None else None
        ),
        "source_task_uri": (
            f"galaris://task/{task.source_task_id}"
            if task.source_task_id is not None
            else None
        ),
        "goal_id": task.goal_id,
        "requester_agent_id": task.requester_agent_id,
        "message_platform": task.message_platform,
        "message_group_id": task.message_group_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "agent": (
            {
                "id": agent.id,
                "code": agent.code,
                "name": f"{agent.first_name} {agent.last_name}".strip(),
                "driver": agent.agent_driver,
            }
            if agent is not None
            else None
        ),
        "messages": task.messages or [],
        "data": task.data or {},
        "dispatch_result": task.dispatch_result,
        "briefing_result": task.briefing_result,
        "plan": task.plan,
        "execution_result": task.execution_result,
    }


def _attempt_payload(attempt: TaskAttempt) -> dict[str, Any]:
    duration = None
    if attempt.finished_at is not None:
        duration = max(0.0, (attempt.finished_at - attempt.started_at).total_seconds())
    return {
        "id": str(attempt.id),
        "task_uri": f"galaris://task/{attempt.task_id}",
        "attempt_number": attempt.attempt_number,
        "phase": attempt.phase,
        "status": attempt.status,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "duration": duration,
        "retryable": attempt.retryable,
        "error": attempt.error,
        "cost": attempt.cost,
        "data": attempt.data or {},
    }


async def _agent_payload(task: Task) -> tuple[dict[str, Any] | None, list[Any], list[str]]:
    if task.agent_id is None:
        return None, [], []
    agent = await agent_service.get(task.agent_id)
    if agent is None:
        return None, [], []
    policy = resolve_pipeline_policy(agent.agent_driver)
    profile = resolve_tool_profile(agent.agent_driver)
    status = next(
        (item for item in list_driver_statuses() if item.code == agent.agent_driver),
        None,
    )
    standard_llm = await llm_service.get_llm_for_agent(agent)
    high_llm = await llm_service.get_executor_llm_for_effort(agent, "high")
    payload = {
        "id": agent.id,
        "code": agent.code,
        "name": f"{agent.first_name} {agent.last_name}".strip(),
        "driver": agent.agent_driver,
        "personality": agent.personality,
        "job_title": agent.job_title,
        "job_description": agent.job_description,
        "standard_model": (
            {"id": standard_llm.id, "label": standard_llm.label, "model": standard_llm.llm_name}
            if standard_llm is not None
            else None
        ),
        "high_model": (
            {
                "id": high_llm.id,
                "label": high_llm.label,
                "model": high_llm.llm_name,
            }
            if high_llm is not None
            else None
        ),
        "driver_status": (
            {
                "declared": status.declared,
                "enabled": status.enabled,
                "configured": status.configured,
                "ready": status.ready,
                "reason": status.reason,
            }
            if status is not None
            else None
        ),
        "static_pipeline_policy": {
            "use_planner": policy.use_planner,
            "use_briefing": policy.use_briefing,
            "briefing_efforts": sorted(policy.briefing_efforts),
        },
        "tool_profile": {
            "voice_calling": profile.voice_calling,
            "file_tools": profile.file_tools,
            "console_execution": profile.console_execution,
        },
    }
    tools: list[Any]
    try:
        tools = cast(list[Any], await list_agent_mcp_tools(agent.id))
    except Exception as exc:
        tools = [{"catalog_error": type(exc).__name__}]
    try:
        skills = await skill_service.get_assigned_codes(agent.id)
    except Exception:
        skills = []
    return payload, tools, skills


def _signals(
    root: Task,
    related: list[Task],
    attempts: list[TaskAttempt],
    llm_calls: list[Any],
    process_runs: list[Any],
) -> list[dict[str, Any]]:
    status = root.status.value
    signals: list[dict[str, Any]] = [
        {
            "code": "task_state",
            "severity": "info",
            "message": f"Selected task is currently {status} (paused={bool(root.paused)}).",
            "evidence": [f"task:{root.id}"],
        }
    ]
    if root.last_error:
        signals.append(
            {
                "code": "task_last_error",
                "severity": "high",
                "message": root.last_error,
                "evidence": [f"task:{root.id}.last_error"],
            }
        )
    execution = root.execution_result if isinstance(root.execution_result, dict) else {}
    execution_success = execution.get("success")
    if status == TaskStatus.SUCCESS.value and execution_success is False:
        signals.append(
            {
                "code": "terminal_result_mismatch",
                "severity": "critical",
                "message": "Task status is SUCCESS while its execution result reports failure.",
                "evidence": [f"task:{root.id}.status", f"task:{root.id}.execution_result"],
            }
        )
    failed_attempts = [
        attempt for attempt in attempts if attempt.status in {"ERROR", "RETRY", "CANCELLED"}
    ]
    if failed_attempts:
        signals.append(
            {
                "code": "attempt_failures",
                "severity": "high",
                "message": f"{len(failed_attempts)} scheduler attempt(s) ended in error, retry, or cancellation.",
                "evidence": [f"attempt:{attempt.id}" for attempt in failed_attempts],
            }
        )
    failed_calls = [call for call in llm_calls if call.status not in {"completed", "cancelled"}]
    if failed_calls:
        signals.append(
            {
                "code": "llm_call_failures",
                "severity": "high",
                "message": f"{len(failed_calls)} LLM call(s) did not complete successfully.",
                "evidence": [f"llm_call:{call.id}" for call in failed_calls],
            }
        )
    length_limited = [call for call in llm_calls if call.finish_reason == "length"]
    if length_limited:
        signals.append(
            {
                "code": "llm_length_limit",
                "severity": "medium",
                "message": f"{len(length_limited)} LLM call(s) stopped because of an output length limit.",
                "evidence": [f"llm_call:{call.id}" for call in length_limited],
            }
        )
    if not llm_calls:
        signals.append(
            {
                "code": "no_llm_trace",
                "severity": "medium",
                "message": "No persisted LLM call is linked to the selected task graph.",
                "evidence": [f"task:{root.id}"],
            }
        )
    failed_related = [
        task
        for task in related
        if task.status == TaskStatus.ERROR
    ]
    if failed_related:
        signals.append(
            {
                "code": "related_task_failures",
                "severity": "high",
                "message": f"{len(failed_related)} related task(s) ended in ERROR.",
                "evidence": [f"task:{task.id}" for task in failed_related],
            }
        )
    active_processes = [
        run for run in process_runs if run.status not in {"success", "error", "cancelled"}
    ]
    if active_processes:
        signals.append(
            {
                "code": "active_processes",
                "severity": "medium",
                "message": f"{len(active_processes)} related process run(s) are still non-terminal.",
                "evidence": [f"process_run:{run.id}" for run in active_processes],
            }
        )
    return signals


async def build_task_evidence(task_id: UUID) -> TaskEvidenceBundle:
    """Build a bounded live dossier without mutating or replaying the task."""

    root, related, graph_truncated = await _task_graph(task_id)
    all_tasks = [root, *related]
    task_ids = [task.id for task in all_tasks]
    attempts = list(
        (
            await get_db().scalars(
                select(TaskAttempt)
                .where(TaskAttempt.task_id.in_(task_ids))
                .order_by(TaskAttempt.started_at.asc(), TaskAttempt.attempt_number.asc())
            )
        ).all()
    )
    calls = await llm_call_service.list_calls(
        task_ids=task_ids,
        limit=_MAX_LLM_CALLS,
    )
    serialized_calls = await llm_call_service.serialize_calls(calls)
    process_runs = await process_service.list_for_task_ids(
        task_ids,
        limit=_MAX_PROCESS_RUNS,
    )
    agent, tools, skills = await _agent_payload(root)
    tool_call_count = sum(len(call.tool_calls) for call in serialized_calls)
    has_final_result = bool(root.execution_result) or root.status in {
        TaskStatus.SUCCESS,
        TaskStatus.ERROR,
    }
    coverage = EvidenceCoverage(
        task_count=len(all_tasks),
        attempt_count=len(attempts),
        llm_call_count=len(serialized_calls),
        tool_call_count=tool_call_count,
        process_run_count=len(process_runs),
        has_agent_configuration=agent is not None,
        has_final_result=has_final_result,
        truncated=(
            graph_truncated
            or len(serialized_calls) >= _MAX_LLM_CALLS
            or len(process_runs) >= _MAX_PROCESS_RUNS
        ),
    )
    payload = {
        "selected_task": _task_payload(root, selected=True),
        "related_tasks": [_task_payload(task, selected=False) for task in related],
        "attempts": [_attempt_payload(attempt) for attempt in attempts],
        "llm_calls": [call.model_dump(mode="json") for call in serialized_calls],
        "process_runs": [run.model_dump(mode="json") for run in process_runs],
        "agent_configuration": agent,
        "available_tools": tools,
        "active_skills": skills,
        "current_task_runtime_settings": {
            field: getattr(runtime_settings, field) for field in _RUNTIME_FIELDS
        },
        "deterministic_signals": _signals(
            root,
            related,
            attempts,
            serialized_calls,
            process_runs,
        ),
        "evidence_notes": [
            "The Lab stores only the selected Task identity; this dossier was loaded live from its canonical resource URI.",
            "Current agent capabilities and runtime settings may differ from those at execution time unless the task trace captured them.",
            "A textual claim is not proof of a tool side effect; use persisted tool calls and process events.",
        ],
    }
    return TaskEvidenceBundle(
        summary=evaluation_service.task_summary(root),
        payload=cast(dict[str, Any], sanitize_evidence(payload)),
        coverage=coverage,
    )
