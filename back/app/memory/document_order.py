"""Atomic personal moves anchored to persisted siblings, including filtered-out rows."""

from dataclasses import dataclass
from uuid import UUID
import unicodedata

from sqlalchemy import delete, or_, select

from app.agent import AgentManagementScope
from core.database import get_db

from . import document_sharing, document_tags
from .events import emit_classification
from .access import human_document_clause, readable_item_for_agents_clause
from .models import DocumentListPosition, DocumentTag, DocumentTagAssignment, MemoryItem
from .schemas import DocumentOrderMove, DocumentOrderSort


@dataclass
class Sibling:
    kind: str
    id: UUID
    title: str
    row: DocumentTag | DocumentTagAssignment | DocumentListPosition


async def reorder(scope: AgentManagementScope, data: DocumentOrderMove) -> None:
    db = get_db()
    await document_tags.lock_tree(scope.user_id)
    previous_tags = list(await db.scalars(select(DocumentTagAssignment.tag_id).where(
        DocumentTagAssignment.document_id == data.node.id,
        DocumentTagAssignment.tag_id.in_(select(DocumentTag.id).where(DocumentTag.user_id == scope.user_id)),
    ))) if data.node.kind == "document" and not data.list_only else []
    if data.list_only and (data.parent_id is not None or data.node.kind != "document"):
        raise ValueError("List ordering only accepts documents without a parent")
    parent_id = data.parent_id
    while parent_id is not None:
        if data.node.kind == "tag" and parent_id == data.node.id:
            raise ValueError("A folder cannot be placed inside itself")
        parent_id = (await document_tags.require_tag(scope.user_id, parent_id)).parent_id
    if data.node.kind == "tag":
        moving: DocumentTag | DocumentTagAssignment | DocumentListPosition = await document_tags.require_tag(scope.user_id, data.node.id)
        title = moving.name
    else:
        await document_sharing.document_actor(data.node.id, scope)
        title = await db.scalar(select(MemoryItem.title).where(MemoryItem.id == data.node.id)) or ""
        if data.list_only or data.parent_id is None:
            existing = await db.scalar(select(DocumentListPosition).where(
                DocumentListPosition.user_id == scope.user_id, DocumentListPosition.document_id == data.node.id,
            ))
            moving = existing or DocumentListPosition(user_id=scope.user_id, document_id=data.node.id, position=0)
        else:
            moving = DocumentTagAssignment(tag_id=data.parent_id, document_id=data.node.id, position=0)

    siblings: list[Sibling] = []
    if data.list_only or (data.node.kind == "document" and data.parent_id is None):
        rows = await db.execute(select(MemoryItem, DocumentListPosition).outerjoin(DocumentListPosition,
            (DocumentListPosition.document_id == MemoryItem.id) & (DocumentListPosition.user_id == scope.user_id),
        ).where(MemoryItem.node_kind == "document", or_(
            readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id),
        )))
        for item, position in rows:
            if item.id != data.node.id:
                siblings.append(Sibling("document", item.id, item.title, position or DocumentListPosition(
                    user_id=scope.user_id, document_id=item.id, position=0,
                )))
    else:
        folders = await db.scalars(select(DocumentTag).where(
            DocumentTag.user_id == scope.user_id, DocumentTag.parent_id == data.parent_id,
        ))
        siblings.extend(Sibling("tag", tag.id, tag.name, tag) for tag in folders
            if not (data.node.kind == "tag" and tag.id == data.node.id))
        if data.parent_id is not None:
            rows = await db.execute(select(DocumentTagAssignment, MemoryItem.title).join(MemoryItem,
                MemoryItem.id == DocumentTagAssignment.document_id,
            ).where(DocumentTagAssignment.tag_id == data.parent_id))
            siblings.extend(Sibling("document", assignment.document_id, name, assignment) for assignment, name in rows
                if not (data.node.kind == "document" and assignment.document_id == data.node.id))
    siblings.sort(key=lambda node: (node.row.position, node.title.lower(), str(node.id)))
    index = len(siblings)
    if data.anchor is not None:
        if data.anchor == data.node:
            raise ValueError("A node cannot be its own anchor")
        if data.anchor.kind == "document":
            await document_sharing.document_actor(data.anchor.id, scope)
        index = next((i for i, node in enumerate(siblings)
            if node.kind == data.anchor.kind and node.id == data.anchor.id), -1)
        if index < 0:
            raise ValueError("The anchor is no longer in this folder")
        index += int(data.after)

    # Validate everything before replacing classification. A stale anchor never moves a document.
    if isinstance(moving, DocumentTag):
        moving.parent_id = data.parent_id
    elif not data.list_only:
        await db.execute(delete(DocumentTagAssignment).where(
            DocumentTagAssignment.document_id == data.node.id,
            DocumentTagAssignment.tag_id.in_(select(DocumentTag.id).where(DocumentTag.user_id == scope.user_id)),
        ))
    siblings.insert(index, Sibling(data.node.kind, data.node.id, title, moving))
    # Manual positioning never places a document before a folder.
    siblings.sort(key=lambda node: node.kind != "tag")
    for position, node in enumerate(siblings, 1):
        node.row.position = position
        db.add(node.row)
    await db.flush()
    if isinstance(moving, DocumentTag):
        from .document_structure import sync_folder_structure
        await sync_folder_structure(scope.user_id)
    elif not data.list_only:
        from .document_structure import sync_document_structure
        item = await db.get(MemoryItem, data.node.id)
        if item is not None:
            await sync_document_structure(item)
    await db.commit()
    await emit_classification(scope.user_id,
        tag_ids=[] if data.list_only else [*previous_tags, *([data.parent_id] if data.parent_id else [])],
        document_ids=[data.node.id] if data.node.kind == "document" and not data.list_only else [],
        tags_changed=not data.list_only,
        list_changed=data.list_only or (data.node.kind == "document" and (data.parent_id is None or not previous_tags)),
    )


async def sort_children(user_id: int, data: DocumentOrderSort) -> None:
    """Persist alphabetical order of direct children, folders before documents."""
    db = get_db()
    await document_tags.lock_tree(user_id)
    if data.parent_id is not None:
        await document_tags.require_tag(user_id, data.parent_id)
    folders = list(await db.scalars(select(DocumentTag).where(
        DocumentTag.user_id == user_id, DocumentTag.parent_id == data.parent_id,
    )))
    documents: list[Sibling] = []
    if data.parent_id is not None:
        rows = await db.execute(select(DocumentTagAssignment, MemoryItem.title).join(
            MemoryItem, MemoryItem.id == DocumentTagAssignment.document_id,
        ).where(DocumentTagAssignment.tag_id == data.parent_id))
        documents = [Sibling("document", row.document_id, title, row) for row, title in rows]

    def alphabetical(node: Sibling) -> tuple[str, str]:
        normalized = unicodedata.normalize("NFKD", node.title.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char)), str(node.id)

    ordered = sorted([Sibling("tag", tag.id, tag.name, tag) for tag in folders], key=alphabetical, reverse=data.descending)
    ordered.extend(sorted(documents, key=alphabetical, reverse=data.descending))
    for position, node in enumerate(ordered, 1):
        node.row.position = position
    await db.commit()
    await emit_classification(user_id, tag_ids=[data.parent_id] if data.parent_id else [], tags_changed=True)
