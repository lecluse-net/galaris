"""DbAdmin contributions for canonical Messenger projections."""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminReconciler, DbAdminRegistry

from .contact_memory import rebuild_messenger_contacts
from .user_service import reconcile_nextcloud_agent_identities


async def _reconcile_agent_identities(_session: AsyncSession) -> None:
    result = await reconcile_nextcloud_agent_identities()
    logger.info("Messenger-agent identity reconciliation: {}", result.model_dump())


async def _reconcile_contacts(_session: AsyncSession) -> None:
    result = await rebuild_messenger_contacts()
    logger.info("Messenger-contact reconciliation: {}", result.model_dump())
    if result.failures:
        raise RuntimeError(
            "Messenger-contact reconciliation failed for: "
            + ", ".join(result.failures)
        )


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.messenger.agent_identities",
            handler=_reconcile_agent_identities,
            depends_on=("app.tools.mandatory.connections",),
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.messenger.contact_memory",
            handler=_reconcile_contacts,
            depends_on=(
                "app.memory.source_projections",
                "app.messenger.agent_identities",
            ),
        )
    )
