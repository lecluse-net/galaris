"""Validate the dedicated disk volume on every synchronization/startup."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminReconciler, DbAdminRegistry

from .identity import ensure_disk_identity
from .lifecycle import resume_file_purges


async def _validate_volume(session: AsyncSession) -> None:
    await ensure_disk_identity(session)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(DbAdminReconciler(
        key="core.storage.disk_identity", handler=_validate_volume,
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="core.storage.pending_purges", handler=resume_file_purges,
        depends_on=("core.storage.disk_identity",), required=False,
    ))
