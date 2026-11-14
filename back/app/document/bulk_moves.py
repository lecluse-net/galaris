"""Bounded, server-owned moves: one transaction and one ACL reconciliation per selection."""

from sqlalchemy import delete, func, select

from app.agent import AgentManagementScope
from core import websocket
from core.database import get_db
from core.authorize import Privileges, check_privilege
from core.user import get_user_record

from . import document_tags, document_sharing, resource_service
from .document_structure import sync_document_classification
from .events import emit_classification
from .lifecycle import notify_document, notify_documents
from .models import Document, DocumentListPosition, DocumentNesting, DocumentTag, DocumentTagAssignment
from .schemas import DocumentOrderBatch, DocumentOwnerBatch, DocumentTopicBatch
from .sharing_inheritance import lock_sharing, reconcile_sharing


async def move_topics(data: DocumentTopicBatch, scope: AgentManagementScope) -> None:
    from .topic_assignment import change_assignment

    db = get_db()
    for entry in sorted(data.documents, key=lambda entry: entry.id):
        await change_assignment(entry.id, scope, **entry.model_dump(exclude={"id", "source_keyword", "keyword"}),
            keyword_move=(entry.source_keyword, entry.keyword))
    await db.commit()
    for entry in data.documents:
        await websocket.emit("document", "update", {"id": str(entry.id), "node_kind": "document"}, None)
        await notify_document(entry.id, "index")
        await notify_document(entry.id, "update")


async def move_owners(data: DocumentOwnerBatch, scope: AgentManagementScope) -> None:
    db = get_db()
    await lock_sharing()
    # Authorize the complete snapshot before any owner/inherited ACL changes.
    actors = {entry.document_id: await document_sharing.document_actor(entry.document_id, scope, write=True)
        for entry in sorted(data.documents, key=lambda entry: entry.document_id)}
    user = await get_user_record(scope.user_id)
    administrative = await check_privilege(user, Privileges.DOCUMENT_ADMIN, db)
    for entry in data.documents:
        item = await resource_service.item_record(entry.document_id, revisions=False, contents=False)
        assert item is not None
        if not (scope.allows(item.owner_agent_id) or item.owner_user_id == scope.user_id or administrative):
            raise resource_service.DocumentPermissionError("Only the document owner can transfer ownership")
        if entry.kind == "agent" and not scope.allows(entry.id):
            raise resource_service.DocumentNotFoundError("Agent not found")
        if entry.kind == "user" and entry.id != scope.user_id and not await check_privilege(user, Privileges.DOCUMENT_ASSIGN_ALL_USERS, db):
            raise resource_service.DocumentPermissionError("User owner denied")
    for entry in sorted(data.documents, key=lambda entry: entry.document_id):
        await resource_service.transfer_document_owner(entry.document_id, entry,
            actor_agent_id=actors[entry.document_id], include_revisions=False, defer_commit=True)
    await reconcile_sharing()
    await db.commit()
    identities = [entry.document_id for entry in data.documents]
    await notify_documents(identities, "sharing")
    await notify_documents(identities, "update")
    await notify_documents([entry.document_id for entry in data.documents if entry.keywords is not None], "index")


async def move_folders(data: DocumentOrderBatch, scope: AgentManagementScope) -> None:
    db = get_db()
    if data.list_only and data.parent_id is not None:
        raise ValueError("List ordering only accepts documents without a parent")
    await document_tags.lock_tree(scope.user_id)
    identities = set(data.document_ids)
    if data.parent_id is not None:
        await document_tags.require_tag(scope.user_id, data.parent_id)
    if data.parent_document_id in identities:
        raise ValueError("A document cannot be placed inside itself")
    for identity in sorted(identities):
        await document_sharing.document_actor(identity, scope)
    if data.anchor is not None and data.anchor.kind == "document":
        await document_sharing.document_actor(data.anchor.id, scope)
    if data.parent_document_id is not None:
        await document_sharing.document_actor(data.parent_document_id, scope)
        parents = dict((await db.execute(select(DocumentNesting.document_id, DocumentNesting.parent_document_id)
            .where(DocumentNesting.user_id == scope.user_id))).tuples().all())
        seen = set(identities)
        current = data.parent_document_id
        while current is not None:
            if current in seen:
                raise ValueError("A document cannot be placed inside a descendant")
            seen.add(current)
            current = parents.get(current)

    own_tags = select(DocumentTag.id).where(DocumentTag.user_id == scope.user_id)
    previous_tags = set(await db.scalars(select(DocumentTagAssignment.tag_id).where(
        DocumentTagAssignment.document_id.in_(identities), DocumentTagAssignment.tag_id.in_(own_tags))))
    previous_parents = set(await db.scalars(select(DocumentNesting.parent_document_id).where(
        DocumentNesting.user_id == scope.user_id, DocumentNesting.document_id.in_(identities))))
    # Read and position siblings once, rather than rewriting the whole directory for every row.
    positions: list[DocumentNesting | DocumentTagAssignment | DocumentListPosition]
    if data.anchor is None:
        positions = []
    elif data.parent_document_id is not None:
        positions = list(await db.scalars(select(DocumentNesting).join(Document, Document.id == DocumentNesting.document_id)
            .where(DocumentNesting.user_id == scope.user_id, DocumentNesting.parent_document_id == data.parent_document_id,
                DocumentNesting.document_id.not_in(identities))
            .order_by(DocumentNesting.position, func.lower(Document.title), Document.id)))
    elif data.parent_id is not None:
        positions = list(await db.scalars(select(DocumentTagAssignment).join(Document, Document.id == DocumentTagAssignment.document_id)
            .where(DocumentTagAssignment.tag_id == data.parent_id, DocumentTagAssignment.document_id.not_in(identities))
            .order_by(DocumentTagAssignment.position, func.lower(Document.title), Document.id)))
    else:
        from .access import human_document_clause, readable_item_for_agents_clause
        from sqlalchemy import or_
        rows = (await db.execute(select(Document.id, DocumentListPosition).outerjoin(DocumentListPosition,
            (DocumentListPosition.document_id == Document.id) & (DocumentListPosition.user_id == scope.user_id))
            .where(Document.id.not_in(identities), Document.node_kind == "document", or_(
                readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id)))
            .order_by(func.coalesce(DocumentListPosition.position, 0), func.lower(Document.title), Document.id))).all()
        positions = [row or DocumentListPosition(user_id=scope.user_id, document_id=identity, at_root=False)
            for identity, row in rows]
    index = len(positions)
    if data.anchor is not None:
        if data.anchor.kind == "tag" and data.parent_document_id is None and not data.list_only:
            anchor = await document_tags.require_tag(scope.user_id, data.anchor.id)
            if anchor.parent_id != data.parent_id:
                raise ValueError("The anchor is no longer in this folder")
            index = 0  # Documents always follow folders.
        else:
            index = next((index for index, row in enumerate(positions) if row.document_id == data.anchor.id), -1)
            if index < 0:
                raise ValueError("The anchor is no longer in this folder")
            index += int(data.after)
    if data.anchor is None and data.parent_document_id is not None:
        start = await db.scalar(select(func.max(DocumentNesting.position)).where(
            DocumentNesting.user_id == scope.user_id, DocumentNesting.parent_document_id == data.parent_document_id)) or 0
    elif data.anchor is None and data.parent_id is not None:
        start = max(await db.scalar(select(func.max(DocumentTagAssignment.position)).where(DocumentTagAssignment.tag_id == data.parent_id)) or 0,
            await db.scalar(select(func.max(DocumentTag.position)).where(DocumentTag.user_id == scope.user_id, DocumentTag.parent_id == data.parent_id)) or 0)
    elif data.anchor is None:
        start = await db.scalar(select(func.max(DocumentListPosition.position)).where(DocumentListPosition.user_id == scope.user_id)) or 0
    else:
        start = (await db.scalar(select(func.max(DocumentTag.position)).where(
            DocumentTag.user_id == scope.user_id, DocumentTag.parent_id == data.parent_id)) or 0) if data.parent_id else 0
    if not data.list_only:
        await db.execute(delete(DocumentNesting).where(DocumentNesting.user_id == scope.user_id, DocumentNesting.document_id.in_(identities)))
        await db.execute(delete(DocumentTagAssignment).where(DocumentTagAssignment.document_id.in_(identities), DocumentTagAssignment.tag_id.in_(own_tags)))
    moving: list[DocumentNesting | DocumentTagAssignment | DocumentListPosition] = []
    roots = {row.document_id: row for row in await db.scalars(select(DocumentListPosition).where(
        DocumentListPosition.user_id == scope.user_id, DocumentListPosition.document_id.in_(identities)))}
    for identity in data.document_ids:
        root = roots.get(identity)
        if not data.list_only and root is not None:
            root.at_root = data.at_root
        if data.parent_document_id is not None:
            moving.append(DocumentNesting(user_id=scope.user_id, document_id=identity, parent_document_id=data.parent_document_id))
        elif data.parent_id is not None:
            moving.append(DocumentTagAssignment(tag_id=data.parent_id, document_id=identity))
        else:
            row = root or DocumentListPosition(user_id=scope.user_id, document_id=identity, at_root=data.at_root)
            moving.append(row)
        if not data.list_only:
            await sync_document_classification(identity)
    positions[index:index] = moving
    for position, row in enumerate(positions, start + 1):
        row.position = position
        db.add(row)
    if not data.list_only:
        await reconcile_sharing()
    await db.commit()
    await emit_classification(scope.user_id, tag_ids=[*previous_tags, *([data.parent_id] if data.parent_id else [])],
        document_ids=[*data.document_ids, *previous_parents, *([data.parent_document_id] if data.parent_document_id else [])],
        list_changed=True)
