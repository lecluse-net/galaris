from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from core.database import get_db_session

from app.agent.contracts import (
    AgentRunEventV1,
    AgentRunIdentityV1,
    ExecutionResult,
    StaleAgentRunError,
    AgentContextCapsule,
    WorkingResource,
)
from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter
from app.task.models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("local_changes", [False, True])
@pytest.mark.parametrize("held", [False, True])
async def test_run_admission_preserves_input_committed_while_context_was_prepared(committed_database, local_changes, held):
    token = uuid4()
    async with get_db_session() as db:
        task = Task(label="Synthetic concurrent admission", status=TaskStatus.EXEC,
            lease_token=token, lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            data={"existing": "keep", "obsolete": "remove", "input_request": {"key": "synthetic", "status": "pending"}})
        db.add(task); await db.flush()
        db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH", status="CLAIMED",
            worker_id="synthetic", lease_token=token))
        identity = task.id

    async with get_db_session() as db:
        preparing = await db.get(Task, identity)
        if local_changes:
            preparing.data = {key: value for key, value in preparing.data.items() if key != "obsolete"} | {"prepared": "keep"}
        async with get_db_session() as reply_db:
            receiving = await reply_db.get(Task, identity)
            receiving.data = {**receiving.data, "input_context": "Synthetic received answer",
                "input_request": {"key": "synthetic", "status": "answered", "response": "Synthetic received answer"}}
            if held:
                from app.task import task_service
                task_service.suspend(receiving, task_service.PAUSE_USER)
        if held:
            with pytest.raises(StaleAgentRunError):
                await SqlAlchemyAgentTaskAdapter().activate_agent_run(preparing,
                    {"request_run_id": str(uuid4()), "driver_code": "internal"})
            await db.rollback()
        else:
            await SqlAlchemyAgentTaskAdapter().activate_agent_run(preparing,
                {"request_run_id": str(uuid4()), "driver_code": "internal"})

    async with get_db_session() as db:
        persisted = await db.get(Task, identity)
        assert persisted.data["input_context"] == "Synthetic received answer"
        assert persisted.data["input_request"]["status"] == "answered"
        assert persisted.data["existing"] == "keep"
        if held:
            assert persisted.paused and persisted.data["pause_reasons"] == ["user"]
            assert "_agent_run_identity" not in persisted.data
        elif local_changes:
            assert persisted.data["prepared"] == "keep" and "obsolete" not in persisted.data


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_finalization_preserves_run_cleanup_and_a_concurrent_input_reply(committed_database, success):
    from dataclasses import replace
    from app.agent import executor_service, facade
    from app.agent.tests.test_driver_testkit import _request

    checkpoint = {"driver_code": "openai_messages", "runtime_run_id": "a" * 64,
        "status": "completed" if success else "interrupted",
        "data": {"version": 1, "run_context": "synthetic-opaque-state"}}
    key = uuid4().hex
    async with get_db_session() as db:
        task = Task(label="Synthetic input continuation", status=TaskStatus.EXEC, data={
            "_agent_run_checkpoint": checkpoint, "_agent_run_identity": {"request_run_id": str(uuid4())},
            "input_request": {"key": key, "status": "pending"}})
        db.add(task); await db.flush()
        identity = task.id

    async with get_db_session() as db:
        task = await db.get(Task, identity)
        result = ExecutionResult(prompt="Synthetic", result="Waiting for an answer", success=success)
        facade._apply_run_result(task, result, replace(_request(), task_id=identity))
        async with get_db_session() as reply_db:
            concurrent = await reply_db.get(Task, identity)
            concurrent.data = {**concurrent.data,
                "input_request": {"key": key, "status": "answered", "response": "synthetic response"},
                "input_context": "synthetic response"}
        await executor_service._update_task_after_execution(task, result, base_cost=0)

    async with get_db_session() as db:
        task = await db.get(Task, identity)
        assert task.status == TaskStatus.DISPATCH and not task.paused
        assert task.data["input_request"]["status"] == "delivered"
        assert task.data["input_context"] == "synthetic response"
        assert "_agent_run_identity" not in task.data
        if success:
            assert "_agent_run_checkpoint" not in task.data
        else:
            assert task.data["_agent_run_checkpoint"] == checkpoint


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_authorization_wait_survives_checkpoint_and_releases_claim(committed_database, success):
    """A driver's authorization UUIDs must survive real JSONB persistence."""
    from app.agent import executor_service
    from app.task import scheduler, task_service

    token = uuid4()
    authorization_ids = [uuid4(), uuid4()]
    checkpoint = {"runtime_run_id": "synthetic-authorization-run", "resume_safe": True}
    result = ExecutionResult(
        prompt="<p>Perform the authorized action.</p>",
        result="Waiting for approval",
        success=False,
        schema_version="galaris.execution-result/v2",
        disposition="waiting_for_authorization",
        authorization_requests=authorization_ids,
        metadata={"runtime_run_id": checkpoint["runtime_run_id"]},
    )
    async with get_db_session() as db:
        task = Task(
            label="Synthetic authorization wait", objective=result.prompt,
            status=TaskStatus.EXEC, cost=0.25,
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            data={"existing": "keep"},
        )
        db.add(task)
        await db.flush()
        attempt = TaskAttempt(
            task_id=task.id, attempt_number=1, phase="DISPATCH",
            status=TaskAttemptStatus.CLAIMED.value, worker_id="test-worker",
            lease_token=token, data={"base_cost": 0.25},
        )
        db.add(attempt)
        await db.flush()
        task_id, attempt_id = task.id, attempt.id

    await SqlAlchemyAgentTaskAdapter().persist_agent_run_state(
        task_id, expected_objective=result.prompt, expected_attempt_id=attempt_id,
        data_patch={"_agent_run_checkpoint": checkpoint}, execution_result=result,
    )
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        assert task.get_execution_result() == result
        await executor_service._update_task_after_execution(task, result, base_cost=0.25)

    await scheduler._complete_claim(task_id, TaskStatus.DISPATCH, token)

    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        attempt = await db.get(TaskAttempt, attempt_id)
        # An approval wait releases transient EXEC into the resumable phase.
        assert task.status == TaskStatus.DISPATCH
        assert task_service.is_paused_for(task, task_service.PAUSE_APPROVAL)
        assert task.execution_result["authorization_requests"] == [str(value) for value in authorization_ids]
        assert task.get_execution_result() == result
        assert task.data["authorization_requests"] == [str(value) for value in authorization_ids]
        assert task.data["_agent_run_checkpoint"] == checkpoint
        assert task.data["existing"] == "keep"
        assert attempt.data["agent_checkpoint"] == checkpoint
        assert attempt.status == TaskAttemptStatus.WAITING_APPROVAL.value
        assert attempt.finished_at is not None
        assert attempt.error is None
        assert task.lease_token is None
        assert task.lease_expires_at is None
        assert task.next_attempt_at is None
        assert task.consecutive_failures == 0

    # A resumed outcome replaces the current wait, while its original attempt
    # remains an immutable historical record of that wait.
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        task_service.release(task, task_service.PAUSE_APPROVAL)
        await executor_service._update_task_status(task, executor_service.TaskPhase.EXEC)
        await executor_service._update_task_after_execution(task, ExecutionResult(
            prompt=result.prompt, result="Synthetic resumed outcome", success=success,
            schema_version="galaris.execution-result/v2",
        ), base_cost=task.cost)
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        attempt = await db.get(TaskAttempt, attempt_id)
        assert task.status == (TaskStatus.SUCCESS if success else TaskStatus.ERROR)
        assert "authorization_requests" not in task.data
        assert task.data["existing"] == "keep"
        assert attempt.status == TaskAttemptStatus.WAITING_APPROVAL.value
        assert attempt.data["agent_checkpoint"] == checkpoint


@pytest.mark.asyncio
async def test_model_activity_without_visible_output_refreshes_only_current_run(committed_database):
    from app.task.activity_snapshot import activity_snapshots

    lease, run_id = uuid4(), uuid4()
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    identity = {"request_run_id": str(run_id)}
    async with get_db_session() as db:
        task = Task(label="Synthetic argument generation", objective="<p>Prepare a report.</p>",
            status=TaskStatus.EXEC, lease_token=lease,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            data={"_agent_run_identity": identity})
        db.add(task)
        await db.flush()
        attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", status="CLAIMED",
            worker_id="synthetic-worker", lease_token=lease, started_at=old,
            data={"agent_run": identity, "effect_checkpoint": {"receipt": "synthetic-saved"}})
        db.add(attempt)
        await db.flush()
        task_id, attempt_id, objective = task.id, attempt.id, task.objective

    partial = ExecutionResult(prompt="", messages=[], result="")
    await SqlAlchemyAgentTaskAdapter().persist_agent_run_state(task_id,
        expected_objective=objective, expected_attempt_id=attempt_id, execution_result=partial)
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        attempt = await db.get(TaskAttempt, attempt_id)
        snapshot = (await activity_snapshots([task]))[0]
        assert snapshot.last_activity_at > old
        assert snapshot.live is None  # Generated arguments are not an executed tool.
        assert task.get_execution_result() == partial
        assert attempt.data["effect_checkpoint"] == {"receipt": "synthetic-saved"}
        task.data = {"_agent_run_identity": {"request_run_id": str(uuid4())}}
        await db.flush()
        assert (await activity_snapshots([task]))[0].last_activity_at == old


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["checkpoint", "progress", "event", "activate", "resource", "capsule", "finalize", "force_terminate"])
async def test_run_writes_do_not_wait_for_uncommitted_llm_trace(
    committed_database, monkeypatch, operation,
) -> None:
    """A trace's foreign keys must not block the run waiting for its checkpoint."""
    from app.llm.models import LLMCall

    engine = committed_database.kw["bind"].sync_engine

    def bound_lock_wait(connection):
        connection.exec_driver_sql("SET LOCAL lock_timeout = '300ms'")

    event.listen(engine, "begin", bound_lock_wait)
    try:
        token, run_id = uuid4(), uuid4()
        async with get_db_session() as db:
            task = Task(label="Concurrent trace", objective="<p>Continue safely</p>",
                status=TaskStatus.EXEC, lease_token=token,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                data={"existing": "keep"})
            db.add(task)
            await db.flush()
            attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH",
                status="CLAIMED", worker_id="test-worker", lease_token=token, data={})
            db.add(attempt)
            await db.flush()
            task_id, attempt_id = task.id, attempt.id

        adapter = SqlAlchemyAgentTaskAdapter()
        async with get_db_session() as trace_db:
            call = LLMCall(task_id=task_id, task_attempt_id=attempt_id)
            trace_db.add(call)
            await trace_db.flush()
            # Hold the actual FK locks until the run write returns, as happens when
            # an inference or tool is waiting for durable progress before committing.
            async with get_db_session() as writer_db:
                current = await writer_db.get(Task, task_id)
                if operation in {"checkpoint", "progress"}:
                    await adapter.persist_agent_run_state(task_id,
                        expected_objective="<p>Continue safely</p>",
                        expected_attempt_id=attempt_id,
                        data_patch={"_agent_run_checkpoint": {"status": "running"}},
                        execution_result=ExecutionResult(prompt="run", result="partial")
                        if operation == "progress" else None)
                elif operation == "event":
                    await adapter.append_agent_run_event(current, AgentRunEventV1(
                        identity=AgentRunIdentityV1(task_id=task_id,
                            attempt_id=attempt_id, run_id=run_id),
                        sequence=1, kind="run.started"))
                elif operation == "activate":
                    assert await adapter.activate_agent_run(current,
                        {"request_run_id": str(run_id), "driver_code": "internal"}) == attempt_id
                elif operation == "resource":
                    await adapter.upsert_working_resource(task_id, WorkingResource(
                        resource_type="artifact", role="source",
                        reference="https://example.test/source"))
                elif operation == "finalize":
                    from app.agent import executor_service
                    await executor_service._update_task_after_execution(current,
                        ExecutionResult(prompt="run", result="Synthetic result"), base_cost=0)
                elif operation == "force_terminate":
                    from app import agent as agent_domain
                    from app.task import task_service
                    from unittest.mock import AsyncMock

                    monkeypatch.setattr(agent_domain, "handle_terminal_task", AsyncMock())
                    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
                    await task_service.force_terminate(task_id, current.revision)
                else:
                    await adapter.freeze_context_capsule(current, AgentContextCapsule(
                        contact_memory_item_id=uuid4(), rendered="Synthetic context"))
            assert trace_db.in_transaction()

        async with get_db_session() as db:
            persisted = await db.get(Task, task_id)
            recorded = await db.get(TaskAttempt, attempt_id)
            assert await db.get(LLMCall, call.id) is not None
            assert persisted.data["existing"] == "keep"
            if operation in {"checkpoint", "progress"}:
                assert recorded.data["agent_checkpoint"] == {"status": "running"}
                if operation == "progress":
                    assert persisted.get_execution_result().result == "partial"
            elif operation == "event":
                assert recorded.data["agent_events"][0]["kind"] == "run.started"
            elif operation == "activate":
                assert recorded.data["agent_run"]["request_run_id"] == str(run_id)
            elif operation == "resource":
                assert (await adapter.get_working_set(task_id)).active("source")
            elif operation == "finalize":
                assert persisted.status == TaskStatus.SUCCESS
                assert persisted.get_execution_result().result == "Synthetic result"
            elif operation == "force_terminate":
                assert persisted.status == TaskStatus.ERROR
                assert persisted.lease_token is None
                assert recorded.status == TaskAttemptStatus.CANCELLED.value
            else:
                assert (await adapter.get_context_capsule(persisted)).rendered == "Synthetic context"
    finally:
        event.remove(engine, "begin", bound_lock_wait)


@pytest.mark.asyncio
@pytest.mark.parametrize("superseded", ["lease", "expired", "terminal", "force_terminated"])
async def test_checkpoint_is_archived_and_late_attempt_cannot_overwrite_it(db, monkeypatch, superseded):
    token = uuid4()
    task = Task(id=uuid4(), label="Fenced checkpoint", objective="<p>Once</p>",
                status=TaskStatus.EXEC, lease_token=token,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), data={})
    attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH", status="CLAIMED",
                          worker_id="first", lease_token=token, data={})
    db.add_all([task, attempt])
    await db.commit()
    adapter = SqlAlchemyAgentTaskAdapter()
    checkpoint = {"data": {"effects": [{"operation_id": str(uuid4()), "status": "started"}]}}
    await adapter.persist_agent_run_state(task.id, expected_objective="<p>Once</p>",
        expected_attempt_id=attempt.id, data_patch={"_agent_run_checkpoint": checkpoint})
    await db.refresh(task)
    await db.refresh(attempt)
    assert attempt.data["agent_checkpoint"] == checkpoint
    if superseded == "lease":
        task.lease_token = uuid4()
    elif superseded == "expired":
        task.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif superseded == "force_terminated":
        from app import agent as agent_domain
        from app.task import task_service
        from unittest.mock import AsyncMock

        monkeypatch.setattr(agent_domain, "handle_terminal_task", AsyncMock())
        monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
        await task_service.force_terminate(task.id, task.revision)
    else:
        attempt.status = "SUCCEEDED"
    await db.commit()
    with pytest.raises(StaleAgentRunError):
        await adapter.persist_agent_run_state(task.id, expected_objective="<p>Once</p>",
            expected_attempt_id=attempt.id, data_patch={"_agent_run_checkpoint": {"data": {"effects": []}}})
    await db.refresh(task)
    await db.refresh(attempt)
    assert task.data["_agent_run_checkpoint"] == checkpoint
    assert attempt.data["agent_checkpoint"] == checkpoint


@pytest.mark.asyncio
async def test_agent_run_identity_and_semantic_events_are_bound_to_attempt(db) -> None:
    task_id = uuid4()
    lease_token = uuid4()
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        status=TaskAttemptStatus.CLAIMED.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    task = Task(
        id=task_id,
        label="trace",
        objective="Trace this run",
        status=TaskStatus.DISPATCH,
        effort="standard",
        lease_token=lease_token,
        data={},
    )
    db.add_all([task, attempt])
    await db.flush()
    run_id = uuid4()
    adapter = SqlAlchemyAgentTaskAdapter()

    attempt_id = await adapter.activate_agent_run(
        task,
        {
            "request_run_id": str(run_id),
            "driver_code": "internal",
            "target_ref": "agent:3:driver:internal",
        },
    )

    assert attempt_id == attempt.id
    assert task.data is not None
    assert task.data["_agent_run_identity"]["attempt_id"] == str(attempt.id)
    await adapter.append_agent_run_event(
        task,
        AgentRunEventV1(
            identity=AgentRunIdentityV1(
                task_id=task.id,
                attempt_id=attempt.id,
                run_id=run_id,
            ),
            sequence=1,
            kind="run.completed",
            result=ExecutionResult(prompt="p", result="done"),
        ),
    )

    await db.refresh(attempt)
    persisted = await db.scalar(select(TaskAttempt).where(TaskAttempt.id == attempt.id))
    assert persisted is not None
    assert persisted.data is not None
    assert persisted.data["agent_run"]["request_run_id"] == str(run_id)
    assert [event["kind"] for event in persisted.data["agent_events"]] == [
        "run.completed"
    ]
    terminal = persisted.data["agent_events"][0]["result"]
    assert terminal["result"] == "done"
    assert "prompt" not in terminal
    assert "messages" not in terminal


@pytest.mark.asyncio
async def test_semantic_event_does_not_close_caller_savepoint(db) -> None:
    task_id = uuid4()
    lease_token = uuid4()
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        status=TaskAttemptStatus.CLAIMED.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    task = Task(
        id=task_id,
        label="trace",
        objective="Preserve the caller transaction",
        status=TaskStatus.DISPATCH,
        effort="standard",
        lease_token=lease_token,
        data={},
    )
    db.add_all([task, attempt])
    await db.commit()
    adapter = SqlAlchemyAgentTaskAdapter()

    async with db.begin_nested() as savepoint:
        await adapter.append_agent_run_event(
            task,
            AgentRunEventV1(
                identity=AgentRunIdentityV1(
                    task_id=task.id,
                    attempt_id=attempt.id,
                    run_id=uuid4(),
                ),
                sequence=1,
                kind="tool.completed",
            ),
        )

        assert savepoint.is_active
        assert await db.scalar(select(Task.id).where(Task.id == task.id)) == task.id


@pytest.mark.asyncio
async def test_run_checkpoint_does_not_close_caller_savepoint(db) -> None:
    task = Task(
        id=uuid4(),
        label="checkpoint",
        objective="Keep parallel work durable",
        status=TaskStatus.EXEC,
        effort="high",
        data={"working_set": {"version": 1, "resources": []}},
    )
    db.add(task)
    await db.commit()

    adapter = SqlAlchemyAgentTaskAdapter()
    result = ExecutionResult(prompt="research", tools_used=["search_web"])
    async with db.begin_nested() as savepoint:
        await adapter.persist_agent_run_state(
            task.id,
            expected_objective="<p>Keep parallel work durable</p>",
            data_patch={
                "_agent_run_checkpoint": {
                    "status": "running",
                    "data": {"resume_safe": True},
                }
            },
            execution_result=result,
        )

        assert savepoint.is_active
        assert await db.scalar(select(Task.id).where(Task.id == task.id)) == task.id

    await db.refresh(task)
    assert task.data is not None
    assert task.data["working_set"]["version"] == 1
    assert task.data["_agent_run_checkpoint"]["status"] == "running"
    assert task.get_execution_result() is not None
    assert task.get_execution_result().tools_used == ["search_web"]


@pytest.mark.asyncio
async def test_agent_run_state_strips_postgresql_incompatible_nuls(db) -> None:
    task = Task(
        id=uuid4(),
        label="checkpoint with NUL",
        objective="Persist external output safely",
        status=TaskStatus.EXEC,
        effort="standard",
        data={"existing": "keep\x00me"},
    )
    db.add(task)
    await db.commit()

    adapter = SqlAlchemyAgentTaskAdapter()
    await adapter.persist_agent_run_state(
        task.id,
        expected_objective="<p>Persist external output safely</p>",
        data_patch={"checkpoint": {"tool_output": "binary\x00text"}},
        execution_result=ExecutionResult(
            prompt="inspect\x00task",
            result="done\x00safely",
        ),
    )

    await db.refresh(task)
    assert task.data == {
        "existing": "keepme",
        "checkpoint": {"tool_output": "binarytext"},
    }
    result = task.get_execution_result()
    assert result is not None
    assert result.prompt == "inspecttask"
    assert result.result == "donesafely"
