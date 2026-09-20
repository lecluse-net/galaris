"""Small public facade for ranked governed-memory search."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from .contracts import MemorySearchItem
from .retrieval import recall_items
from .schemas import (
    MemoryNodeKind,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemoryRoleFilter,
    MemoryType,
)


def _search_request(
    text: str,
    *,
    agent_id: int,
    semantic_query: str | None,
    limit: int | None,
    memory_types: Sequence[MemoryType],
    node_kinds: Sequence[MemoryNodeKind],
    memory_role: MemoryRoleFilter | None,
    task_id: UUID | None,
    topic_item_id: UUID | None,
    contact_item_id: UUID | None,
    strict_contact_scope: bool,
    exclude_agent_projections: bool,
    exclude_source_managed: bool,
) -> MemoryRecallRequest:
    return MemoryRecallRequest(
        agent_id=agent_id,
        query=text,
        semantic_query=semantic_query,
        limit=limit,
        memory_types=list(memory_types),
        node_kinds=list(node_kinds),
        memory_role=memory_role,
        task_id=task_id,
        topic_item_id=topic_item_id,
        contact_item_id=contact_item_id,
        strict_contact_scope=strict_contact_scope,
        exclude_agent_projections=exclude_agent_projections,
        exclude_source_managed=exclude_source_managed,
    )


async def search_memory(
    text: str,
    *,
    agent_id: int,
    semantic_query: str | None = None,
    limit: int | None = None,
    memory_types: Sequence[MemoryType] = (),
    node_kinds: Sequence[MemoryNodeKind] = (),
    memory_role: MemoryRoleFilter | None = None,
    task_id: UUID | None = None,
    topic_item_id: UUID | None = None,
    contact_item_id: UUID | None = None,
    strict_contact_scope: bool = False,
    exclude_agent_projections: bool = False,
    exclude_source_managed: bool = False,
) -> list[MemorySearchItem]:
    """Return plain relevant items, most relevant first.

    ``agent_id`` is required because ACLs are part of the search contract. The
    ranking strategy is resolved from the live application Params by the
    retrieval service. Scores remain an internal implementation detail.
    """

    result = await search_memory_detailed(
        text,
        agent_id=agent_id,
        semantic_query=semantic_query,
        limit=limit,
        memory_types=memory_types,
        node_kinds=node_kinds,
        memory_role=memory_role,
        task_id=task_id,
        topic_item_id=topic_item_id,
        contact_item_id=contact_item_id,
        strict_contact_scope=strict_contact_scope,
        exclude_agent_projections=exclude_agent_projections,
        exclude_source_managed=exclude_source_managed,
    )
    return [
        MemorySearchItem(
            id=hit.item.id,
            title=hit.item.title,
            excerpt=hit.excerpt,
            memory_type=hit.item.memory_type,
            node_kind=hit.item.node_kind,
            source_refs=tuple(hit.source_refs),
            uri=f"{'document' if hit.item.node_kind == 'document' else 'memory'}://{hit.item.id}",
            revision=hit.item.revision,
        )
        for hit in result.hits
    ]


async def search_memory_detailed(
    text: str,
    *,
    agent_id: int,
    semantic_query: str | None = None,
    limit: int | None = None,
    memory_types: Sequence[MemoryType] = (),
    node_kinds: Sequence[MemoryNodeKind] = (),
    memory_role: MemoryRoleFilter | None = None,
    task_id: UUID | None = None,
    topic_item_id: UUID | None = None,
    contact_item_id: UUID | None = None,
    strict_contact_scope: bool = False,
    exclude_agent_projections: bool = False,
    exclude_source_managed: bool = False,
    record_llm_access: bool = False,
    telemetry_kind: str | None = None,
) -> MemoryRecallResult:
    """Run the canonical search while retaining diagnostics for internal consumers."""

    request = _search_request(
        text,
        agent_id=agent_id,
        semantic_query=semantic_query,
        limit=limit,
        memory_types=memory_types,
        node_kinds=node_kinds,
        memory_role=memory_role,
        task_id=task_id,
        topic_item_id=topic_item_id,
        contact_item_id=contact_item_id,
        strict_contact_scope=strict_contact_scope,
        exclude_agent_projections=exclude_agent_projections,
        exclude_source_managed=exclude_source_managed,
    )
    return await recall_items(
        request,
        record_llm_access=record_llm_access,
        telemetry_kind=telemetry_kind,
    )


from .attachment_description import record_attachment_description
from .attachment_analysis import (
    AttachmentAnalysisSource,
    attachment_analysis_path,
    attachment_analysis_source,
    empty_attachment_items,
    fill_attachment_description,
)


async def reconcile_structure_subject(kind: str, identity: UUID) -> int:
    """Re-read a source under its domain lock; never replay a Dream snapshot."""
    from sqlalchemy import select
    from core.database import get_db
    from .models import DocumentTag, MemoryItem
    from .document_structure import sync_document_structure, sync_folder_structure
    from .document_tags import lock_tree

    if kind == "folder":
        tag = await get_db().get(DocumentTag, identity)
        if tag is None:
            return 0
        await lock_tree(tag.user_id)
        await sync_folder_structure(tag.user_id)
    else:
        document = await get_db().scalar(select(MemoryItem).where(
            MemoryItem.id == identity, MemoryItem.node_kind == "document",
        ).with_for_update().execution_options(populate_existing=True))
        if document is None:
            return 0
        await sync_document_structure(document)
    return 1

async def enqueue_goal_folder_reconciliation(
    *, user_id: int | None = None, goal_id: UUID | None = None,
) -> UUID:
    """Queue personal Goal filing; caller commits, omitted filters select all."""
    from .goal_folders import enqueue_goal_folder_reconciliation as enqueue

    return await enqueue(user_id=user_id, goal_id=goal_id)


__all__ = ["search_memory", "search_memory_detailed", "record_attachment_description", "reconcile_structure_subject", "enqueue_goal_folder_reconciliation",
           "AttachmentAnalysisSource", "attachment_analysis_path", "attachment_analysis_source",
           "empty_attachment_items", "fill_attachment_description"]
