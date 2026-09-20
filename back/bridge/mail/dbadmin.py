"""DbAdmin backfill for outbound Mail journal ownership snapshots."""

from typing import cast

from sqlalchemy import Table, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.connection import Connection
from core.dbadmin import (
    DbAdminAction,
    DbAdminPhase,
    DbAdminRegistry,
    SchemaTransitionSet,
)

from .models import MailOutboundDelivery


def _introduces_agent_snapshot(transitions: SchemaTransitionSet) -> bool:
    return "mail_outbound_deliveries.agent_id" in transitions.added_columns


async def _backfill_agent_snapshots(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    deliveries = cast(Table, MailOutboundDelivery.__table__)
    connections = cast(Table, Connection.__table__)
    agents = cast(Table, Agent.__table__)
    agent_id = (
        select(connections.c.agent_id)
        .where(connections.c.id == deliveries.c.connection_id)
        .limit(1)
        .scalar_subquery()
    )
    agent_label = (
        select(func.btrim(func.concat_ws(" ", agents.c.first_name, agents.c.last_name)))
        .select_from(
            connections.join(agents, agents.c.id == connections.c.agent_id)
        )
        .where(connections.c.id == deliveries.c.connection_id)
        .limit(1)
        .scalar_subquery()
    )
    await session.execute(
        update(deliveries)
        .where(
            deliveries.c.connection_id.is_not(None),
            or_(
                deliveries.c.agent_id.is_(None),
                deliveries.c.agent_label == "",
            ),
        )
        .values(
            agent_id=func.coalesce(deliveries.c.agent_id, agent_id),
            agent_label=func.coalesce(func.nullif(deliveries.c.agent_label, ""), agent_label, ""),
        )
    )


async def _all_connected_deliveries_have_agents(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    deliveries = cast(Table, MailOutboundDelivery.__table__)
    missing = await session.scalar(
        select(func.count())
        .select_from(deliveries)
        .where(
            deliveries.c.connection_id.is_not(None),
            deliveries.c.agent_id.is_(None),
        )
    )
    return int(missing or 0) == 0


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="bridge.mail.backfill_outbound_agent_snapshots",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="agent-id-and-display-label-from-connection-v1",
            predicate=_introduces_agent_snapshot,
            handler=_backfill_agent_snapshots,
            postcondition=_all_connected_deliveries_have_agents,
        )
    )


__all__ = ["register_dbadmin"]
