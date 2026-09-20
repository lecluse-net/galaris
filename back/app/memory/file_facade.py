"""File-like public facade for governed memories and working documents."""

from __future__ import annotations

from typing import Literal
from core.util import read_html_page
from uuid import UUID

from . import document_attachment_service, document_service, facade, service
from .document_types import DocumentType
from .schemas import MemoryItemUpdate, MemoryPayload, MemorySearchRequest


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
        raise service.MemoryConflictError("The selected memory is not a document.")
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
        raise service.MemoryNotFoundError("Document attachment not found.")
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
    expected_kind: Literal["memory", "document"],
) -> dict[str, object]:
    """Describe an authorized item without leaking its storage locator."""

    item, _content, access, _content_type, media_type = await service.get_item(
        item_id,
        agent_id=agent_id,
    )
    if expected_kind == "document" and item.node_kind != "document":
        raise service.MemoryConflictError("The selected memory is not a document.")
    if expected_kind == "memory" and item.node_kind == "document":
        raise service.MemoryConflictError("Use document:// for a working document.")
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
            "document_type": item.document_type,
            "folder": str(item.metadata_.get("document_path") or ""),
            "content_profile": item.content_profile,
            "content_profile_version": item.content_profile_version,
            "offset_unit": "block" if media_type == "text/html" else "character",
            "node_kind": item.node_kind,
        },
    }


async def read_file_resource_text(
    item_id: UUID,
    *,
    agent_id: int,
    task_id: UUID | None,
    expected_kind: Literal["memory", "document"],
    offset: int,
    max_chars: int,
) -> dict[str, object]:
    """Read one bounded UTF-8 slice through Memory ACLs."""

    if expected_kind == "document":
        return await document_service.read_document(
            item_id,
            actor_agent_id=agent_id,
            task_id=task_id,
            offset=offset,
            max_chars=max_chars,
        )
    item, content, _access, content_type, media_type = await service.get_item(
        item_id,
        agent_id=agent_id,
        record_llm_access=True,
        task_id=task_id,
    )
    if item.node_kind == "document":
        raise service.MemoryConflictError("Use document:// for a working document.")
    if content_type != "text" and not media_type.startswith("text/"):
        raise service.MemoryConflictError("The selected memory is not UTF-8 text.")
    text = content.decode("utf-8")
    if media_type == "text/html" and item.content_profile_version == 1:
        return {**read_html_page(text, offset=offset, max_chars=max_chars), "revision": item.revision, "content_profile": item.content_profile}
    start = min(max(0, offset), len(text))
    end = min(len(text), start + max_chars)
    return {
        "media_type": media_type,
        "content": text[start:end],
        "start": start,
        "end": end,
        "total": len(text),
        "next_offset": end if end < len(text) else None,
        "revision": item.revision,
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
        raise service.MemoryConflictError(
            "expected_revision is required to replace a document; call file_read first."
        )
    item, _content, _access, _content_type, _media_type = await service.get_item(
        item_id,
        agent_id=agent_id,
    )
    if item.node_kind != "document":
        raise service.MemoryConflictError("The selected memory is not a document.")
    updated = await service.update_item(
        item_id,
        MemoryItemUpdate(
            expected_revision=expected_revision,
            payload=MemoryPayload(text=content),
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


async def search_file_resources(
    *,
    agent_id: int,
    task_id: UUID | None,
    expected_kind: Literal["memory", "document"],
    query: str,
    mode: Literal["name", "text", "semantic"],
    limit: int | None,
    offset: int,
) -> dict[str, object]:
    """Search authorized memories and return stable identifiers and excerpts."""

    ranked = bool(query.strip())
    diagnostics: dict[str, object] = {}
    if ranked:
        page_limit = limit if limit is not None else 50
        page = await facade.search_memory_detailed(
            query,
            agent_id=agent_id,
            limit=min(500, offset + page_limit + 1),
            node_kinds=["document"] if expected_kind == "document" else (),
            task_id=task_id,
            record_llm_access=False,
            telemetry_kind="search",
        )
        hits = page.hits[offset:offset + page_limit]
        total = len(page.hits)
        has_more = offset + len(hits) < len(page.hits)
        diagnostics = {
            "retrieval_mode": getattr(page, "mode", None),
            "degraded": getattr(page, "degraded", False),
            "degradation_reason": getattr(page, "degradation_reason", None),
            "ranking_version": getattr(page, "ranking_version", None),
            "relevance_status": getattr(page, "relevance_status", "matched" if page.hits else "no_sufficient_evidence"),
            "candidate_window_exhausted": page.has_more and not has_more,
            "index_coverage": (coverage.model_dump() if (coverage := getattr(page, "index_coverage", None)) is not None else None),
        }
        await service.record_llm_retrieval(agent_id=agent_id,
            item_scores=[(hit.item.id, hit.score) for hit in hits], query=query, task_id=task_id)
    else:
        browse_limit = limit if limit is not None else 50
        browse_page = await service.search_items(
            MemorySearchRequest(
                agent_id=agent_id,
                query=query,
                limit=browse_limit,
                offset=offset,
                node_kinds=["document"] if expected_kind == "document" else ["memory"],
                task_id=task_id,
            ),
            record_llm_access=True,
        )
        hits = browse_page.hits
        total = browse_page.total
        has_more = browse_page.has_more
    return {
        **diagnostics,
        "hits": [
            {
                "id": str(hit.item.id),
                "uri": f"{'document' if hit.item.node_kind == 'document' else 'memory'}://{hit.item.id}",
                "node_kind": hit.item.node_kind,
                "title": hit.item.title,
                "filename": hit.item.filename,
                "media_type": hit.item.media_type,
                "size": hit.item.size_bytes,
                "revision": hit.item.revision,
                "checksum": hit.item.content_hash,
                "updated_at": (
                    hit.item.updated_at.isoformat()
                    if hit.item.updated_at is not None
                    else None
                ),
                "score": hit.score,
                "excerpt": hit.excerpt,
                "can_write": hit.item.access.can_write,
                "metadata": {**hit.item.metadata, "document_type": hit.item.document_type},
                "retrieval_sources": hit.retrieval_sources,
                "source_refs": hit.source_refs,
                "passages": [passage.model_dump() for passage in hit.passages],
            }
            for hit in hits
        ],
        "total": total,
        "has_more": has_more,
        "next_offset": offset + len(hits) if has_more else None,
    }


__all__ = [
    "append_document_resource_text",
    "create_document_attachment_file_resource",
    "create_document_file_resource",
    "delete_document_attachment_file_resource",
    "describe_document_attachment_file_resource",
    "describe_file_resource",
    "list_document_attachment_file_resources",
    "read_document_attachment_file_resource",
    "read_file_resource_text",
    "search_file_resources",
    "write_document_resource_text",
]
