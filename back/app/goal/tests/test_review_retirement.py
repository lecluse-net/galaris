"""Retire the old schema/control metadata, preserving the corresponding Tasks."""

from copy import deepcopy

import pytest
from sqlalchemy import func, select, text

from app.goal import dbadmin
from app.goal.tests.test_autonomous_goal import setup_cycle
from app.task import Task, TaskCreate, TaskStatus, task_service
from core.database import get_db_session
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, SchemaTransitionSet


DELTA = SchemaTransitionSet(removed_columns=frozenset({"goal_cycles.review_task_id"}))


async def legacy_graph(session):
    goal, cycle, source = await setup_cycle(session)
    source.data = {**(source.data or {}), "retention_reasons": ["goal_judgement"]}
    identities = []
    for marked in (False, True):
        data = {"retention_reasons": ["goal_judgement", "synthetic_other_owner"],
                "synthetic_checkpoint": {"preserve": True}}
        if marked:
            data["goal_review"] = {"cycle": str(cycle.id)}
        task = task_service.build(TaskCreate(label="Synthetic ordinary work", objective="<p>Preserve this Task.</p>",
            agent_id=source.agent_id, goal_id=goal.id, parent_id=source.id,
            status=TaskStatus.EXEC if marked else TaskStatus.SUCCESS, cost=0.2, data=data))
        task.feedback = "Synthetic acquired result."
        session.add(task)
        await session.flush()
        identities.append(task.id)
    await session.execute(text("""ALTER TABLE public.goal_cycles ADD COLUMN review_task_id uuid
        REFERENCES public.tasks(id) ON DELETE SET NULL"""))
    await session.execute(text("CREATE UNIQUE INDEX ix_goal_cycles_review_task_id ON public.goal_cycles(review_task_id)"))
    await session.execute(text("UPDATE public.goal_cycles SET review_task_id=:task WHERE id=:cycle"),
        {"task": identities[0], "cycle": cycle.id})
    await session.commit()
    return source.id, identities


async def task_snapshots(session, identities):
    tasks = list(await session.scalars(select(Task).where(Task.id.in_(identities))
        .execution_options(populate_existing=True)))
    return {task.id: {"row": (await session.execute(text(
        "SELECT to_jsonb(t)-'data' FROM public.tasks t WHERE id=:id"), {"id": task.id})).scalar_one(),
        "data": deepcopy(task.data)} for task in tasks}


def test_retirement_is_triggered_only_by_its_removed_column():
    assert dbadmin.needs_review_retirement(DELTA)
    assert not dbadmin.needs_review_retirement(SchemaTransitionSet())
    assert not dbadmin.needs_review_retirement(SchemaTransitionSet(removed_columns=frozenset({"goals.unrelated"})))


@pytest.mark.asyncio
async def test_metadata_retirement_is_atomic_idempotent_and_preserves_task_state(db):
    source_id, retired_ids = await legacy_graph(db)
    identities = [source_id, *retired_ids]
    before = await task_snapshots(db, identities)
    assert not await dbadmin.review_retirement_complete(db, DELTA)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        async with db.begin_nested():
            await dbadmin.retire_review_metadata(db, DELTA)
            raise RuntimeError("Synthetic interruption")
    assert await task_snapshots(db, identities) == before
    await dbadmin.retire_review_metadata(db, DELTA)
    assert await dbadmin.review_retirement_complete(db, DELTA)
    await dbadmin.retire_review_metadata(db, DELTA)
    after = await task_snapshots(db, identities)
    assert set(after) == set(before)
    assert after[source_id] == before[source_id]
    for identity in retired_ids:
        assert after[identity]["row"] == before[identity]["row"]
        expected_data = deepcopy(before[identity]["data"])
        expected_data.pop("goal_review", None)
        expected_data["retention_reasons"] = ["synthetic_other_owner"]
        assert after[identity]["data"] == expected_data


@pytest.mark.asyncio
async def test_real_dbadmin_contraction_drops_reference_but_keeps_every_task(committed_database, monkeypatch):
    from core.dbadmin import orchestrator
    from core.dbadmin._internal import atlas

    factory = committed_database
    isolated_engine = factory.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", isolated_engine)
    monkeypatch.setattr(atlas, "engine", isolated_engine)
    monkeypatch.setattr(atlas.settings, "POSTGRES_DB", isolated_engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda _registry: None)
    registry = DbAdminRegistry()
    dbadmin.register_dbadmin(registry)
    async with get_db_session() as session:
        source_id, retired_ids = await legacy_graph(session)
        before = await task_snapshots(session, [source_id, *retired_ids])
        count = await session.scalar(select(func.count()).select_from(Task))
    result = await orchestrator.synchronize_database(target_registry=registry)
    assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
    assert "goal_cycles.review_task_id" in result.transitions.removed_columns
    async with factory() as session:
        assert not await dbadmin._review_reference_exists(session)
        assert await dbadmin.review_retirement_complete(session, DELTA)
        assert await session.scalar(select(func.count()).select_from(Task)) == count
        after = await task_snapshots(session, [source_id, *retired_ids])
        assert after[source_id] == before[source_id]
        assert all(after[identity]["row"] == before[identity]["row"] for identity in retired_ids)
    repeated = await orchestrator.synchronize_database(target_registry=registry)
    assert repeated.verdict is DbAdminVerdict.CONVERGED, repeated.issues
