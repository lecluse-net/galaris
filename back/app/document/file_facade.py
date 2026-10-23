"""File Sharing adapter over canonical documents and their attachments."""
from __future__ import annotations
from typing import Literal, cast
from uuid import UUID
from . import document_attachment_service, document_service, resource_service as service
from .document_types import DocumentType
from .schemas import DocumentUpdate,DocumentPayload
from core.util import read_html_page, visible_text
from core.database import get_db
from sqlalchemy import select, func, or_
from .models import Document
from .access import readable_item_clause


async def read_file_resource_text(
    item_id: UUID, *, agent_id: int, task_id: UUID | None,
    expected_kind: str, offset: int, max_chars: int,
) -> dict[str, object]:
    item, body, _, _, _ = await service.get_item(item_id, agent_id=agent_id,
        record_llm_access=True, task_id=task_id, include_revisions=False)
    return {**read_html_page(body.decode(), offset=offset, max_chars=max_chars),
        "revision": item.revision, "content_profile": item.content_profile}


async def search_file_resources(
    *, agent_id: int, task_id: UUID | None, expected_kind: str,
    query: str, mode: Literal["name", "text", "semantic"], limit: int | None,
    offset: int, conversation_turn: object | None = None,
) -> dict[str, object]:
    """Search the canonical Document index with live ACLs and bounded pagination.

    Optional indexes preserve ranked passages. Admission and revision freshness
    are checked again here; discovery remains available without any adapter.
    """
    page_size = limit or 50
    if not 1 <= page_size <= 500 or offset < 0:
        raise ValueError("Invalid document search pagination")
    from .search_index import document_search_index
    index = document_search_index()
    if index is not None and mode != "name" and query.strip():
        indexed = await index(agent_id=agent_id, task_id=task_id, expected_kind="document",
            query=query, mode=mode, limit=page_size, offset=offset, conversation_turn=conversation_turn)
        candidates = cast(list[dict[str, object]], indexed.get("hits", []))
        if candidates:
            identities = [UUID(str(hit["id"])) for hit in candidates]
            rows = (await get_db().execute(select(Document.id, Document.revision).where(
                Document.id.in_(identities), readable_item_clause(agent_id), Document.document_type == "html",
            ))).all()
            versions = {identity: revision for identity, revision in rows}
            if all(versions.get(identity) == hit["revision"] for identity, hit in zip(identities, candidates, strict=True)):
                return indexed
    filters = [readable_item_clause(agent_id), Document.document_type == "html"]
    if query.strip():
        pattern = "%" + query.strip().replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(Document.title.ilike(pattern, escape="\\") if mode == "name" else or_(
            Document.search_vector.op("@@")(func.websearch_to_tsquery("simple", query)),
            Document.title.ilike(pattern, escape="\\"),
            Document.search_text.ilike(pattern, escape="\\"),
        ))
    db = get_db()
    total = int(await db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0)
    rows = list(await db.scalars(select(Document).where(*filters).order_by(
        func.lower(Document.title), Document.id).offset(offset).limit(page_size)))
    hits: list[dict[str, object]] = []
    for item in rows:
        access = await service.assert_item_access(item, agent_id)
        hits.append(dict(id=str(item.id), uri=f"document://{item.id}", node_kind="document",
            title=item.title, filename=item.filename, media_type=item.media_type,
            size=item.size_bytes, revision=item.revision, checksum=item.content_hash,
            updated_at=item.updated_at.isoformat() if item.updated_at is not None else None, score=1.0,
            excerpt="" if mode == "name" else visible_text(item.search_text)[:500], can_write=access.can_write,
            metadata={"document_type": item.document_type, "temporal": item.temporal},
            source_refs=await service.source_refs(item.id), retrieval_sources=["document_lexical"], passages=[]))
    more = offset + len(hits) < total
    return dict(hits=hits, total=total, has_more=more, next_offset=offset+len(hits) if more else None,
        retrieval_mode="lexical", degraded=mode=="semantic",
        degradation_reason="Document semantic search is unavailable" if mode=="semantic" else None)

async def create_document_file_resource(
    *,
    agent_id: int,
    task_id: UUID | None,
    title: str,
    content: str,
    document_type: DocumentType = "html",
) -> dict[str, object]:
    """Create a private working document from an explicit text-file copy."""

    item = await document_service.create_document(
        owner_agent_id=agent_id,
        title=title,
        content=content,
        document_type=document_type,
        task_id=task_id,
    )
    return {"id": str(item.id), "size": item.size_bytes, "revision": item.revision}

async def list_document_attachment_file_resources(
    document_id: UUID,
    *,
    agent_id: int,
) -> dict[str, object]:
    """List attachment metadata under one authorized document."""

    item, _content, access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=agent_id,
    )
    if item.node_kind != "document":
        raise service.DocumentConflictError("The selected memory is not a document.")
    attachments = await document_attachment_service.attachment_companions(document_attachment_service.attachments_from_item(item))
    return {
        "attachments": [value.model_dump(mode="json") for value in attachments],
        "can_write": access.can_write,
    }

async def describe_document_attachment_file_resource(
    document_id: UUID,
    attachment_id: UUID,
    *,
    agent_id: int,
) -> dict[str, object]:
    """Describe one attachment after applying its parent document ACL."""

    item, _, access, _, _ = await service.get_item(document_id, agent_id=agent_id)
    attachment = next((entry for entry in document_attachment_service.attachments_from_item(item, include_retained=True) if entry.id == attachment_id), None)
    if attachment is None:
        raise service.DocumentNotFoundError("Document attachment not found.")
    attachment = (await document_attachment_service.attachment_companions([attachment]))[0]
    return {**attachment.model_dump(mode="json"), "can_write": access.can_write}

async def create_document_attachment_file_resource(
    document_id: UUID,
    *,
    agent_id: int,
    name: str,
    content: bytes,
) -> dict[str, object]:
    """Create one immutable attachment under an editable document."""

    attachment = await document_attachment_service.add_document_attachment_bytes(
        document_id,
        actor_agent_id=agent_id,
        name=name,
        media_type=None,
        content=content,
    )
    return attachment.model_dump(mode="json")

async def read_document_attachment_file_resource(
    document_id: UUID,
    attachment_id: UUID,
    *,
    agent_id: int,
) -> tuple[dict[str, object], bytes]:
    """Read one attachment after applying its parent document ACL."""

    attachment, content = await document_attachment_service.read_document_attachment(
        document_id,
        attachment_id,
        actor_agent_id=agent_id,
    )
    return attachment.model_dump(mode="json"), content

async def delete_document_attachment_file_resource(
    document_id: UUID,
    attachment_id: UUID,
    *,
    agent_id: int,
) -> None:
    """Delete one attachment from an editable document."""

    await document_attachment_service.delete_document_attachment(
        document_id,
        attachment_id,
        actor_agent_id=agent_id,
    )

async def describe_file_resource(
    item_id: UUID,
    *,
    agent_id: int,
    expected_kind: Literal["document"],
) -> dict[str, object]:
    """Describe an authorized item without leaking its storage locator."""

    item, _content, access, _content_type, media_type = await service.get_item(
        item_id,
        agent_id=agent_id,
    )
    if expected_kind == "document" and item.node_kind != "document":
        raise service.DocumentConflictError("The selected memory is not a document.")
    return {
        "id": str(item.id),
        "title": item.title,
        "filename": item.filename,
        "media_type": media_type,
        "size": item.size_bytes,
        "revision": item.revision,
        "checksum": item.content_hash,
        "can_write": access.can_write and item.node_kind == "document",
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "metadata": {
            "temporal": item.temporal,
            "document_type": item.document_type,
            "folder": str(item.metadata_.get("document_path") or ""),
            "content_profile": item.content_profile,
            "content_profile_version": item.content_profile_version,
            "offset_unit": "block" if media_type == "text/html" else "character",
            "node_kind": item.node_kind,
        },
    }

async def write_document_resource_text(
    item_id: UUID,
    *,
    agent_id: int,
    task_id: UUID | None,
    content: str,
    expected_revision: int | None,
) -> dict[str, object]:
    """Replace an authorized document with optimistic concurrency."""

    if expected_revision is None:
        raise service.DocumentConflictError(
            "expected_revision is required to replace a document; call file_read first."
        )
    item, _content, _access, _content_type, _media_type = await service.get_item(
        item_id,
        agent_id=agent_id,
    )
    if item.node_kind != "document":
        raise service.DocumentConflictError("The selected memory is not a document.")
    updated = await service.update_item(
        item_id,
        DocumentUpdate(
            expected_revision=expected_revision,
            payload=DocumentPayload(text=content),
        ),
        actor_agent_id=agent_id,
        actor_task_id=task_id,
        document_revision_author_agent_id=agent_id,
    )
    return {
        "state": "written",
        "size": updated.size_bytes,
        "revision": updated.revision,
    }

async def append_document_resource_text(
    item_id: UUID,
    *,
    agent_id: int,
    task_id: UUID | None,
    content: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Append text through the existing document concurrency contract."""

    return await document_service.append_document(
        item_id,
        actor_agent_id=agent_id,
        task_id=task_id,
        content=content,
        expected_revision=expected_revision,
    )
