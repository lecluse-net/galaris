from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.incident import FailureEvent, FailureIncident, FailureIncidentTrace, FailurePattern, record_failure
from app.incident.retention import prune_traces
from core.params import runtime_settings


@pytest.mark.asyncio
async def test_retention_is_opt_in_bounded_and_keeps_unresolved_incidents(db, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(days=60)
    records = []
    for index in range(3):
        incident = await record_failure(db, FailureEvent(
            idempotency_key=f"retention-{index}", kind="tool", error_type="ValueError",
            error_message="failure", trace={"large": "x" * 10_000},
        ))
        trace = await db.get(FailureIncidentTrace, incident.id)
        trace.created_at = old
        if index < 2:
            incident.recovered_at = old
        records.append((incident, trace))
    await db.flush()
    monkeypatch.setattr(runtime_settings, "INCIDENT_TRACE_RETENTION_DAYS", 0)
    assert await prune_traces() == 0
    monkeypatch.setattr(runtime_settings, "INCIDENT_TRACE_RETENTION_DAYS", 30)
    assert await prune_traces(preview=True) == 2
    assert all(trace.byte_size > 0 for _, trace in records)
    assert await prune_traces(batch_size=1) == 1
    assert await prune_traces() == 1
    assert await prune_traces() == 0
    assert records[2][1].payload["large"]
    assert await db.scalar(select(func.count(FailureIncident.id))) == 3
    assert await db.scalar(select(func.sum(FailurePattern.occurrence_count))) == 3
    assert all(trace.content_hash for _, trace in records)
    await record_failure(db, FailureEvent(
        idempotency_key="retention-0", kind="tool", error_message="failure",
        trace={"late_observation": "Must not resurrect expired details"},
    ))
    await db.refresh(records[0][1])
    assert records[0][1].payload == {"retention": "expired"}
    assert records[0][1].byte_size == 0
