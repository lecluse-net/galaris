"""Document notifications retain live ACL admission and private classification."""
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID
from sqlalchemy import or_, select
from app.agent import management_scope_for
from core import websocket
from core.database import get_db
from core.user import UserModel
from .models import Document
from .access import human_document_clause, readable_item_for_agents_clause


class DocumentRoom(websocket.BaseRoom):
    """A document's live room uses the same admission as global notifications."""


async def _room_authorized(user_id: int, document_id: str) -> bool:
    from core.user import get_user_record
    user = await get_user_record(user_id)
    if user is None:
        return False
    return await _authorize(user, "read", {"id": document_id})


async def _authorize(user: UserModel, action: str, data: Mapping[str, Any]) -> bool:
    if action == "classification":
        return data.get("user_id") == user.id
    if action == "invalidate" and not data:
        return True
    scope=await management_scope_for(user, get_db())
    return await get_db().scalar(select(Document.id).where(Document.id == UUID(str(data["id"])), or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(user.id)))) is not None


def register_events() -> None:
    websocket.register_resource_room("document", DocumentRoom,
        required_privileges=("DOCUMENT_ACCESS", "DOCUMENT_EDIT", "DOCUMENT_ADMIN"),
        authorize=_room_authorized)
    websocket.register_event_authorization("document", _authorize)


async def emit_classification(user_id: int, *, tag_ids: Sequence[UUID] = (), document_ids: Sequence[UUID] = (), tags_changed: bool = False, list_changed: bool = False) -> None:
    if get_db().info.pop("document_sharing_changed", False):
        await websocket.emit("document", "invalidate", {})
    await websocket.emit("document", "classification", {"user_id":user_id,"tag_ids":[str(v) for v in tag_ids],"document_ids":[str(v) for v in document_ids],"tags_changed":tags_changed,"list_changed":list_changed})
    from .document_structure import flush_projection_changes
    await flush_projection_changes()
