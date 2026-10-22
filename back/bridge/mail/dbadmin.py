"""DbAdmin backfill for outbound Mail journal ownership snapshots."""

from typing import cast

from sqlalchemy import Table, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.connection import Connection
from app.tools.facade import authorization_reviews, prepared_authorization_links
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
    registry.register_action(
        DbAdminAction(
            key="bridge.mail.link_prepared_authorizations",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="prepared-mail-authorization-links-v1",
            predicate=_introduces_authorization_link,
            handler=_backfill_authorization_links,
            postcondition=_all_prepared_authorizations_linked,
        )
    )


def _introduces_authorization_link(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("mail_outbound_deliveries", "authorization_id")


async def _backfill_authorization_links(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> None:
    cursor = None
    while True:
        links, next_cursor = await prepared_authorization_links(
            capability_names=("mail_send", "mail_reply", "mail_forward"),
            resource_key="delivery_id", after_id=cursor,
        )
        deliveries = {
            item.id: item for item in await session.scalars(
                select(MailOutboundDelivery)
                .where(MailOutboundDelivery.id.in_([identity for _, identity in links]))
            )
        } if links else {}
        reviews = await authorization_reviews({
            item.authorization_id for item in deliveries.values()
            if item.authorization_id is not None
        })
        for review, identity in links:
            delivery = deliveries.get(identity)
            if delivery is None or delivery.agent_id != review.agent_id or delivery.connection_id != review.connection_id:
                continue
            existing = reviews.get(delivery.authorization_id) if delivery.authorization_id is not None else None
            if existing is not None and existing.created_at >= review.created_at:
                continue
            delivery.authorization_id = review.id
            delivery.approver_user_id = review.approver_user_id
            delivery.approval_required = True
            reviews[review.id] = review
        await session.flush()
        if next_cursor is None:
            return
        cursor = next_cursor


async def _all_prepared_authorizations_linked(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> bool:
    cursor = None
    while True:
        links, next_cursor = await prepared_authorization_links(
            capability_names=("mail_send", "mail_reply", "mail_forward"),
            resource_key="delivery_id", after_id=cursor,
        )
        deliveries = {
            item.id: item for item in await session.scalars(
                select(MailOutboundDelivery)
                .where(MailOutboundDelivery.id.in_([identity for _, identity in links]))
            )
        } if links else {}
        reviews = await authorization_reviews({
            item.authorization_id for item in deliveries.values()
            if item.authorization_id is not None
        })
        for review, identity in links:
            delivery = deliveries.get(identity)
            if delivery is None or delivery.agent_id != review.agent_id or delivery.connection_id != review.connection_id:
                continue
            existing = reviews.get(delivery.authorization_id) if delivery.authorization_id is not None else None
            if existing is None or existing.created_at < review.created_at:
                return False
        if next_cursor is None:
            return True
        cursor = next_cursor


__all__ = ["register_dbadmin"]
