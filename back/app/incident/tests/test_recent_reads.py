"""Compact recent incidents must not transfer detailed errors or pattern diagnoses."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect

from app.incident import router, service
from app.incident.models import FailureIncident, FailureIncidentTrace, FailurePattern


@pytest.mark.asyncio
async def test_recent_read_is_compact_and_preserves_full_journal_details(db):
    now = datetime.now(timezone.utc)
    pattern = FailurePattern(fingerprint="synthetic-recent-read", kind="tool", category="unexpected",
                             title="Synthetic failure", diagnosis="synthetic diagnosis " * 20000,
                             first_seen_at=now, last_seen_at=now)
    db.add(pattern)
    await db.flush()
    incidents = [FailureIncident(id=uuid4(), pattern_id=pattern.id, idempotency_key=f"synthetic-recent-{index}",
                                kind="tool", category="unexpected", phase="execute", severity="error",
                                error_type="SyntheticError", error_message="synthetic error " * 10000,
                                occurred_at=now - timedelta(minutes=index // 2),
                                recovered_at=now if index % 2 == 0 else None) for index in range(64)]
    db.add_all(incidents)
    await db.commit()
    expected = sorted(incidents, key=lambda row: (row.occurred_at, row.id), reverse=True)
    expected_items = [{"id": row.id, "kind": row.kind, "occurred_at": row.occurred_at,
                       "recovered_at": row.recovered_at} for row in expected]
    latest_id = expected[0].id
    full_error = expected[0].error_message
    diagnosis = pattern.diagnosis
    db.add(FailureIncidentTrace(incident_id=latest_id, payload={"synthetic": True},
                                content_hash="0" * 64, byte_size=19))
    await db.commit()
    db.expunge_all()
    connection = await db.connection()
    statements = []
    loaded_bytes = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    def loaded(_session, instance):
        if isinstance(instance, FailurePattern):
            loaded_bytes.append(len(instance.diagnosis.encode()))
        elif isinstance(instance, FailureIncident) and "error_message" not in inspect(instance).unloaded:
            loaded_bytes.append(len(instance.error_message.encode()))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    event.listen(db.sync_session, "loaded_as_persistent", loaded)
    try:
        page = await router.read_recent_incidents(page_size=50)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
        event.remove(db.sync_session, "loaded_as_persistent", loaded)
    assert page.total == 64 and page.page == 1 and page.page_size == 50
    assert [item.model_dump() for item in page.items] == expected_items[:50]
    default = await router.read_recent_incidents()
    assert [item.model_dump() for item in default.items] == expected_items[:5]
    detail = await service.get_incident(latest_id)
    assert detail is not None
    assert detail[0].error_message == full_error and detail[1].diagnosis == diagnosis

    report = {"items": len(page.items), "queries": len(statements), "loaded_detail_bytes": sum(loaded_bytes)}
    destination = Path(__file__).resolve().parents[4] / "artifacts/recent-incident-performance.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    assert report["queries"] <= 2
    assert report["loaded_detail_bytes"] == 0, report
