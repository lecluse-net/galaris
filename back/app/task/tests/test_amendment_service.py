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
