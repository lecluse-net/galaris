from core.dbadmin import DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.dbadmin.contracts import RequiredColumnTransition

from app.agent.dbadmin import register_dbadmin

import pytest
from sqlalchemy import delete, select, update
from app.agent.models import Agent, AgentGroup, Title
from app.agent.models import AgentTeam
from core.dbadmin.actions import run_actions
from core.dbadmin.models import DbAdminActionRecord


@pytest.mark.asyncio
async def test_fresh_database_has_initial_titles_and_initialization_is_idempotent(db):
    expected = {("agent_titles.mr", "M"), ("agent_titles.ms", "F")}
    # The real DbAdmin startup of the isolated PostgreSQL database seeds these rows.
    assert set((await db.execute(select(Title.label, Title.gender))).tuples()) == expected
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    action = next(action for action in registry.actions if action.key == "app.agent.initial_titles")
    initial_delta = SchemaTransitionSet(added_tables=frozenset({"titles"}))
    assert action.predicate(initial_delta)
    assert not action.predicate(SchemaTransitionSet())

    await db.execute(delete(Title))
    assert not await action.postcondition(db, initial_delta)
    await action.handler(db, initial_delta)
    await action.handler(db, initial_delta)
    assert await action.postcondition(db, initial_delta)
    rows = list((await db.execute(select(Title.label, Title.gender))).tuples())
    assert len(rows) == 2 and set(rows) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("previously_initialized", [False, True])
async def test_later_sync_preserves_edited_deleted_and_custom_titles_even_when_all_are_removed(db, previously_initialized):
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    if not previously_initialized:
        # An existing installation predating these defaults has no action journal.
        await db.execute(delete(DbAdminActionRecord).where(DbAdminActionRecord.key == "app.agent.initial_titles"))
    await db.execute(update(Title).where(Title.label == "agent_titles.mr").values(label="Custom title", gender="F"))
    await db.execute(delete(Title).where(Title.label == "agent_titles.ms"))
    db.add(Title(label="Another title", gender="M"))
    await db.commit()
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not results and not issues
    assert set((await db.execute(select(Title.label, Title.gender))).tuples()) == {
        ("Custom title", "F"), ("Another title", "M"),
    }

    await db.execute(delete(Title))
    await db.commit()
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not results and not issues
    assert list(await db.scalars(select(Title))) == []


@pytest.mark.asyncio
async def test_legacy_group_membership_is_preserved_and_backfill_is_idempotent(db):
    team = AgentGroup(name="Existing group")
    title = Title(label="Mx", gender="M")
    db.add_all([team, title])
    await db.flush()
    agent = Agent(code="legacy-team", first_name="Legacy", last_name="Agent", title_id=title.id, group_id=team.id)
    db.add(agent)
    await db.flush()
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    action = next(action for action in registry.actions if action.key == "app.agent.team_memberships")
    delta = SchemaTransitionSet()
    assert not await action.postcondition(db, delta)
    await action.handler(db, delta)
    await action.handler(db, delta)
    assert await action.postcondition(db, delta)
    rows = (await db.scalars(select(AgentTeam).where(AgentTeam.agent_id == agent.id))).all()
    assert len(rows) == 1 and rows[0].team_id == team.id


def test_dbadmin_registers_required_agent_manager_backfill() -> None:
    registry = DbAdminRegistry()
    register_dbadmin(registry)

    action = next(action for action in registry.actions if action.key == "app.agent.backfill_human_managers")
    assert action.key == "app.agent.backfill_human_managers"
    assert action.phase is DbAdminPhase.AFTER_EXPAND
    assert action.required is True
    assert action.predicate(
        SchemaTransitionSet(
            required_columns=(RequiredColumnTransition("agents", "user_id"),)
        )
    )
    assert not action.predicate(SchemaTransitionSet())
