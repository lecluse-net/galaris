"""Convergence of source labels persisted in Memory's catalogue projections."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminReconciler, DbAdminRegistry

from .catalogue import reconcile_catalogue_root_titles


async def _reconcile_root_titles(_session: AsyncSession) -> None:
    await reconcile_catalogue_root_titles()


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(DbAdminReconciler(
        key="app.file_share.catalogue_root_titles", handler=_reconcile_root_titles,
        depends_on=("app.tools.mandatory.tools", "app.memory.catalogue_editability"),
    ))
