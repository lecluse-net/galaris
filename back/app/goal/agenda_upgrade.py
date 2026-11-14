"""Append-only snapshots of cycles that predate the Goal agenda contract."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


async def snapshot_legacy_cycles(session: AsyncSession, goal_id: UUID | None = None) -> None:
    # Raw SQL deliberately includes retired Goals: restoring one must not rewrite its past.
    # Keep the same identity as the old read projection, and never refresh an existing snapshot.
    await session.execute(text("""INSERT INTO goal_occurrences
        (id, goal_id, cycle_id, scheduled_at, title, timezone, state)
        SELECT c.id, c.goal_id, c.id, c.created_at, g.title, 'UTC', 'linked'
        FROM goal_cycles c JOIN goals g ON g.id = c.goal_id
        WHERE (CAST(:goal AS uuid) IS NULL OR c.goal_id = CAST(:goal AS uuid))
          AND NOT EXISTS (SELECT 1 FROM goal_occurrences o WHERE o.cycle_id = c.id)
        ON CONFLICT DO NOTHING"""), {"goal": str(goal_id) if goal_id is not None else None})


def needs_agenda_snapshots(delta: SchemaTransitionSet) -> bool:
    return delta.table_added("goal_occurrences") or delta.column_added("goals", "recurrence")


async def snapshots_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return not bool(await session.scalar(text("""SELECT EXISTS (
        SELECT 1 FROM goal_cycles c WHERE NOT EXISTS (
            SELECT 1 FROM goal_occurrences o WHERE o.cycle_id = c.id))""")))


async def backfill_snapshots(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await snapshot_legacy_cycles(session)


def register_agenda_upgrade(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.goal.agenda_cycle_snapshots", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="append-only-cycle-date-title-and-task-links-v1",
        predicate=needs_agenda_snapshots, handler=backfill_snapshots,
        postcondition=snapshots_complete,
        requires_schema=frozenset({"goal_occurrences", "goals.recurrence"}),
    ))
