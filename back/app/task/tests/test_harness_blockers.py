from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.task import scheduler, task_service
from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter
from app.task.models import Task, TaskAttempt, TaskStatus


def _task(
    *, agent_id: int, label: str, paused: bool, parent_id: UUID | None = None
) -> Task:
    return Task(
        id=uuid4(),
        agent_id=agent_id,
        parent_id=parent_id,
        label=label,
        objective=label,
        status=TaskStatus.DISPATCH,
        paused=paused,
        ai=False,
        cost=0.0,
        effort="standard",
        auto_approve=False,
    )


@pytest.mark.asyncio
async def test_harness_blockers_only_report_open_root_tasks(db: AsyncSession) -> None:
    title = Title(label=f"Harness blockers {uuid4()}", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Harness",
        last_name="Owner",
        code=f"hb-{uuid4().hex}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    paused = _task(agent_id=agent.id, label="Paused root", paused=True)
    active = _task(agent_id=agent.id, label="Active root", paused=False)
    # An attempt failure is not a terminal Task: pending retries must stay visible.
    active.last_error = "Temporary failure in name resolution"
    active.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    active.attempt_count = 5
    paused_child = _task(
        agent_id=agent.id,
        label="Paused child",
        paused=True,
        parent_id=paused.id,
    )
    terminal = _task(agent_id=agent.id, label="Terminal", paused=False)
    terminal.status = TaskStatus.SUCCESS
    deleted = _task(agent_id=agent.id, label="Deleted root", paused=False)
    deleted.deleted_at = datetime.now(timezone.utc)
    db.add_all([paused, active, paused_child, terminal, deleted])
    await db.commit()

    blockers = await SqlAlchemyAgentTaskAdapter().harness_blockers(agent.id)

    assert [(task.id, task.label) for task in blockers.paused_tasks] == [
        (paused.id, "Paused root")
    ]
    assert blockers.active_count == 1
    assert [(task.id, task.label) for task in blockers.active_tasks] == [
        (active.id, "Active root")
    ]
    open_tasks = await SqlAlchemyAgentTaskAdapter().list_for_agent(agent.id, limit=50)
    assert {task.id for task in open_tasks} == {paused.id, active.id}


@pytest.mark.asyncio
async def test_terminate_paused_for_agent_uses_force_termination(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title = Title(label=f"Terminate blockers {uuid4()}", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Harness",
        last_name="Owner",
        code=f"tb-{uuid4().hex}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    paused = _task(agent_id=agent.id, label="Paused root", paused=True)
    db.add(paused)
    await db.commit()

    async def terminate(task_id: UUID, expected_revision: int | None) -> Task:
        assert task_id == paused.id
        assert expected_revision is None
        paused.status = TaskStatus.ERROR
        paused.paused = False
        await db.commit()
        return paused

    force_terminate = AsyncMock(side_effect=terminate)
    monkeypatch.setattr(task_service, "force_terminate", force_terminate)

    blockers = await SqlAlchemyAgentTaskAdapter().force_terminate_paused_for_agent(
        agent.id
    )

    force_terminate.assert_awaited_once_with(paused.id, None)
    assert blockers.paused_tasks == ()
    assert blockers.active_count == 0
    assert blockers.active_tasks == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_failures,still_blocks", [(6, True), (7, False)])
async def test_network_retry_budget_releases_harness_blocker_when_exhausted(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
    previous_failures: int, still_blocks: bool,
) -> None:
    title = Title(label=f"Retry blockers {uuid4()}", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id, first_name="Retry", last_name="Owner",
        code=f"retry-{uuid4().hex}", agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    agent_id = agent.id
    task = _task(agent_id=agent_id, label="Network retry", paused=False)
    task_id, token = task.id, uuid4()
    task.lease_token = token
    task.consecutive_failures = previous_failures
    task.attempt_count = previous_failures + 1
    attempt = TaskAttempt(
        task_id=task_id, attempt_number=task.attempt_count,
        phase=TaskStatus.DISPATCH.value, worker_id="test-worker", lease_token=token,
    )
    db.add_all([task, attempt])
    await db.commit()
    monkeypatch.setattr(scheduler.runtime_settings, "TASK_NETWORK_MAX_ATTEMPTS", 8)
    monkeypatch.setattr(scheduler, "wake", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "_resume_after_terminal_failure", AsyncMock())

    await scheduler._fail_claim(
        task_id, TaskStatus.DISPATCH, token,
        ConnectionError("Temporary failure in name resolution"),
    )

    db.expire_all()
    updated = await db.get(Task, task_id)
    assert updated is not None
    assert updated.lease_token is None
    assert updated.status == (TaskStatus.DISPATCH if still_blocks else TaskStatus.ERROR)
    assert (updated.next_attempt_at is not None) == still_blocks
    blockers = await SqlAlchemyAgentTaskAdapter().harness_blockers(agent_id)
    assert blockers.active_count == int(still_blocks)
    assert [item.id for item in blockers.active_tasks] == ([task_id] if still_blocks else [])
