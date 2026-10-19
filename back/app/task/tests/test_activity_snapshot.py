from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest

from app.agent import AIMessage, AgentLiveEvent, ExecutionResult
from app.agent.models import Agent, Title
from app.task import live_checkpoint, task_service
from app.task.activity_snapshot import activity_snapshots, readable_activity_tasks
from app.task.models import Task, TaskAttempt, TaskStatus
from app.task.schemas import TaskCreate
from app.task.startup_timing import startup_timing, task_startup_timings


@pytest.mark.asyncio
async def test_reconnect_recovers_current_attempt_without_leaking_payloads_or_replaying_effects(db):
    run_id, lease = uuid4(), uuid4()
    identity = {"request_run_id": str(run_id), "execution_target": {"metadata": {"streams_ai_messages": False}}}
    task = Task(id=uuid4(), label="Task", objective="Deliver report", status=TaskStatus.EXEC,
                paused=True, lease_token=lease, data={"pause_reasons": ["user"], "_agent_run_identity": identity})
    attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", status="CLAIMED",
                          worker_id="worker", lease_token=lease,
                          data={"agent_run": identity, "effect_checkpoint": {"receipt": "delivered"}})
    db.add_all([task, attempt])
    await db.flush()
    first = AgentLiveEvent(task_id=task.id, run_id=run_id, sequence=1, kind="message",
                           message=AIMessage(type="tool", tool_name="search", content="Found", stream_id="tool",
                                             tool_arguments={"secret": "hidden"}, tool_result={"token": "hidden"}))
    await live_checkpoint.checkpoint_live_event(first)
    live_checkpoint._cache.clear()  # Simulate a new worker after a reconnect/restart.
    await live_checkpoint.checkpoint_live_event(AgentLiveEvent(
        task_id=task.id, run_id=run_id, sequence=2, kind="message",
        message=AIMessage(type="text", content="Hello", stream_id="text")))
    await db.refresh(attempt)
    snapshot = (await activity_snapshots([task]))[0]
    assert snapshot.pause_pending and snapshot.operational["operational_state"] == "PAUSED"
    assert snapshot.attempt_number == 1 and not snapshot.streams_ai_messages
    assert [message.content for message in snapshot.live.result.messages] == ["Found", "Hello"]
    assert "hidden" not in snapshot.model_dump_json()
    assert attempt.data["effect_checkpoint"] == {"receipt": "delivered"}
    # Duplicate and old sequences cannot concatenate a second copy.
    assert await live_checkpoint.checkpoint_live_event(first) is None
    await live_checkpoint.checkpoint_live_event(AgentLiveEvent(
        task_id=task.id, run_id=run_id, sequence=3, kind="result",
        result=ExecutionResult(prompt="private prompt", system_prompt="private system", result="Done")))
    await db.refresh(attempt)
    assert attempt.data["live_activity"]["result"]["prompt"] == ""
    assert attempt.data["effect_checkpoint"]["receipt"] == "delivered"
    task.data = {"_agent_run_identity": {"request_run_id": str(uuid4())}}
    await db.flush()
    assert (await activity_snapshots([task]))[0].live is None


@pytest.mark.asyncio
async def test_activity_batch_only_contains_managed_tasks(db):
    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    agents = [Agent(code=f"activity-{uuid4()}", first_name="Agent", last_name=str(i), title_id=title.id) for i in range(2)]
    db.add_all(agents)
    await db.flush()
    tasks = [Task(label="Task", objective="Work", agent_id=agent.id) for agent in agents]
    db.add_all(tasks)
    await db.flush()
    ids = [task.id for task in tasks] + [uuid4()]
    assert [task.id for task in await readable_activity_tasks(ids, {agents[0].id})] == [tasks[0].id]
    assert await readable_activity_tasks(ids, set()) == []
    assert len(await readable_activity_tasks(ids, None)) == 2
    snapshots = await activity_snapshots(await readable_activity_tasks(ids, {agents[0].id}))
    assert [item.startup_timing.task_id for item in snapshots] == [tasks[0].id]
    assert snapshots[0].startup_timing.queue_wait_upper_bound_seconds is None


@pytest.mark.asyncio
async def test_activity_reads_only_live_children_without_loading_their_results(db):
    from sqlalchemy import event, inspect
    from app.agent import TaskMessage
    from app.task.operational_state import operational_snapshot
    from tests.sql_reads import measured_reads

    parents = [Task(label="Synthetic parent"), Task(label="Synthetic independent parent")]
    db.add_all(parents)
    await db.flush()
    children = [Task(label=f"Synthetic finished child {index}", parent_id=parents[0].id,
        status=TaskStatus.SUCCESS if index % 2 else TaskStatus.ERROR,
        data={"delegated": True}, plan={"steps": []},
        execution_result={"result": "Synthetic result. " * 1000}) for index in range(200)]
    awaiting = Task(label="Synthetic question", parent_id=parents[0].id, status=TaskStatus.DISPATCH,
        objective="<p>Which period?</p>", paused=True,
        data={"awaiting_reply": {"peer_display": "Synthetic peer"}})
    delegated = Task(label="Synthetic delegation", parent_id=parents[0].id, status=TaskStatus.EXEC,
        objective="<p>Prepare the report</p>", data={"delegated": True},
        execution_result={"result": "Synthetic partial result. " * 1000},
        dispatch_result={"route": "EXEC"}, messages=[TaskMessage(text="Synthetic context")])
    planned = Task(label="Synthetic plan", parent_id=parents[1].id, status=TaskStatus.PLAN, plan={"steps": []})
    deleted = Task(label="Synthetic deleted child", parent_id=parents[1].id,
        data={"delegated": True}, deleted_at=datetime.now(timezone.utc))
    children.extend([awaiting, delegated, planned, deleted])
    db.add_all(children)
    await db.flush()
    expected = [operational_snapshot(parent, [child for child in children
                if child.parent_id == parent.id and child.deleted_at is None]) for parent in parents]
    parent_ids = [parent.id for parent in parents]
    active_ids = {awaiting.id, delegated.id, planned.id}
    delegated_id = delegated.id
    db.expunge_all()
    parents = [await db.get(Task, identity) for identity in parent_ids]
    loaded = []

    def capture(_session, instance):
        if isinstance(instance, Task):
            loaded.append(instance)

    event.listen(db.sync_session, "loaded_as_persistent", capture)
    try:
        async with measured_reads(db, "task-activity-200-finished-children") as reads:
            snapshots = await activity_snapshots(parents)
    finally:
        event.remove(db.sync_session, "loaded_as_persistent", capture)
    # Child queries have no ordering contract; compare the same waits by identity.
    actual = [snapshot.operational for snapshot in snapshots]
    for state in [*actual, *expected]:
        state["waits"].sort(key=lambda wait: wait.get("coordination_task_id", ""))
    assert actual == expected
    print(f"ACTIVITY_CHILDREN loaded={len(loaded)} result_payloads="
          f"{sum('execution_result' not in inspect(child).unloaded for child in loaded)}")
    assert {child.id for child in loaded} == active_ids
    assert all({"execution_result", "dispatch_result", "messages"} <= inspect(child).unloaded for child in loaded)
    assert len(reads) <= 5

    # A later read observes completions immediately; it must neither retain stale
    # waits nor keep amendment blocked by finished delegated/planned children.
    for child in loaded:
        child.status = TaskStatus.SUCCESS
    await db.flush()
    reopened = await activity_snapshots(parents)
    assert all(snapshot.operational["waits"] == [] for snapshot in reopened)
    assert all(snapshot.operational["amendable"] for snapshot in reopened)
    completed = await task_service.get_by_id(delegated_id)
    assert completed.execution_result == {"result": "Synthetic partial result. " * 1000}
    assert completed.dispatch_result == {"route": "EXEC"}
    assert [message.text for message in completed.messages] == ["Synthetic context"]


@pytest.mark.asyncio
async def test_activity_scope_summary_keeps_polling_payload_bounded(db):
    import json
    from pathlib import Path
    from app.agent import admitted_scope, parse_scope

    demand = "<p>" + "Synthetic requirement. " * 3500 + "</p>"
    task = Task(id=uuid4(), label="Synthetic long demand", objective=demand,
        data={"_original_demand": demand})
    scope = admitted_scope(task.id, demand)
    task.data = {**task.data, "execution_scope": scope.model_dump(mode="json")}
    db.add(task)
    await db.flush()
    snapshot = (await activity_snapshots([task]))[0]
    scope_bytes = len(json.dumps(snapshot.execution_scope).encode())
    snapshot_bytes = len(snapshot.model_dump_json().encode())
    destination = Path(__file__).resolve().parents[4] / "artifacts/scope-activity-payload.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"demand_characters": len(demand),
        "scope_bytes": scope_bytes, "snapshot_bytes": snapshot_bytes}, indent=2))
    assert scope_bytes < 1000, "Polling must expose provenance summaries, not repeat the full admitted demand"
    assert snapshot.execution_scope["revision"] == scope.revision
    assert snapshot.execution_scope["source_task_id"] == str(task.id)
    assert snapshot.execution_scope["requirement_count"] == len(scope.requirements)
    assert snapshot.execution_scope["grant_count"] == len(scope.grants)
    assert parse_scope(task.data) == scope  # The complete durable contract remains available.


@pytest.mark.asyncio
async def test_initial_startup_separates_preparation_from_queue_and_survives_retry(db):
    start = datetime(2026, 9, 13, 5, 44, 40, tzinfo=timezone.utc)
    def at(seconds):
        return (start + timedelta(seconds=seconds)).isoformat()

    task = Task(label="Generate image", status=TaskStatus.CREATE, created_at=start,
                data={"_startup_timing": {"preparation_started_at": at(0),
                      "preparation_finished_at": at(15), "enqueued_at": at(15.2)}})
    db.add(task)
    await db.flush()
    # Persisted, but not claimed yet: no fabricated waiting duration.
    waiting = (await activity_snapshots([task]))[0].startup_timing
    assert waiting.preparation_seconds == 15
    assert waiting.admission_seconds == pytest.approx(.2)
    assert waiting.queue_wait_upper_bound_seconds is None
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="CREATE", status="SUCCESS",
                       worker_id="first", lease_token=uuid4(), started_at=start,
                       data={"claimed_at": at(15.3)}))
    db.add(TaskAttempt(task_id=task.id, attempt_number=2, phase="DISPATCH", status="SUCCESS",
                       worker_id="retry", lease_token=uuid4(),
                       data={"claimed_at": at(120)}))
    task.status = TaskStatus.SUCCESS
    task.updated_at = start + timedelta(seconds=200)
    from app.llm.models import LLMCall, LLMCallEvent

    dispatch = LLMCall(task_id=task.id, purpose="agent.dispatch", requested_model="synthetic", status="completed",
        started_at=start + timedelta(seconds=15.4), completed_at=start + timedelta(seconds=17), duration=1.6)
    execution = LLMCall(task_id=task.id, purpose="agent.exec", requested_model="synthetic", status="completed",
        started_at=start + timedelta(seconds=18), completed_at=start + timedelta(seconds=25), duration=7,
        first_token_at=start + timedelta(seconds=18.1))
    db.add_all([dispatch, execution])
    await db.flush()
    for call, sequence, seconds, message in [
        (dispatch, 1, 16, {"type": "text", "content": "Internal choice"}),
        (execution, 1, 18.1, {"type": "thinking", "content": "Private reasoning"}),
        (execution, 2, 18.2, {"type": "text", "content": "  \n\t"}),
        (execution, 3, 21, {"type": "tool", "tool_name": "file_read"}),
        (execution, 4, 22, {"type": "text", "content": "Useful text"}),
    ]:
        db.add(LLMCallEvent(call_id=call.id, sequence=sequence, created_at=start + timedelta(seconds=seconds),
                            payload={"kind": "message", "message": message}))
    await db.flush()
    task_id = task.id
    db.expire_all()
    reloaded = (await task_startup_timings([task_id]))[0]
    assert reloaded.preparation_seconds == 15
    assert reloaded.admission_seconds == pytest.approx(.2)
    assert reloaded.queue_wait_upper_bound_seconds == pytest.approx(.1)
    assert reloaded.first_claimed_at.isoformat() == at(15.3)
    assert reloaded.claimed_to_output_seconds == pytest.approx(5.7)
    assert reloaded.enqueued_to_output_seconds == pytest.approx(5.8)
    assert reloaded.execution_timing.first_output_at.isoformat() == at(21)
    assert reloaded.execution_timing.first_output_seconds == pytest.approx(5.6)
    assert reloaded.execution_timing.call_seconds_before_output == pytest.approx(4.6)
    assert reloaded.execution_timing.between_calls_seconds == 1
    assert "Private reasoning" not in reloaded.model_dump_json()


@pytest.mark.parametrize("admission,claimed", [
    (None, None), ({}, "invalid"),
    ({"enqueued_at": "2026-09-13T05:44:40"}, "2026-09-13T05:44:41Z"),
    ({"enqueued_at": "2026-09-13T05:44:42Z"}, "2026-09-13T05:44:41Z"),
])
def test_missing_invalid_or_reversed_timing_is_unknown(admission, claimed):
    assert startup_timing(uuid4(), "Historical", admission, claimed).queue_wait_upper_bound_seconds is None


def test_admitted_demand_is_preserved_separately_from_amendments():
    task = task_service.build(TaskCreate(label="Report", objective="<p>Initial demand</p>",
                                       data={"_original_demand": "injected", "other": True}))
    task.objective = "<p>Amended objective</p>"
    assert task.data["_original_demand"] == "<p>Initial demand</p>"
    assert task.data["other"] is True


@pytest.mark.asyncio
async def test_every_task_records_enqueue_and_distinguishes_pause_backoff_and_processing(db, monkeypatch):
    from app.task import timing_events
    from app.task.task_service import suspend, release, PAUSE_USER

    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(timing_events, "datetime", Clock)
    task = Task(label="API task")
    db.add(task)
    await db.flush()
    assert task.data is None
    assert datetime.fromisoformat(task.lifecycle_timing["enqueued_at"]) == now
    now += timedelta(seconds=2)
    suspend(task, PAUSE_USER)
    await db.flush()
    now += timedelta(seconds=10)
    release(task, PAUSE_USER)
    task.next_attempt_at = now + timedelta(seconds=4)
    await db.flush()
    now += timedelta(seconds=7)
    task.lease_token = uuid4()
    await db.flush()
    now += timedelta(seconds=3)
    task.status = TaskStatus.SUCCESS
    task.lease_token = None
    await db.flush()
    recorded = task.lifecycle_timing
    assert timing_events.timing_totals(recorded, now + timedelta(days=1)) == {
        "queue": 5, "user_pause": 10, "backoff": 4, "processing": 3,
    }
    assert task.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_historical_task_recovers_actual_provider_timestamps_without_using_transaction_start(db):
    from app.llm import LLMCall

    start = datetime(2026, 9, 13, tzinfo=timezone.utc)
    task = Task(label="Historical", created_at=start - timedelta(seconds=15))
    db.add(task)
    await db.flush()
    # Simulate storage predating the new observers, without reinterpreting created_at.
    from sqlalchemy import update
    await db.execute(update(Task).where(Task.id == task.id).values(data=None, lifecycle_timing=None))
    revision = task.revision
    task.label = task.label
    await db.flush()
    assert task.revision == revision
    assert task.lifecycle_timing is None
    call = LLMCall(task_id=task.id, purpose="agent.dispatch", started_at=start,
                   completed_at=start + timedelta(seconds=2), duration=2)
    db.add(call)
    await db.flush()
    measured = (await task_startup_timings([task.id]))[0]
    assert measured.enqueued_at is None
    assert len(measured.processing_intervals) == 1
    assert measured.processing_intervals[0].started_at == start
    assert measured.processing_intervals[0].seconds == 2


@pytest.mark.asyncio
async def test_resumed_attempt_reuses_run_but_has_its_own_activity_and_sequences(db):
    run = uuid4()
    identity = {"request_run_id": str(run)}
    task = Task(id=uuid4(), label="Resume", objective="Work", status=TaskStatus.EXEC,
                data={"_agent_run_identity": identity})
    first = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", status="CLAIMED",
                        lease_token=uuid4(), worker_id="old", data={"agent_run": identity})
    db.add_all([task, first])
    await db.flush()
    await live_checkpoint.checkpoint_live_event(AgentLiveEvent(task_id=task.id, run_id=run,
        attempt_id=first.id, sequence=100, kind="message", message=AIMessage(type="text", content="Old work")))
    await db.refresh(first)
    first.status = "RETRY"
    second = TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC", status="CLAIMED",
                         lease_token=uuid4(), worker_id="new", data={"agent_run": identity})
    db.add(second)
    await db.flush()
    await live_checkpoint.checkpoint_live_event(AgentLiveEvent(task_id=task.id, run_id=run,
        attempt_id=second.id, sequence=1, kind="message", message=AIMessage(type="text", content="Resumed work")))
    await db.refresh(second)
    snapshot = (await activity_snapshots([task]))[0]
    assert snapshot.live.attempt_id == second.id
    assert snapshot.live.sequence == 1
    assert [message.content for message in snapshot.live.result.messages] == ["Resumed work"]
    await live_checkpoint.checkpoint_live_event(AgentLiveEvent(task_id=task.id, run_id=run,
        attempt_id=first.id, sequence=101, kind="result", result=ExecutionResult(prompt="", result="Late")))
    await db.refresh(second)
    assert second.data["live_activity"]["result"]["messages"][0]["content"] == "Resumed work"
