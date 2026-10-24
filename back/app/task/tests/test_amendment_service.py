from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db_session

from app.task import amendment_service, scheduler, task_service
from app.task.models import Task, TaskAmendment, TaskStatus


def _task(**values: object) -> Task:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "revision": 1,
        "label": "Quarterly report",
        "objective": "Prepare the quarterly report.",
        "status": TaskStatus.DISPATCH,
        "paused": False,
        "ai": True,
        "cost": 0.0,
    }
    defaults.update(values)
    return Task(**defaults)


@pytest.mark.asyncio
async def test_delegated_amendment_survives_a_new_session_and_is_applied_before_synthesis(committed_database, monkeypatch):
    from app.agent import executor_service
    from app.agent.contracts import ExecutionResult
    from app.task import collab
    monkeypatch.setattr(scheduler, "wake", MagicMock())
    cancel = MagicMock()
    monkeypatch.setattr(scheduler, "cancel", cancel)
    monkeypatch.setattr(amendment_service, "_MAX_PENDING_AMENDMENTS", 2)
    monkeypatch.setattr("app.task.runner.go_next", lambda *_args, **_kwargs: None)
    async with get_db_session() as db:
        parent = _task(status=TaskStatus.EXEC, objective="<p>Budget 7200 EUR, engagements 6300 EUR.</p>")
        db.add(parent)
        await db.flush()
        children = [_task(parent_id=parent.id, source_task_id=parent.id, status=TaskStatus.EXEC,
                          data={"delegated": True}) for _ in range(2)]
        db.add_all(children)
        await db.commit()
        revision = parent.revision
        parent_id, child_ids = parent.id, [child.id for child in children]
        command = dict(task_id=parent.id, expected_revision=revision,
            instruction="Le budget passe à 6800 EUR ; les engagements restent de 6300 EUR.",
            disposition="AMEND_CURRENT", reason="Same summary, revised budget", source_kind="conversation_round",
            source_id="synthetic-budget-round", idempotency_key="synthetic-budget-amendment")
        first = await amendment_service.amend_task(**command)
        repeated = await amendment_service.amend_task(**command)
        assert first.deferred and not first.interrupted and not repeated.created
        assert first.amendment.applied_at is None
        assert parent.revision == revision and "6800" not in parent.objective
        assert all(child.status == TaskStatus.EXEC for child in children)
        second = {**command, "instruction": "Conserver les inscriptions ouvertes.", "idempotency_key": "second-budget-instruction"}
        assert (await amendment_service.amend_task(**second)).deferred
        with pytest.raises(task_service.TaskEditConflict, match="too many pending"):
            await amendment_service.amend_task(**{**second, "idempotency_key": "third-budget-instruction"})
        assert not (await amendment_service.amend_task(**command)).created
    cancel.assert_not_called()
    # A different session simulates recovery after the receiving worker has exited.
    async with get_db_session() as db:
        parent = await db.get(Task, parent_id)
        for child_id in child_ids:
            child = await db.get(Task, child_id)
            child.status, child.feedback = TaskStatus.SUCCESS, "Original reserve: 900 EUR."
        await db.commit()
        await executor_service._update_task_after_execution(parent,
            ExecutionResult(prompt="Initial work", result="Original budget", success=True), base_cost=0)
        assert parent.status == TaskStatus.DISPATCH and not parent.paused
        assert "6800" in parent.objective
        assert parent.objective.index(command["instruction"]) < parent.objective.index(second["instruction"])
        amendment = await db.scalar(select(TaskAmendment).where(TaskAmendment.task_id == parent_id))
        assert amendment.applied_at is not None
        assert "900 EUR" in collab.collab_context(parent)
        await collab.maybe_fan_in(parent_id)
        assert parent.objective.count(command["instruction"]) == 1
        # The revised synthesis, rather than the superseded result, may now become final.
        parent.status = TaskStatus.EXEC
        await task_service.save(parent)
        await executor_service._update_task_after_execution(parent,
            ExecutionResult(prompt=parent.objective, result="6800 - 6300 = 500 EUR", success=True), base_cost=0)
        assert parent.status == TaskStatus.SUCCESS and "500 EUR" in parent.feedback
        for child_id in child_ids:
            child = await db.get(Task, child_id)
            assert child.status == TaskStatus.SUCCESS and child.feedback == "Original reserve: 900 EUR."


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["resume", "cancel", "unsafe_checkpoint"])
async def test_deferred_instruction_respects_human_hold_and_terminal_state(db, monkeypatch, outcome):
    from app.task import collab
    from app.task.workflow import TaskEvent, transition
    monkeypatch.setattr("app.task.runner.go_next", lambda *_args, **_kwargs: None)
    parent = _task(paused=True, data={"pause_reasons": ["user", "child"]})
    db.add(parent)
    await db.flush()
    child = _task(parent_id=parent.id, status=TaskStatus.EXEC, data={"delegated": True})
    db.add(child)
    await db.commit()
    queued = await amendment_service.amend_task(task_id=parent.id, expected_revision=parent.revision,
        instruction="Use revised constraints", disposition="AMEND_CURRENT", reason=None,
        source_kind="conversation_round", source_id="held-parent", idempotency_key="held-parent-change")
    child.status, child.feedback = TaskStatus.SUCCESS, "Preserved contribution"
    await db.commit()
    await collab.maybe_fan_in(parent.id)
    assert queued.amendment.applied_at is None and parent.paused
    if outcome == "cancel":
        transition(parent, TaskEvent.CANCEL)
    else:
        task_service.release(parent, "user")
        if outcome == "unsafe_checkpoint":
            parent.data = {**parent.data, "_agent_run_checkpoint": {
                "driver_code": "hermes", "runtime_run_id": "remote-run", "status": "interrupted",
                "data": {"version": 4, "resume_safe": True, "effects": []}}}
    await task_service.save(parent)
    await collab.maybe_fan_in(parent.id)
    await db.refresh(queued.amendment)
    assert (queued.amendment.applied_at is None) is (outcome != "resume")
    assert ("Use revised constraints" in parent.objective) is (outcome == "resume")
    assert parent.status == (TaskStatus.ERROR if outcome == "cancel" else TaskStatus.DISPATCH)
    if outcome == "unsafe_checkpoint":
        assert parent.paused and parent.last_error
    assert child.status == TaskStatus.SUCCESS and child.feedback == "Preserved contribution"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["checkpoint", "remote_checkpoint", "execution_started", "objective", "plan", "terminal", "forced_effort"])
async def test_amendment_rechecks_definition_after_another_session_commits(committed_database, monkeypatch, change):
    import asyncio

    monkeypatch.setattr(scheduler, "wake", MagicMock())
    cancel = MagicMock()
    monkeypatch.setattr(scheduler, "cancel", cancel)
    safe_checkpoint = {"driver_code": "internal", "runtime_run_id": "synthetic-run",
        "status": "interrupted", "data": {"version": 4, "resume_safe": True, "effects": []}}
    async with get_db_session() as db:
        task = _task(status=TaskStatus.CREATE)
        db.add(task)
        await db.flush()
        task_id, revision = task.id, task.revision
        basis = amendment_service.amendment_basis(task)
    loaded = asyncio.Event()
    committed = asyncio.Event()
    async def amend_from_old_snapshot():
        async with get_db_session() as db:
            retained = await db.get(Task, task_id)
            assert retained is not None
            loaded.set()
            await committed.wait()
            kwargs = dict(task_id=task_id, expected_revision=revision, expected_basis=basis,
                normalize_disposition=True,
                instruction="Add the PDF.", disposition="AMEND_QUEUED", reason=None,
                source_kind="conversation_round", source_id="test-round", idempotency_key="one-amendment")
            if change == "checkpoint":
                result = await amendment_service.amend_task(**kwargs)
                assert result.created
                assert result.task.data["_agent_run_checkpoint"] == safe_checkpoint
            elif change in {"remote_checkpoint", "execution_started"}:
                with pytest.raises(task_service.TaskEditConflict):
                    await amendment_service.amend_task(**kwargs)
            else:
                with pytest.raises(task_service.TaskRevisionConflict):
                    await amendment_service.amend_task(**kwargs)
    async def update():
        await loaded.wait()
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            if change == "checkpoint":
                task.data = {"_agent_run_checkpoint": safe_checkpoint}
            elif change == "remote_checkpoint":
                task.data = {"_agent_run_checkpoint": {**safe_checkpoint, "driver_code": "hermes"}}
            elif change == "execution_started":
                task.lease_token = uuid4()
            elif change == "objective":
                task.objective = "<p>Another objective</p>"
            elif change == "plan":
                task.plan = {"steps": [], "cursor": 0}
            elif change == "terminal":
                task.status = TaskStatus.SUCCESS
            else:
                task.forced_effort = "high"
        committed.set()
    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(amend_from_old_snapshot())
        group.create_task(update())
    async with get_db_session() as db:
        amendments = list(await db.scalars(select(TaskAmendment).where(TaskAmendment.task_id == task_id)))
        assert len(amendments) == (1 if change == "checkpoint" else 0)
        if change in {"remote_checkpoint", "execution_started"}:
            task = await db.get(Task, task_id)
            assert "Add the PDF." not in task.objective
    cancel.assert_not_called()


@pytest.mark.asyncio
async def test_revision_remains_strict_without_a_known_definition(db):
    task = _task(status=TaskStatus.CREATE)
    db.add(task)
    await db.commit()
    revision = task.revision
    task.data = {"progress": "changed"}
    await db.commit()
    with pytest.raises(task_service.TaskRevisionConflict):
        await amendment_service.amend_task(task_id=task.id, expected_revision=revision,
            instruction="Add PDF", disposition="AMEND_QUEUED", reason=None,
            source_kind="http", source_id="client", idempotency_key="strict-command")


@pytest.mark.asyncio
async def test_amendment_is_audited_and_routes_through_create(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(
        execution_result={"prompt": "old", "result": "partial", "success": True},
        feedback="Partial result",
        last_error="Old error",
        data={
            "_agent_run_checkpoint": {
                "driver_code": "internal",
                "runtime_run_id": "run-1",
                "status": "running",
                "data": {"version": 1, "resume_safe": True},
            }
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    initial_revision = task.revision
    wake = MagicMock()
    monkeypatch.setattr(scheduler, "wake", wake)

    result = await amendment_service.amend_task(
        task_id=task.id,
        expected_revision=initial_revision,
        instruction="Also produce a PDF version.",
        disposition="AMEND_QUEUED",
        reason="Same deliverable, new output format.",
        source_kind="conversation_round",
        source_id="round-1",
        idempotency_key="amendment-key-1",
    )

    assert result.created is True
    assert result.task.id == task.id
    assert result.task.status == TaskStatus.CREATE
    assert "Also produce a PDF version." in str(result.task.objective)
    assert result.task.revision == initial_revision + 1
    assert result.task.execution_result is None
    assert result.task.feedback is None
    assert result.task.last_error is None
    assert result.task.data is not None
    assert "_agent_run_checkpoint" in result.task.data
    amendment = await db.scalar(
        select(TaskAmendment).where(TaskAmendment.task_id == task.id)
    )
    assert amendment is not None
    assert amendment.disposition == "AMEND_QUEUED"
    assert amendment.reason == "Same deliverable, new output format."
    wake.assert_called_once_with(task.id)


@pytest.mark.asyncio
async def test_amendment_idempotency_does_not_append_twice(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(status=TaskStatus.CREATE)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    monkeypatch.setattr(scheduler, "wake", MagicMock())
    kwargs = {
        "task_id": task.id,
        "expected_revision": task.revision,
        "instruction": "Use the revised template.",
        "disposition": "AMEND_QUEUED",
        "reason": None,
        "source_kind": "conversation_round",
        "source_id": "round-2",
        "idempotency_key": "amendment-key-2",
    }

    first = await amendment_service.amend_task(**kwargs)
    second = await amendment_service.amend_task(**kwargs)

    assert first.created is True
    assert second.created is False
    assert str(second.task.objective).count("Use the revised template.") == 1
    rows = (
        await db.scalars(
            select(TaskAmendment).where(TaskAmendment.task_id == task.id)
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_materialized_plan_rejects_silent_amendment(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(plan={"steps": [], "cursor": 0})
    db.add(task)
    await db.commit()
    await db.refresh(task)
    monkeypatch.setattr(scheduler, "wake", MagicMock())

    with pytest.raises(task_service.TaskEditConflict, match="materialized plan"):
        await amendment_service.amend_task(
            task_id=task.id,
            expected_revision=task.revision,
            instruction="Change the scope.",
            disposition="AMEND_CURRENT",
            reason=None,
            source_kind="conversation_round",
            source_id="round-3",
            idempotency_key="amendment-key-3",
        )


@pytest.mark.asyncio
async def test_user_held_amendment_revises_resume_phase(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(
        paused=True,
        data={"pause_reasons": [task_service.PAUSE_USER]},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    wake = MagicMock()
    monkeypatch.setattr(scheduler, "wake", wake)

    result = await amendment_service.amend_task(
        task_id=task.id,
        expected_revision=task.revision,
        instruction="Add the legal appendix after resumption.",
        disposition="AMEND_CURRENT",
        reason=None,
        source_kind="conversation_round",
        source_id="round-4",
        idempotency_key="amendment-key-4",
    )

    assert result.task.status == TaskStatus.CREATE
    assert result.task.paused is True
    assert task_service.pause_reasons(result.task) == [task_service.PAUSE_USER]
    wake.assert_not_called()


@pytest.mark.asyncio
async def test_current_disposition_rejects_a_queued_task(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(status=TaskStatus.CREATE)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    monkeypatch.setattr(scheduler, "wake", MagicMock())

    with pytest.raises(task_service.TaskEditConflict, match="AMEND_QUEUED"):
        await amendment_service.amend_task(
            task_id=task.id,
            expected_revision=task.revision,
            instruction="Use the new template.",
            disposition="AMEND_CURRENT",
            reason=None,
            source_kind="conversation_round",
            source_id="round-5",
            idempotency_key="amendment-key-5",
        )
