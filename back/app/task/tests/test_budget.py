from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.llm.models import LLMCall
from app.task.budget import admit, inspect_budget
from app.task.models import Task, TaskStatus
from core.params import runtime_settings


@pytest.mark.asyncio
async def test_cyclic_lineage_defers_work_and_recovers_when_repaired(db, monkeypatch):
    now = datetime.now(timezone.utc)
    first, second = Task(label="First", feedback="saved"), Task(label="Second")
    db.add_all([first, second])
    await db.flush()
    first.parent_id, second.parent_id = second.id, first.id
    await db.flush()
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 1000)
    assert not await admit(db, first, now)
    assert first.next_attempt_at == now + timedelta(seconds=60)
    assert first.feedback == "saved" and first.status == TaskStatus.CREATE
    second.parent_id = None
    await db.flush()
    assert await admit(db, first, now)
    assert first.last_error is None and first.feedback == "saved"


@pytest.mark.asyncio
async def test_per_user_capacity_cannot_admit_an_unknown_execution_agent(db, monkeypatch):
    agent, *_ = await _agents(db)
    task = Task(label="No owner", agent_id=agent.id)
    db.add(task)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER", 1)
    assert not await admit(db, task, datetime.now(timezone.utc), agent_id=2147483647)
    assert task.lease_token is None and task.status == TaskStatus.CREATE


async def _agents(db):
    from app.agent.models import Agent, Title
    from core.user import UserModel

    title = Title(label="Budget test", gender="X")
    users = [UserModel(email=f"budget-{uuid4().hex}@example.test", hashed_password="unused") for _ in range(2)]
    db.add_all([title, *users])
    await db.flush()
    agents = [Agent(user_id=users[owner].id, title_id=title.id, code=uuid4().hex,
                    first_name="Budget", last_name="Test") for owner in (0, 0, 1)]
    db.add_all(agents)
    await db.flush()
    return agents


async def _goal(db, agent):
    from app.goal.models import Goal
    from app.memory.models import MemoryItem

    documents = [MemoryItem(owner_agent_id=agent.id, provider_code="native",
                            resource_id=f"budget-{uuid4().hex}.md", title="Budget test",
                            content_hash=uuid4().hex) for _ in range(2)]
    db.add_all(documents)
    await db.flush()
    goal = Goal(agent_id=agent.id, title="Budget across cycles",
                description_document_id=documents[0].id, tracking_document_id=documents[1].id)
    db.add(goal)
    await db.flush()
    return goal


@pytest.mark.asyncio
@pytest.mark.parametrize("cost_limit", [0.0, 0.6], ids=["tokens-only", "tokens-and-cost"])
async def test_causal_descendants_share_accounting_and_lease_reservations(db, monkeypatch, cost_limit):
    now = datetime.now(timezone.utc)
    root = Task(label="Root", status=TaskStatus.PLAN)
    db.add(root)
    await db.flush()
    child = Task(label="Planned child", parent_id=root.id)
    peer = Task(label="Delegated peer", source_task_id=root.id)
    db.add_all([child, peer])
    await db.flush()
    db.add(LLMCall(task_id=child.id, status="completed", total_tokens=600, cost=0.2))
    await db.flush()
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 1000)
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_RESERVE_TOKENS", 300)
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_COST", cost_limit)
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_RESERVE_COST", 0.3)
    assert await admit(db, child, now)
    child.lease_token = uuid4()
    child.lease_expires_at = now + timedelta(seconds=60)
    await db.flush()
    assert not await admit(db, peer, now)
    assert peer.next_attempt_at is not None
    snapshot = await inspect_budget(db, peer)
    assert snapshot.recorded_tokens == 600
    assert snapshot.recorded_cost == pytest.approx(0.2)
    assert snapshot.active_phases == 1
    assert snapshot.reserved_tokens == 300
    assert snapshot.remaining_tokens == 100
    assert snapshot.remaining_cost == (pytest.approx(0.1) if cost_limit else None)
    assert snapshot.provider_hard_cap is False
    # A crashed worker releases its reservation by lease expiry, without deleting usage.
    child.lease_expires_at = now - timedelta(seconds=1)
    await db.flush()
    assert await admit(db, peer, now)
    assert peer.last_error is None
    assert (await inspect_budget(db, peer)).reserved_tokens == 0
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 500)
    assert not await admit(db, peer, now)
    # Increasing the global limit preserves and resumes the same task lineage.
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 2000)
    assert await admit(db, peer, now)


@pytest.mark.asyncio
async def test_time_budget_and_disabled_policy_preserve_existing_results(db, monkeypatch):
    now = datetime.now(timezone.utc)
    root = Task(label="Root", created_at=now - timedelta(hours=2), feedback="partial result")
    db.add(root)
    await db.flush()
    child = Task(label="Continuation", source_task_id=root.id)
    db.add(child)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_SECONDS", 3600)
    assert not await admit(db, child, now)
    assert root.feedback == "partial result"
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_SECONDS", 0)
    assert await admit(db, child, now)
    snapshot = await inspect_budget(db, child)
    assert snapshot.enabled is False
    assert snapshot.max_tokens is snapshot.max_cost is snapshot.max_seconds is None
    assert snapshot.remaining_tokens is snapshot.remaining_cost is snapshot.remaining_seconds is None
    assert root.feedback == "partial result"


@pytest.mark.asyncio
async def test_independent_workers_cannot_reserve_the_same_root_capacity(committed_database, monkeypatch):
    from core.database.database import db_session_ctx

    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 1000)
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_RESERVE_TOKENS", 600)
    now = datetime.now(timezone.utc)
    async with committed_database() as seed:
        root = Task(label="Shared root")
        seed.add(root)
        await seed.flush()
        children = [Task(label=f"Worker {index}", parent_id=root.id) for index in range(2)]
        seed.add_all(children)
        await seed.commit()
        child_ids = [child.id for child in children]

    async with committed_database() as first, committed_database() as second:
        first_child = await first.get(Task, child_ids[0])
        second_child = await second.get(Task, child_ids[1])
        assert first_child is not None and second_child is not None
        token = db_session_ctx.set(first)
        try:
            assert await admit(first, first_child, now)
            # A second connection cannot reserve while the first holds the root lock.
            db_session_ctx.set(second)
            assert not await admit(second, second_child, now)
            await second.rollback()
            first_child.lease_token = uuid4()
            first_child.lease_expires_at = now + timedelta(minutes=1)
            await first.commit()
            second_child = await second.get(Task, child_ids[1])
            assert second_child is not None
            # Once committed, the durable lease consumes capacity across connections.
            assert not await admit(second, second_child, now)
            await second.rollback()
            await first.refresh(first_child)
            first_child.lease_expires_at = now - timedelta(seconds=1)
            await first.commit()
            second_child = await second.get(Task, child_ids[1])
            assert second_child is not None
            assert await admit(second, second_child, now)
        finally:
            db_session_ctx.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,value", [("TOKENS", 1000), ("COST", 1.0), ("SECONDS", 3600)])
async def test_goal_cycles_share_usage_and_origin_only_when_enabled(db, monkeypatch, limit, value):
    now = datetime.now(timezone.utc)
    agent, *_ = await _agents(db)
    goal = await _goal(db, agent)
    other_goal = await _goal(db, agent)
    first = Task(label="First cycle", goal_id=goal.id, agent_id=agent.id,
                 created_at=now - timedelta(hours=2), deleted_at=now, status=TaskStatus.SUCCESS)
    second = Task(label="New cycle", goal_id=goal.id, agent_id=agent.id, created_at=now)
    other = Task(label="Unrelated goal", goal_id=other_goal.id, agent_id=agent.id, created_at=now)
    db.add_all([first, second, other])
    await db.flush()
    descendant = Task(label="Delegation", source_task_id=first.id, deleted_at=now)
    db.add(descendant)
    await db.flush()
    db.add(LLMCall(task_id=descendant.id, status="completed", total_tokens=900, cost=0.9))
    await db.flush()
    monkeypatch.setattr(runtime_settings, f"TASK_ROOT_MAX_{limit}", value)
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_RESERVE_TOKENS", 200)
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_RESERVE_COST", 0.2)
    assert await admit(db, second, now)
    monkeypatch.setattr(runtime_settings, "TASK_BUDGET_SHARE_GOAL", True)
    assert not await admit(db, second, now)
    snapshot = await inspect_budget(db, second)
    assert snapshot.scope == "goal"
    assert snapshot.recorded_tokens == 900
    assert snapshot.recorded_cost == pytest.approx(0.9)
    assert second.next_attempt_at is not None
    assert await admit(db, other, now)
    assert second.status == TaskStatus.CREATE
    monkeypatch.setattr(runtime_settings, f"TASK_ROOT_MAX_{limit}", value * 10)
    assert await admit(db, second, now)
    assert second.last_error is None


@pytest.mark.asyncio
async def test_archiving_a_causal_task_cannot_reset_its_budget(db, monkeypatch):
    now = datetime.now(timezone.utc)
    root = Task(label="Archived root", deleted_at=now)
    db.add(root)
    await db.flush()
    child = Task(label="Still running", source_task_id=root.id)
    db.add_all([child, LLMCall(task_id=root.id, total_tokens=1000, status="completed")])
    await db.flush()
    monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 1000)
    db.expunge(root)
    assert not await admit(db, child, now)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["owner", "goal"])
async def test_independent_workers_share_capacity_across_agents_and_cycles(committed_database, monkeypatch, policy):
    from core.database.database import db_session_ctx

    if policy == "owner":
        monkeypatch.setattr(runtime_settings, "TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER", 1)
    else:
        monkeypatch.setattr(runtime_settings, "TASK_BUDGET_SHARE_GOAL", True)
        monkeypatch.setattr(runtime_settings, "TASK_ROOT_MAX_TOKENS", 1000)
        monkeypatch.setattr(runtime_settings, "TASK_ROOT_RESERVE_TOKENS", 600)
    now = datetime.now(timezone.utc)
    async with committed_database() as seed:
        agents = await _agents(seed)
        goal = await _goal(seed, agents[0])
        tasks = [Task(label=f"Cycle {i}", agent_id=agent.id, goal_id=goal.id if i < 2 else None)
                 for i, agent in enumerate(agents)]
        seed.add_all(tasks)
        await seed.commit()
        ids = [task.id for task in tasks]
    async with committed_database() as first, committed_database() as second:
        token = db_session_ctx.set(first)
        try:
            task = await first.get(Task, ids[0])
            assert await admit(first, task, now)
            db_session_ctx.set(second)
            peer = await second.get(Task, ids[1])
            assert not await admit(second, peer, now)
            await second.rollback()
            task.lease_token = uuid4()
            task.lease_expires_at = now + timedelta(minutes=1)
            task.deleted_at = now  # A hidden but running lease still consumes capacity.
            await first.commit()
            peer = await second.get(Task, ids[1])
            assert not await admit(second, peer, now)
            other = await second.get(Task, ids[2])
            assert await admit(second, other, now)
            await second.rollback()
            task.lease_expires_at = now - timedelta(seconds=1)
            await first.commit()
            peer = await second.get(Task, ids[1])
            assert await admit(second, peer, now)
            assert peer.last_error is None
        finally:
            db_session_ctx.reset(token)
