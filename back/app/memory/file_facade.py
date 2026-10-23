"""File-like public facade for governed memories and working documents."""

from __future__ import annotations

from typing import Literal
from core.util import read_html_page
from uuid import UUID

from . import facade, service
from .schemas import MemorySearchRequest
from .recall_scope import resolve_recall_scope














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
            "temporal": item.temporal,
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






async def search_file_resources(
    *,
    agent_id: int,
    task_id: UUID | None,
    expected_kind: Literal["memory", "document"],
    query: str,
    mode: Literal["name", "text", "semantic"],
    limit: int | None,
    offset: int,
    conversation_turn: object | None = None,
) -> dict[str, object]:
    """Search authorized memories and return stable identifiers and excerpts."""

    name_only = expected_kind == "document" and mode == "name"
    topic_item_id, contact_item_id = (None, None) if name_only else await resolve_recall_scope(
        agent_id=agent_id, task_id=task_id, conversation_turn=conversation_turn,
    )
    ranked = bool(query.strip()) and not name_only
    diagnostics: dict[str, object] = {}
    if ranked:
        page_limit = limit if limit is not None else 50
        page = await facade.search_memory_detailed(
            query,
            agent_id=agent_id,
            limit=min(500, offset + page_limit + 1),
            node_kinds=["document"] if expected_kind == "document" else (),
            task_id=task_id,
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
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
                topic_item_id=topic_item_id,
                contact_item_id=contact_item_id,
            ),
            record_llm_access=True,
            name_only=name_only,
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
                "metadata": {**({} if name_only else hit.item.metadata), "document_type": hit.item.document_type,
                             "temporal": hit.item.temporal.model_dump(mode="json") if hit.item.temporal else None},
                "retrieval_sources": hit.retrieval_sources,
                "source_refs": hit.source_refs,
                "passages": [] if name_only else [passage.model_dump() for passage in hit.passages],
            }
            for hit in hits
        ],
        "total": total,
        "has_more": has_more,
        "next_offset": offset + len(hits) if has_more else None,
    }


__all__=["describe_file_resource","read_file_resource_text","search_file_resources"]
