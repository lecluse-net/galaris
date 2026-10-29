"""DbAdmin initialization and transitions owned by the agent domain."""

from typing import cast

from sqlalchemy import Table, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from core.dbadmin import (
    DbAdminAction,
    DbAdminDataSource,
    DbAdminPhase,
    DbAdminRegistry,
    SchemaTransitionSet,
)
from core.user import UserModel

from .models import Agent, Title


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
    if not await _has_legacy_column(session, "group_id"):
        return
    await session.execute(text("""
        INSERT INTO agent_teams (agent_id, team_id)
        SELECT id, group_id FROM agents WHERE group_id IS NOT NULL
        ON CONFLICT (agent_id, team_id) DO NOTHING
    """))


async def _teams_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    if not await _has_legacy_column(session, "group_id"):
        return True
    missing = await session.scalar(text("""
        SELECT id FROM agents AS agent WHERE group_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM agent_teams AS membership
            WHERE membership.agent_id = agent.id AND membership.team_id = agent.group_id
        ) LIMIT 1
    """))
    return missing is None


async def _has_legacy_column(session: AsyncSession, name: str) -> bool:
    return bool(await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'agents' AND column_name = :name)
    """), {"name": name}))


async def _galaris_identity_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await _has_legacy_column(session, "initialization_key"):
        return True
    return not bool(await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM agents AS agent WHERE initialization_key = 'galaris'
            AND NOT EXISTS (SELECT 1 FROM params WHERE name = 'galaris.agent_id'
                AND value = agent.id::text))
    """)))


async def _preserve_galaris_identity(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    if not await _has_legacy_column(session, "initialization_key"):
        return
    await session.execute(text("""
        INSERT INTO params (name, value)
        SELECT 'galaris.agent_id', id::text FROM agents WHERE initialization_key = 'galaris'
        ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value
        WHERE params.value IS NULL OR params.value = ''
    """))


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
    from .defaults import default_agent_dataset

    registry.register_data_source(DbAdminDataSource(
        key="app.agent", factory=lambda: (default_agent_dataset(),),
    ))
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
        predicate=lambda delta: delta.table_added("agent_teams") or "agents.group_id" in delta.removed_columns,
        handler=_backfill_agent_teams, postcondition=_teams_complete,
    ))
    from .html_migration import register_html_conversion
    register_html_conversion(registry)
    registry.register_action(DbAdminAction(
        key="app.agent.galaris_identity", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="global-parameter-preserves-initial-agent-id",
        predicate=lambda delta: "agents.initialization_key" in delta.removed_columns,
        handler=_preserve_galaris_identity, postcondition=_galaris_identity_complete,
    ))
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
