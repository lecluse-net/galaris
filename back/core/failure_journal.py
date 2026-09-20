"""Runtime-neutral core port for durable AI failure capture."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession


FailureKind = Literal["llm", "tool"]


class FailureEvent(BaseModel):
    """One failed invocation attempt before persistence and sanitization."""

    idempotency_key: str = Field(min_length=1, max_length=300)
    kind: FailureKind
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: str | None = Field(default=None, max_length=60)
    phase: str = Field(default="execution", max_length=100)
    severity: str = Field(default="error", max_length=20)
    error_type: str = Field(default="Error", max_length=300)
    error_code: str | None = Field(default=None, max_length=200)
    error_message: str = Field(default="", max_length=200_000)
    retryable: bool | None = None
    attempt_number: int | None = Field(default=None, ge=1)
    retry_limit: int | None = Field(default=None, ge=0)
    will_retry: bool | None = None
    task_id: UUID | None = None
    task_attempt_id: UUID | None = None
    llm_call_id: UUID | None = None
    conversation_round_id: UUID | None = None
    process_run_id: UUID | None = None
    agent_id: int | None = None
    run_uuid: UUID | None = None
    causal_incident_id: UUID | None = None
    driver_code: str | None = Field(default=None, max_length=100)
    provider_code: str | None = Field(default=None, max_length=100)
    model_code: str | None = Field(default=None, max_length=500)
    tool_name: str | None = Field(default=None, max_length=500)
    tool_call_external_id: str | None = Field(default=None, max_length=500)
    trace: dict[str, Any] = Field(default_factory=dict[str, Any])


RecordInSession = Callable[[AsyncSession, FailureEvent], Awaitable[object | None]]
RecordIsolated = Callable[[FailureEvent], Awaitable[object | None]]
MarkRecovered = Callable[[UUID], Awaitable[int]]

_record_in_session: RecordInSession | None = None
_record_isolated: RecordIsolated | None = None
_mark_recovered: MarkRecovered | None = None


def register_failure_journal(
    *,
    record_in_session: RecordInSession,
    record_isolated: RecordIsolated,
    mark_recovered: MarkRecovered,
) -> None:
    """Bind the application-owned implementation at the composition root."""

    global _record_in_session, _record_isolated, _mark_recovered
    _record_in_session = record_in_session
    _record_isolated = record_isolated
    _mark_recovered = mark_recovered


async def record_failure_in_session(
    db: AsyncSession,
    event: FailureEvent,
) -> object | None:
    if _record_in_session is None:
        logger.warning(
            "Failure journal is not registered; event key={} was not persisted",
            event.idempotency_key,
        )
        return None
    return await _record_in_session(db, event)


async def record_failure_event(event: FailureEvent) -> object | None:
    if _record_isolated is None:
        logger.warning(
            "Failure journal is not registered; event key={} was not persisted",
            event.idempotency_key,
        )
        return None
    return await _record_isolated(event)


async def mark_failure_run_recovered(run_uuid: UUID) -> int:
    if _mark_recovered is None:
        return 0
    return await _mark_recovered(run_uuid)


__all__ = [
    "FailureEvent",
    "FailureKind",
    "mark_failure_run_recovered",
    "record_failure_event",
    "record_failure_in_session",
    "register_failure_journal",
]
