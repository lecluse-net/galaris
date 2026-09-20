"""Document routes retain their kind constraint over the common item sharing service."""

from uuid import UUID

from app.agent import AgentManagementScope
from core.user import HumanActor

from . import item_sharing, service
from .item_sharing import can_manage
from .schemas import DocumentSharing, DocumentSharingLevelUpdate, DocumentSharingUpdate

__all__ = ["can_manage", "document_actor", "sharing", "update_level", "update_sharing"]


async def _require_document(document_id: UUID) -> None:
    if await service.document_record(document_id) is None:
        raise service.MemoryNotFoundError("Document not found")


async def document_actor(document_id: UUID, scope: AgentManagementScope, *, write: bool = False) -> int | HumanActor:
    await _require_document(document_id)
    return await item_sharing.item_actor(document_id, scope, write=write)


async def sharing(document_id: UUID, scope: AgentManagementScope) -> DocumentSharing:
    await _require_document(document_id)
    return await item_sharing.sharing(document_id, scope)


async def update_level(document_id: UUID, data: DocumentSharingLevelUpdate, scope: AgentManagementScope) -> DocumentSharing:
    await _require_document(document_id)
    return await item_sharing.update_level(document_id, data, scope)


async def update_sharing(document_id: UUID, data: DocumentSharingUpdate, scope: AgentManagementScope) -> DocumentSharing:
    await _require_document(document_id)
    return await item_sharing.update_sharing(document_id, data, scope)
