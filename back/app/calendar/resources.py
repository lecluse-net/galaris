"""Stable, credential-free Calendar projections for native resource references."""
from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import or_, select

from app.connection import Connection
from app.services.facade import administration_scope
from core.database import get_db
from .models import CalendarFeed


async def read_calendar_event_label(calendar_id: int, uid: str, agent_ids: frozenset[int] | None) -> str | None:
    """Project the event summary within the same managed scope as Calendar reads."""
    from . import service

    try:
        _, connection = await service.feed_context(calendar_id)
        if agent_ids is not None and connection.agent_id not in agent_ids:
            return None
        event = await service.event_detail(calendar_id, uid)
        return event.summary if not event.deleted else None
    except (LookupError, PermissionError, ValueError):
        return None


def _payload(feed: CalendarFeed, agent_id: int) -> dict[str, object]:
    return {
        "id": feed.id, "uri": f"galaris://calendar/{feed.id}",
        "agent_id": agent_id, "label": feed.label, "owner_label": feed.owner_label,
        "source_kind": feed.source_kind, "timezone": feed.timezone,
        "active": feed.active, "writable": feed.writable,
        "created_at": feed.created_at.isoformat(), "updated_at": feed.updated_at.isoformat() if feed.updated_at else None,
    }


async def read_calendar_resource(calendar_id: int, actor_agent_id: int) -> dict[str, object] | None:
    scope = await administration_scope(actor_agent_id, "calendar")
    statement = select(CalendarFeed, Connection.agent_id).join(
        Connection, Connection.id == CalendarFeed.connection_id).where(
        CalendarFeed.id == calendar_id, Connection.active.is_(True))
    if scope.agent_ids is not None:
        statement = statement.where(Connection.agent_id.in_(scope.agent_ids | {actor_agent_id}))
    row = (await get_db().execute(statement)).first()
    return _payload(*row) if row is not None else None


async def search_calendar_resources(
    agent_ids: Collection[int] | None, query: str, offset: int, limit: int,
) -> list[dict[str, object]]:
    statement = select(CalendarFeed, Connection.agent_id).join(
        Connection, Connection.id == CalendarFeed.connection_id).where(Connection.active.is_(True))
    if agent_ids is not None:
        statement = statement.where(Connection.agent_id.in_(agent_ids))
    if query.strip():
        pattern = f"%{query.strip().replace('/', '//').replace('%', '/%').replace('_', '/_')}%"
        statement = statement.where(or_(CalendarFeed.label.ilike(pattern, escape="/"),
                                        CalendarFeed.owner_label.ilike(pattern, escape="/")))
    rows = (await get_db().execute(statement.order_by(CalendarFeed.label, CalendarFeed.id)
        .offset(max(0, offset)).limit(min(max(1, limit), 1001)))).all()
    return [_payload(feed, owner) for feed, owner in rows]


async def list_calendar_resources(actor_agent_id: int, query: str, offset: int, limit: int) -> list[dict[str, object]]:
    scope = await administration_scope(actor_agent_id, "calendar")
    owners = None if scope.agent_ids is None else scope.agent_ids | {actor_agent_id}
    return await search_calendar_resources(owners, query, offset, limit)
