"""Observed initial admission timings, independent from scheduling decisions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy import select

from core.database import get_db
from app.llm.facade import LLMProcessingTiming, task_processing_timings
from .models import Task, TaskAttempt
from .timing_events import parse_lifecycle, phase_totals, timing_totals

STARTUP_TIMING_DATA_KEY = "_startup_timing"
CLAIMED_AT_DATA_KEY = "claimed_at"


class TaskAdmissionTiming(BaseModel):
    preparation_started_at: AwareDatetime | None = None
    preparation_finished_at: AwareDatetime | None = None
    enqueued_at: AwareDatetime | None = None


class TaskStartupTiming(TaskAdmissionTiming):
    task_id: UUID
    label: str
    first_claimed_at: AwareDatetime | None = None
    preparation_seconds: float | None = None
    preparation_source: Literal["observed", "llm_calls"] = "observed"
    preparation_to_first_call_seconds: float | None = None
    admission_seconds: float | None = None
    queue_wait_upper_bound_seconds: float | None = None
    processing_intervals: list[LLMProcessingTiming] = Field(default_factory=list[LLMProcessingTiming])
    lifecycle_seconds: dict[str, float] = Field(default_factory=dict[str, float])
    lifecycle_observed_since: AwareDatetime | None = None
    phase_seconds: dict[str, dict[str, float]] = Field(default_factory=dict[str, dict[str, float]])


def elapsed_seconds(start: datetime | None, end: datetime | None) -> float | None:
    """Missing evidence or a reversed clock is unknown, never zero waiting."""
    if start is None or end is None:
        return None
    elapsed = (end - start).total_seconds()
    return elapsed if elapsed >= 0 else None


def startup_timing(
    task_id: UUID, label: str, admission: object, claimed_at: object,
    lifecycle: object = None,
) -> TaskStartupTiming:
    try:
        recorded = TaskAdmissionTiming.model_validate(admission)
    except ValidationError:
        recorded = TaskAdmissionTiming()
    observed = parse_lifecycle(lifecycle)
    if recorded.enqueued_at is None and observed is not None:
        recorded.enqueued_at = observed.enqueued_at
    try:
        result = TaskStartupTiming.model_validate({
            "task_id": task_id, "label": label, **recorded.model_dump(),
            "first_claimed_at": claimed_at,
        })
    except ValidationError:
        result = TaskStartupTiming(task_id=task_id, label=label, **recorded.model_dump())
    result.preparation_seconds = elapsed_seconds(result.preparation_started_at, result.preparation_finished_at)
    result.admission_seconds = elapsed_seconds(result.preparation_finished_at, result.enqueued_at)
    result.queue_wait_upper_bound_seconds = elapsed_seconds(result.enqueued_at, result.first_claimed_at)
    return result


async def task_startup_timings(
    task_ids: Sequence[UUID], *, agent_id: int | None = None,
) -> list[TaskStartupTiming]:
    """Project already-authorized Tasks, including historical unknown measurements.

    The enqueue timestamp precedes the INSERT/commit. Its distance to the first
    claim includes persistence and any pause before that claim, so it is an upper
    bound on scheduler waiting. Neither created_at nor updated_at is a substitute.
    Only attempt 1 counts: retries and later phases cannot rewrite initial timing.
    """
    if not task_ids:
        return []
    query = (
        select(
            Task.id, Task.label, Task.data[STARTUP_TIMING_DATA_KEY],
            TaskAttempt.data[CLAIMED_AT_DATA_KEY], Task.lifecycle_timing,
        )
        .outerjoin(TaskAttempt, (TaskAttempt.task_id == Task.id) & (TaskAttempt.attempt_number == 1))
        .where(Task.id.in_(task_ids))
        .order_by(Task.created_at, Task.id)
    )
    # A conversation link survives reassignment of a Task. Its existence alone
    # must not expose that Task's current label outside the round's agent scope.
    if agent_id is not None:
        query = query.where(Task.agent_id == agent_id)
    rows = (await get_db().execute(query)).all()
    historical = tuple(row[0] for row in rows
                       if startup_timing(row[0], row[1], row[2], row[3], row[4]).enqueued_at is None)
    intervals = await task_processing_timings(historical) if historical else {}
    result: list[TaskStartupTiming] = []
    for task_id, label, admission, claimed_at, lifecycle in rows:
        timing = startup_timing(task_id, label, admission, claimed_at, lifecycle)
        timing.processing_intervals = intervals.get(task_id, [])
        preparation = [item for item in timing.processing_intervals
                       if item.purpose == "conversation.task_objective"]
        execution = [item for item in timing.processing_intervals
                     if item.purpose != "conversation.task_objective"]
        if timing.preparation_started_at is None and preparation:
            timing.preparation_started_at = preparation[0].started_at
            timing.preparation_source = "llm_calls"
            if all(item.completed_at is not None for item in preparation):
                timing.preparation_finished_at = max(item.completed_at for item in preparation if item.completed_at is not None)
                timing.preparation_seconds = elapsed_seconds(timing.preparation_started_at, timing.preparation_finished_at)
                if execution:
                    timing.preparation_to_first_call_seconds = elapsed_seconds(
                        timing.preparation_finished_at, execution[0].started_at)
        recorded = parse_lifecycle(lifecycle)
        if recorded is not None:
            now = datetime.now(timezone.utc)
            timing.lifecycle_seconds = timing_totals(recorded.model_dump(), now)
            timing.lifecycle_observed_since = recorded.observed_since
            timing.phase_seconds = phase_totals(recorded, now)
        result.append(timing)
    return result
