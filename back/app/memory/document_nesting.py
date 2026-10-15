"""Personal sub-documents, serialized with the existing folder tree edits."""

from uuid import UUID

from sqlalchemy import delete, func, select

from app.agent import AgentManagementScope
from core.database import get_db

from . import document_sharing, document_tags
from .events import emit_classification
from .models import DocumentNesting, DocumentTag, DocumentTagAssignment, MemoryItem
from .schemas import DocumentOrderMove, DocumentOrderNode


async def clear_parent(user_id: int, document_id: UUID) -> UUID | None:
    db = get_db()
    previous = await db.scalar(select(DocumentNesting.parent_document_id).where(
        DocumentNesting.user_id == user_id, DocumentNesting.document_id == document_id,
    ))
    await db.execute(delete(DocumentNesting).where(
        DocumentNesting.user_id == user_id, DocumentNesting.document_id == document_id,
    ))
    return previous


async def validate_parent(scope: AgentManagementScope, document_id: UUID, parent_id: UUID) -> None:
    await document_sharing.document_actor(document_id, scope)
    await document_sharing.document_actor(parent_id, scope)
    # All personal placements use the same transaction lock. Check even ancestors
    # that have become unreadable, so restored access cannot uncover a cycle.
    parents = dict((await get_db().execute(select(
        DocumentNesting.document_id, DocumentNesting.parent_document_id,
    ).where(DocumentNesting.user_id == scope.user_id))).tuples().all())
    seen: set[UUID] = {document_id}
    current: UUID | None = parent_id
    while current is not None:
        if current in seen:
            raise ValueError("A document cannot be placed inside itself or one of its descendants")
        seen.add(current)
        current = parents.get(current)


async def move(scope: AgentManagementScope, document_id: UUID, parent_id: UUID | None) -> None:
    if parent_id is None:
        await document_tags.move_document(scope, document_id, None)
        return
    await reorder(scope, DocumentOrderMove(
        node=DocumentOrderNode(kind="document", id=document_id), parent_document_id=parent_id,
    ))


async def reorder(scope: AgentManagementScope, data: DocumentOrderMove) -> None:
    db = get_db()
    await document_tags.lock_tree(scope.user_id)
    parent_id = data.parent_document_id
    if parent_id is None or data.node.kind != "document":
        raise ValueError("Expected a document parent")
    await validate_parent(scope, data.node.id, parent_id)
    siblings = list(await db.scalars(select(DocumentNesting).join(
        MemoryItem, MemoryItem.id == DocumentNesting.document_id,
    ).where(DocumentNesting.user_id == scope.user_id,
        DocumentNesting.parent_document_id == parent_id,
        DocumentNesting.document_id != data.node.id,
    ).order_by(DocumentNesting.position, func.lower(MemoryItem.title), DocumentNesting.document_id)))
    index = len(siblings)
    if data.anchor is not None:
        if data.anchor.kind != "document" or data.anchor.id == data.node.id:
            raise ValueError("Invalid document anchor")
        await document_sharing.document_actor(data.anchor.id, scope)
        index = next((i for i, row in enumerate(siblings) if row.document_id == data.anchor.id), -1)
        if index < 0:
            raise ValueError("The anchor is no longer under this document")
        index += int(data.after)
    previous_tags = list(await db.scalars(select(DocumentTagAssignment.tag_id).where(
        DocumentTagAssignment.document_id == data.node.id,
        DocumentTagAssignment.tag_id.in_(select(DocumentTag.id).where(DocumentTag.user_id == scope.user_id)),
    )))
    previous_parent = await clear_parent(scope.user_id, data.node.id)
    await db.execute(delete(DocumentTagAssignment).where(
        DocumentTagAssignment.document_id == data.node.id,
        DocumentTagAssignment.tag_id.in_(select(DocumentTag.id).where(DocumentTag.user_id == scope.user_id)),
    ))
    siblings.insert(index, DocumentNesting(user_id=scope.user_id, document_id=data.node.id, parent_document_id=parent_id))
    for position, row in enumerate(siblings, 1):
        row.position = position
        db.add(row)
    await document_tags.sync_classified_document(data.node.id)
    await db.commit()
    await emit_classification(scope.user_id, tag_ids=previous_tags,
        document_ids=[data.node.id, parent_id, *([previous_parent] if previous_parent else [])], list_changed=True)
