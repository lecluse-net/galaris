"""Deterministic document, attachment and folder projections; never calls a model.

The source document/tag owns structure. Text on an attachment's Memory companion
is acquired separately and is deliberately never recomputed by reconciliation.
All functions use the caller's transaction and do not commit.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select

from core.database import get_db

from .document_attachment_service import attachments_from_item
from .models import DocumentAttachment, DocumentTag, DocumentTagAssignment, MemoryItem, MemoryLink, MemorySource
from .semantic_index import stage_embedding_refresh
from .storage import get_storage


PROJECTION = "memory.document_structure"
RELATIONS = frozenset({"references", "has_attachment", "uses_attachment", "in_folder", "parent_of"})
_VERSION = 1


class _References(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a":
            value = values.get("data-rich-reference") or values.get("href")
        elif tag in {"img", "audio", "video", "source"}:
            value = values.get("src")
        else:
            return
        if value:
            self.references.add(value)


def document_references(content: str) -> set[tuple[UUID, UUID | None]]:
    """Resolve explicit canonical URIs and local document viewer links only."""
    parser = _References()
    parser.feed(content)
    result: set[tuple[UUID, UUID | None]] = set()
    for value in parser.references:
        try:
            uri = urlsplit(value)
            if uri.scheme == "document" and not uri.query and not uri.fragment:
                document_id = UUID(uri.netloc)
                if not uri.path:
                    result.add((document_id, None))
                elif uri.path.startswith("/attachments/"):
                    attachment_id = UUID(uri.path.removeprefix("/attachments/"))
                    result.add((document_id, attachment_id))
            elif not uri.scheme and not uri.netloc and uri.path == "/memory/documents":
                query = parse_qs(uri.query)
                document_id = UUID(query["document_id"][0])
                attachment = query.get("attachment_id", [])
                result.add((document_id, UUID(attachment[0]) if attachment else None))
        except (ValueError, KeyError, IndexError):
            continue
    return result


async def lock_structure(kind: str, identity: UUID) -> None:
    # Separate namespace from the document classifier's per-user tree lock.
    key = int.from_bytes(hashlib.sha256(f"{kind}:{identity}".encode()).digest()[:8], "big", signed=True)
    await get_db().execute(select(func.pg_advisory_xact_lock(key)))


async def _node(
    *, kind: Literal["attachment", "folder"], source_id: UUID, title: str,
    owner_agent_id: int | None, owner_user_id: int | None,
    metadata: dict[str, object],
) -> MemoryItem:
    db = get_db()
    item = await db.scalar(select(MemoryItem).where(
        MemoryItem.managed_source_kind == kind,
        MemoryItem.managed_source_ref == str(source_id),
    ).execution_options(include_historized=True))
    if item is None:
        resource_id = await get_storage("native").create(b"")
        item = MemoryItem(
            id=uuid4(), node_kind=kind, owner_agent_id=owner_agent_id,
            owner_user_id=owner_user_id, title=title, memory_type="working",
            provider_code="native", resource_id=resource_id, content_type="text",
            media_type="text/html", content_profile_version=1,
            content_hash=hashlib.sha256(b"").hexdigest(), size_bytes=0,
            search_text="", keywords=[], metadata_=metadata, visibility="private",
            source_managed=True, read_only=True, deletion_protected=True,
            managed_source_kind=kind, managed_source_ref=str(source_id),
        )
        db.add(item)
    else:
        # Ownership and descriptive metadata follow the source. The payload,
        # revisions, independent grants and acquired description never do.
        item.owner_agent_id = owner_agent_id
        item.owner_user_id = owner_user_id
        item.title = title
        item.metadata_ = metadata
    stage_embedding_refresh(item)
    await db.flush()
    uri = metadata.get("resource_uri")
    if isinstance(uri, str) and not await db.scalar(select(MemorySource.id).where(
        MemorySource.item_id == item.id, MemorySource.source_kind == kind, MemorySource.source_ref == uri,
    )):
        db.add(MemorySource(item_id=item.id, source_kind=kind, source_ref=uri))
    return item


async def _edges(source_id: UUID, desired: set[tuple[UUID, str]]) -> None:
    db = get_db()
    existing = list(await db.scalars(select(MemoryLink).where(
        MemoryLink.source_item_id == source_id,
        MemoryLink.relation_type.in_(RELATIONS),
    ).execution_options(include_historized=True)))
    indexed = {(edge.target_item_id, edge.relation_type): edge for edge in existing}
    for edge in existing:
        if edge.projection_key == PROJECTION and (edge.target_item_id, edge.relation_type) not in desired:
            if edge.deleted_at is None:
                edge.soft_delete()
    for target_id, relation in sorted(desired, key=lambda entry: (str(entry[0]), entry[1])):
        if source_id == target_id:
            continue
        edge = indexed.get((target_id, relation))
        if edge is not None:
            if edge.projection_key == PROJECTION and edge.deleted_at is not None:
                edge.deleted_at = None
                edge.deleted_by = None
            continue  # Never acquire or overwrite a manually owned relation.
        db.add(MemoryLink(
            source_item_id=source_id, target_item_id=target_id,
            relation_type=relation, confidence=1.0, suggested=False,
            projection_key=PROJECTION, projection_version=_VERSION,
            metadata_={"source": "document_structure"},
        ))
    await db.flush()


async def sync_document_structure(document: MemoryItem, content: bytes | None = None) -> None:
    """Reconcile a locked/current document manifest before its transaction commits."""
    if document.node_kind != "document":
        return
    db = get_db()
    await lock_structure("document", document.id)
    attachments = attachments_from_item(document)
    active_ids: set[UUID] = {attachment.id for attachment in attachments} if document.deleted_at is None else set()
    records = {row.id: row for row in await db.scalars(select(DocumentAttachment).where(
        DocumentAttachment.document_id == document.id,
    ))}
    desired: set[tuple[UUID, str]] = set()
    for attachment in attachments_from_item(document, include_retained=True):
        if attachment.id in records:
            record = records[attachment.id]
            node = await db.get(MemoryItem, record.memory_item_id)
            if node is None:
                raise ValueError("Attachment companion is missing")
            node.title = attachment.name
            node.owner_agent_id = document.owner_agent_id
            node.owner_user_id = document.owner_user_id
            stage_embedding_refresh(node)
        else:
            node = await _node(
                kind="attachment", source_id=attachment.id, title=attachment.name,
                owner_agent_id=document.owner_agent_id, owner_user_id=document.owner_user_id,
                metadata={"resource_uri": f"document://{document.id}/attachments/{attachment.id}",
                          "resource_media_type": attachment.media_type,
                          "resource_size_bytes": attachment.size_bytes},
            )
            record = DocumentAttachment(id=attachment.id, document_id=document.id,
                                        memory_item_id=node.id, active=attachment.id in active_ids)
            db.add(record)
            records[attachment.id] = record
        record.active = attachment.id in active_ids
        if record.active:
            desired.add((node.id, "has_attachment"))
    for identity, record in records.items():
        record.active = identity in active_ids
    await db.flush()
    if document.deleted_at is None:
        payload = content if content is not None else await get_storage(document.provider_code).read(document.resource_id)
        references: set[tuple[UUID, UUID | None]] = document_references(payload.decode("utf-8")) if document.document_type == "html" else set()
        for document_id, attachment_id in references:
            target = await db.scalar(select(MemoryItem).where(MemoryItem.id == document_id, MemoryItem.node_kind == "document"))
            if target is None:
                continue
            if attachment_id is None:
                desired.add((target.id, "references"))
            else:
                attachment = await db.scalar(select(DocumentAttachment).where(
                    DocumentAttachment.id == attachment_id, DocumentAttachment.document_id == target.id,
                    DocumentAttachment.active.is_(True),
                ))
                if attachment is not None:
                    desired.add((attachment.memory_item_id, "uses_attachment"))
        folders = await db.scalars(select(DocumentTag.memory_item_id).join(
            DocumentTagAssignment, DocumentTagAssignment.tag_id == DocumentTag.id,
        ).where(DocumentTagAssignment.document_id == document.id, DocumentTag.memory_item_id.is_not(None)))
        desired.update((identity, "in_folder") for identity in folders if identity is not None)
    await _edges(document.id, desired)


async def sync_folder_structure(user_id: int) -> None:
    """Refresh one private classification tree under its existing mutation lock."""
    db = get_db()
    retired = await db.scalars(select(DocumentTag).where(
        DocumentTag.user_id == user_id, DocumentTag.deleted_at.is_not(None),
        DocumentTag.memory_item_id.is_not(None),
    ).execution_options(include_historized=True))
    for tag in retired:
        if tag.memory_item_id is not None:
            await _edges(tag.memory_item_id, set())
            node = await db.get(MemoryItem, tag.memory_item_id)
            if node is not None:
                node.soft_delete()
    tags = list(await db.scalars(select(DocumentTag).where(DocumentTag.user_id == user_id)))
    by_id = {tag.id: tag for tag in tags}
    for tag in tags:
        node = await _node(kind="folder", source_id=tag.id, title=tag.name,
                           owner_agent_id=None, owner_user_id=user_id,
                           metadata={"folder_id": str(tag.id)})
        tag.memory_item_id = node.id
    await db.flush()
    children: dict[UUID, set[tuple[UUID, str]]] = {tag.id: set() for tag in tags}
    for tag in tags:
        seen = {tag.id}
        parent = tag.parent_id
        valid = True
        while parent is not None:
            if parent in seen or parent not in by_id:
                valid = False
                break
            seen.add(parent)
            parent = by_id[parent].parent_id
        if valid and tag.parent_id is not None and tag.memory_item_id is not None:
            children[tag.parent_id].add((tag.memory_item_id, "parent_of"))
    for tag in tags:
        if tag.memory_item_id is not None:
            await _edges(tag.memory_item_id, children[tag.id])


async def reconcile_document_structure() -> int:
    """Bounded keyset scans; mutations and repair share the same projection rules."""
    db = get_db()
    users = await db.scalars(select(DocumentTag.user_id).distinct())
    for user_id in users:
        from .document_tags import lock_tree
        await lock_tree(user_id)
        await sync_folder_structure(user_id)
    count = 0
    # Two passes resolve forward references to attachments created later in the
    # first scan. No source snapshot is replayed after a concurrent source edit.
    for _pass in range(2):
        cursor: UUID | None = None
        while True:
            query = select(MemoryItem).where(MemoryItem.node_kind == "document")
            if cursor is not None:
                query = query.where(MemoryItem.id > cursor)
            documents = list(await db.scalars(query.order_by(MemoryItem.id).limit(100).with_for_update()))
            if not documents:
                break
            for document in documents:
                await sync_document_structure(document)
                if _pass == 0:
                    count += 1
            cursor = documents[-1].id
    return count
