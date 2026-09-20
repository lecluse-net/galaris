"""Durable process workflows, with only the remote engine replaced."""

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
from app.process.schemas import (
    EngineError, EngineRunSnapshot, EngineStartResult, ProcessCallbackEvent,
    ProcessDefinitionCreate, ProcessDefinitionUpdate,
    ProcessFileInput,
)
from app.task.models import Task, TaskStatus
from app.tools.models import Tool


@pytest_asyncio.fixture
async def workflow(db, monkeypatch):
    title = Title(label="Process workflows", gender="X")
    tool = Tool(code="fake", label="Remote workflows", connection_schema={})
    db.add_all([title, tool])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"workflow-{uuid4().hex}", first_name=name, last_name="Test")
              for name in ("Owner", "Other")]
    db.add_all(agents)
    await db.flush()
    engine = SimpleNamespace(
        supports_cancel=True,
        start_run=AsyncMock(return_value=EngineStartResult(accepted=True, engine_run_id="remote")),
        get_run=AsyncMock(return_value=EngineRunSnapshot(status="running")),
        cancel_run=AsyncMock(return_value=EngineRunSnapshot(status="cancelled")),
    )
    monkeypatch.setattr(service.registry, "get", lambda code: engine)
    definition = await service.create_definition(ProcessDefinitionCreate(
        agent_id=agents[0].id, tool_id=tool.id, engine_process_id="report", label="Quarterly report",
    ))
    return SimpleNamespace(owner=agents[0], other=agents[1], tool=tool, definition=definition, engine=engine)


async def start(workflow, **options):
    return await service.start_process(agent_id=workflow.owner.id, workflow_id="report", input_data={"period": "Q1"}, **options)


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["root", "descendant", "wait"])
@pytest.mark.parametrize("status, remote_may_continue, deleted, blocked", [
    ("queued", False, False, True), ("running", False, False, True),
    ("cancelled", True, False, True), ("cancelled", True, True, True),
    ("cancelled", False, False, False),
    ("success", False, False, False), ("error", False, False, False),
])
async def test_replacement_uses_process_evidence_even_without_a_task_wait(
    db, workflow, monkeypatch, link, status, remote_may_continue, deleted, blocked,
):
    from app.process import replacement_blocked_task_ids
    from app.task import replacement, task_service

    monkeypatch.setattr(replacement, "_blockers", {})
    replacement.register_replacement_blocker("process", replacement_blocked_task_ids)
    original = Task(id=uuid4(), label="Original", objective="<p>Prepare a report.</p>",
                    agent_id=workflow.owner.id, status=TaskStatus.CREATE)
    unrelated = Task(id=uuid4(), label="Independent", agent_id=workflow.owner.id, status=TaskStatus.CREATE)
    db.add_all([original, unrelated])
    await db.commit()
    owner = original
    if link != "root":
        owner = Task(id=uuid4(), label="Finished descendant", parent_id=original.id,
                     agent_id=workflow.owner.id, status=TaskStatus.SUCCESS)
        db.add(owner)
        await db.commit()
    admitted = await start(workflow, task_id=owner.id if link != "wait" else unrelated.id)
    run = await service.get_run(admitted.run_id)
    if link == "wait":
        run.task_id = None
        run.await_task_id = owner.id
    run.status = status
    run.engine_metadata = {"remote_may_continue": remote_may_continue}
    if deleted:
        run.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    successor = Task(id=uuid4(), label="Successor", objective="<p>Prepare another report.</p>",
                     agent_id=workflow.owner.id, status=TaskStatus.CREATE)
    before = original.revision
    if blocked:
        with pytest.raises(task_service.TaskEditConflict):
            await replacement.prepare_replacement(successor, predecessor_id=original.id,
                expected_revision=before, action_key="replace")
        assert original.status == TaskStatus.CREATE and original.revision == before
    else:
        await replacement.prepare_replacement(successor, predecessor_id=original.id,
            expected_revision=before, action_key="replace")
        await db.commit()
        await replacement.reconcile_replacements()
        assert replacement.replacement_state(successor)["state"] == "confirmed"
    # A different Task remains replaceable even while this process is running.
    independent_successor = Task(id=uuid4(), label="Independent successor",
        agent_id=workflow.owner.id, status=TaskStatus.CREATE)
    await replacement.prepare_replacement(independent_successor, predecessor_id=unrelated.id,
        expected_revision=unrelated.revision, action_key="independent")
    await db.commit()
    await replacement.reconcile_replacements()
    assert replacement.replacement_state(independent_successor)["state"] == "confirmed"
    workflow.engine.cancel_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_late_process_blocks_successor_release(db, workflow, monkeypatch):
    from app.process import replacement_blocked_task_ids
    from app.task import replacement

    monkeypatch.setattr(replacement, "_blockers", {})
    replacement.register_replacement_blocker("process", replacement_blocked_task_ids)
    original = Task(id=uuid4(), label="Original", agent_id=workflow.owner.id, status=TaskStatus.CREATE)
    db.add(original)
    await db.commit()
    successor = Task(id=uuid4(), label="Successor", agent_id=workflow.owner.id, status=TaskStatus.CREATE)
    await replacement.prepare_replacement(successor, predecessor_id=original.id,
        expected_revision=original.revision, action_key="replace")
    await db.commit()
    await start(workflow, task_id=original.id)
    await db.commit()
    await replacement.reconcile_replacements()
    assert replacement.replacement_state(successor)["state"] == "conflict"
    assert successor.paused and successor.lease_token is None
    workflow.engine.cancel_run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, " invoice-42 "])
async def test_repeated_admission_persists_one_job_and_one_run(db, workflow, key):
    first = await start(workflow, idempotency_key=key)
    again = await start(workflow, idempotency_key=key)
    assert first.run_id == again.run_id
    assert not first.deduplicated and again.deduplicated
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1
    workflow.engine.start_run.assert_not_awaited()
    assert await service.process_start_jobs(batch_size=1, engine_code="fake") == 1
    run = await service.get_run(first.run_id)
    assert run.status == "running" and run.engine_run_id == "remote"
    assert (await db.scalar(select(ProcessStartJob))).status == "done"
    assert await service.process_start_jobs(batch_size=1) == 0
    workflow.engine.start_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabling_content_window_allows_intentional_identical_runs(db, workflow, monkeypatch):
    monkeypatch.setattr(service.runtime_settings, "PROCESS_IDEMPOTENCY_WINDOW_SECONDS", 0)
    first, second = await start(workflow), await start(workflow)
    assert first.run_id != second.run_id
    assert not second.deduplicated


@pytest.mark.asyncio
async def test_assignment_is_rechecked_before_reusing_an_idempotency_key(db, workflow):
    admitted = await start(workflow, idempotency_key="stable")
    await service.update_definition(workflow.definition.id, ProcessDefinitionUpdate(agent_id=workflow.other.id))
    with pytest.raises(PermissionError):
        await start(workflow, idempotency_key="stable")
    assert (await service.get_run(admitted.run_id)).launcher_agent_id == workflow.owner.id
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["tool", "agent", "duplicate", "null_label"])
async def test_invalid_definition_edits_preserve_assignment_and_identity(db, workflow, invalid):
    changes = {"tool": {"tool_id": 2147483647}, "agent": {"agent_id": 2147483647},
               "null_label": {"label": None}, "duplicate": {"engine_process_id": "other"}}[invalid]
    if invalid == "duplicate":
        await service.create_definition(ProcessDefinitionCreate(tool_id=workflow.tool.id, engine_process_id="other", label="Other"))
    with pytest.raises((LookupError, ValueError)):
        await service.update_definition(workflow.definition.id, ProcessDefinitionUpdate(**changes))
    await db.refresh(workflow.definition)
    assert workflow.definition.agent_id == workflow.owner.id
    assert workflow.definition.engine_process_id == "report"
    assert workflow.definition.label == "Quarterly report"


@pytest.mark.asyncio
async def test_deleted_definition_cannot_start_but_past_run_keeps_its_label(db, workflow):
    response = await start(workflow)
    assert await service.delete_definition(workflow.definition.id)
    assert not await service.has_process_definitions(agent_ids=[workflow.owner.id])
    assert await service.list_for_agent(workflow.owner.id) == []
    with pytest.raises(PermissionError):
        await start(workflow)
    detail = await service.get_run_detail(response.run_id)
    assert detail.workflow_id == "report" and detail.process_label == "Quarterly report"
    assert [event.event_type for event in detail.events] == ["run.created", "engine.start.requested"]


@pytest.mark.asyncio
async def test_admin_scope_includes_unassigned_definitions_without_other_agents(db, workflow):
    unassigned = await service.create_definition(ProcessDefinitionCreate(tool_id=workflow.tool.id, engine_process_id="unassigned", label="Available"))
    own = await service.list_definitions(agent_ids=[workflow.owner.id])
    other = await service.list_definitions(agent_ids=[workflow.other.id])
    assert {row.id for row in own} == {workflow.definition.id, unassigned.id}
    assert [row.id for row in other] == [unassigned.id]
    assert [row.id for row in await service.list_definitions(agent_id=workflow.owner.id)] == [workflow.definition.id]
    assert await service.get_definition_by_workflow_id("report", agent_ids=[workflow.other.id]) is None
    assert await service.get_for_agent(workflow.other.id, "report") is None
    assert await service.update_definition(2147483647, ProcessDefinitionUpdate(label="Absent")) is None
    assert not await service.delete_definition(2147483647)
    assert (await service.get_process_tool_by_code(" fake ")).id == workflow.tool.id
    with pytest.raises(ValueError):
        await service.get_process_tool_by_code(" ")
    with pytest.raises(LookupError):
        await service.get_process_tool_by_code("missing-engine")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error", "running"])
async def test_external_execution_is_correlated_once_and_scoped_to_its_workflow(db, workflow, status):
    workflow.engine.get_run.return_value = EngineRunSnapshot(
        status=status, output={"report": "saved", "api_key": "hidden"},
        error=EngineError(code="provider", message="Failed") if status == "error" else None,
        raw={"workflowId": "report", "Authorization": "hidden"},
    )
    run = await service.resolve_engine_run("report", "external-42", agent_ids=[workflow.owner.id])
    assert run.launcher_agent_id == workflow.owner.id and run.status == status
    assert run.output["report"] == "saved" and "hidden" not in str(run.output)
    assert "hidden" not in str(run.raw_snapshot)
    assert run.error_code == ("provider" if status == "error" else None)
    assert (await service.resolve_engine_run("report", "external-42")).id == run.id
    workflow.engine.get_run.assert_awaited_once()
    with pytest.raises(LookupError):
        await service.resolve_engine_run("report", "external-42", agent_ids=[workflow.other.id])
    await service.create_definition(ProcessDefinitionCreate(agent_id=workflow.owner.id, tool_id=workflow.tool.id, engine_process_id="other", label="Other"))
    with pytest.raises(PermissionError):
        await service.resolve_engine_run("other", "external-42")


@pytest.mark.asyncio
async def test_remote_workflow_mismatch_never_creates_a_local_execution(db, workflow):
    workflow.engine.get_run.return_value = EngineRunSnapshot(status="success", raw={"workflowId": "foreign"})
    with pytest.raises(PermissionError):
        await service.resolve_engine_run("report", "external")
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "waiting", "unknown", "cancelling", "success", "error", "cancelled"])
async def test_delete_and_retry_respect_terminal_state_contracts(db, workflow, status):
    admitted = await start(workflow)
    run = await service.get_run(admitted.run_id)
    run.status = status
    run.output = {"result": "original"}
    await db.commit()
    if status in {"error", "cancelled"}:
        retry = await service.retry_run(run.id)
        assert retry.run_id != run.id and not retry.deduplicated
        retried = await service.get_run(retry.run_id)
        assert retried.input == {"period": "Q1"} and retried.status == "queued"
        assert run.output == {"result": "original"} and run.status == status
        event = await db.scalar(select(ProcessRunEvent).where(ProcessRunEvent.event_type == "run.retried"))
        assert event.payload["new_run_id"] == str(retry.run_id)
    else:
        with pytest.raises(ValueError):
            await service.retry_run(run.id)
    if status in {"success", "error", "cancelled"}:
        assert await service.delete_run(run.id)
        assert await service.get_run(run.id) is None
        assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.run_id == run.id)) == 0
    else:
        with pytest.raises(ValueError):
            await service.delete_run(run.id)
        assert (await service.get_run(run.id)).status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["refresh_run", "cancel_run", "retry_run", "analyze_run"])
async def test_missing_run_is_reported_without_remote_effect(db, workflow, method):
    with pytest.raises(LookupError):
        await getattr(service, method)(uuid4())
    workflow.engine.get_run.assert_not_awaited()
    workflow.engine.cancel_run.assert_not_awaited()
    assert not await service.delete_run(uuid4())
    assert await service.get_run_detail(uuid4()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reject", "timeout", "network", "provider"])
async def test_start_failure_is_durable_and_retry_budget_is_bounded(db, workflow, monkeypatch, failure):
    monkeypatch.setattr(service.runtime_settings, "PROCESS_START_MAX_RETRIES", 2)
    if failure == "reject":
        workflow.engine.start_run.return_value = EngineStartResult(accepted=False)
    else:
        workflow.engine.start_run.side_effect = {"timeout": TimeoutError(), "network": OSError("connection lost"),
            "provider": ProcessEngineError("configuration", "Invalid configuration")}[failure]
    admitted = await start(workflow)
    assert await service.process_start_jobs(batch_size=1, engine_code="fake") == 1
    run = await service.get_run(admitted.run_id)
    job = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == run.id))
    if failure in {"timeout", "network"}:
        assert job.status == "pending" and run.status == "queued"
        assert job.attempts == 1 and job.locked_at is None
        assert job.available_at > datetime.now(timezone.utc)
        job.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        assert await service.process_start_jobs(batch_size=1, job_id=job.id) == 1
    assert run.status == "error" and run.finished_at is not None
    assert job.status == "failed" and job.locked_at is None
    assert run.error_code == {"reject": "engine_rejected", "provider": "configuration"}.get(failure, "engine_unreachable")
    assert await service.process_start_jobs(batch_size=1) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "network", "provider"])
async def test_stale_detail_retains_execution_and_reports_unavailable_observation(db, workflow, failure):
    admitted = await start(workflow)
    run = await service.get_run(admitted.run_id)
    run.status = "running"
    run.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
    run.engine_metadata = {"refresh_failures": "broken-legacy-counter"}
    await db.commit()
    workflow.engine.get_run.side_effect = {"timeout": TimeoutError(), "network": OSError("offline"),
        "provider": ProcessEngineError("unreachable", "offline", retryable=True)}[failure]
    detail = await service.get_run_detail(run.id, refresh_if_stale=True)
    assert not detail.fresh
    assert detail.status in {"running", "unknown"} and detail.finished_at is None
    assert run.engine_metadata["refresh_failures"] == 1
    assert any(event.event_type == "engine.refresh.failed" for event in detail.events)


@pytest.mark.asyncio
async def test_analysis_preserves_failure_evidence_and_authorizes_agent_calls(db, workflow):
    admitted = await start(workflow)
    run = await service.get_run(admitted.run_id)
    await service.record_inbound_call(run.id, kind="agent", target_code=workflow.owner.code, agent_ids=[workflow.owner.id])
    await service.record_inbound_call(run.id, kind="llm", target_code="model", metadata={"api_key": "hidden"})
    with pytest.raises(PermissionError):
        await service.record_inbound_call(run.id, kind="agent", target_code=workflow.other.code)
    with pytest.raises(LookupError):
        await service.record_inbound_call(run.id, kind="llm", target_code="model", agent_ids=[workflow.other.id])
    run.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await db.commit()
    await service.receive_callback(run.id, run.callback_token, ProcessCallbackEvent(
        event_id="failed", status="error", occurred_at=datetime.now(),
        error=EngineError(code="unauthorized", message="Provider denied access", node_name="Send report"),
    ))
    analysis = await service.analyze_run(run.id)
    assert not analysis.success and analysis.status == "error"
    assert analysis.duration_seconds >= 5
    assert analysis.failed_steps == ["Send report"]
    assert analysis.agent_calls[0]["target_code"] == workflow.owner.code
    assert len(analysis.recommendations) == 2
    await db.refresh(run)
    assert run.analysis == analysis.model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_name", ["agent_id", "agent_ids", "process_id", "workflow_id", "status", "active", "search", "created_after", "created_before"])
async def test_run_filters_count_only_matching_authorized_results(db, workflow, filter_name):
    first = await start(workflow, idempotency_key="first")
    second = await start(workflow, idempotency_key="second")
    own, other = await service.get_run(first.run_id), await service.get_run(second.run_id)
    old = datetime.now(timezone.utc) - timedelta(days=2)
    own.status, own.engine_run_id = "success", "unique-receipt"
    other.launcher_agent_id, other.created_at = workflow.other.id, old
    different = await service.create_definition(ProcessDefinitionCreate(agent_id=workflow.other.id, tool_id=workflow.tool.id, engine_process_id="other", label="Other"))
    other.process_id = different.id
    await db.commit()
    filters = {"agent_id": workflow.owner.id, "agent_ids": [workflow.owner.id], "process_id": workflow.definition.id,
               "workflow_id": "report", "status": "success", "active": False, "search": " unique-receipt ",
               "created_after": old + timedelta(days=1), "created_before": old + timedelta(days=1)}
    rows, total = await service.paginate_runs(**{filter_name: filters[filter_name]}, descending=False, sort_by="status", page_size=1)
    expected = other.id if filter_name == "created_before" else own.id
    assert total == 1 and [row.id for row in rows] == [expected]
    rows, total = await service.paginate_runs(**{filter_name: filters[filter_name]}, page=2, page_size=1)
    assert rows == [] and total == 1
    listed = await service.list_runs(agent_id=workflow.owner.id, workflow_id="report", status="success")
    assert [row.id for row in listed] == [own.id]
    assert (await service.get_operations(agent_ids=[workflow.owner.id])).status_counts == {"success": 1}
    assert (await service.get_operations(agent_ids=[])).pending_start_jobs == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["run", "task", "both", "empty"])
async def test_execution_summaries_preserve_scope_deduplication_and_pagination(db, workflow, scope):
    task = Task(label="Caller", agent_id=workflow.owner.id, status=TaskStatus.DISPATCH)
    db.add(task)
    await db.commit()
    response = await start(workflow, task_id=task.id)
    await start(workflow, idempotency_key="unrelated")
    run_ids = [response.run_id, response.run_id] if scope in {"run", "both"} else []
    task_ids = [task.id, task.id] if scope in {"task", "both"} else []
    expected = [] if scope == "empty" else [response.run_id]
    rows = await service.list_run_summaries_for_scope(run_ids, task_ids)
    assert [row.id for row in rows] == expected
    page, total = await service.list_run_summaries_page_for_scope(run_ids, task_ids, page_size=1)
    assert [row.id for row in page] == expected and total == len(expected)
    page, total = await service.list_run_summaries_page_for_scope(run_ids, task_ids, page=2, page_size=1)
    assert page == [] and total == len(expected)
    details = await service.list_for_task_ids(task_ids)
    assert [row.id for row in details] == ([response.run_id] if task_ids else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("file_state", ["valid", "expired", "wrong_file", "wrong_token", "missing_run"])
async def test_process_download_capability_is_bound_to_run_file_and_expiry(db, workflow, monkeypatch, file_state):
    from app.file_share import ResourceDescriptor
    import app.file_share as resources
    monkeypatch.setattr(resources, "resource_info", AsyncMock(return_value=ResourceDescriptor(
        uri="nextcloud://opaque", name="Report.pdf", size=6, media_type="application/pdf",
    )))
    response = await start(workflow, files=[ProcessFileInput(uri="nextcloud://opaque", description="Original report")])
    run = await service.get_run(response.run_id)
    ref = run.launch_snapshot["files"][0]
    if file_state == "expired":
        ref["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        run.launch_snapshot = {**run.launch_snapshot, "files": [ref]}
        await db.commit()
    args = (uuid4() if file_state == "missing_run" else run.id,
            "wrong" if file_state == "wrong_file" else ref["id"],
            "wrong" if file_state == "wrong_token" else run.callback_token)
    if file_state == "valid":
        downloadable = await service.file_reference(*args)
        assert downloadable.uri == "nextcloud://opaque" and downloadable.filename == "Report.pdf"
        assert downloadable.description == "Original report"
    else:
        with pytest.raises(LookupError if file_state == "missing_run" else PermissionError):
            await service.file_reference(*args)


@pytest.mark.asyncio
async def test_export_pages_preserve_events_without_exposing_capabilities(db, workflow):
    from app.process.export import export_run
    admitted = await start(workflow)
    run = await service.get_run(admitted.run_id)
    run.launch_snapshot = {**run.launch_snapshot, "files": [{"download_url": "secret-capability", "uri": "nextcloud://source"}]}
    run.raw_snapshot = {"api_key": "secret-key", "receipt": "kept"}
    await db.commit()
    first = await export_run(run.id, page_size=1)
    second = await export_run(run.id, page_size=1, after_event=first["next_event"])
    assert first["events"][0]["event_type"] == "run.created"
    assert second["events"][0]["event_type"] == "engine.start.requested"
    assert second["next_event"] is None
    assert run.callback_token not in str(first)
    assert "secret-capability" not in str(first) and "secret-key" not in str(first)
    assert first["raw_snapshot"]["receipt"] == "kept"
    with pytest.raises(LookupError):
        await export_run(uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error", "cancelled"])
@pytest.mark.parametrize("response", ["lost", "accepted"])
async def test_lost_start_response_cannot_overwrite_a_terminal_callback(db, workflow, status, response):
    admitted = await start(workflow)
    run = await service.get_run(admitted.run_id)
    async def complete_before_response(*args, **kwargs):
        await service.receive_callback(run.id, run.callback_token, ProcessCallbackEvent(
            event_id="finished", status=status, output={"receipt": "durable"}, engine_run_id="accepted-remote",
            error=EngineError(code="provider-final", message="Final provider error") if status == "error" else None,
        ))
        if response == "lost":
            raise TimeoutError("The HTTP response was lost after completion")
        return EngineStartResult(accepted=True, engine_run_id="obsolete-start-id", raw={"older": "snapshot"})
    workflow.engine.start_run.side_effect = complete_before_response
    assert await service.process_start_jobs(batch_size=1) == 1
    await db.refresh(run)
    assert run.status == status and run.output == {"receipt": "durable"}
    assert run.engine_run_id == "accepted-remote"
    assert run.error_code == ("provider-final" if status == "error" else None)
    assert run.error_message == ("Final provider error" if status == "error" else None)
    assert await service.process_start_jobs(batch_size=1) == 0
    workflow.engine.start_run.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("before_wait", ["queued", "success", "error"])
async def test_wait_link_added_on_replay_recovers_a_completion_that_arrived_first(db, workflow, monkeypatch, before_wait):
    from app.task import runner
    monkeypatch.setattr(runner, "go_next", lambda *args, **kwargs: None)
    parent = Task(label="Caller awaiting process", agent_id=workflow.owner.id, status=TaskStatus.DISPATCH,
                  paused=True, data={"pause_reasons": ["await"]})
    db.add(parent)
    await db.commit()
    admitted = await start(workflow, task_id=parent.id, idempotency_key="wait")
    run = await service.get_run(admitted.run_id)
    if before_wait != "queued":
        await service.receive_callback(run.id, run.callback_token, ProcessCallbackEvent(
            event_id="finished", status=before_wait, output={"report": "done"},
        ))
    replay = await start(workflow, task_id=parent.id, idempotency_key="wait", wait_for_completion=True)
    assert replay.run_id == run.id and replay.deduplicated
    child = await db.get(Task, run.await_task_id)
    assert child is not None
    if before_wait != "queued":
        assert child.status == (TaskStatus.SUCCESS if before_wait == "success" else TaskStatus.ERROR)
        assert not parent.paused
    else:
        assert parent.paused
        await service.cancel_run(run.id)
        assert child.status == TaskStatus.ERROR and not parent.paused


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["invalid", "malformed", "collection", "oversize", "unknown_size", "console"])
async def test_process_file_admission_rejects_invalid_resources_and_cleans_temporary_access(db, workflow, monkeypatch, condition):
    import app.file_share as resources
    import app.console as console
    from app.file_share import ResourceDescriptor
    descriptor = ResourceDescriptor(uri="nextcloud://file", name="report.pdf", media_type="",
        size=None if condition == "unknown_size" else service.PROCESS_FILE_MAX_BYTES + 1 if condition == "oversize" else 6,
        is_collection=condition == "collection")
    monkeypatch.setattr(resources, "resource_info", AsyncMock(return_value=descriptor))
    paths = []
    async def materialize(ctx, uri, path, *, max_bytes):
        paths.append(path)
        path.write_bytes(b"report")
        assert max_bytes == service.PROCESS_FILE_MAX_BYTES
        return SimpleNamespace(size=6)
    monkeypatch.setattr(resources, "materialize_resource", materialize)
    console_resource = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(console, "build_run_resource", AsyncMock(return_value=console_resource))
    uri = {"invalid": "local/file", "malformed": "://file", "console": "console://report.pdf"}.get(condition, "nextcloud://file")
    if condition in {"invalid", "malformed", "collection", "oversize"}:
        with pytest.raises((ValueError, IsADirectoryError)):
            await start(workflow, files=[ProcessFileInput(uri=uri)])
        assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0
    else:
        admitted = await start(workflow, files=[ProcessFileInput(uri=uri)])
        run = await service.get_run(admitted.run_id)
        ref = run.launch_snapshot["files"][0]
        assert ref["size"] == 6 and ref["content_type"] == "application/pdf"
        assert ref["uri"] == uri
    assert all(not path.exists() for path in paths)
    if condition == "console":
        console_resource.close.assert_awaited_once()
