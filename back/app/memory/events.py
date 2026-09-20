"""Authorize live notifications with the domain's HTTP management scope."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from app.agent import management_scope_for
from core import websocket
from core.database import get_db
from core.user import UserModel
from .models import MemoryItem
from .access import human_document_clause, readable_item_for_agents_clause


async def _authorize(user: UserModel, _action: str, data: Mapping[str, Any]) -> bool:
    if _action == "classification":
        return data.get("user_id") == user.id
    if _action == "invalidate" and not data:
        return True  # No object identity, title, count or former audience is disclosed.
    scope = await management_scope_for(user, get_db())
    return await get_db().scalar(select(MemoryItem.id).where(
        MemoryItem.id == UUID(str(data["id"])),
        or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(user.id)),
    )) is not None


def register_events() -> None:
    websocket.register_event_authorization("memory", _authorize)


async def emit_classification(
    user_id: int, *, tag_ids: Sequence[UUID] = (), document_ids: Sequence[UUID] = (),
    tags_changed: bool = False, list_changed: bool = False,
) -> None:
    """Refresh only this user's affected classification, without invalidating access."""
    await websocket.emit("memory", "classification", {
        "user_id": user_id,
        "tag_ids": [str(value) for value in tag_ids],
        "document_ids": [str(value) for value in document_ids],
        "tags_changed": tags_changed,
        "list_changed": list_changed,
    })
