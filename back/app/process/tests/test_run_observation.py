"""Participants see durable evidence; only launchers and Process administrators control runs."""

from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.connection import Connection
from app.dataset.facade import set_dataset_grant, dataset_record
from app.process import process_service
from app.process.bpmn import Actor
from app.process.dbadmin import _backfill_run_participants
from app.process.mcp import processus_get, process_get_run, process_list_runs
from app.process.native_definitions import create, update
from app.process.native_runs import inspect_run, list_runs, control_run, inspect_occurrence, run_metrics, children
from app.process.models import ProcessRun, ProcessNodeRun, ProcessNodeAttempt
from app.tools import McpToolContext, ToolModel
from core.user import UserModel
from core.user import HumanActor

from .test_native_bpmn import native as native, graph


def test_participation_uses_nested_execution_defaults_and_used_roles_only():
    from app.process.run_participants import participant_agents
    snapshot = {"definition": {"graph": {"execution_agent_id": 2, "actors": [], "nodes": [
        {"kind": "for", "body": {"actors": [{"id": "unused", "kind": "agent", "agent_id": 9}],
            "nodes": [{"kind": "task", "config": {}}]}},
        {"kind": "while", "body": {"execution_agent_id": 3, "actors": [
            {"id": "assigned", "kind": "agent", "agent_id": 4}, {"id": "person", "kind": "human", "user_id": 5}],
            "nodes": [{"kind": "task"}, {"kind": "task", "config": {"actor": "assigned"}},
                {"kind": "if", "config": {"actor": "person"}}]}},
    ]}}}
    assert participant_agents(snapshot, 1) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_run_list_exposes_bounded_result_and_prioritizes_error(db, native):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic result preview", graph=graph())
    identity = (await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})).run_id
    run = await db.get(ProcessRun, identity)
    for output, error_message, error_code, expected in [
        (None, None, None, ""),
        ({"résultat": "Synthetic completed work"}, None, None, '{"résultat": "Synthetic completed work"}'),
        ({"result": "Partial output"}, "Synthetic failure\nRetry later", "synthetic_error", "Synthetic failure\nRetry later"),
        (None, None, "synthetic_error", "synthetic_error"),
        ({"result": "x" * 2000}, None, None, ('{"result": "' + "x" * 2000)[:1199] + "…"),
    ]:
        run.output, run.error_message, run.error_code = output, error_message, error_code
        await db.commit()
        page = await list_runs(owner.id, code=definition.code)
        assert page["total"] == 1
        assert page["items"][0]["id"] == str(identity)
        assert page["items"][0]["result_preview"] == expected
        assert (await inspect_run(identity, owner.id))["output"] == output


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_run_list_exposes_actual_execution_times(db, native, started):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic run timing", graph=graph())
    identity = (await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})).run_id
    run = await db.get(ProcessRun, identity)
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    run.started_at = start if started else None
    run.finished_at = start + timedelta(seconds=65) if started else None
    run.status = "success" if started else "queued"
    await db.commit()
    item = (await list_runs(owner.id, code=definition.code))["items"][0]
    assert item["started_at"] == (start.isoformat() if started else None)
    assert item["finished_at"] == ((start + timedelta(seconds=65)).isoformat() if started else None)


@pytest.mark.asyncio
async def test_frozen_participants_and_revocable_dedicated_admin_apply_to_every_run_read(db, native, tmp_path):
    from app.file_share import ResourceContext, resource_info, resource_read, resource_write, resource_move, materialize_resource, list_schemes
    owner, participant = native
    observer = Agent(title_id=owner.title_id, code=f"observer-{uuid4().hex}", first_name="Observer", last_name="Example", agent_driver="internal")
    human = UserModel(email=f"synthetic-launcher-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add_all([observer, human]); await db.flush()
    owner.user_id = participant.user_id = human.id
    value = graph()
    value.actors = [Actor(id="worker", name="Assigned role", kind="agent", agent_id=participant.id),
        Actor(id="unused", name="Unused role", kind="agent", agent_id=observer.id)]
    value.nodes[1].config["actor"] = "worker"
    definition = await create(actor_agent_id=owner.id, title="Synthetic scoped progress", graph=value)
    run_id = (await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
        input_data={}, requester_user_id=human.id)).run_id
    run = await db.get(ProcessRun, run_id)
    assert run.launch_snapshot["participant_agents"] == sorted([owner.id, participant.id])
    ctx = McpToolContext(agent_id=participant.id, runtime="internal")
    uri = f"processus://run/{run_id}"
    file_ctx = ResourceContext(agent_id=participant.id, runtime="internal")
    assert "processus" in {scheme.scheme for scheme in await list_schemes(file_ctx)}
    info = await resource_info(file_ctx, uri)
    assert info.uri == uri and set(info.capabilities) == {"info", "read", "copy"}
    snapshot = json.loads((await resource_read(file_ctx, uri, max_chars=200_000)).content)
    assert snapshot["id"] == str(run_id) and snapshot["resource_uri"] == uri and snapshot["status"] == "queued"
    partial = await resource_read(file_ctx, uri, max_chars=20)
    assert partial.next_offset == 20 and partial.total > partial.end
    assert (await processus_get(ctx, uri))["id"] == str(run_id)
    with pytest.raises(PermissionError, match="read-only"):
        await resource_write(file_ctx, uri, b"{}")
    with pytest.raises(PermissionError, match="cannot be moved"):
        await resource_move(file_ctx, uri, "file://")
    exported = await materialize_resource(file_ctx, uri, tmp_path / "run.json", max_bytes=200_000)
    assert exported.uri == uri and json.loads((tmp_path / "run.json").read_text())["id"] == str(run_id)
    with pytest.raises(ValueError, match="byte limit"):
        await materialize_resource(file_ctx, uri, tmp_path / "oversized.json", max_bytes=1)
    assert not (tmp_path / "oversized.json").exists()
    assert (await processus_get(ctx, str(run_id)))["operational"]["phase"] == "queued"
    assert (await list_runs(participant.id))["total"] == 1
    assert len(await process_list_runs(ctx)) == 1
    assert (await process_get_run(ctx, str(run_id)))["id"] == str(run_id)
    assert not (await inspect_run(run_id, participant.id))["can_control"]
    with pytest.raises(PermissionError):
        await control_run(run_id, participant.id, "pause")
    # Changing the definition cannot grant another agent access to an existing run.
    value.nodes[1].config["actor"] = "unused"
    await update(definition.code, owner.id, expected_revision=1, graph=value)
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(run_id)
    await db.refresh(run)
    dataset = await dataset_record(run.dataset_document_id, HumanActor(human.id))
    await set_dataset_grant(dataset.id, HumanActor(human.id), kind="agent", principal=observer.id,
        can_write=False, expected_lock_version=dataset.lock_version)
    occurrence = await db.scalar(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id).order_by(ProcessNodeRun.admission_order.desc()))
    assert (await list_runs(observer.id))["total"] == 0
    assert await process_list_runs(McpToolContext(agent_id=observer.id, runtime="internal")) == []
    denied_ctx = ResourceContext(agent_id=observer.id, runtime="internal")
    for operation in (lambda: resource_read(denied_ctx, uri), lambda: resource_info(denied_ctx, uri),
                      lambda: inspect_run(run_id, observer.id), lambda: inspect_occurrence(run_id, occurrence.id, observer.id),
                      lambda: run_metrics(run_id, observer.id), lambda: children(run_id, observer.id)):
        with pytest.raises(PermissionError):
            await operation()
    global_tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris_admin"))
    db.add(Connection(agent_id=observer.id, tool_id=global_tool.id, active=True)); await db.commit()
    with pytest.raises(PermissionError):
        await processus_get(McpToolContext(agent_id=observer.id, runtime="internal"), str(run_id))
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "process_admin"))
    connection = Connection(agent_id=observer.id, tool_id=tool.id, active=True)
    db.add(connection); await db.commit()
    assert (await inspect_run(run_id, observer.id))["can_control"]
    assert (await resource_read(denied_ctx, uri)).uri == uri
    assert (await list_runs(observer.id))["total"] == 1
    await control_run(run_id, observer.id, "pause")
    connection.active = False
    await db.commit()
    with pytest.raises(PermissionError):
        await inspect_run(run_id, observer.id)
    with pytest.raises(PermissionError):
        await resource_read(denied_ctx, uri)
    # Legacy runs get the same frozen projection, without altering their graph.
    frozen = run.launch_snapshot["definition"]
    run.launch_snapshot = {key: item for key, item in run.launch_snapshot.items() if key != "participant_agents"}
    await db.commit()
    await _backfill_run_participants(db); await db.commit()
    await _backfill_run_participants(db); await db.commit()
    assert run.launch_snapshot["participant_agents"] == sorted([owner.id, participant.id])
    assert run.launch_snapshot["definition"] == frozen


@pytest.mark.asyncio
async def test_operational_progress_explains_human_wait_pause_resume_and_complete_stop(db, native):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic observable workflow", graph=graph())
    run_id = (await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})).run_id
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4):
        await process_service.refresh_run(run_id)
    occurrence = await db.scalar(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == "work"))
    attempt = await db.scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.node_run_id == occurrence.id))
    from app.task import task_service
    task = await task_service.get_by_id(attempt.task_id)
    task_service.suspend(task, task_service.PAUSE_APPROVAL)
    await db.commit()
    authorized_view = await processus_get(McpToolContext(agent_id=owner.id, runtime="internal"), str(run_id))
    assert authorized_view["operational"]["activities"][0]["kind"] == "authorization"
    task_service.release(task, task_service.PAUSE_APPROVAL)
    occurrence.context = {**occurrence.context, "activity_question": {"status": "pending", "question": "Which invented value?", "user_id": 17}}
    await db.commit()
    ctx = McpToolContext(agent_id=owner.id, runtime="internal", task_id=attempt.task_id)
    snapshot = await processus_get(ctx)
    assert snapshot["operational"]["phase"] == "waiting"
    assert snapshot["operational"]["activities"][0]["question"] == "Which invented value?"
    assert snapshot["operational"]["progress"]["completed"] >= 1
    key = uuid4()
    paused = await control_run(run_id, owner.id, "pause", command_key=key)
    assert await control_run(run_id, owner.id, "pause", command_key=key) == paused
    assert (await processus_get(ctx))["operational"]["phase"] == "paused"
    await control_run(run_id, owner.id, "resume")
    assert (await processus_get(ctx))["operational"]["phase"] == "waiting"
    await process_service.cancel_run(run_id)
    for _ in range(4):
        await process_service.refresh_run(run_id)
    stopped = await processus_get(ctx)
    assert stopped["status"] == "cancelled"
    assert stopped["operational"]["available_actions"] == []
    assert stopped["operational"]["activities"] == []
    with pytest.raises(ValueError, match="terminal"):
        await control_run(run_id, owner.id, "resume")
