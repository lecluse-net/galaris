from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent.models import Agent, Title
from app.process import process_service as service
from app.process.engine import ProcessEngineError
from app.process.models import ProcessDefinition, ProcessRun, ProcessRunEvent, ProcessStartJob
from app.process.schemas import EngineError, EngineRunSnapshot, ProcessCallbackEvent
from app.task import collab, task_service
from app.task.models import Task, TaskStatus
from app.tools.models import Tool


@pytest_asyncio.fixture
async def waiting_run(db, monkeypatch):
    from app.task import runner

    monkeypatch.setattr(runner, "go_next", lambda *args, **kwargs: None)
    title = Title(label="Recovery", gender="X")
    tool = Tool(code=f"recovery-{uuid4().hex}", label="Recovery", connection_schema={})
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(title_id=title.id, code=f"recovery-{uuid4().hex}", first_name="Recovery", last_name="Test")
    db.add(agent)
    await db.flush()
    definition = ProcessDefinition(agent_id=agent.id, tool_id=tool.id, engine_process_id="recovery", label="Recovery")
    parent = Task(label="Parent", agent_id=agent.id, status=TaskStatus.DISPATCH, paused=True, data={"pause_reasons": ["await"]})
    db.add_all([definition, parent])
    await db.flush()
    run = ProcessRun(
        process_id=definition.id, launcher_agent_id=agent.id, engine_code="fake",
        correlation_id=uuid4().hex, callback_token="token", status="running",
        engine_run_id="remote", launch_snapshot={"workflow_id": "recovery"}, task_id=parent.id,
    )
    db.add(run)
    await db.commit()
    child = await collab.dispatch_process_wait(parent=parent, run_id=run.id, process_label="Recovery", timeout_seconds=600)
    run.await_task_id = child.id
    await db.commit()
    return run, parent, child


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["success", "error", "cancelled"])
async def test_callback_completion_resumes_wait_once_and_survives_redelivery(
    db, waiting_run, terminal_status,
):
    """The provider receipt, durable result and waiting Task agree after replay."""
    run, parent, child = waiting_run
    event = ProcessCallbackEvent(
        event_id="completion", status=terminal_status, engine_run_id="remote",
        output={"report": "Original result"},
        error=EngineError(code="provider_failure", message="Provider failed")
        if terminal_status == "error" else None,
    )
    event_count = await db.scalar(
        select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.run_id == run.id)
    )
    with pytest.raises(PermissionError):
        await service.receive_callback(run.id, "wrong-token", event)
    await db.refresh(run)
    assert run.status == "running"
    assert parent.paused
    assert await db.scalar(
        select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.run_id == run.id)
    ) == event_count

    _, duplicate = await service.receive_callback(run.id, "token", event)
    assert not duplicate
    await db.refresh(run)
    await db.refresh(child)
    await db.refresh(parent)
    assert run.status == terminal_status
    assert run.output == {"report": "Original result"}
    assert run.engine_run_id == "remote"
    assert run.error_code == ("provider_failure" if terminal_status == "error" else None)
    assert run.error_message == ("Provider failed" if terminal_status == "error" else None)
    assert child.status == (TaskStatus.SUCCESS if terminal_status == "success" else TaskStatus.ERROR)
    assert not parent.paused
    resolved_at = run.await_resolved_at
    assert resolved_at is not None
    original = (run.status, run.output, run.error_code, run.error_message, run.engine_run_id)
    child_result = (child.status, child.feedback, child.execution_result)

    # Duplicate identities and new but late provider events must both preserve
    # the result. The real journal and SQL constraints participate in this test.
    for event_id, status, expected_duplicate in [
        ("completion", "running", True),
        ("late-progress", "running", False),
        ("late-success", "success", False),
        ("late-error", "error", False),
        ("late-cancel", "cancelled", False),
    ]:
        replay = ProcessCallbackEvent(
            event_id=event_id, status=status, engine_run_id="wrong-execution",
            output={"report": "Must not replace"},
            error=EngineError(code="late", message="Must not replace"),
        )
        try:
            _, duplicate = await service.receive_callback(run.id, "token", replay)
        except Exception as error:
            pytest.fail(f"An authenticated callback replay must remain usable: {type(error).__name__}")
        assert duplicate is expected_duplicate
        await db.refresh(run)
        await db.refresh(child)
        await db.refresh(parent)
        assert (run.status, run.output, run.error_code, run.error_message, run.engine_run_id) == original
        assert run.await_resolved_at == resolved_at
        assert (child.status, child.feedback, child.execution_result) == child_result
        assert not parent.paused
    assert await db.scalar(
        select(func.count()).select_from(ProcessRunEvent).where(
            ProcessRunEvent.run_id == run.id, ProcessRunEvent.event_id == "completion",
        )
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queued", "unsupported", "confirmed", "remote_unsupported"])
async def test_every_cancel_path_resolves_wait(db, monkeypatch, waiting_run, mode):
    run, parent, child = waiting_run
    engine = SimpleNamespace(
        supports_cancel=mode != "unsupported",
        cancel_run=AsyncMock(return_value=EngineRunSnapshot(status="cancelled")),
    )
    if mode == "remote_unsupported":
        engine.cancel_run.side_effect = ProcessEngineError("cancel_unsupported", "Unsupported")
    monkeypatch.setattr(service.registry, "get", lambda _: engine)
    if mode == "queued":
        run.status = "queued"
        db.add(ProcessStartJob(run_id=run.id, status="pending"))
        await db.commit()
    await service.cancel_run(run.id)
    assert run.status == "cancelled"
    assert child.status == TaskStatus.ERROR
    assert parent.paused is False
    assert run.await_resolved_at is not None


@pytest.mark.asyncio
async def test_refresh_failure_does_not_invent_remote_failure(db, waiting_run):
    run, parent, child = waiting_run
    await service._record_refresh_failure(run.id, ProcessEngineError("gone", "Gone", retryable=False))
    assert run.status == "unknown"
    assert child.status != TaskStatus.ERROR
    assert parent.paused
    assert run.await_resolved_at is None


@pytest.mark.asyncio
async def test_local_admission_does_not_consume_provider_attempt(db, monkeypatch, waiting_run):
    from core.util import BufferedAdmissionDeferred
    from core.params import runtime_settings
    run, _parent, _child = waiting_run
    run.status = "queued"
    job = ProcessStartJob(run_id=run.id, status="pending", attempts=runtime_settings.PROCESS_START_MAX_RETRIES)
    db.add(job)
    await db.commit()
    before = job.attempts
    engine = SimpleNamespace(start_run=AsyncMock(side_effect=BufferedAdmissionDeferred("local capacity")))
    monkeypatch.setattr(service.registry, "get", lambda _: engine)
    assert await service.process_start_jobs(batch_size=1, engine_code=run.engine_code) == 1
    await db.refresh(job)
    await db.refresh(run)
    assert job.attempts == before and job.status == "pending"
    assert run.status == "queued" and job.locked_at is None


@pytest.mark.asyncio
async def test_success_can_be_recovered_after_long_observation_outage(db, monkeypatch, waiting_run):
    run, parent, child = waiting_run
    for _ in range(12):
        await service._record_refresh_failure(run.id, ProcessEngineError("timeout", "Unavailable", retryable=True))
    assert run.status == "unknown" and run.finished_at is None
    assert run.engine_run_id == "remote"
    engine = SimpleNamespace(get_run=AsyncMock(return_value=EngineRunSnapshot(status="success", output={"receipt": "kept"})))
    monkeypatch.setattr(service.registry, "get", lambda _: engine)
    await service.refresh_run(run.id)
    assert run.status == "success"
    assert run.error_code is None
    assert child.status == TaskStatus.SUCCESS
    assert not parent.paused
    assert engine.get_run.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", ["callback", "scheduler", "refresh"])
async def test_terminal_commit_is_reconciled_without_reexecuting_engine(db, monkeypatch, waiting_run, recovery):
    run, parent, child = waiting_run
    original = collab.resolve_process_await
    monkeypatch.setattr(collab, "resolve_process_await", AsyncMock(side_effect=RuntimeError("interrupted")))
    event = ProcessCallbackEvent(event_id="done", status="success", output={"ok": True})
    with pytest.raises(RuntimeError):
        await service.receive_callback(run.id, "token", event)
    assert run.status == "success" and run.await_resolved_at is None
    monkeypatch.setattr(collab, "resolve_process_await", original)
    if recovery == "callback":
        _, duplicate = await service.receive_callback(run.id, "token", event)
        assert duplicate
    elif recovery == "scheduler":
        await service.refresh_active_runs()
    else:
        await service.refresh_run(run.id)
    assert child.status == TaskStatus.SUCCESS
    assert not parent.paused
    assert run.await_resolved_at is not None


@pytest.mark.asyncio
async def test_child_commit_before_fan_in_can_be_replayed(db, monkeypatch, waiting_run):
    run, parent, child = waiting_run
    original = collab.maybe_fan_in
    monkeypatch.setattr(collab, "maybe_fan_in", AsyncMock(side_effect=RuntimeError("interrupted")))
    event = ProcessCallbackEvent(event_id="done", status="success")
    with pytest.raises(RuntimeError):
        await service.receive_callback(run.id, "token", event)
    assert child.status == TaskStatus.SUCCESS and parent.paused
    monkeypatch.setattr(collab, "maybe_fan_in", original)
    await service.receive_callback(run.id, "token", event)
    assert not parent.paused
    assert run.await_resolved_at is not None


@pytest.mark.asyncio
async def test_cancelling_run_is_still_polled(db, monkeypatch, waiting_run):
    run, parent, child = waiting_run
    monkeypatch.setattr(service.runtime_settings, "PROCESS_REFRESH_STALENESS_SECONDS", 0)
    engine = SimpleNamespace(
        supports_cancel=True,
        cancel_run=AsyncMock(side_effect=OSError("connection lost")),
        get_run=AsyncMock(return_value=EngineRunSnapshot(status="cancelled")),
    )
    monkeypatch.setattr(service.registry, "get", lambda _: engine)
    with pytest.raises(OSError):
        await service.cancel_run(run.id)
    assert run.status == "cancelling"
    assert await service.refresh_active_runs() == 1
    assert run.status == "cancelled" and child.status == TaskStatus.ERROR
    assert not parent.paused


@pytest.mark.asyncio
async def test_retention_protects_waiters_and_active_owners_before_preview_and_purge(db, monkeypatch, waiting_run):
    from app.conversation.facade import register_runtime
    from app.process.models import ProcessRunEvent
    from app.process import retention
    from sqlalchemy import select

    monkeypatch.setattr(retention, "_guards", {})
    register_runtime()
    for name in ("RAW_SNAPSHOT", "EVENTS", "OUTPUT", "RUN"):
        monkeypatch.setattr(service.runtime_settings, f"PROCESS_RETENTION_{name}_DAYS", 1)
    run, parent, child = waiting_run
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc) - timedelta(days=10)
    run.output = {"result": "needed"}
    run.raw_snapshot = {"receipt": "needed"}
    event = ProcessRunEvent(run_id=run.id, source="engine", event_type="completed", created_at=run.finished_at)
    db.add(event)
    await db.commit()
    assert not any((await service.purge_retention()).values())
    run.await_resolved_at = datetime.now(timezone.utc)
    child.status = TaskStatus.SUCCESS
    await db.commit()
    assert not any((await service.purge_retention()).values())
    parent.status = TaskStatus.SUCCESS
    await db.commit()
    expected = {"raw_snapshot": 1, "events": 1, "output": 1, "runs": 1}
    assert await service.purge_retention(preview=True) == expected
    assert run.output == {"result": "needed"}
    assert await db.scalar(select(ProcessRunEvent.id).where(ProcessRunEvent.id == event.id))
    identifier = run.id
    assert await service.purge_retention() == expected
    assert await db.scalar(select(ProcessRun.id).where(ProcessRun.id == identifier)) is None


@pytest.mark.asyncio
async def test_retention_filters_consumers_before_batch_limit(db, monkeypatch, waiting_run):
    from app.process import retention
    from sqlalchemy import select

    run, parent, _child = waiting_run
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc) - timedelta(days=10)
    run.await_resolved_at = datetime.now(timezone.utc)
    run.task_id = None
    run.output = {"protected": True}
    other = ProcessRun(process_id=run.process_id, launcher_agent_id=run.launcher_agent_id,
        engine_code="fake", correlation_id=uuid4().hex, callback_token="token",
        status="success", finished_at=run.finished_at + timedelta(days=1), output={"old": True})
    db.add(other)
    await db.commit()
    monkeypatch.setattr(retention, "_guards", {"test": lambda: select(ProcessRun.id).where(ProcessRun.id == run.id)})
    for name in ("RAW_SNAPSHOT", "EVENTS", "RUN"):
        monkeypatch.setattr(service.runtime_settings, f"PROCESS_RETENTION_{name}_DAYS", 0)
    monkeypatch.setattr(service.runtime_settings, "PROCESS_RETENTION_OUTPUT_DAYS", 1)
    assert (await service.purge_retention(batch_size=1))["output"] == 1
    assert run.output == {"protected": True} and other.output is None
    assert not any((await service.purge_retention(batch_size=1)).values())


@pytest.mark.asyncio
async def test_llm_trace_waits_for_process_consumer_release(db, monkeypatch, waiting_run):
    from sqlalchemy import false, select
    from app.llm import retention as traces
    from app.llm.models import LLMCall
    from app.process import retention

    run, parent, child = waiting_run
    old = datetime.now(timezone.utc) - timedelta(days=60)
    run.status = "success"
    run.finished_at = old
    call = LLMCall(process_run_id=run.id, status="completed", completed_at=old,
                   updated_at=old, prompt="provider proof", cost=0.75)
    db.add(call)
    await db.flush()
    monkeypatch.setattr(traces, "_releases", {"process_run": retention.released_trace_ids})
    monkeypatch.setattr(retention, "_guards", {"pending": lambda: select(ProcessRun.id).where(ProcessRun.id == run.id)})
    monkeypatch.setattr(service.runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    assert await traces.prune_traces() == 0
    run.await_resolved_at = datetime.now(timezone.utc)
    parent.status = child.status = TaskStatus.SUCCESS
    await db.flush()
    assert await traces.prune_traces() == 0
    monkeypatch.setattr(retention, "_guards", {"released": lambda: select(ProcessRun.id).where(false())})
    assert await traces.prune_traces() == 1
    assert call.prompt == "" and call.cost == 0.75


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [{"version": 2}, {"files": "invalid"}, {"input": []}, {"files": [{}]}])
async def test_invalid_launch_isolated_before_external_effect(db, waiting_run, monkeypatch, invalid):
    from app.process.schemas import EngineStartResult
    run, _, _ = waiting_run
    run.status = "queued"
    run.launch_snapshot = invalid
    healthy = ProcessRun(process_id=run.process_id, launcher_agent_id=run.launcher_agent_id,
        engine_code=run.engine_code, correlation_id=uuid4().hex, callback_token="healthy", status="queued",
        launch_snapshot={"input": None, "files": None})
    db.add(healthy); await db.flush()
    first = ProcessStartJob(run_id=run.id)
    second = ProcessStartJob(run_id=healthy.id)
    db.add_all([first, second]); await db.commit()
    engine = SimpleNamespace(start_run=AsyncMock(return_value=EngineStartResult(accepted=True, engine_run_id="healthy-remote")))
    monkeypatch.setattr(service.registry, "get", lambda _: engine)
    assert await service.process_start_jobs(batch_size=2, engine_code=run.engine_code) == 2
    assert first.status == "failed" and run.error_code == "invalid_launch_snapshot"
    assert second.status == "done" and healthy.status == "running"
    assert engine.start_run.await_count == 1
    assert engine.start_run.call_args.args[2].launch_snapshot["version"] == 1


@pytest.mark.asyncio
async def test_export_is_paged_redacted_and_does_not_mutate_source(db, waiting_run):
    from app.process.export import export_run
    from app.process.models import ProcessRunEvent
    run, _, _ = waiting_run
    run.launch_snapshot = {"files": [{"download_url": "capability-secret"}], "future_field": "kept"}
    run.raw_snapshot = {"token": "provider-secret", "receipt": "safe"}
    db.add_all([ProcessRunEvent(run_id=run.id, source="test", event_type="progress", payload={"index": i}) for i in range(12)])
    await db.commit()
    first = await export_run(run.id, page_size=10)
    second = await export_run(run.id, page_size=10, after_event=first["next_event"])
    ids = [event["id"] for event in first["events"] + second["events"]]
    assert len(ids) == len(set(ids)) == 12 and second["next_event"] is None
    assert first["raw_snapshot"] == {"token": "***", "receipt": "safe"}
    assert first["launch_snapshot"]["files"][0]["download_url"] == "***"
    assert "callback_token" not in first["run"]
    assert run.raw_snapshot["token"] == "provider-secret"


@pytest.mark.asyncio
async def test_invalid_optional_backoff_does_not_make_run_unrecoverable(db, waiting_run, monkeypatch):
    run, _, _ = waiting_run
    run.engine_metadata = {"refresh_failures": "old-invalid-value"}
    await db.commit()
    await service._record_refresh_failure(run.id, ProcessEngineError("timeout", "Unavailable", retryable=True))
    assert run.engine_metadata["refresh_failures"] == 1
    run.engine_metadata = {**run.engine_metadata, "next_refresh_at": "zzz-invalid-date"}
    run.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db.commit()
    refresh = AsyncMock(return_value=run)
    monkeypatch.setattr(service, "refresh_run", refresh)
    assert await service.refresh_active_runs(engine_code=run.engine_code) == 1
    refresh.assert_awaited_once_with(run.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [0, 7, 42, 20260911])
async def test_generated_callback_sequences_preserve_first_terminal_result(db, waiting_run, seed):
    """Vary ordering, repeated identities and invalid credentials against real persistence."""
    import random

    random_source = random.Random(seed)
    run, parent, child = waiting_run
    seen = set()
    terminal = None
    history = []
    for index in range(24):
        event_id = str(random_source.randrange(12))
        status = random_source.choice(["running", "waiting", "success", "error", "cancelled"])
        valid = index % 5 != 0
        history.append((event_id, status, valid))
        before = (run.status, run.output, run.engine_run_id, run.await_resolved_at)
        event = ProcessCallbackEvent(event_id=event_id, status=status, output={"sequence": index})
        if not valid:
            with pytest.raises(PermissionError):
                await service.receive_callback(run.id, "invalid", event)
            await db.refresh(run)
            assert (run.status, run.output, run.engine_run_id, run.await_resolved_at) == before, (seed, history)
        else:
            _, duplicate = await service.receive_callback(run.id, "token", event)
            assert duplicate == (event_id in seen), (seed, history)
            if terminal is None and event_id not in seen and status in {"success", "error", "cancelled"}:
                terminal = (status, {"sequence": index})
            seen.add(event_id)
            await db.refresh(run)
            await db.refresh(parent)
            await db.refresh(child)
            if terminal is not None:
                assert (run.status, run.output) == terminal, (seed, history)
                assert run.await_resolved_at is not None and not parent.paused, (seed, history)
                assert child.status == (TaskStatus.SUCCESS if terminal[0] == "success" else TaskStatus.ERROR)
        persisted = list(await db.scalars(select(ProcessRunEvent.event_id).where(
            ProcessRunEvent.run_id == run.id, ProcessRunEvent.event_id.is_not(None))))
        assert len(persisted) == len(set(persisted)) == len(seen), (seed, history)
    assert terminal is not None, "The fixed corpus must exercise a terminal outcome"
