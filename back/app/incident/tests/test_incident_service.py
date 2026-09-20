"""Persistence and grouping guarantees for the failure journal."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incident.contracts import FailureEvent
from app.incident.models import FailureIncident, FailureIncidentTrace, FailurePattern
from app.incident.schemas import FailurePatternUpdate
from app.incident import service


@pytest.mark.asyncio
async def test_record_failure_is_idempotent_and_redacts_secrets(
    db: AsyncSession,
) -> None:
    run_uuid = uuid4()
    event = FailureEvent(
        idempotency_key="tool-call:run:call-1",
        kind="tool",
        error_type="RetryPromptPart",
        error_message="Invalid section",
        run_uuid=run_uuid,
        tool_name="skill_galaris_read_file",
        tool_call_external_id="call-1",
        trace={
            "arguments": {"section": "missing", "authorization": "Bearer secret"},
            "error": "Authorization: Bearer another-secret",
        },
    )

    first = await service.record_failure(db, event)
    second = await service.record_failure(
        db,
        event.model_copy(update={"retry_limit": 3}),
    )
    await db.commit()

    assert second.id == first.id
    assert second.retry_limit == 3
    assert await db.scalar(select(func.count(FailureIncident.id))) == 1
    pattern = await db.get(FailurePattern, first.pattern_id)
    trace = await db.get(FailureIncidentTrace, first.id)
    assert pattern is not None
    assert pattern.occurrence_count == 1
    assert trace is not None
    assert trace.payload["arguments"]["authorization"] == "[REDACTED]"
    assert "another-secret" not in str(trace.payload)
    assert "$.arguments.authorization" in trace.redacted_fields


@pytest.mark.asyncio
async def test_new_occurrence_reopens_resolved_pattern_as_regression(
    db: AsyncSession,
) -> None:
    first = await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="llm-call:first",
            kind="llm",
            error_type="UnexpectedModelBehavior",
            error_message="Tool exceeded max retries count of 2",
            model_code="model",
        ),
    )
    await db.commit()
    updated = await service.update_pattern(
        first.pattern_id,
        FailurePatternUpdate(
            status="resolved",
            remediation="Validate skill sections before calling the tool.",
        ),
    )
    assert updated is not None
    assert updated.resolved_at is not None

    second = await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="llm-call:second",
            kind="llm",
            error_type="UnexpectedModelBehavior",
            error_message="Tool exceeded max retries count of 2",
            model_code="model",
        ),
    )
    await db.commit()
    pattern = await db.get(FailurePattern, second.pattern_id)
    assert pattern is not None
    await db.refresh(pattern)

    assert second.pattern_id == first.pattern_id
    assert pattern.status == "regression"
    assert pattern.occurrence_count == 2
    assert pattern.resolved_at is None


@pytest.mark.asyncio
async def test_error_references_do_not_fragment_failure_patterns(
    db: AsyncSession,
) -> None:
    first = await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="tool-call:first-reference",
            kind="tool",
            error_type="ValueError",
            error_message=(
                "Tool 'task_get' failed.\nTechnical type: ValueError.\n"
                "Error reference: 0123456789ab"
            ),
            tool_name="task_get",
        ),
    )
    second = await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="tool-call:second-reference",
            kind="tool",
            error_type="ValueError",
            error_message=(
                "Tool 'task_get' failed.\nTechnical type: ValueError.\n"
                "Error reference: fedcba987654"
            ),
            tool_name="task_get",
        ),
    )
    await db.commit()

    assert second.pattern_id == first.pattern_id
    pattern = await db.get(FailurePattern, first.pattern_id)
    assert pattern is not None
    assert pattern.fingerprint_version == 2
    assert pattern.occurrence_count == 2


@pytest.mark.asyncio
async def test_successful_run_marks_prior_failures_recovered(
    db: AsyncSession,
) -> None:
    run_uuid = uuid4()
    incident = await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="tool-call:recoverable",
            kind="tool",
            error_type="ModelRetry",
            error_message="Correct the arguments",
            run_uuid=run_uuid,
            will_retry=True,
        ),
    )
    await db.commit()

    assert await service.mark_run_recovered(run_uuid) == 1
    await db.commit()
    await db.refresh(incident)
    assert incident.recovered_at is not None


@pytest.mark.asyncio
async def test_cleanup_all_empties_incidents_traces_and_patterns(
    db: AsyncSession,
) -> None:
    await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="cleanup:tool",
            kind="tool",
            error_type="ToolError",
            error_message="Tool failed",
        ),
    )
    await service.record_failure(
        db,
        FailureEvent(
            idempotency_key="cleanup:llm",
            kind="llm",
            error_type="ModelError",
            error_message="Model failed",
        ),
    )
    await db.commit()

    await service.cleanup_all()
    await service.cleanup_all()

    assert await db.scalar(select(func.count(FailureIncidentTrace.incident_id))) == 0
    assert await db.scalar(select(func.count(FailureIncident.id))) == 0
    assert await db.scalar(select(func.count(FailurePattern.id))) == 0
