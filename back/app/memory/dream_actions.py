"""Authorized Memory ports for explicitly requested Dream maintenance."""

from uuid import UUID

from sqlalchemy import select

from app.agent import AgentManagementScope, get_agent_record
from core.database import get_db

from . import service
from .attachment_analysis import attachment_analysis_source
from .models import MemoryItem, DocumentTag


async def dream_action_item(
    item_id: UUID, agent_id: int, scope: AgentManagementScope
) -> MemoryItem:
    if not scope.allows(agent_id) or await get_agent_record(agent_id) is None:
        raise service.MemoryNotFoundError("Agent not found")
    item, *_ = await service.get_item(item_id, agent_id=agent_id, include_revisions=False)
    # A read grant alone must never permit replacing acquired content.
    if item.node_kind == "attachment":
        source = await attachment_analysis_source(item_id, allow_existing=True)
        if source is None:
            raise service.MemoryNotFoundError("Attachment not found")
        if source.owner_agent_id != agent_id and source.owner_user_id != scope.user_id:
            raise service.MemoryPermissionError("Attachment owner required")
    elif item.node_kind == "folder":
        tag = await get_db().scalar(
            select(DocumentTag).where(
                DocumentTag.memory_item_id == item_id,
                DocumentTag.deleted_at.is_(None),
            )
        )
        if tag is None or tag.user_id != scope.user_id:
            raise service.MemoryPermissionError("Folder owner required")
    elif item.owner_agent_id != agent_id and not (
        item.node_kind == "document" and item.owner_user_id == scope.user_id
    ):
        raise service.MemoryPermissionError("Memory owner required")
    return item


async def dream_structure_identity(item: MemoryItem) -> UUID:
    if item.node_kind == "folder":
        identity = await get_db().scalar(
            select(DocumentTag.id).where(DocumentTag.memory_item_id == item.id)
        )
        if identity is None:
            raise service.MemoryNotFoundError("Folder not found")
        return identity
    return item.id
