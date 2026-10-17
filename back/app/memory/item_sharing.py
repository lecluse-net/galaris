"""Atomic sharing of memory items and documents, independent of Agent identity."""

from app.share import sharing_directory as principal_directory, sharing_state, replace_sharing, set_grant

from uuid import UUID
from typing import Literal

from sqlalchemy import select

from app.agent import AgentManagementScope
from app.tools.contracts import current_tool_execution
from core.authorize import Privileges, check_privilege
from core.database import get_db
from core.user import HumanActor, get_user_record

from . import service
from .access import human_item_access, managed_item_agent_ids
from .models import MemoryItem
from .schemas import DocumentSharing, DocumentSharingUpdate, DocumentSharingLevelUpdate


async def item_actor(
    document_id: UUID, scope: AgentManagementScope, *, write: bool = False,
    document_only: bool = False,
) -> int | HumanActor:
    item = await service.item_record(document_id, revisions=False)
    if document_only and (item is None or item.node_kind != "document"):
        raise service.MemoryNotFoundError("Document not found")
    if item is None:
        raise service.MemoryNotFoundError("Memory not found")
    human = await human_item_access(item, scope.user_id)
    if human.can_write if write else human.can_read:
        return HumanActor(scope.user_id)
    readable, writable = await managed_item_agent_ids(item, scope.agent_ids)
    candidates = writable if write else readable
    if not candidates:
        raise service.MemoryNotFoundError("Document not found")
    return candidates[0]


async def can_manage(item: MemoryItem, scope: AgentManagementScope) -> bool:
    if item.node_kind != "document" or item.source_managed or item.read_only:
        return False
    if item.document_type == "process":
        from .document_policy import orphan_process_clause
        orphan = await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == item.id, orphan_process_clause()))
        if orphan:
            return await check_privilege(await get_user_record(scope.user_id), "PROCESS_ADMIN", get_db())
    return (
        item.owner_user_id == scope.user_id or scope.allows(item.owner_agent_id)
        or await check_privilege(await get_user_record(scope.user_id), Privileges.MEMORY_ADMIN, get_db())
    )


async def sharing(document_id: UUID, scope: AgentManagementScope) -> DocumentSharing:
    await item_actor(document_id, scope)
    item = await service.item_record(document_id)
    assert item is not None
    if item.node_kind != "document" and not item.source_managed and item.node_kind not in {"folder", "attachment"}:
        raise service.MemoryNotFoundError("Document not found")
    manage = await can_manage(item, scope)
    return await _sharing_state(item, manage=manage)


async def _sharing_state(item: MemoryItem, *, manage: bool) -> DocumentSharing:
    result = await sharing_state(item.share_id, owner_agent_id=item.owner_agent_id,
        owner_user_id=item.owner_user_id, can_manage=manage, lock_version=item.lock_version)
    if item.source_managed and item.visibility == "public":
        result = result.model_copy(update={"level": "public", "can_write": False})
    return result


async def sharing_preview(scope: AgentManagementScope, *, owner_agent_id: int | None) -> DocumentSharing:
    if owner_agent_id is not None:
        scope.require(owner_agent_id)
    return await principal_directory(owner_agent_id=owner_agent_id, owner_user_id=scope.user_id if owner_agent_id is None else None)


async def sharing_directory(*, owner_agent_id: int | None, owner_user_id: int | None) -> DocumentSharing:
    return await principal_directory(owner_agent_id=owner_agent_id, owner_user_id=owner_user_id)


async def update_level(document_id: UUID, data: DocumentSharingLevelUpdate, scope: AgentManagementScope) -> DocumentSharing:
    item = await _editable_sharing(document_id, data.expected_lock_version, scope)
    current = await sharing(document_id, scope)
    try:
        await replace_sharing(item.share_id, data, current)
    except LookupError as error:
        raise service.MemoryNotFoundError(str(error)) from error
    item.visibility = "shared" if data.level == "public" or data.grants else "private"
    item.lock_version += 1
    await service.commit_item_sharing(item)
    return await sharing(document_id, scope)


async def _editable_sharing(document_id: UUID, expected: int, scope: AgentManagementScope) -> MemoryItem:
    # Serialize edits to the same document, including concurrent first-time grants.
    await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == document_id).with_for_update())
    item = await service.item_record(document_id)
    if item is None or not await can_manage(item, scope):
        raise service.MemoryPermissionError("Only the owner can manage sharing")
    await item_actor(document_id, scope, write=True)
    if item.lock_version != expected:
        raise service.MemoryConflictError("Document sharing changed; reload and retry")
    return item


async def update_sharing(document_id: UUID, data: DocumentSharingUpdate, scope: AgentManagementScope) -> DocumentSharing:
    item = await _editable_sharing(document_id, data.expected_lock_version, scope)
    await _update_grant(item, data)
    return await sharing(document_id, scope)


async def _update_grant(item: MemoryItem, data: DocumentSharingUpdate) -> None:
    directory = await principal_directory(owner_agent_id=item.owner_agent_id, owner_user_id=item.owner_user_id)
    if data.can_write is not None and not any(p.kind == data.kind and p.id == data.id for p in directory.options):
        raise service.MemoryNotFoundError("Collaborator not found")
    await set_grant(item.share_id, data.kind, data.id, data.can_write)
    if item.visibility != "public":
        item.visibility = "shared" if item.global_access or item.group_access or await service.has_document_grants(item.id) else "private"
    item.lock_version += 1
    await service.commit_item_sharing(item)


async def agent_sharing(item_id: UUID, *, agent_id: int) -> DocumentSharing:
    """Let an agent inspect its own recipients without impersonating its human manager."""
    item = await service.item_record(item_id)
    if item is None:
        raise service.MemoryNotFoundError("Memory not found")
    if item.node_kind != "document":
        raise service.MemoryPermissionError("Memories are private; sharing belongs to documents")
    if item.owner_agent_id != agent_id:
        raise service.MemoryPermissionError("Only the owner can manage sharing")
    return await _sharing_state(item, manage=not item.read_only and not item.source_managed)


async def update_agent_sharing(
    item_id: UUID, *, agent_id: int, kind: Literal["agent", "user", "team"],
    target_id: int, access: Literal["read", "edit", "none"],
    expected_lock_version: int | None = None, document_only: bool = False,
) -> DocumentSharing:
    """Update one explicit grant atomically; edits do not grant the right to reshare."""
    await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == item_id).with_for_update())
    item = await service.item_record(item_id)
    if item is None:
        raise service.MemoryNotFoundError("Memory not found")
    if item.node_kind != "document":
        raise service.MemoryConflictError("The selected memory is not a document.")
    if item.owner_agent_id != agent_id or item.read_only or item.source_managed:
        raise service.MemoryPermissionError("Only the owner of an editable item can manage sharing")
    if expected_lock_version is not None and item.lock_version != expected_lock_version:
        # This check precedes every grant mutation. A stale version (including one
        # invalidated by a content edit) is safe for the model to reload and retry.
        # Do not infer this evidence from a later exception: commit or notification
        # failures can occur after the sharing has already taken effect.
        execution = current_tool_execution()
        if execution is not None:
            execution.outcome = "rejected"
        raise service.MemoryConflictError(
            "Sharing changed; call memory_sharing again for the current lock_version, then retry"
        )
    data = DocumentSharingUpdate(
        kind=kind, id=target_id,
        can_write=None if access == "none" else access == "edit",
        expected_lock_version=item.lock_version,
    )
    await _update_grant(item, data)
    return await agent_sharing(item_id, agent_id=agent_id)
