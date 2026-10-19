"""Observed call latency; journal output is not a client delivery receipt."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.sql.selectable import ScalarSelect

from .models import LLMCall, LLMCallEvent, USEFUL_OUTPUT_EVENT_SQL


class LLMProcessingTiming(BaseModel):
    call_id: UUID
    purpose: str | None
    started_at: datetime
    completed_at: datetime | None
    seconds: float
    first_output_at: datetime | None = None


class LLMExecutionTiming(BaseModel):
    first_call_at: datetime | None = None
    first_output_at: datetime | None = None
    first_output_seconds: float | None = None
    call_seconds_before_output: float | None = None
    between_calls_seconds: float | None = None


def first_output_timestamp() -> ScalarSelect[datetime]:
    """Seek the earliest useful event, ignoring reasoning and internal decisions."""
    return select(LLMCallEvent.created_at).where(
        LLMCallEvent.call_id == LLMCall.id,
        LLMCallEvent.created_at >= LLMCall.started_at,
        LLMCall.purpose.in_(("agent.exec", "agent.synthesis", "conversation.text", "conversation.audio")),
        text(USEFUL_OUTPUT_EVENT_SQL),
    ).order_by(LLMCallEvent.created_at).limit(1).correlate(LLMCall).scalar_subquery()


def execution_timing(intervals: list[LLMProcessingTiming]) -> LLMExecutionTiming:
    """Union call spans before first output: overlapping calls count only once.

    Missing end evidence leaves the decomposition unknown. Journal timestamps
    measure server observation, not first rendered token or pure network latency.
    """
    if not intervals:
        return LLMExecutionTiming()
    start = min(item.started_at for item in intervals)
    outputs = [item.first_output_at for item in intervals if item.first_output_at is not None]
    output = min(outputs) if outputs else None
    result = LLMExecutionTiming(first_call_at=start, first_output_at=output)
    if output is None or output < start:
        return result
    result.first_output_seconds = (output - start).total_seconds()
    spans: list[tuple[datetime, datetime]] = []
    for item in intervals:
        if item.started_at > output:
            continue
        end = item.completed_at or item.first_output_at
        if end is None or end < item.started_at:
            return result
        spans.append((item.started_at, min(end, output)))
    covered = 0.0
    cursor = start
    for begin, end in sorted(spans):
        covered += max(0.0, (end - max(cursor, begin)).total_seconds())
        cursor = max(cursor, end)
    result.call_seconds_before_output = covered
    result.between_calls_seconds = max(0.0, result.first_output_seconds - covered)
    return result
