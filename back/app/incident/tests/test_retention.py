from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.incident import FailureEvent, FailureIncident, FailureIncidentTrace, FailurePattern, record_failure
from app.incident.retention import prune_traces
from core.params import runtime_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("preview", [True, False])
async def test_incident_retention_avoids_loading_discarded_payloads(db, monkeypatch, preview):
    import json
    from pathlib import Path
    import tracemalloc
    from sqlalchemy import update

    old = datetime.now(timezone.utc) - timedelta(days=60)
    ids = []
    for number in range(12):
        incident = await record_failure(db, FailureEvent(
            idempotency_key=f"synthetic-large-retention-{number}", kind="tool", error_type="SyntheticError",
            error_message="Synthetic recovered diagnostic", trace={"detail": "x" * 400000},
        ))
        ids.append(incident.id)
    await db.execute(update(FailureIncident).where(FailureIncident.id.in_(ids)).values(recovered_at=old))
    await db.execute(update(FailureIncidentTrace).where(FailureIncidentTrace.incident_id.in_(ids)).values(created_at=old))
    await db.commit()
    db.expunge_all()
    monkeypatch.setattr(runtime_settings, "INCIDENT_TRACE_RETENTION_DAYS", 30)
    tracemalloc.start()
    try:
        assert await prune_traces(preview=preview) == len(ids)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    traces = (await db.scalars(select(FailureIncidentTrace))).all()
    assert len(traces) == len(ids)
    assert all(trace.content_hash for trace in traces)
    assert all((trace.byte_size > 0) is preview for trace in traces)
    assert all((trace.payload == {"retention": "expired"}) is (not preview) for trace in traces)
    assert await db.scalar(select(func.sum(FailurePattern.occurrence_count))) == len(ids)
    destination = Path(__file__).resolve().parents[4] / f"artifacts/incident-retention-performance-{preview}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"incidents": len(ids), "preview": preview,
        "logical_detail_bytes": 400000 * len(ids), "python_peak_bytes": peak}, indent=2) + "\n")
    assert peak < 4 * 1024 * 1024, f"Incident retention allocated {peak} bytes to discard traces"


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
