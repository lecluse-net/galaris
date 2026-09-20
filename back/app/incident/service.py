"""Persistence, grouping, review, and querying for failure incidents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Collection, cast
from uuid import UUID, uuid4

import logfire
from loguru import logger
from sqlalchemy import Select, case, delete as sa_delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, get_db_session

from .contracts import FailureEvent
from .models import FailureIncident, FailureIncidentTrace, FailurePattern
from .sanitizer import categorize_failure, fingerprint_failure, sanitize_trace
from .schemas import FailurePatternUpdate


_REVIEW_STATUSES = frozenset(
    {"new", "triaged", "fix_planned", "resolved", "ignored", "regression"}
)


def _pattern_title(event: FailureEvent) -> str:
    component = event.tool_name or event.model_code or event.provider_code or event.driver_code
    detail = event.error_message.strip().splitlines()[0][:300] if event.error_message.strip() else event.error_type
    return (f"{component}: {detail}" if component else detail)[:500]


def _enrich_existing_incident(
    incident: FailureIncident,
    event: FailureEvent,
) -> None:
    """Fill correlations learned by a later observer of the same invocation."""

    fields = (
        "causal_incident_id",
        "task_id",
        "task_attempt_id",
        "llm_call_id",
        "conversation_round_id",
        "process_run_id",
        "agent_id",
        "run_uuid",
        "driver_code",
        "provider_code",
        "model_code",
        "tool_name",
        "tool_call_external_id",
        "retryable",
        "attempt_number",
        "retry_limit",
        "will_retry",
    )
    for field in fields:
        if getattr(incident, field) is None:
            value = getattr(event, field)
            if value is not None:
                setattr(incident, field, value)


async def record_failure(db: AsyncSession, event: FailureEvent) -> FailureIncident:
    """Append an occurrence and trace exactly once inside the caller transaction."""

    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(event.idempotency_key, 0)
            )
        )
    )
    existing = await db.scalar(
        select(FailureIncident).where(
            FailureIncident.idempotency_key == event.idempotency_key
        )
    )
    if existing is not None:
        _enrich_existing_incident(existing, event)
        await db.flush()
        return existing

    category = categorize_failure(event)
    fingerprint = fingerprint_failure(event, category)
    pattern_id = uuid4()
    pattern_statement = (
        insert(FailurePattern)
        .values(
            id=pattern_id,
            fingerprint=fingerprint,
            fingerprint_version=2,
            kind=event.kind,
            category=category,
            title=_pattern_title(event),
            status="new",
            occurrence_count=1,
            first_seen_at=event.occurred_at,
            last_seen_at=event.occurred_at,
        )
        .on_conflict_do_update(
            index_elements=[FailurePattern.fingerprint],
            set_={
                "occurrence_count": FailurePattern.occurrence_count + 1,
                "last_seen_at": func.greatest(
                    FailurePattern.last_seen_at, event.occurred_at
                ),
                "status": case(
                    (FailurePattern.status == "resolved", "regression"),
                    else_=FailurePattern.status,
                ),
                "resolved_at": case(
                    (FailurePattern.status == "resolved", None),
                    else_=FailurePattern.resolved_at,
                ),
                "updated_at": func.now(),
            },
        )
        .returning(FailurePattern.id)
    )
    persisted_pattern_id = (await db.execute(pattern_statement)).scalar_one()
    incident = FailureIncident(
        pattern_id=persisted_pattern_id,
        causal_incident_id=event.causal_incident_id,
        idempotency_key=event.idempotency_key,
        kind=event.kind,
        category=category,
        phase=event.phase,
        severity=event.severity,
        error_type=event.error_type,
        error_code=event.error_code,
        error_message=event.error_message,
        retryable=event.retryable,
        attempt_number=event.attempt_number,
        retry_limit=event.retry_limit,
        will_retry=event.will_retry,
        task_id=event.task_id,
        task_attempt_id=event.task_attempt_id,
        llm_call_id=event.llm_call_id,
        conversation_round_id=event.conversation_round_id,
        process_run_id=event.process_run_id,
        agent_id=event.agent_id,
        run_uuid=event.run_uuid,
        driver_code=event.driver_code,
        provider_code=event.provider_code,
        model_code=event.model_code,
        tool_name=event.tool_name,
        tool_call_external_id=event.tool_call_external_id,
        occurred_at=event.occurred_at,
    )
    db.add(incident)
    await db.flush()
    payload, redacted, truncated, content_hash, byte_size = sanitize_trace(event.trace)
    db.add(
        FailureIncidentTrace(
            incident_id=incident.id,
            payload=payload,
            redacted_fields=redacted,
            truncated_fields=truncated,
            content_hash=content_hash,
            byte_size=byte_size,
        )
    )
    await db.flush()
    logfire.warning(
        "Failure incident recorded {incident_id}",
        incident_id=str(incident.id),
        failure_kind=event.kind,
        failure_category=category,
        failure_fingerprint=fingerprint,
        tool_name=event.tool_name,
        provider_code=event.provider_code,
        run_uuid=str(event.run_uuid) if event.run_uuid is not None else None,
    )
    return incident


async def record_failure_isolated(event: FailureEvent) -> FailureIncident | None:
    """Persist from a long-running runtime without contaminating its primary work."""

    try:
        async with get_db_session() as db:
            return await record_failure(db, event)
    except Exception:
        logger.exception(
            "Could not persist failure incident kind={} key={}",
            event.kind,
            event.idempotency_key,
        )
        return None


async def mark_run_recovered(run_uuid: UUID) -> int:
    """Mark earlier failures from a run that ultimately produced a success."""

    now = datetime.now(timezone.utc)
    recovered_ids = list(
        (
            await get_db().scalars(
                update(FailureIncident)
                .where(
                    FailureIncident.run_uuid == run_uuid,
                    FailureIncident.recovered_at.is_(None),
                )
                .values(recovered_at=now)
                .returning(FailureIncident.id)
            )
        ).all()
    )
    await get_db().flush()
    return len(recovered_ids)


async def mark_run_recovered_isolated(run_uuid: UUID) -> int:
    """Apply recovery from a driver root that has no database transaction."""

    try:
        async with get_db_session():
            return await mark_run_recovered(run_uuid)
    except Exception:
        logger.exception("Could not mark failure incidents recovered for run={}", run_uuid)
        return 0


def _incident_filters(
    query: Select[Any],
    *,
    kind: str | None,
    category: str | None,
    recovered: bool | None,
    search: str | None,
    agent_ids: Collection[int] | None,
) -> Select[Any]:
    if kind:
        query = query.where(FailureIncident.kind == kind)
    if category:
        query = query.where(FailureIncident.category == category)
    if recovered is True:
        query = query.where(FailureIncident.recovered_at.is_not(None))
    elif recovered is False:
        query = query.where(FailureIncident.recovered_at.is_(None))
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(
            or_(
                FailureIncident.error_message.ilike(needle),
                FailureIncident.error_type.ilike(needle),
                FailureIncident.tool_name.ilike(needle),
                FailureIncident.provider_code.ilike(needle),
                FailureIncident.model_code.ilike(needle),
            )
        )
    if agent_ids is not None:
        query = query.where(FailureIncident.agent_id.in_(agent_ids))
    return query


async def list_incidents(
    *,
    page: int,
    page_size: int,
    kind: str | None = None,
    category: str | None = None,
    recovered: bool | None = None,
    search: str | None = None,
    agent_ids: Collection[int] | None = None,
) -> tuple[list[tuple[FailureIncident, FailurePattern]], int]:
    count_query = _incident_filters(
        select(func.count(FailureIncident.id)),
        kind=kind,
        category=category,
        recovered=recovered,
        search=search,
        agent_ids=agent_ids,
    )
    total = int((await get_db().scalar(count_query)) or 0)
    query = _incident_filters(
        select(FailureIncident, FailurePattern).join(
            FailurePattern, FailurePattern.id == FailureIncident.pattern_id
        ),
        kind=kind,
        category=category,
        recovered=recovered,
        search=search,
        agent_ids=agent_ids,
    )
    rows = (
        await get_db().execute(
            query.order_by(
                FailureIncident.occurred_at.desc(), FailureIncident.id.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [(incident, pattern) for incident, pattern in rows], total


async def get_incident(
    incident_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> tuple[FailureIncident, FailurePattern, FailureIncidentTrace] | None:
    query = (
        select(FailureIncident, FailurePattern, FailureIncidentTrace)
        .join(FailurePattern, FailurePattern.id == FailureIncident.pattern_id)
        .join(
            FailureIncidentTrace,
            FailureIncidentTrace.incident_id == FailureIncident.id,
        )
        .where(FailureIncident.id == incident_id)
    )
    if agent_ids is not None:
        query = query.where(FailureIncident.agent_id.in_(agent_ids))
    row = (await get_db().execute(query)).one_or_none()
    return cast(tuple[FailureIncident, FailurePattern, FailureIncidentTrace], row) if row else None


async def list_patterns(
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    kind: str | None = None,
    search: str | None = None,
) -> tuple[list[FailurePattern], int]:
    query = select(FailurePattern)
    count_query = select(func.count(FailurePattern.id))
    conditions: list[Any] = []
    if status:
        conditions.append(FailurePattern.status == status)
    if kind:
        conditions.append(FailurePattern.kind == kind)
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(
            or_(
                FailurePattern.title.ilike(needle),
                FailurePattern.diagnosis.ilike(needle),
                FailurePattern.root_cause.ilike(needle),
                FailurePattern.remediation.ilike(needle),
            )
        )
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)
    total = int((await get_db().scalar(count_query)) or 0)
    rows = list(
        (
            await get_db().scalars(
                query.order_by(
                    FailurePattern.last_seen_at.desc(), FailurePattern.id.desc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return rows, total


async def update_pattern(
    pattern_id: UUID, data: FailurePatternUpdate
) -> FailurePattern | None:
    pattern = await get_db().get(FailurePattern, pattern_id)
    if pattern is None:
        return None
    values = data.model_dump(exclude_unset=True, exclude_none=True)
    status = values.get("status")
    if status is not None and status not in _REVIEW_STATUSES:
        raise ValueError(f"Unsupported incident status: {status}")
    for key, value in values.items():
        setattr(pattern, key, value)
    if status == "resolved":
        pattern.resolved_at = datetime.now(timezone.utc)
    elif status is not None:
        pattern.resolved_at = None
    await get_db().commit()
    await get_db().refresh(pattern)
    return pattern


async def cleanup_all() -> None:
    """Permanently empty the failure journal and its review patterns."""

    db = get_db()
    await db.execute(sa_delete(FailureIncidentTrace))
    await db.execute(sa_delete(FailureIncident))
    await db.execute(sa_delete(FailurePattern))
    await db.commit()


__all__ = [
    "cleanup_all",
    "get_incident",
    "list_incidents",
    "list_patterns",
    "mark_run_recovered",
    "mark_run_recovered_isolated",
    "record_failure",
    "record_failure_isolated",
    "update_pattern",
]
