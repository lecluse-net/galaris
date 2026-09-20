"""Administrative API for the durable failure journal."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize

from . import service
from .models import FailureIncident, FailurePattern
from .schemas import (
    FailureIncidentDetail,
    FailureIncidentPage,
    FailureIncidentRead,
    FailureIncidentSummaryPage,
    FailureIncidentSummaryRead,
    FailurePatternPage,
    FailurePatternRead,
    FailurePatternUpdate,
)


router = APIRouter(prefix="/incidents", tags=["failure-incidents"])


def _incident_read(row: FailureIncident, pattern: FailurePattern) -> FailureIncidentRead:
    return FailureIncidentRead(
        id=row.id,
        pattern_id=row.pattern_id,
        pattern_status=pattern.status,
        pattern_occurrence_count=pattern.occurrence_count,
        causal_incident_id=row.causal_incident_id,
        idempotency_key=row.idempotency_key,
        kind=row.kind,
        category=row.category,
        phase=row.phase,
        severity=row.severity,
        error_type=row.error_type,
        error_code=row.error_code,
        error_message=row.error_message,
        retryable=row.retryable,
        attempt_number=row.attempt_number,
        retry_limit=row.retry_limit,
        will_retry=row.will_retry,
        recovered_at=row.recovered_at,
        task_id=row.task_id,
        task_attempt_id=row.task_attempt_id,
        llm_call_id=row.llm_call_id,
        conversation_round_id=row.conversation_round_id,
        process_run_id=row.process_run_id,
        agent_id=row.agent_id,
        run_uuid=row.run_uuid,
        driver_code=row.driver_code,
        provider_code=row.provider_code,
        model_code=row.model_code,
        tool_name=row.tool_name,
        tool_call_external_id=row.tool_call_external_id,
        occurred_at=row.occurred_at,
        created_at=row.created_at,
    )


def _incident_summary(row: FailureIncident) -> FailureIncidentSummaryRead:
    return FailureIncidentSummaryRead(
        id=row.id,
        kind=row.kind,
        recovered_at=row.recovered_at,
        occurred_at=row.occurred_at,
    )


@router.get("", response_model=FailureIncidentPage)
@authorize(privileges=[Privileges.INCIDENT_ACCESS, Privileges.INCIDENT_EDIT])
async def read_incidents(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    kind: Annotated[str | None, Query(max_length=20)] = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
    recovered: bool | None = None,
    search: Annotated[str | None, Query(max_length=300)] = None,
) -> FailureIncidentPage:
    rows, total = await service.list_incidents(
        page=page,
        page_size=page_size,
        kind=kind,
        category=category,
        recovered=recovered,
        search=search,
    )
    return FailureIncidentPage(
        items=[_incident_read(incident, pattern) for incident, pattern in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/patterns", response_model=FailurePatternPage)
@authorize(privileges=[Privileges.INCIDENT_ACCESS, Privileges.INCIDENT_EDIT])
async def read_patterns(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    pattern_status: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    kind: Annotated[str | None, Query(max_length=20)] = None,
    search: Annotated[str | None, Query(max_length=300)] = None,
) -> FailurePatternPage:
    rows, total = await service.list_patterns(
        page=page,
        page_size=page_size,
        status=pattern_status,
        kind=kind,
        search=search,
    )
    return FailurePatternPage(
        items=[FailurePatternRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/recent", response_model=FailureIncidentSummaryPage)
@authorize(privileges=[Privileges.INCIDENT_ACCESS, Privileges.INCIDENT_EDIT])
async def read_recent_incidents(
    page_size: Annotated[int, Query(ge=1, le=50)] = 5,
) -> FailureIncidentSummaryPage:
    """Return a small error log without messages, traces, or correlations."""

    rows, total = await service.list_incidents(page=1, page_size=page_size)
    return FailureIncidentSummaryPage(
        items=[_incident_summary(incident) for incident, _pattern in rows],
        total=total,
        page=1,
        page_size=page_size,
    )


@router.delete("/cleanup", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.INCIDENT_PURGE)
async def cleanup_incidents() -> None:
    """Permanently empty the durable failure journal."""

    await service.cleanup_all()
    return None


@router.get("/{incident_id}", response_model=FailureIncidentDetail)
@authorize(privileges=[Privileges.INCIDENT_ACCESS, Privileges.INCIDENT_EDIT])
async def read_incident(incident_id: UUID) -> FailureIncidentDetail:
    row = await service.get_incident(incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Failure incident not found")
    incident, pattern, trace = row
    return FailureIncidentDetail(
        **_incident_read(incident, pattern).model_dump(),
        pattern=FailurePatternRead.model_validate(pattern),
        trace_schema_version=trace.schema_version,
        trace=trace.payload,
        redacted_fields=trace.redacted_fields,
        truncated_fields=trace.truncated_fields,
        trace_content_hash=trace.content_hash,
        trace_byte_size=trace.byte_size,
    )


@router.patch("/patterns/{pattern_id}", response_model=FailurePatternRead)
@authorize(privileges=Privileges.INCIDENT_EDIT)
async def patch_pattern(
    pattern_id: UUID, data: FailurePatternUpdate
) -> FailurePatternRead:
    try:
        row = await service.update_pattern(pattern_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failure pattern not found",
        )
    return FailurePatternRead.model_validate(row)
