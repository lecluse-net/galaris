"""Bounded activity snapshots; durable attempts remain the authority for outcomes."""
from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.agent import AIMessage, AIResult
from app.agent.facade import recorded_checkpoint_tools
from app.llm.facade import MailSubscriptionAccessError
from core.database import get_db
from core.util import visible_text
from .models import Task, TaskAmendment, TaskAttempt, TaskStatus
from .operational_state import TaskOperationalSnapshot, operational_snapshot
from .working_set import parse_working_set
from .startup_timing import TaskStartupTiming, task_startup_timings
from .call_recovery import TaskCallRecoveryState, recovery_state, supports_call_recovery
from .trace_projection import project_tool_payload


_AMENDED_TOOL_LIMIT = 40


class TaskActivityQuery(BaseModel):
    task_ids: list[UUID] = Field(min_length=1, max_length=50)


class LiveActivity(BaseModel):
    run_id: UUID
    attempt_id: UUID | None = None
    sequence: int
    result: AIResult
    last_activity_at: datetime


class HistoricalToolActivity(BaseModel):
    attempt_id: UUID
    message: AIMessage


class TaskActivitySnapshot(BaseModel):
    task_id: UUID
    startup_timing: TaskStartupTiming | None = None
    revision: int
    phase: str
    operational: TaskOperationalSnapshot
    pause_pending: bool = False
    attempt_number: int = Field(default=0, description="Attempt ordinal within the latest scheduler phase.")
    attempt_status: str | None = None
    latest_attempt: dict[str, str | int | None] | None = None
    last_activity_at: datetime | None = None
    next_attempt_at: datetime | None = None
    run_id: UUID | None = None
    streams_ai_messages: bool = True
    call_recovery_supported: bool = False
    call_recovery: TaskCallRecoveryState | None = None
    live: LiveActivity | None = None
    amended_tool_history: list[HistoricalToolActivity] = Field(default_factory=list[HistoricalToolActivity])
    original_demand: str | None = None
    parent_task_id: UUID | None = None
    source_task_id: UUID | None = None
    messenger_message_id: UUID | None = None
    mail_subscription_routing: Literal["fallback", "blocked"] | None = None
    delivery_policy: str | None = None
    resources: list[dict[str, str | None]] = Field(default_factory=list[dict[str, str | None]])
    execution_scope: dict[str, Any] | None = None
    scope_preflights: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


def _scope_summary(raw: object) -> dict[str, object] | None:
    """Keep repeated activity reads independent of admitted demand size."""
    if not isinstance(raw, dict):
        return None
    data = cast(dict[str, object], raw)
    summary: dict[str, object] = {}
    for key in ("schema_version", "revision", "source_task_id", "delivery_owner_task_id"):
        value = data.get(key)
        if isinstance(value, (str, int)) and len(str(value)) <= 100:
            summary[key] = value
    for field, count in (("requirements", "requirement_count"), ("grants", "grant_count")):
        values = data.get(field)
        summary[count] = len(cast(Sequence[object], values)) if isinstance(values, (list, tuple)) else 0
    return summary


async def readable_activity_tasks(ids: Sequence[UUID], agent_ids: Collection[int] | None) -> list[Task]:
    query = select(Task).where(Task.id.in_(ids))
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    return list((await get_db().scalars(query)).all())


async def _amended_tool_history(tasks: Sequence[Task]) -> dict[UUID, list[HistoricalToolActivity]]:
    ids = [task.id for task in tasks if (task.data or {}).get("amendment_count")]
    if not ids:
        return {}
    checkpoint = TaskAttempt.data["agent_checkpoint"]
    driver_code = checkpoint["driver_code"].as_string()
    runtime_run_id = checkpoint["runtime_run_id"].as_string()
    amended_after_start = select(TaskAmendment.id).where(
        TaskAmendment.task_id == TaskAttempt.task_id,
        TaskAmendment.applied_at >= TaskAttempt.started_at,
    ).correlate(TaskAttempt).exists()
    # Attempts resuming the same runtime carry its cumulative checkpoint. A
    # delegation fan-in may start a new runtime, so also retain its predecessors.
    latest_per_run = (select(TaskAttempt.task_id, TaskAttempt.id, TaskAttempt.attempt_number)
        .where(TaskAttempt.task_id.in_(ids), runtime_run_id.is_not(None), amended_after_start)
        .distinct(TaskAttempt.task_id, driver_code, runtime_run_id)
        .order_by(TaskAttempt.task_id, driver_code, runtime_run_id, TaskAttempt.attempt_number.desc()).subquery())
    rank = func.row_number().over(partition_by=latest_per_run.c.task_id,
        order_by=latest_per_run.c.attempt_number.desc())
    ranked = select(latest_per_run.c.task_id, latest_per_run.c.id, rank.label("rank")).subquery()
    query = (select(ranked.c.task_id, ranked.c.id, checkpoint).select_from(ranked)
        .join(TaskAttempt, TaskAttempt.id == ranked.c.id)
        .where(ranked.c.rank <= 4).order_by(ranked.c.task_id, ranked.c.rank.desc()))
    history: dict[UUID, list[HistoricalToolActivity]] = {}
    for task_id, attempt_id, raw_checkpoint in (await get_db().execute(query)).tuples():
        tools = history.setdefault(task_id, [])
        for message in recorded_checkpoint_tools(raw_checkpoint, limit=_AMENDED_TOOL_LIMIT):
            message.tool_arguments = project_tool_payload(message.tool_arguments, limit=1_000)
            message.tool_result = project_tool_payload(message.tool_result, limit=1_000)
            tools.append(HistoricalToolActivity(attempt_id=attempt_id, message=message))
        del tools[:-_AMENDED_TOOL_LIMIT]
    return history


async def activity_snapshots(tasks: Sequence[Task]) -> list[TaskActivitySnapshot]:
    """Project only already-authorized Tasks, in a constant number of queries."""
    if not tasks:
        return []
    ids = [task.id for task in tasks]
    timings = {item.task_id: item for item in await task_startup_timings(ids)}
    historical_tools = await _amended_tool_history(tasks)
    db = get_db()
    # Routing (CREATE) and execution (DISPATCH) each claim a durable attempt.
    # Number the displayed attempts by phase without changing their audit identity.
    phase_attempt_number = func.count().over(partition_by=(TaskAttempt.task_id, TaskAttempt.phase))
    latest = select(TaskAttempt, phase_attempt_number).where(TaskAttempt.task_id.in_(ids)).distinct(
        TaskAttempt.task_id
    ).order_by(TaskAttempt.task_id, TaskAttempt.attempt_number.desc())
    attempts: dict[UUID, TaskAttempt] = {}
    attempt_numbers: dict[UUID, int] = {}
    for attempt, number in (await db.execute(latest)).tuples():
        attempts[attempt.task_id] = attempt
        attempt_numbers[attempt.task_id] = int(number)
    # Operational state ignores finished children and never consumes their
    # execution payloads. Keep repeated monitoring independent of that history.
    children = (await db.scalars(select(Task).where(
        Task.parent_id.in_(ids), Task.status.not_in((TaskStatus.SUCCESS, TaskStatus.ERROR)),
    ).options(
        defer(Task.execution_result, raiseload=True),
        defer(Task.dispatch_result, raiseload=True),
        defer(Task.messages, raiseload=True),
    ))).all()
    children_by_parent: dict[UUID, list[Task]] = {}
    for child in children:
        if child.parent_id is not None:
            children_by_parent.setdefault(child.parent_id, []).append(child)
    result: list[TaskActivitySnapshot] = []
    for task in tasks:
        attempt = attempts.get(task.id)
        timing = timings.get(task.id)
        mail_routing: Literal["fallback", "blocked"] | None = None
        if task.status == TaskStatus.ERROR and any(
            MailSubscriptionAccessError.__name__ in (reason or "")
            for reason in (task.last_error, task.feedback, attempt.error if attempt else None)
        ):
            mail_routing = "blocked"
        elif timing and any(call.mail_subscription_fallback for call in timing.processing_intervals):
            mail_routing = "fallback"
        data = dict(attempt.data or {}) if attempt else {}
        identity: dict[str, Any] = (task.data or {}).get("_agent_run_identity") or {}
        run_id = identity.get("request_run_id")
        target: dict[str, Any] = identity.get("execution_target") or {}
        metadata: dict[str, Any] = target.get("metadata") or {}
        live = LiveActivity.model_validate(data["live_activity"]) if data.get("live_activity") else None
        if live and (str(live.run_id) != str(run_id)
                     or live.attempt_id is not None and attempt is not None and live.attempt_id != attempt.id):
            live = None
        last_activity = live.last_activity_at if live else (
            attempt.finished_at or attempt.started_at if attempt else None
        )
        # SDK argument deltas update progress without publishing a fake tool event.
        # Only activity from this run and attempt may postpone a silence warning.
        runtime_activity = data.get("runtime_activity")
        recorded_activity = cast(dict[str, object], runtime_activity) if isinstance(runtime_activity, dict) else {}
        if run_id and recorded_activity.get("run_id") == str(run_id):
            raw_at = recorded_activity.get("at")
            if isinstance(raw_at, str):
                try:
                    at = datetime.fromisoformat(raw_at)
                    if at.tzinfo is not None and (last_activity is None or at > last_activity):
                        last_activity = at
                except ValueError:
                    pass
        operational = operational_snapshot(task, children_by_parent.get(task.id, ()))
        result.append(TaskActivitySnapshot(
            task_id=task.id, revision=task.revision, phase=task.status.value,
            startup_timing=timing,
            operational=operational,
            pause_pending=operational["operational_state"] == "PAUSED" and task.lease_token is not None,
            attempt_number=attempt_numbers.get(task.id, 0),
            attempt_status=attempt.status if attempt else None,
            latest_attempt={
                "id": str(attempt.id), "attempt_number": attempt.attempt_number,
                "phase": attempt.phase, "status": attempt.status,
                "started_at": attempt.started_at.isoformat(),
                "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
            } if attempt else None,
            last_activity_at=last_activity,
            next_attempt_at=task.next_attempt_at, run_id=run_id,
            streams_ai_messages=metadata.get("streams_ai_messages") is not False,
            call_recovery_supported=supports_call_recovery(task),
            call_recovery=recovery_state(task, attempt),
            live=live,
            amended_tool_history=historical_tools.get(task.id, []),
            original_demand=(visible_text(str(task.data["_original_demand"]))[:8_000]
                             if task.data and "_original_demand" in task.data else None),
            parent_task_id=task.parent_id, source_task_id=task.source_task_id,
            messenger_message_id=task.messenger_message_id,
            mail_subscription_routing=mail_routing,
            delivery_policy=(task.data or {}).get("delivery_policy"),
            execution_scope=_scope_summary((task.data or {}).get("execution_scope")),
            scope_preflights=data.get("scope_preflights", (task.data or {}).get("scope_preflights", []))[-20:],
            resources=[{
                "type": resource.resource_type, "reference": resource.reference,
                "label": resource.label, "state": resource.state,
                "producer_task_id": str(resource.producer_task_id) if resource.producer_task_id else None,
            } for resource in parse_working_set(task).resources[-100:]],
        ))
    return result
