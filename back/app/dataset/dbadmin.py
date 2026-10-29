"""DbAdmin owns the additive Dataset transfer and its postconditions."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminReconciler, DbAdminRegistry, SchemaTransitionSet


async def transfer(_session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    from app.share import transfer_legacy_sharing as transfer_shares
    await transfer_shares(_session)
    from .migration import migrate_legacy
    await migrate_legacy()


async def complete(_session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    from .migration import migration_complete
    return await migration_complete()


def register_dbadmin(registry: DbAdminRegistry) -> None:
    async def summaries(_session: AsyncSession) -> None:
        from .resource_summaries import reconcile
        await reconcile()
    registry.register_reconciler(DbAdminReconciler(key="app.dataset.current_summaries", handler=summaries))
    registry.register_action(DbAdminAction(key="app.dataset.legacy_documents", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="dataset-additive-authority-v1", predicate=lambda delta: delta.table_added("datasets"),
        handler=transfer, postcondition=complete))
