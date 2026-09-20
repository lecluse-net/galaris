"""Bounded activity snapshots; durable attempts remain the authority for outcomes."""
from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import AIResult
from core.database import get_db
from core.util import visible_text
from .models import Task, TaskAttempt
from .operational_state import TaskOperationalSnapshot, operational_snapshot
from .working_set import parse_working_set
from .startup_timing import TaskStartupTiming, task_startup_timings


class TaskActivityQuery(BaseModel):
    task_ids: list[UUID] = Field(min_length=1, max_length=50)


class LiveActivity(BaseModel):
    run_id: UUID
    attempt_id: UUID | None = None
    sequence: int
    result: AIResult
    last_activity_at: datetime


class TaskActivitySnapshot(BaseModel):
    task_id: UUID
    startup_timing: TaskStartupTiming | None = None
    revision: int
    phase: str
    operational: TaskOperationalSnapshot
    pause_pending: bool = False
    attempt_number: int = 0
    attempt_status: str | None = None
    latest_attempt: dict[str, str | int | None] | None = None
    last_activity_at: datetime | None = None
    next_attempt_at: datetime | None = None
    run_id: UUID | None = None
    streams_ai_messages: bool = True
    live: LiveActivity | None = None
    original_demand: str | None = None
    parent_task_id: UUID | None = None
    source_task_id: UUID | None = None
    messenger_message_id: UUID | None = None
    delivery_policy: str | None = None
    resources: list[dict[str, str | None]] = Field(default_factory=list[dict[str, str | None]])


async def readable_activity_tasks(ids: Sequence[UUID], agent_ids: Collection[int] | None) -> list[Task]:
    query = select(Task).where(Task.id.in_(ids))
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    return list((await get_db().scalars(query)).all())


async def activity_snapshots(tasks: Sequence[Task]) -> list[TaskActivitySnapshot]:
    """Project only already-authorized Tasks, in a constant number of queries."""
    if not tasks:
        return []
    ids = [task.id for task in tasks]
    timings = {item.task_id: item for item in await task_startup_timings(ids)}
    db = get_db()
    latest = select(TaskAttempt).where(TaskAttempt.task_id.in_(ids)).distinct(
        TaskAttempt.task_id
    ).order_by(TaskAttempt.task_id, TaskAttempt.attempt_number.desc())
    attempts = {attempt.task_id: attempt for attempt in (await db.scalars(latest)).all()}
    children = (await db.scalars(select(Task).where(Task.parent_id.in_(ids)))).all()
    result: list[TaskActivitySnapshot] = []
    for task in tasks:
        attempt = attempts.get(task.id)
        data = dict(attempt.data or {}) if attempt else {}
        identity: dict[str, Any] = (task.data or {}).get("_agent_run_identity") or {}
        run_id = identity.get("request_run_id")
        target: dict[str, Any] = identity.get("execution_target") or {}
        metadata: dict[str, Any] = target.get("metadata") or {}
        live = LiveActivity.model_validate(data["live_activity"]) if data.get("live_activity") else None
        if live and (str(live.run_id) != str(run_id)
                     or live.attempt_id is not None and attempt is not None and live.attempt_id != attempt.id):
            live = None
        operational = operational_snapshot(task, [child for child in children if child.parent_id == task.id])
        result.append(TaskActivitySnapshot(
            task_id=task.id, revision=task.revision, phase=task.status.value,
            startup_timing=timings.get(task.id),
            operational=operational,
            pause_pending=operational["operational_state"] == "PAUSED" and task.lease_token is not None,
            attempt_number=attempt.attempt_number if attempt else 0,
            attempt_status=attempt.status if attempt else None,
            latest_attempt={
                "id": str(attempt.id), "attempt_number": attempt.attempt_number,
                "phase": attempt.phase, "status": attempt.status,
                "started_at": attempt.started_at.isoformat(),
                "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
            } if attempt else None,
            last_activity_at=live.last_activity_at if live else (
                attempt.finished_at or attempt.started_at if attempt else None
            ),
            next_attempt_at=task.next_attempt_at, run_id=run_id,
            streams_ai_messages=metadata.get("streams_ai_messages") is not False,
            live=live,
            original_demand=(visible_text(str(task.data["_original_demand"]))[:8_000]
                             if task.data and "_original_demand" in task.data else None),
            parent_task_id=task.parent_id, source_task_id=task.source_task_id,
            messenger_message_id=task.messenger_message_id,
            delivery_policy=(task.data or {}).get("delivery_policy"),
            resources=[{
                "type": resource.resource_type, "reference": resource.reference,
                "label": resource.label, "state": resource.state,
                "producer_task_id": str(resource.producer_task_id) if resource.producer_task_id else None,
            } for resource in parse_working_set(task).resources[-100:]],
        ))
    return result
