"""Sharing rules for a private folder; the tree itself remains private."""

from uuid import UUID

from app.agent import AgentManagementScope
from app.share import replace_sharing, sharing_state
from core.database import get_db

from . import document_tags, service, sharing_inheritance
from .models import MemoryItem
from .schemas import DocumentSharing, DocumentSharingLevelUpdate


async def _folder(tag_id: UUID, scope: AgentManagementScope) -> MemoryItem:
    tag = await document_tags.require_tag(scope.user_id, tag_id)
    if tag.memory_item_id is None:
        from .document_structure import sync_folder_structure
        await sync_folder_structure(scope.user_id)
    assert tag.memory_item_id is not None
    item = await get_db().get(MemoryItem, tag.memory_item_id)
    if item is None:
        raise service.MemoryNotFoundError("Folder not found")
    return item


async def sharing(tag_id: UUID, scope: AgentManagementScope) -> DocumentSharing:
    await document_tags.lock_tree(scope.user_id)
    item = await _folder(tag_id, scope)
    return await sharing_state(item.share_id, owner_agent_id=None, owner_user_id=scope.user_id,
        can_manage=True, lock_version=item.lock_version)


async def update(tag_id: UUID, data: DocumentSharingLevelUpdate, scope: AgentManagementScope) -> DocumentSharing:
    await document_tags.lock_tree(scope.user_id)
    item = await _folder(tag_id, scope)
    if item.lock_version != data.expected_lock_version:
        raise service.MemoryConflictError("Folder sharing changed; reload and retry")
    current = await sharing(tag_id, scope)
    own = await sharing_inheritance.replacement_intent(item, data, current)
    await sharing_inheritance.prepare_own_sharing(item)
    await replace_sharing(item.share_id, own, current)
    item.lock_version += 1
    await sharing_inheritance.finish_own_sharing(item)
    await get_db().commit()
    await service.invalidate_memory_views()
    return await sharing(tag_id, scope)
