"""Audit counterexamples: assertions describe defects, not desired behavior."""
import asyncio
import threading

import pytest
from sqlalchemy import select

from app.multimedia.tests.test_multimedia import media_agent, _run
from app.multimedia.engine import MultimediaEngine
from app.multimedia.models import MediaOutputReceipt
from app.llm import MediaArtifact, MediaResult
from app.process.interface import engine_checkpoint
from app.memory.storage import NativeFileStorage
from core.util.byte_budget import ByteBudget
from core.runtime import RuntimeComponent, RuntimeSupervisor


@pytest.mark.asyncio
async def test_media_delivery_budget_cannot_compose():
    budget = ByteBudget(1024 * 1024 * 1024)
    async with budget.reserve(800_000_000, owner="media:1"):
        with pytest.raises(TimeoutError):
            async with budget.reserve(3 * 100_000_000, owner="telegram:1:room", timeout=0.02):
                pytest.fail("nested allocation unexpectedly admitted")
    assert budget.used == 0


@pytest.mark.asyncio
async def test_late_provider_error_overwrites_saved_success(db, media_agent):
    run, reference = await _run(db, media_agent)
    engine = MultimediaEngine()
    await engine._receive(run.id, MediaResult("success", artifacts=(
        MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),
    )))
    await engine._receive(run.id, MediaResult("error", error="stale provider response"))
    state = await engine_checkpoint(run.id, "multimedia")
    assert state["metadata"]["provider_state"] == "error"
    assert await db.scalar(select(MediaOutputReceipt.id).where(MediaOutputReceipt.run_id == run.id))
    result = await engine.get_run(reference)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_cancelled_native_create_leaves_unreported_resource(tmp_path, monkeypatch):
    storage = NativeFileStorage(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = storage._atomic_write

    def delayed(path, content):
        entered.set()
        assert release.wait(5)
        try:
            original(path, content)
        finally:
            finished.set()

    monkeypatch.setattr(storage, "_atomic_write", delayed)
    operation = asyncio.create_task(storage.create(b"private orphan"))
    assert await asyncio.to_thread(entered.wait, 5)
    operation.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert not finished.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    resources = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(resources) == 1 and resources[0].read_bytes() == b"private orphan"


@pytest.mark.asyncio
async def test_optional_root_can_block_later_critical_start():
    started = []
    async def hang():
        await asyncio.Event().wait()
    async def critical():
        started.append("critical")
    async def stop():
        pass
    supervisor = RuntimeSupervisor()
    supervisor.configure([
        RuntimeComponent("optional", hang, stop, lambda: False, critical=False),
        RuntimeComponent("critical", critical, stop, lambda: bool(started)),
    ])
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(supervisor.start(), 0.02)
    assert started == []
    await supervisor.stop()


def test_calendar_limit_is_checked_after_expanding_all_occurrences(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from bridge.calendar import ical
    content = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:audit\r\nDTSTART:20260907T000000Z\r\nDTEND:20260907T000001Z\r\nRRULE:FREQ=SECONDLY;COUNT=5000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    original = ical.recurring_ical_events.of
    expanded = []
    def observe(*args, **kwargs):
        query = original(*args, **kwargs)
        def between(*bounds):
            result = query.between(*bounds)
            expanded.append(len(result))
            return result
        return SimpleNamespace(between=between)
    monkeypatch.setattr(ical.recurring_ical_events, "of", observe)
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="1000"):
        ical.events_between(content, start, start + timedelta(seconds=5000))
    assert expanded == [5000]


@pytest.mark.asyncio
@pytest.mark.parametrize("intervention", ["cancel", "replace_lease"])
async def test_lab_late_result_ignores_concurrent_control(db, monkeypatch, intervention):
    from uuid import uuid4
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sqlalchemy import update
    from core.database.database import AsyncSessionLocal
    from app.lab.models import LabEvaluationDataset, LabEvaluationCase, LabEvaluationRun
    from app.lab import mechanism_evaluation_service as service

    dataset = LabEvaluationDataset(name=f"audit-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    case = LabEvaluationCase(dataset_id=dataset.id, name="case")
    db.add(case)
    await db.flush()
    run = LabEvaluationRun(dataset_id=dataset.id, total_cases=1, case_snapshots=[{
        "id": str(case.id), "input_data": "test", "expected_output": {"result": "ok", "choices": []},
    }])
    db.add(run)
    await db.commit()
    run_id, replacement = run.id, uuid4()
    monkeypatch.setattr(service.llm_service, "get_llm", AsyncMock(return_value=SimpleNamespace()))
    async def evaluate(*args, **kwargs):
        async with AsyncSessionLocal() as independent:
            values = {"cancel_requested": True} if intervention == "cancel" else {"lease_token": replacement}
            await independent.execute(update(LabEvaluationRun).where(LabEvaluationRun.id == run_id).values(**values))
            await independent.commit()
        return {"result": "ok", "choices": []}, 0.1
    monkeypatch.setattr(service, "evaluate_mechanism", evaluate)
    assert await service.process_runs() == 1
    await db.refresh(run)
    assert run.completed_cases == 1 and run.status == "partial"
    if intervention == "cancel":
        assert run.cancel_requested is True
    else:
        assert run.lease_token is None


def test_atlas_log_scrubber_does_not_mask_encoded_password(monkeypatch):
    from core.dbadmin._internal import atlas
    from sqlalchemy.engine import make_url
    fake_secret = "audit-only@reserved:slash/value"
    monkeypatch.setattr(atlas.settings, "POSTGRES_PASSWORD", fake_secret)
    rendered = atlas._atlas_database_url("public")
    scrubbed = atlas._scrub(rendered)
    assert fake_secret not in rendered
    assert make_url(scrubbed).password == fake_secret
