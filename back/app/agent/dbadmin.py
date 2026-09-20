"""DbAdmin initialization and transitions owned by the agent domain."""

from typing import cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from core.dbadmin import (
    DbAdminAction,
    DbAdminPhase,
    DbAdminRegistry,
    SchemaTransitionSet,
)
from core.user import UserModel

from .models import Agent, AgentTeam, Title


_INITIAL_TITLES = (("agent_titles.mr", "M"), ("agent_titles.ms", "F"))


async def _initialize_titles(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    existing = set((await session.execute(select(Title.label, Title.gender))).tuples())
    missing = [
        {"label": label, "gender": gender}
        for label, gender in _INITIAL_TITLES
        if (label, gender) not in existing
    ]
    if missing:
        await session.execute(insert(Title), missing)


async def _initial_titles_complete(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    existing = set((await session.execute(select(Title.label, Title.gender))).tuples())
    return set(_INITIAL_TITLES).issubset(existing)


async def _backfill_agent_teams(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    await session.execute(insert(AgentTeam).from_select(
        ["agent_id", "team_id"], select(Agent.id, Agent.group_id).where(Agent.group_id.is_not(None))
    ).on_conflict_do_nothing())


async def _teams_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    missing = await session.scalar(select(Agent.id).where(Agent.group_id.is_not(None), ~select(AgentTeam.id).where(
        AgentTeam.agent_id == Agent.id, AgentTeam.team_id == Agent.group_id
    ).exists()).limit(1))
    return missing is None


def _requires_manager_backfill(transitions: SchemaTransitionSet) -> bool:
    return any(item.key == "agents.user_id" for item in transitions.required_columns)


async def _backfill_agent_managers(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    agents = cast(Table, Agent.__table__)
    users = cast(Table, UserModel.__table__)
    fallback_user_id = (
        select(users.c.id)
        .order_by(users.c.is_active.desc(), users.c.id)
        .limit(1)
        .scalar_subquery()
    )
    await session.execute(
        update(agents)
        .where(agents.c.user_id.is_(None))
        .values(user_id=func.coalesce(agents.c.created_by, fallback_user_id))
    )


async def _all_agents_have_managers(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    agents = cast(Table, Agent.__table__)
    missing = await session.scalar(
        select(func.count()).select_from(agents).where(agents.c.user_id.is_(None))
    )
    return int(missing or 0) == 0


def register_dbadmin(registry: DbAdminRegistry) -> None:
    # A permanent dataset would recreate deleted/renamed titles on every sync.
    # These defaults belong exclusively to the creation of the titles table.
    registry.register_action(DbAdminAction(
        key="app.agent.initial_titles",
        phase=DbAdminPhase.AFTER_EXPAND,
        checksum="initial-i18n-mr-ms",
        predicate=lambda delta: delta.table_added("titles"),
        handler=_initialize_titles,
        postcondition=_initial_titles_complete,
    ))
    registry.register_action(DbAdminAction(
        key="app.agent.team_memberships", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="preserve-group-identities-and-agent-memberships",
        predicate=lambda delta: delta.table_added("agent_teams"),
        handler=_backfill_agent_teams, postcondition=_teams_complete,
    ))
    from .html_migration import register_html_conversion
    register_html_conversion(registry)
    registry.register_action(
        DbAdminAction(
            key="app.agent.backfill_human_managers",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1-created-by-then-first-user",
            predicate=_requires_manager_backfill,
            handler=_backfill_agent_managers,
            postcondition=_all_agents_have_managers,
        )
    )
