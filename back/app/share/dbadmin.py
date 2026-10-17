"""Required, idempotent migration of existing resource sharing configurations."""

from sqlalchemy.ext.asyncio import AsyncSession
from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from .migration import transfer, complete


def needs_transfer(delta: SchemaTransitionSet) -> bool:
    return delta.table_added("share_configs") or any(
        delta.column_added(table, "share_id")
        for table in ("memory_items", "documents", "datasets", "process_definitions")
    )


async def migrate(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await transfer(session)


async def migrated(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return await complete(session)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.share.resource_acls",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="exclusive-configs-preserve-grants-and-live-owner-groups-v1",
            predicate=needs_transfer,
            handler=migrate,
            postcondition=migrated,
        )
    )
