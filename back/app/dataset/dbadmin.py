"""DbAdmin owns the additive Dataset transfer and its postconditions."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


async def transfer(_session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    from .migration import migrate_legacy
    await migrate_legacy()


async def complete(_session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    from .migration import migration_complete
    return await migration_complete()


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.dataset.legacy_documents", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="dataset-additive-authority-v1", predicate=lambda delta: delta.table_added("datasets"),
        handler=transfer, postcondition=complete))
