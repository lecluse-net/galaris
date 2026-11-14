"""Stable, credential-free Calendar projections for native resource references."""
from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import or_, select

from app.connection import Connection
from core.database import get_db
from .models import CalendarFeed


def _payload(feed: CalendarFeed, agent_id: int) -> dict[str, object]:
    return {
        "id": feed.id, "uri": f"galaris://calendar/{feed.id}",
        "agent_id": agent_id, "label": feed.label, "owner_label": feed.owner_label,
        "source_kind": feed.source_kind, "timezone": feed.timezone,
        "active": feed.active, "writable": feed.writable,
        "created_at": feed.created_at.isoformat(), "updated_at": feed.updated_at.isoformat() if feed.updated_at else None,
    }


async def read_calendar_resource(calendar_id: int, actor_agent_id: int) -> dict[str, object] | None:
    row = (await get_db().execute(select(CalendarFeed, Connection.agent_id).join(
        Connection, Connection.id == CalendarFeed.connection_id).where(
        CalendarFeed.id == calendar_id, Connection.agent_id == actor_agent_id,
        Connection.active.is_(True)))).first()
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
    return await search_calendar_resources([actor_agent_id], query, offset, limit)
