"""Governed memory persistence, retrieval, revision, and graph services."""

from __future__ import annotations

from core.user import HumanActor

import base64
import asyncio
import binascii
import hashlib
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Sequence, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import and_, case, delete, exists, func, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased, raiseload, selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql.elements import ColumnElement

from app.agent import Agent, get_agent_record
from core import websocket
from core.util import convert_to_html, visible_text, image_references, attachment_reference, archived_document_html
from .document_types import validate_dataset
from .document_apps import document_apps
from core.database import get_db
from core.user import get_user_record
from core.util import complete_await

from .access import (
    effective_access,
    managed_item_agent_ids,
    readable_item_clause,
)
from .admission import admit_search_hits
from .passages import lexical_excerpt, query_identity
from . import relevance
from .contracts import (
    MemoryAccess,
    ResourceStorageError,
    SourceMemoryDocument,
    TopicLinkedMemory,
    TopicLinkedDocument,
)
from .content_diff import content_diff_hunks as _content_diff_hunks
from .item_projection import item_to_public as item_to_public
from .library_queries import (
    list_recent_memories as list_recent_memories,
    list_document_keywords as list_document_keywords,
    list_document_owner_options as list_document_owner_options,
    browse_document_library as browse_document_library,
)
from .lifecycle import notify_memory_item
from .models import (
    MemoryAssociation,
    MemoryAutomationJob,
    MemoryAcquisition,
    MemoryContextEdge,
    MemoryContextNode,
    MemoryContactItem,
    MemoryFinding,
    MemoryItem,
    MemoryItemGrant,
    DocumentUserGrant,
    DocumentTeamGrant,
    MemoryLink,
    MemoryRevision,
    MemorySource,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
    MemoryUsage,
)
from .provenance import MemorySourceTargets, source_targets
from .schemas import (
    DocumentContentDiff,
    DocumentContentRevisionDetail,
    DocumentContentRevisionPage,
    DocumentContentRevisionPublic,
    DocumentGlobalAccessUpdate,
    DocumentFolderOption,
    DocumentOwnerUpdate,
    MemoryForgetResult,
    MemoryFilterOption,
    MemoryFilterOptions,
    MemoryGraphCursor,
    MemoryGraphEdge,
    MemoryGraphExpandRequest,
    MemoryGraphNode,
    MemoryGraphPage,
    MemoryGraphRootsRequest,
    MemoryGrantUpdate,
    MemoryItemCreate,
    MemoryItemDetail,
    MemoryItemUpdate,
    MemoryLinkCreate,
    MemoryLinkPublic,
    MemoryPayload,
    MemoryRevisionPublic,
    MemoryRetentionPreview,
    MemorySearchHit,
    MemorySearchPage,
    MemorySearchRequest,
    MemorySortField,
    MemorySourceCreate,
    MemoryType,
)
from .safety import assert_safe_text, assert_safe_value
from .storage import get_storage


class MemoryError(RuntimeError):
    """Base domain error."""


class MemoryNotFoundError(MemoryError):
    """The requested governed object is absent or invisible to the actor."""


class MemoryPermissionError(MemoryError):
    """The actor cannot perform the requested operation."""


class MemoryConflictError(MemoryError):
    """The requested state conflicts with an existing governed object."""


async def _commit_with_conflict(message: str) -> None:
    """Commit an optimistic write and expose stale ORM state as a domain conflict."""

    db = get_db()
    try:
        await db.commit()
    except StaleDataError as exc:
        await db.rollback()
        raise MemoryConflictError(message) from exc


def _assert_not_source_managed(item: MemoryItem) -> None:
    if item.source_managed:
        raise MemoryPermissionError(
            "This memory is generated from source data and can only be changed through that source."
        )


def _assert_not_deletion_protected(item: MemoryItem) -> None:
    if item.deletion_protected:
        raise MemoryPermissionError(
            "This document is owned by another Galaris resource and cannot be forgotten."
        )


def _is_goal_document(item: MemoryItem) -> bool:
    return item.metadata_.get("goal_document_kind") in {
        "description",
        "tracking",
    }


def decode_payload(payload: MemoryPayload) -> bytes:
    if payload.text is not None:
        return payload.text.encode("utf-8")
    assert payload.base64 is not None
    try:
        return base64.b64decode(payload.base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("The payload is not valid base64.") from exc


def encode_payload(content: bytes, *, content_type: str, media_type: str) -> MemoryPayload:
    textual = content_type == "text" or media_type.startswith("text/")
    if textual:
        try:
            return MemoryPayload(text=content.decode("utf-8"))
        except UnicodeDecodeError:
            pass
    return MemoryPayload(base64=base64.b64encode(content).decode("ascii"))


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _keywords(values: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()[:100]
        folded = value.casefold()
        if not value or folded in seen:
            continue
        normalized.append(value)
        seen.add(folded)
    return normalized[:50]


def _search_text(content: bytes, *, content_type: str, media_type: str) -> str:
    if content_type != "text" and not media_type.startswith("text/"):
        return ""
    decoded = content.decode("utf-8", errors="replace")
    return (
        visible_text(decoded) if content_type == "text" and media_type == "text/html" else decoded
    )[:2_000_000]


def _set_semantic_fingerprint(item: MemoryItem) -> None:
    from .semantic_index import stage_embedding_refresh

    stage_embedding_refresh(item)


async def _enqueue_semantic_projection(item: MemoryItem) -> None:
    """Keep memory writes fail-open while scheduling their vector projection."""

    try:
        from .semantic_index import enqueue_embedding_refresh

        await enqueue_embedding_refresh(item)
    except Exception:
        logger.exception(
            "Memory semantic-index scheduling failed: memory_id={}",
            item.id,
        )
        try:
            await get_db().rollback()
        except Exception:
            logger.exception(
                "Memory semantic-index scheduling rollback failed: memory_id={}",
                item.id,
            )


async def _emit_memory_event(
    action: Literal["create", "update", "delete"],
    item: MemoryItem,
) -> None:
    """Publish a content-free memory change notification after persistence."""

    if item.node_kind == "document" and action in {"update", "delete"}:
        from .document_thumbnail_cache import invalidate

        try:
            await asyncio.to_thread(invalidate, item.id)
        except OSError:
            logger.exception("Document thumbnail invalidation failed: document_id={}", item.id)

    try:
        await websocket.emit(
            "memory",
            action,
            {
                "id": str(item.id),
                "owner_agent_id": item.owner_agent_id,
                "owner_user_id": item.owner_user_id,
                "node_kind": item.node_kind,
                "revision": item.revision,
                "lock_version": item.lock_version,
                "media_type": item.media_type,
                "content_profile": item.content_profile,
                "content_profile_version": item.content_profile_version,
            },
            None,
        )
    except Exception:
        logger.exception(
            "Memory WebSocket emission failed: memory_id={} action={}",
            item.id,
            action,
        )


def _item_options(*, revisions: bool = True) -> tuple[Any, ...]:
    return (
        selectinload(MemoryItem.grants),
        selectinload(MemoryItem.revisions) if revisions else raiseload(MemoryItem.revisions),
    )


def _memory_sort_expression(sort_by: MemorySortField) -> ColumnElement[Any]:
    if sort_by == "title":
        return func.lower(MemoryItem.title)
    if sort_by == "memory_type":
        return cast(ColumnElement[Any], MemoryItem.memory_type)
    if sort_by == "visibility":
        return cast(ColumnElement[Any], MemoryItem.visibility)
    if sort_by == "owner":
        displayed_name = func.lower(
            func.trim(func.concat_ws(" ", Agent.first_name, Agent.last_name))
        )
        return func.coalesce(
            func.nullif(displayed_name, ""),
            func.lower(Agent.code),
        )
    if sort_by == "access_count":
        return cast(ColumnElement[Any], MemoryItem.access_count)
    if sort_by == "last_accessed_at":
        return cast(ColumnElement[Any], MemoryItem.last_accessed_at)
    if sort_by == "updated_at":
        return func.coalesce(MemoryItem.updated_at, MemoryItem.created_at)
    raise ValueError(f"Unsupported memory sort field: {sort_by}")


def _graph_item_filters(
    request: MemoryGraphRootsRequest | MemoryGraphExpandRequest,
    *,
    now: datetime,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = [
        readable_item_clause(request.agent_id),
        or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
        or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
        or_(
            MemoryItem.managed_source_kind.is_(None),
            MemoryItem.managed_source_kind != "agent",
        ),
        or_(
            MemoryItem.managed_source_kind.is_(None),
            MemoryItem.managed_source_kind != "topic",
            _topic_related_to_agent_clause(request.agent_id),
        ),
    ]
    if request.memory_types:
        filters.append(MemoryItem.memory_type.in_(request.memory_types))
    filters.extend(
        _exact_scope_filters(
            agent_id=request.agent_id,
            topic_item_id=request.topic_item_id,
            contact_item_id=request.contact_item_id,
        )
    )
    normalized = request.query.strip()
    if normalized:
        ts_query = func.websearch_to_tsquery("simple", normalized)
        filters.append(
            or_(
                MemoryItem.search_vector.op("@@")(ts_query),
                MemoryItem.title.ilike(f"%{normalized}%"),
                MemoryItem.search_text.ilike(f"%{normalized}%"),
            )
        )
    return filters


def _topic_related_to_agent_clause(agent_id: int) -> ColumnElement[bool]:
    """Require a Topic to contain memory owned by or directly granted to an agent."""

    related_item = aliased(MemoryItem)
    direct_grant = exists(
        select(MemoryItemGrant.id).where(
            MemoryItemGrant.item_id == related_item.id,
            MemoryItemGrant.agent_id == agent_id,
        )
    )
    return exists(
        select(MemoryLink.id)
        .join(related_item, related_item.id == MemoryLink.target_item_id)
        .where(
            MemoryLink.source_item_id == MemoryItem.id,
            MemoryLink.relation_type == "topic_contains",
            MemoryLink.suggested.is_(False),
            or_(related_item.owner_agent_id == agent_id, direct_grant),
        )
    )


def _exact_scope_filters(
    *,
    agent_id: int,
    topic_item_id: UUID | None,
    contact_item_id: UUID | None,
) -> list[ColumnElement[bool]]:
    """Return independent exact filters for administrative memory browsing."""

    filters: list[ColumnElement[bool]] = []
    if topic_item_id is not None:
        filters.append(
            exists(
                select(MemoryLink.id).where(
                    MemoryLink.source_item_id == topic_item_id,
                    MemoryLink.target_item_id == MemoryItem.id,
                    MemoryLink.relation_type == "topic_contains",
                    MemoryLink.suggested.is_(False),
                )
            )
        )
    if contact_item_id is not None:
        direct_membership = exists(
            select(MemoryContactItem.id).where(
                MemoryContactItem.item_id == MemoryItem.id,
                MemoryContactItem.owner_agent_id == agent_id,
                MemoryContactItem.contact_item_id == contact_item_id,
            )
        )
        scoped_membership = exists(
            select(MemoryTopicContactItem.id)
            .join(
                MemoryTopicContactScope,
                MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
            )
            .where(
                MemoryTopicContactItem.item_id == MemoryItem.id,
                MemoryTopicContactScope.owner_agent_id == agent_id,
                MemoryTopicContactScope.contact_item_id == contact_item_id,
            )
        )
        filters.append(or_(direct_membership, scoped_membership))
    return filters


def _graph_node(item: MemoryItem, *, relation_count: int) -> MemoryGraphNode:
    entity_kind: Literal["memory", "document", "attachment", "folder", "topic", "contact"] = "memory"
    if item.node_kind == "document":
        entity_kind = "document"
    elif item.node_kind == "attachment":
        entity_kind = "attachment"
    elif item.node_kind == "folder":
        entity_kind = "folder"
    elif item.managed_source_kind == "topic":
        entity_kind = "topic"
    elif item.managed_source_kind == "messenger_contact":
        entity_kind = "contact"
    return MemoryGraphNode(
        id=item.id,
        resource_media_type=item.metadata_.get("resource_media_type") if item.node_kind == "attachment" else None,
        node_kind=cast(Any, item.node_kind),
        entity_kind=entity_kind,
        owner_agent_id=item.owner_agent_id,
        title=item.title,
        memory_type=cast(Any, item.memory_type),
        visibility=cast(Any, item.visibility),
        source_managed=item.source_managed,
        access_count=item.access_count,
        last_accessed_at=item.last_accessed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        activity_at=item.activity_at,
        has_relations=relation_count > 0,
        relation_count=relation_count,
    )


def _graph_context_node(
    node: MemoryContextNode,
    *,
    relation_count: int,
) -> MemoryGraphNode:
    return MemoryGraphNode(
        id=node.id,
        node_kind="conversation",
        entity_kind="conversation",
        owner_agent_id=node.owner_agent_id,
        title=node.title,
        memory_type="episodic",
        visibility="private",
        source_managed=True,
        access_count=0,
        last_accessed_at=None,
        created_at=node.created_at,
        updated_at=node.updated_at,
        activity_at=node.activity_at,
        has_relations=relation_count > 0,
        relation_count=relation_count,
    )


def _graph_edge(link: MemoryLink) -> MemoryGraphEdge:
    return MemoryGraphEdge(
        id=link.id,
        source_item_id=link.source_item_id,
        target_item_id=link.target_item_id,
        relation_type=link.relation_type,
        confidence=link.confidence,
        suggested=link.suggested,
    )


def _graph_context_edge(edge: MemoryContextEdge) -> MemoryGraphEdge:
    return MemoryGraphEdge(
        id=edge.id,
        source_item_id=edge.context_node_id,
        target_item_id=edge.item_id,
        relation_type=edge.relation_type,
        confidence=1.0,
        suggested=False,
    )


async def _graph_relation_counts(
    node_ids: Sequence[UUID],
    request: MemoryGraphRootsRequest | MemoryGraphExpandRequest,
    *,
    now: datetime,
) -> dict[UUID, int]:
    """Count distinct accessible neighboring items for each requested node."""

    if not node_ids:
        return {}
    accessible_items = (
        select(MemoryItem.id.label("id")).where(*_graph_item_filters(request, now=now)).subquery()
    )
    neighbor_pairs = union_all(
        select(
            MemoryLink.source_item_id.label("node_id"),
            MemoryLink.target_item_id.label("neighbor_id"),
        ).join(
            accessible_items,
            accessible_items.c.id == MemoryLink.target_item_id,
        ),
        select(
            MemoryLink.target_item_id.label("node_id"),
            MemoryLink.source_item_id.label("neighbor_id"),
        ).join(
            accessible_items,
            accessible_items.c.id == MemoryLink.source_item_id,
        ),
    ).subquery()
    db = get_db()
    result = await db.execute(
        select(
            neighbor_pairs.c.node_id,
            func.count(func.distinct(neighbor_pairs.c.neighbor_id)),
        )
        .where(neighbor_pairs.c.node_id.in_(node_ids))
        .group_by(neighbor_pairs.c.node_id)
    )
    counts = {cast(UUID, row.node_id): int(row[1]) for row in result}
    context_result = await db.execute(
        select(
            MemoryContextEdge.item_id,
            func.count(func.distinct(MemoryContextEdge.context_node_id)),
        )
        .join(
            MemoryContextNode,
            MemoryContextNode.id == MemoryContextEdge.context_node_id,
        )
        .where(
            MemoryContextEdge.item_id.in_(node_ids),
            MemoryContextNode.owner_agent_id == request.agent_id,
        )
        .group_by(MemoryContextEdge.item_id)
    )
    for row in context_result:
        item_id = cast(UUID, row[0])
        counts[item_id] = counts.get(item_id, 0) + int(row[1])
    return counts


async def _get_item_record(
    item_id: UUID, *, include_historized: bool = False, revisions: bool = True
) -> MemoryItem | None:
    db = get_db()
    # Services intentionally reuse the request-scoped session. Refresh loaded
    # relationships so a grant written earlier in the same transaction
    # is immediately reflected by the in-memory ACL evaluation.
    query = (
        select(MemoryItem)
        .options(*_item_options(revisions=revisions))
        .where(MemoryItem.id == item_id)
        .execution_options(populate_existing=True)
    )
    if include_historized:
        query = query.execution_options(include_historized=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def item_record(item_id: UUID) -> MemoryItem | None:
    """Load a current memory resource and its grants for domain services."""
    return await _get_item_record(item_id)


async def document_record(document_id: UUID) -> MemoryItem | None:
    """Load the current document, including its grants, for document services."""
    item = await _get_item_record(document_id)
    return item if item is not None and item.node_kind == "document" else None


async def commit_item_sharing(item: MemoryItem) -> None:
    """Commit sharing without changing content revisions and notify open views."""
    await _commit_with_conflict("Document sharing changed; reload and retry")
    await _emit_memory_event("update", item)
    await invalidate_memory_views()
    await notify_memory_item(item.id, "sharing")


async def invalidate_memory_views() -> None:
    """Ask authenticated readers to discard snapshots after access changes."""
    await websocket.emit("memory", "invalidate", {}, None)


async def assert_item_access(
    item: MemoryItem,
    agent_id: int | HumanActor | None,
    *,
    write: bool = False,
    administrative: bool = False,
) -> MemoryAccess:
    if write:
        _assert_not_source_managed(item)
    if administrative:
        return MemoryAccess(can_read=True, can_write=not item.source_managed)
    if agent_id is None:
        raise MemoryPermissionError("An agent identity is required.")
    access = await effective_access(item, agent_id)
    allowed = access.can_write if write else access.can_read
    if not allowed:
        raise MemoryPermissionError("Memory access denied.")
    return access


async def _add_source(
    item: MemoryItem, source: MemorySourceCreate, *, content_hash: str | None = None
) -> None:
    assert_safe_value(source.model_dump())
    db = get_db()
    existing = await db.scalar(
        select(MemorySource).where(
            MemorySource.item_id == item.id,
            MemorySource.source_kind == source.source_kind,
            MemorySource.source_ref == source.source_ref,
        )
    )
    targets = await _existing_source_targets(
        source.source_kind,
        source.source_ref,
    )
    if existing is not None:
        existing.task_id = existing.task_id or targets.task_id
        existing.conversation_round_id = (
            existing.conversation_round_id or targets.conversation_round_id
        )
        return
    db.add(
        MemorySource(
            item_id=item.id,
            task_id=targets.task_id,
            conversation_round_id=targets.conversation_round_id,
            source_kind=source.source_kind,
            source_ref=source.source_ref,
            excerpt=source.excerpt,
            content_hash=content_hash,
            metadata_=dict(source.metadata),
        )
    )
    item.old_at = None
    item.old_reason = None


async def _existing_source_targets(
    source_kind: str,
    source_ref: str,
) -> MemorySourceTargets:
    """Return only canonical targets that currently exist in PostgreSQL."""

    from app.conversation import ConversationRound
    from app.task import Task

    parsed = source_targets(source_kind, source_ref)
    db = get_db()
    task_id = (
        await db.scalar(
            select(Task.id)
            .where(Task.id == parsed.task_id)
            .execution_options(include_historized=True)
        )
        if parsed.task_id is not None
        else None
    )
    conversation_round_id = (
        await db.scalar(
            select(ConversationRound.id).where(ConversationRound.id == parsed.conversation_round_id)
        )
        if parsed.conversation_round_id is not None
        else None
    )
    return MemorySourceTargets(
        task_id=task_id,
        conversation_round_id=conversation_round_id,
    )


def _revision_for(
    item: MemoryItem,
    *,
    author_agent_id: int | None,
    task_id: UUID | None = None,
    document_content_version: bool | None = None,
    document_append: bool = False,
) -> MemoryRevision:
    return MemoryRevision(
        item_id=item.id,
        revision=item.revision,
        task_id=task_id,
        provider_code=item.provider_code,
        resource_id=item.resource_id,
        content_hash=item.content_hash,
        document_content_version=document_content_version,
        document_append=document_append,
        content_type=item.content_type,
        media_type=item.media_type,
        content_profile_version=item.content_profile_version,
        filename=item.filename,
        title=item.title,
        keywords=list(item.keywords),
        metadata_=dict(item.metadata_),
        author_agent_id=author_agent_id,
    )


async def create_item(
    data: MemoryItemCreate,
    *,
    actor_task_id: UUID | None = None,
    deletion_protected: bool = False,
    deduplicate: bool = True,
    owner_user_id: int | None = None,
    initial_editor_agent_id: int | None = None,
) -> tuple[MemoryItem, bool]:
    """Create a logical memory and immutable first resource revision."""

    if owner_user_id is not None and data.node_kind != "document":
        raise ValueError("Only a document can be owned by a User.")
    if owner_user_id is None and initial_editor_agent_id is not None:
        raise ValueError("An initial editor grant is only valid for a User-owned document.")
    if any(
        key in data.metadata
        for key in ("document_attachments", "retained_document_attachments", "content_images")
    ):
        raise MemoryPermissionError("Attachment metadata is server-owned.")
    content = decode_payload(data.payload)
    if data.node_kind == "document" and data.document_type == "dataset":
        if deletion_protected:
            raise ValueError("Managed editorial documents cannot be datasets.")
        validate_dataset(content)
    if data.content_type == "text" and data.media_type in {
        "text/html",
        "text/markdown",
        "text/plain",
    }:
        content = convert_to_html(
            content.decode("utf-8"),
            data.media_type,
            profile="document"
            if data.node_kind == "document" and not deletion_protected
            else "rich-text",
        ).encode("utf-8")
        # A new document has no attachments yet. References can be inserted only
        # after upload, through update_item's ownership validation.
        if image_references(content.decode("utf-8")):
            raise MemoryPermissionError(
                "The image must belong to this document's attachments."
            )
        data = data.model_copy(update={"media_type": "text/html"})
    if data.content_type == "text" or data.media_type.startswith("text/"):
        assert_safe_text(content.decode("utf-8", errors="replace"))
    assert_safe_value(data.model_dump(exclude={"payload", "source"}, mode="python"))
    if data.source is not None:
        assert_safe_value(data.source.model_dump(mode="python"))
    if data.node_kind == "document" and data.document_type == "html":
        apps = document_apps(content.decode("utf-8"))
        if apps and deletion_protected:
            raise ValueError("Managed editorial documents cannot contain applications.")
    digest = _content_hash(content)
    db = get_db()
    if deduplicate and data.node_kind == "memory":
        existing_result = await db.execute(
            select(MemoryItem)
            .options(*_item_options())
            .where(
                MemoryItem.owner_agent_id == data.owner_agent_id,
                MemoryItem.content_hash == digest,
                MemoryItem.valid_from.is_not_distinct_from(data.valid_from),
                MemoryItem.valid_until.is_not_distinct_from(data.valid_until),
                MemoryItem.source_managed.is_(False),
                MemoryItem.node_kind == "memory",
            )
            .order_by(MemoryItem.created_at)
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            if data.source is not None:
                await _add_source(existing, data.source, content_hash=digest)
                await db.commit()
            await _enqueue_semantic_projection(existing)
            return existing, False

    provider = get_storage(data.provider_code)
    resource_id = await provider.create(content)
    item = MemoryItem(
        owner_agent_id=None if owner_user_id is not None else data.owner_agent_id,
        owner_user_id=owner_user_id,
        provider_code=provider.code,
        resource_id=resource_id,
        title=data.title.strip(),
        memory_type=data.memory_type,
        node_kind=data.node_kind,
        document_type=data.document_type,
        content_type=data.content_type,
        media_type=data.media_type,
        content_profile_version=1
        if data.content_type == "text" and data.media_type == "text/html"
        else None,
        filename=data.filename,
        keywords=_keywords(data.keywords),
        metadata_=dict(data.metadata),
        visibility=data.visibility,
        read_only=data.read_only,
        deletion_protected=deletion_protected,
        content_hash=digest,
        size_bytes=len(content),
        search_text=_search_text(
            content, content_type=data.content_type, media_type=data.media_type
        ),
        valid_from=data.valid_from,
        valid_until=data.valid_until,
    )
    _set_semantic_fingerprint(item)
    try:
        db.add(item)
        await db.flush()
        if initial_editor_agent_id is not None:
            db.add(
                MemoryItemGrant(
                    item_id=item.id,
                    agent_id=initial_editor_agent_id,
                    can_write=True,
                )
            )
        db.add(
            _revision_for(
                item,
                author_agent_id=None if owner_user_id is not None else data.owner_agent_id,
                task_id=actor_task_id,
                document_content_version=(True if data.node_kind == "document" else None),
            )
        )
        if data.source is not None:
            await _add_source(item, data.source, content_hash=digest)
        if item.node_kind == "document":
            from .document_structure import sync_document_structure
            await sync_document_structure(item, content)
        await db.commit()
    except BaseException:

        async def discard_unpublished() -> None:
            await db.rollback()
            # A cancelled COMMIT may have reached PostgreSQL. Never delete its
            # file until a fresh transaction confirms that no item was published.
            referenced = await db.scalar(
                select(MemoryItem.id)
                .where(
                    MemoryItem.provider_code == provider.code,
                    MemoryItem.resource_id == resource_id,
                )
                .execution_options(include_historized=True)
                .limit(1)
            )
            if referenced is None:
                await provider.delete(resource_id)

        try:
            await complete_await(discard_unpublished())
        except Exception:
            logger.exception("Unable to reconcile an interrupted Memory creation")
        raise
    loaded = await _get_item_record(item.id)
    assert loaded is not None
    await _enqueue_semantic_projection(loaded)
    await _emit_memory_event("create", loaded)
    await notify_memory_item(loaded.id, "create")
    return loaded, True


async def _upsert_managed_source(
    item: MemoryItem,
    document: SourceMemoryDocument,
    *,
    content_hash: str,
) -> None:
    """Keep the provenance row aligned with its deterministic projection."""

    db = get_db()
    source = await db.scalar(
        select(MemorySource).where(
            MemorySource.item_id == item.id,
            MemorySource.source_kind == document.source_kind,
            MemorySource.source_ref == document.source_ref,
        )
    )
    metadata = {
        **document.metadata,
        "managed_projection": True,
    }
    if source is None:
        db.add(
            MemorySource(
                item_id=item.id,
                source_kind=document.source_kind,
                source_ref=document.source_ref,
                excerpt=item.search_text[:8_000],
                content_hash=content_hash,
                metadata_=metadata,
            )
        )
        return
    source.excerpt = item.search_text[:8_000]
    source.content_hash = content_hash
    source.metadata_ = metadata


async def upsert_source_managed_item(
    document: SourceMemoryDocument,
    *,
    provider_code: str | None = None,
    recreate: bool = False,
) -> MemoryItem:
    """Create or refresh one immutable-to-users projection from canonical data."""

    source_kind = document.source_kind.strip()
    source_ref = document.source_ref.strip()
    if not source_kind or len(source_kind) > 80:
        raise ValueError("A managed memory source kind is required.")
    if not source_ref or len(source_ref) > 1_024:
        raise ValueError("A managed memory source reference is required.")
    if document.visibility == "private":
        if document.owner_agent_id is None or document.owner_agent_id <= 0:
            raise ValueError("A private managed memory requires an owner agent.")
    elif document.owner_agent_id is not None:
        raise ValueError("A public managed memory must not have an owner agent.")
    if source_kind == "topic":
        if document.topic_id is None:
            raise ValueError("A Topic projection requires its canonical Topic id.")
        if document.visibility != "public":
            raise ValueError("A Topic projection must be public.")
    elif document.topic_id is not None:
        raise ValueError("Only a Topic projection can own a canonical Topic id.")
    content = convert_to_html(document.content, document.media_type).encode("utf-8")
    assert_safe_text(document.content)
    assert_safe_value(document.metadata)
    assert_safe_value(document.keywords)
    digest = _content_hash(content)
    normalized_title = document.title.strip()[:500]
    normalized_keywords = _keywords(document.keywords)
    normalized_metadata = dict(document.metadata)
    normalized_filename = document.filename.strip()[:500] or None
    if not normalized_title:
        raise ValueError("A managed memory title is required.")

    db = get_db()
    item: MemoryItem | None = None
    if document.memory_item_id is not None:
        pointed = await _get_item_record(document.memory_item_id)
        if pointed is not None:
            if not pointed.source_managed:
                raise MemoryConflictError("The source points to a user-managed memory item.")
            if (
                pointed.managed_source_kind != source_kind
                or pointed.managed_source_ref != source_ref
            ):
                raise MemoryConflictError(
                    "The source points to a different managed memory projection."
                )
            item = pointed
    if item is None:
        item = await db.scalar(
            select(MemoryItem)
            .options(*_item_options())
            .where(
                MemoryItem.source_managed.is_(True),
                MemoryItem.managed_source_kind == source_kind,
                MemoryItem.managed_source_ref == source_ref,
            )
        )

    if recreate and item is not None:
        await _forget_item_record(item, forget_kind="retention")
        item = None

    selected_provider_code = (provider_code or "native").strip()
    if item is not None and provider_code is not None:
        if item.provider_code != selected_provider_code:
            raise MemoryConflictError("Changing a managed memory provider requires recreation.")

    if item is None:
        provider = get_storage(selected_provider_code)
        resource_id = await provider.create(content)
        item = MemoryItem(
            owner_agent_id=document.owner_agent_id,
            topic_id=document.topic_id,
            provider_code=provider.code,
            resource_id=resource_id,
            title=normalized_title,
            memory_type=document.memory_type,
            content_type="text",
            media_type="text/html",
            content_profile_version=1,
            filename=normalized_filename,
            keywords=normalized_keywords,
            metadata_=normalized_metadata,
            visibility=document.visibility,
            read_only=True,
            source_managed=True,
            managed_source_kind=source_kind,
            managed_source_ref=source_ref,
            content_hash=digest,
            size_bytes=len(content),
            search_text=_search_text(
                content,
                content_type="text",
                media_type="text/html",
            ),
        )
        _set_semantic_fingerprint(item)
        try:
            db.add(item)
            await db.flush()
            db.add(
                _revision_for(
                    item,
                    author_agent_id=None,
                )
            )
            await _upsert_managed_source(item, document, content_hash=digest)
            await db.commit()
        except Exception:
            await db.rollback()
            await provider.delete(resource_id)
            raise
        loaded = await _get_item_record(item.id)
        assert loaded is not None
        await _enqueue_semantic_projection(loaded)
        return loaded

    new_resource_id: str | None = None
    provider = get_storage(item.provider_code)
    content_changed = item.content_hash != digest
    keywords_changed = list(item.keywords) != normalized_keywords
    changed = (
        content_changed
        or keywords_changed
        or any(
            (
                item.owner_agent_id != document.owner_agent_id,
                item.topic_id != document.topic_id,
                item.title != normalized_title,
                item.memory_type != document.memory_type,
                item.content_type != "text",
                item.media_type != "text/html",
                item.filename != normalized_filename,
                dict(item.metadata_) != normalized_metadata,
                item.visibility != document.visibility,
                not item.read_only,
                not item.source_managed,
            )
        )
    )
    if content_changed:
        new_resource_id = await provider.create(content)
        item.resource_id = new_resource_id
        item.content_hash = digest
        item.size_bytes = len(content)
        item.search_text = _search_text(
            content,
            content_type="text",
            media_type="text/html",
        )
    item.owner_agent_id = document.owner_agent_id
    item.topic_id = document.topic_id
    item.title = normalized_title
    item.memory_type = document.memory_type
    item.content_type = "text"
    item.media_type = "text/html"
    item.content_profile_version = 1
    item.filename = normalized_filename
    item.keywords = normalized_keywords
    item.metadata_ = normalized_metadata
    item.visibility = document.visibility
    item.read_only = True
    item.source_managed = True
    item.managed_source_kind = source_kind
    item.managed_source_ref = source_ref
    await db.execute(delete(MemoryItemGrant).where(MemoryItemGrant.item_id == item.id))
    await _upsert_managed_source(item, document, content_hash=digest)
    _set_semantic_fingerprint(item)
    if not changed:
        await db.commit()
        loaded = await _get_item_record(item.id)
        assert loaded is not None
        await _enqueue_semantic_projection(loaded)
        return loaded

    if content_changed or keywords_changed:
        item.updated_at = datetime.now(timezone.utc)
    # A document revision describes its payload, not its metadata or ACLs.
    if item.node_kind != "document" or content_changed:
        item.revision += 1
        db.add(
            _revision_for(
                item,
                author_agent_id=None,
                document_content_version=(True if item.node_kind == "document" else None),
            )
        )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if new_resource_id is not None:
            await provider.delete(new_resource_id)
        raise
    loaded = await _get_item_record(item.id)
    assert loaded is not None
    await _enqueue_semantic_projection(loaded)
    await _emit_memory_event("update", loaded)
    return loaded


async def get_item(
    item_id: UUID,
    *,
    agent_id: int | HumanActor | None,
    administrative: bool = False,
    revision: int | None = None,
    record_llm_access: bool = False,
    task_id: UUID | None = None,
) -> tuple[MemoryItem, bytes, MemoryAccess, str, str]:
    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    access = await assert_item_access(item, agent_id, administrative=administrative)
    provider_code = item.provider_code
    resource_id = item.resource_id
    content_type = item.content_type
    media_type = item.media_type
    if revision is not None and revision != item.revision:
        snapshot = next((entry for entry in item.revisions if entry.revision == revision), None)
        if snapshot is None:
            raise MemoryNotFoundError("Memory revision not found.")
        provider_code = snapshot.provider_code
        resource_id = snapshot.resource_id
        content_type = snapshot.content_type
        media_type = snapshot.media_type
    content = await get_storage(provider_code).read(resource_id)
    if record_llm_access and isinstance(agent_id, int):
        db = get_db()
        accessed_at = datetime.now(timezone.utc)
        await db.execute(
            update(MemoryItem)
            .where(MemoryItem.id == item.id)
            .values(
                last_accessed_at=accessed_at,
                access_count=MemoryItem.access_count + 1,
                updated_at=MemoryItem.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        usage_values = {
            "item_id": item.id,
            "agent_id": agent_id,
            "task_id": task_id,
            "access_kind": "read",
            "query": "",
        }
        if task_id is None:
            db.add(MemoryUsage(**usage_values))
        else:
            await db.execute(
                pg_insert(MemoryUsage)
                .values(**usage_values)
                .on_conflict_do_nothing(constraint="uq_memory_usage_task_item")
            )
        # The native MCP wrapper owns the transaction. Flushing here keeps concurrent
        # reads atomic without committing halfway through resource-effect recording.
        await db.flush()
        await db.refresh(
            item,
            attribute_names=[
                "last_accessed_at",
                "access_count",
                "updated_at",
            ],
        )
    return item, content, access, content_type, media_type


async def source_refs(item_id: UUID) -> list[str]:
    result = await get_db().execute(
        select(MemorySource.source_ref)
        .where(MemorySource.item_id == item_id)
        .order_by(MemorySource.created_at)
    )
    return list(result.scalars().all())


async def _source_refs_by_item(item_ids: list[UUID]) -> dict[UUID, list[str]]:
    if not item_ids:
        return {}
    rows = await get_db().execute(
        select(MemorySource.item_id, MemorySource.source_ref)
        .where(MemorySource.item_id.in_(item_ids))
        .order_by(MemorySource.created_at)
    )
    refs: dict[UUID, list[str]] = {}
    for item_id, reference in rows:
        refs.setdefault(item_id, []).append(reference)
    return refs


async def add_item_source(
    item_id: UUID,
    source: MemorySourceCreate,
    *,
    actor_agent_id: int | None,
    administrative: bool = False,
) -> None:
    """Attach idempotent provenance after an accepted update."""

    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    await assert_item_access(item, actor_agent_id, write=True, administrative=administrative)
    await _add_source(item, source, content_hash=item.content_hash)
    await get_db().commit()
    await notify_memory_item(item.id, "source")


async def link_item_source(
    item_id: UUID,
    source: MemorySourceCreate,
    *,
    actor_agent_id: int,
) -> None:
    """Link provenance to any readable node without modifying that node."""

    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    await assert_item_access(item, actor_agent_id)
    await _add_source(item, source, content_hash=item.content_hash)
    await get_db().commit()
    await notify_memory_item(item.id, "source")


async def item_to_detail(
    item: MemoryItem,
    content: bytes,
    access: MemoryAccess,
    *,
    content_type: str | None = None,
    media_type: str | None = None,
    revision: int | None = None,
) -> MemoryItemDetail:
    public = item_to_public(item, access)
    values = public.model_dump()
    values["media_type"] = media_type or item.media_type
    values["content_type"] = content_type or item.content_type
    values["content_profile_version"] = (
        item.content_profile_version if values["media_type"] == "text/html" else None
    )
    if revision is not None and revision != item.revision:
        selected = next((entry for entry in item.revisions if entry.revision == revision), None)
        if selected is None:
            raise MemoryNotFoundError("Memory revision not found.")
        values.update(
            revision=selected.revision,
            media_type=selected.media_type,
            content_type=selected.content_type,
            content_profile_version=selected.content_profile_version,
            content_hash=selected.content_hash,
            size_bytes=len(content),
            title=selected.title,
            keywords=list(selected.keywords),
        )
    return MemoryItemDetail(
        **values,
        payload=encode_payload(
            content,
            content_type=content_type or item.content_type,
            media_type=media_type or item.media_type,
        ),
        source_refs=await source_refs(item.id),
    )


async def list_revisions(
    item_id: UUID,
    *,
    agent_id: int | None,
    administrative: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryRevisionPublic]:
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Invalid revision pagination")
    item = await _get_item_record(item_id, revisions=False)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    await assert_item_access(item, agent_id, administrative=administrative)
    rows = await get_db().scalars(
        select(MemoryRevision)
        .where(MemoryRevision.item_id == item_id)
        .order_by(MemoryRevision.revision)
        .offset(offset)
        .limit(limit)
    )
    return [MemoryRevisionPublic.model_validate(entry) for entry in rows]


def _document_content_revision_rows(item: MemoryItem) -> list[MemoryRevision]:
    """Return explicit content versions plus recoverable legacy Agent versions."""

    rows: list[MemoryRevision] = []
    previous_hash: str | None = None
    for entry in item.revisions:
        legacy_content_version = bool(
            entry.document_content_version is None
            and (
                entry.revision == 1
                or (
                    entry.task_id is not None
                    and previous_hash is not None
                    and entry.content_hash != previous_hash
                )
            )
        )
        if entry.document_content_version is True or legacy_content_version:
            rows.append(entry)
        previous_hash = entry.content_hash
    return rows


async def list_document_content_revisions(
    item_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
    limit: int = 50,
    offset: int = 0,
) -> DocumentContentRevisionPage:
    """List only restorable document-content versions, newest first."""

    item = await _get_item_record(item_id, revisions=False)
    if item is None or item.node_kind != "document":
        raise MemoryNotFoundError("Document not found.")
    await assert_item_access(item, actor_agent_id)
    from .revision_queries import content_revision_page

    rows, total = await content_revision_page(item_id, limit=limit, offset=offset)
    return DocumentContentRevisionPage(
        items=[DocumentContentRevisionPublic.model_validate(entry) for entry in rows],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + limit < total,
    )


async def _document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    actor_agent_id: int | HumanActor,
) -> tuple[MemoryItem, MemoryRevision, bytes]:
    item = await _get_item_record(item_id)
    if item is None or item.node_kind != "document":
        raise MemoryNotFoundError("Document not found.")
    await assert_item_access(item, actor_agent_id)
    entry = next(
        (
            candidate
            for candidate in _document_content_revision_rows(item)
            if candidate.revision == revision
        ),
        None,
    )
    if entry is None:
        raise MemoryNotFoundError("Document content revision not found.")
    content = await get_storage(entry.provider_code).read(entry.resource_id)
    return item, entry, content


async def get_document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    actor_agent_id: int | HumanActor,
) -> DocumentContentRevisionDetail:
    """Read one immutable UTF-8 document-content version."""

    _item, entry, content = await _document_content_revision(
        item_id,
        revision,
        actor_agent_id=actor_agent_id,
    )
    return DocumentContentRevisionDetail(
        **DocumentContentRevisionPublic.model_validate(entry).model_dump(),
        content=content.decode("utf-8"),
    )


async def diff_document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    actor_agent_id: int | HumanActor,
) -> DocumentContentDiff:
    """Compare one stored content version with the current document text."""

    item, entry, previous_content = await _document_content_revision(
        item_id,
        revision,
        actor_agent_id=actor_agent_id,
    )
    current_content = await get_storage(item.provider_code).read(item.resource_id)
    hunks, additions, deletions = _content_diff_hunks(
        visible_text(previous_content.decode("utf-8"))
        if entry.media_type == "text/html"
        else previous_content.decode("utf-8"),
        visible_text(current_content.decode("utf-8"))
        if item.media_type == "text/html"
        else current_content.decode("utf-8"),
    )
    return DocumentContentDiff(
        revision=revision,
        current_revision=item.revision,
        additions=additions,
        deletions=deletions,
        hunks=hunks,
        structure_changed=entry.content_hash != item.content_hash
        and (entry.media_type == "text/html" or item.media_type == "text/html"),
        previous_html=previous_content.decode("utf-8") if entry.media_type == "text/html" else None,
        current_html=current_content.decode("utf-8") if item.media_type == "text/html" else None,
    )


async def _delete_resource_if_unreferenced(
    provider_code: str,
    resource_id: str,
) -> None:
    db = get_db()
    current_reference = await db.scalar(
        select(MemoryItem.id)
        .where(
            MemoryItem.provider_code == provider_code,
            MemoryItem.resource_id == resource_id,
        )
        .limit(1)
    )
    revision_reference = await db.scalar(
        select(MemoryRevision.id)
        .where(
            MemoryRevision.provider_code == provider_code,
            MemoryRevision.resource_id == resource_id,
        )
        .limit(1)
    )
    if current_reference is not None or revision_reference is not None:
        return
    try:
        await get_storage(provider_code).delete(resource_id)
    except Exception as exc:
        logger.warning(
            "Unreferenced memory resource cleanup failed: provider={} resource={} error={}",
            provider_code,
            resource_id,
            exc,
        )


async def update_item(
    item_id: UUID,
    data: MemoryItemUpdate,
    *,
    actor_agent_id: int | HumanActor | None,
    administrative: bool = False,
    actor_task_id: UUID | None = None,
    notify_observers: bool = True,
    preserve_document_attachments: bool = True,
    document_revision_author_agent_id: int | None = None,
    document_append: bool = False,
    allow_goal_document_metadata_sync: bool = False,
) -> MemoryItem:
    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    await assert_item_access(item, actor_agent_id, write=True, administrative=administrative)
    if data.expected_revision is not None and data.expected_revision != item.revision:
        raise MemoryConflictError(
            f"Memory revision conflict: expected {data.expected_revision}, "
            f"current revision is {item.revision}."
        )
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise MemoryConflictError(
            "The document changed while it was being edited; reload and retry."
        )
    fields = data.model_fields_set - {
        "expected_revision",
        "expected_lock_version",
    }
    if not fields:
        return item
    if "visibility" in fields and data.visibility != item.visibility:
        owns_item = (
            item.owner_agent_id == actor_agent_id if isinstance(actor_agent_id, int)
            else isinstance(actor_agent_id, HumanActor) and item.owner_user_id == actor_agent_id.user_id
        )
        if not administrative and not owns_item:
            raise MemoryPermissionError("Only the owner can manage sharing.")
        if item.global_access > 0 and data.visibility != "shared":
            raise MemoryConflictError("Update public access through the sharing form.")
    is_goal_document = _is_goal_document(item)
    if (
        is_goal_document
        and "title" in fields
        and data.title != item.title
        and not allow_goal_document_metadata_sync
    ):
        raise MemoryPermissionError(
            "The title, owner, and path of a Goal document are controlled by its Goal "
            "and cannot be changed directly."
        )
    if "metadata" in fields and data.metadata is not None:
        goal_metadata_changed = any(
            data.metadata.get(key) != item.metadata_.get(key)
            for key in ("goal_id", "goal_document_kind", "document_path")
        )
        if is_goal_document and goal_metadata_changed and not allow_goal_document_metadata_sync:
            raise MemoryPermissionError(
                "The title, owner, and path of a Goal document are controlled by its Goal "
                "and cannot be changed directly."
            )
    if item.node_kind == "document":
        if data.memory_type not in (None, "working"):
            raise MemoryConflictError("A document must keep memory_type='working'.")
        if data.content_type not in (None, "text"):
            raise MemoryConflictError("A document must contain text.")
        if item.document_type == "dataset" and data.media_type not in (None, "application/json"):
            raise MemoryConflictError("A Dataset document must retain its application/json format.")
        if item.document_type == "html" and data.media_type is not None and not data.media_type.startswith("text/"):
            raise MemoryConflictError("A document must contain text.")
        if data.visibility == "public":
            raise MemoryConflictError("A document must be shared through explicit agent grants.")
        if data.visibility == "private" and (item.global_access > 0 or item.group_access > 0):
            raise MemoryConflictError("A globally shared document must keep shared visibility.")
        if data.read_only:
            raise MemoryConflictError("A working document must remain editable.")
    assert_safe_value(
        data.model_dump(
            exclude={"payload", "expected_revision", "expected_lock_version"},
            exclude_unset=True,
            mode="python",
        )
    )

    if item.content_profile_version == 1 and (
        data.content_type not in (None, "text") or data.media_type not in (None, "text/html")
    ):
        raise MemoryConflictError("Editorial content must retain its text/html profile.")
    if data.media_type is not None and data.media_type != item.media_type and data.payload is None:
        raise MemoryConflictError("A format change requires an explicit converted payload.")
    previous_values = {
        name: getattr(item, name)
        for name in (
            "title",
            "memory_type",
            "content_type",
            "media_type",
            "filename",
            "visibility",
            "read_only",
            "valid_from",
            "valid_until",
        )
    }
    previous_metadata = dict(item.metadata_)
    previous_provider_code = item.provider_code
    previous_resource_id = item.resource_id
    new_resource_id: str | None = None
    content_changed = False
    provider = get_storage(item.provider_code)
    if "payload" in fields and data.payload is not None:
        content = decode_payload(data.payload)
        if item.node_kind == "document" and item.document_type == "dataset":
            validate_dataset(content)
        future_content_type = data.content_type or item.content_type
        future_media_type = data.media_type or item.media_type
        if future_content_type == "text" and future_media_type in {
            "text/html",
            "text/markdown",
            "text/plain",
        }:
            content = convert_to_html(
                content.decode("utf-8"), future_media_type, profile=item.content_profile
            ).encode("utf-8")
            if item.node_kind == "document":
                apps = document_apps(content.decode("utf-8"))
                if apps and item.deletion_protected:
                    raise ValueError("Managed editorial documents cannot contain applications.")
            if item.media_type == "text/html" and data.media_type not in (None, "text/html"):
                raise MemoryConflictError(
                    "This content now requires explicit text/html writes. Refresh the client."
                )
            if item.node_kind == "document":
                from .document_attachment_service import attachments_from_item

                allowed = {
                    str(value.id)
                    for value in attachments_from_item(item, include_retained=True)
                    if value.media_type in {"image/png", "image/jpeg", "image/webp", "image/gif"}
                }
                for uri in image_references(content.decode("utf-8")):
                    reference = attachment_reference(uri)
                    if (
                        reference is None
                        or reference[0] != item.id
                        or str(reference[1]) not in allowed
                    ):
                        raise MemoryPermissionError(
                            "The image must belong to this document's attachments."
                        )
            if _is_goal_document(item) and item.metadata_.get("goal_document_kind") == "tracking":
                if (
                    len(content.decode("utf-8")) > 120_000
                    or len(visible_text(content.decode("utf-8"))) > 30_000
                ):
                    raise MemoryConflictError(
                        "Goal tracking exceeds its serialized or visible text limit."
                    )
            future_media_type = "text/html"
            data = data.model_copy(update={"media_type": "text/html"})
            fields.add("media_type")
            item.content_profile_version = 1
            if item.node_kind == "document":
                item.metadata_ = {
                    **item.metadata_,
                    "content_images": sorted(image_references(content.decode("utf-8"))),
                }
        if future_content_type == "text" or future_media_type.startswith("text/"):
            assert_safe_text(content.decode("utf-8", errors="replace"))
        digest = _content_hash(content)
        content_changed = item.content_hash != digest
        if content_changed:
            new_resource_id = await provider.create(content)
            item.resource_id = new_resource_id
            item.content_hash = digest
            item.size_bytes = len(content)
            item.search_text = _search_text(
                content,
                content_type=future_content_type,
                media_type=future_media_type,
            )

    scalar_fields = (
        "title",
        "memory_type",
        "content_type",
        "media_type",
        "filename",
        "visibility",
        "read_only",
        "valid_from",
        "valid_until",
    )
    for field_name in scalar_fields:
        if field_name in fields:
            setattr(item, field_name, getattr(data, field_name))
    keywords_changed = False
    if "keywords" in fields and data.keywords is not None:
        normalized_keywords = _keywords(data.keywords)
        keywords_changed = list(item.keywords) != normalized_keywords
        item.keywords = normalized_keywords
    if "metadata" in fields and data.metadata is not None:
        metadata = dict(data.metadata)
        if item.node_kind == "document" and preserve_document_attachments:
            for attachment_key in (
                "document_attachments",
                "retained_document_attachments",
                "content_images",
            ):
                if attachment_key in item.metadata_:
                    metadata[attachment_key] = item.metadata_[attachment_key]
                else:
                    metadata.pop(attachment_key, None)
        item.metadata_ = metadata
    _set_semantic_fingerprint(item)
    meaningful_change = bool(
        fields
        & {
            "payload",
            "title",
            "memory_type",
            "keywords",
            "metadata",
            "valid_from",
            "valid_until",
        }
    )
    if content_changed or keywords_changed:
        item.updated_at = datetime.now(timezone.utc)
    if meaningful_change:
        item.old_at = None
        item.old_reason = None
        await get_db().execute(
            update(MemoryFinding)
            .where(
                MemoryFinding.primary_item_id == item.id,
                MemoryFinding.kind == "aging",
                MemoryFinding.status == "pending",
            )
            .values(status="obsolete", resolved_at=datetime.now(timezone.utc))
        )
    changed = (
        content_changed
        or keywords_changed
        or previous_metadata != item.metadata_
        or any(getattr(item, name) != value for name, value in previous_values.items())
    )
    # A document revision describes its payload, not its metadata or ACLs.
    if content_changed or (item.node_kind != "document" and changed):
        item.revision += 1
    db = get_db()
    if content_changed or (item.node_kind != "document" and changed):
        db.add(
            _revision_for(
                item,
                author_agent_id=(
                    document_revision_author_agent_id
                    if item.node_kind == "document"
                    else (actor_agent_id if isinstance(actor_agent_id, int) else None)
                ),
                task_id=actor_task_id,
                document_content_version=(True if item.node_kind == "document" else None),
                document_append=document_append if item.node_kind == "document" else False,
            )
        )
    try:
        if item.node_kind == "document":
            from .document_structure import sync_document_structure
            await db.flush()
            await sync_document_structure(item)
        await db.commit()
    except StaleDataError as exc:
        await db.rollback()
        if new_resource_id is not None:
            await provider.delete(new_resource_id)
        raise MemoryConflictError(
            "The document changed while it was being edited; reload and retry."
        ) from exc
    except Exception:
        await db.rollback()
        if new_resource_id is not None:
            await provider.delete(new_resource_id)
        raise
    loaded = await _get_item_record(item.id)
    assert loaded is not None
    if content_changed and previous_resource_id != loaded.resource_id:
        await _delete_resource_if_unreferenced(
            previous_provider_code,
            previous_resource_id,
        )
    await _enqueue_semantic_projection(loaded)
    await _emit_memory_event("update", loaded)
    if notify_observers:
        await notify_memory_item(loaded.id, "update")
    return loaded


async def restore_document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    expected_revision: int,
    actor_agent_id: int | HumanActor,
) -> MemoryItem:
    """Restore only editorial content while keeping current metadata and ACLs."""

    item, entry, content = await _document_content_revision(
        item_id,
        revision,
        actor_agent_id=actor_agent_id,
    )
    await assert_item_access(item, actor_agent_id, write=True)
    if expected_revision != item.revision:
        raise MemoryConflictError(
            f"Memory revision conflict: expected {expected_revision}, "
            f"current revision is {item.revision}."
        )
    if entry.content_hash == item.content_hash:
        return item
    return await update_item(
        item_id,
        MemoryItemUpdate(
            expected_revision=expected_revision,
            payload=MemoryPayload(
                text=content.decode("utf-8") if item.document_type == "dataset" else convert_to_html(
                    archived_document_html(content.decode("utf-8"))
                    if entry.media_type == "text/html" and item.content_profile == "document"
                    else content.decode("utf-8"),
                    entry.media_type, profile=item.content_profile
                )
            ),
            media_type="application/json" if item.document_type == "dataset" else "text/html",
        ),
        actor_agent_id=actor_agent_id,
        document_revision_author_agent_id=None,
    )


async def _forget_item_record(
    item: MemoryItem,
    *,
    forget_kind: Literal["explicit", "retention"],
) -> MemoryForgetResult:
    """Erase one already-authorized memory, including every resource revision."""

    item_id = item.id
    original_content_hash = item.content_hash
    source_rows = list(
        (
            await get_db().execute(
                select(MemorySource.source_kind, MemorySource.source_ref).where(
                    MemorySource.item_id == item_id
                )
            )
        ).all()
    )
    resources = {
        (item.provider_code, item.resource_id),
        *((entry.provider_code, entry.resource_id) for entry in item.revisions),
    }
    if item.node_kind == "document":
        from .models import DocumentAttachment
        from .semantic_index import delete_item_embeddings

        attachments = list(await get_db().scalars(select(DocumentAttachment).where(
            DocumentAttachment.document_id == item.id,
        )))
        for attachment in attachments:
            attachment.active = False
            companion = await _get_item_record(attachment.memory_item_id)
            if companion is None:
                continue
            resources.add((companion.provider_code, companion.resource_id))
            resources.update((revision.provider_code, revision.resource_id) for revision in companion.revisions)
            await delete_item_embeddings(companion.id)
            for model in (MemoryRevision, MemorySource, MemoryItemGrant, MemoryUsage):
                await get_db().execute(delete(model).where(model.item_id == companion.id))
            await get_db().execute(delete(MemoryLink).where(or_(
                MemoryLink.source_item_id == companion.id, MemoryLink.target_item_id == companion.id,
            )))
            await get_db().execute(delete(MemoryAssociation).where(or_(
                MemoryAssociation.item_a_id == companion.id, MemoryAssociation.item_b_id == companion.id,
            )))
            set_committed_value(companion, "revisions", [])
            set_committed_value(companion, "grants", [])
            companion.search_text = ""
            companion.title = "Forgotten attachment"
            companion.keywords = []
            companion.metadata_ = {}
            companion.content_hash = _content_hash(b"")
            companion.semantic_fingerprint = ""
            companion.size_bytes = 0
            companion.resource_id = "forgotten"
            companion.soft_delete()
    raw_attachments_value = [
        *item.metadata_.get("document_attachments", []),
        *item.metadata_.get("retained_document_attachments", []),
    ]
    raw_attachments = cast(list[object], raw_attachments_value)
    resources.update(
        ("native", attachment_id)
        for raw in raw_attachments
        if isinstance(raw, dict)
        and isinstance((attachment_id := cast(dict[object, object], raw).get("id")), str)
    )
    item.search_text = ""
    if item.node_kind != "document":
        item.title = "Forgotten memory"
    item.keywords = []
    item.metadata_ = {}
    item.content_hash = _content_hash(b"")
    item.semantic_fingerprint = ""
    item.size_bytes = 0
    item.resource_id = "forgotten"
    # Private projections can become ordinary owner-bound tombstones and release
    # their durable source identity. Public ownerless projections must retain it:
    # an ownerless, non-source-managed item would violate the governed-memory
    # constraint, even after soft deletion.
    if item.owner_agent_id is not None:
        item.source_managed = False
        item.managed_source_kind = None
        item.managed_source_ref = None
    item.soft_delete()
    db = get_db()
    # Forget removes payload pointers, excerpts, ACLs, graph edges, and usage
    # traces; document tombstones retain their title for historical Chat previews.
    from .semantic_index import delete_item_embeddings

    await delete_item_embeddings(item_id)
    for model in (MemoryRevision, MemorySource, MemoryItemGrant, MemoryUsage):
        await db.execute(delete(model).where(model.item_id == item_id))
    # Bulk DELETE bypasses relationship collections. Forgetting and then physically
    # deleting the same item must not cascade a second DELETE from stale loaded rows.
    set_committed_value(item, "revisions", [])
    set_committed_value(item, "grants", [])
    await db.execute(
        delete(MemoryLink).where(
            or_(
                MemoryLink.source_item_id == item_id,
                MemoryLink.target_item_id == item_id,
            )
        )
    )
    await db.execute(
        delete(MemoryAssociation).where(
            or_(
                MemoryAssociation.item_a_id == item_id,
                MemoryAssociation.item_b_id == item_id,
            )
        )
    )
    forgotten_metadata = {
        "forget_kind": forget_kind,
        "forgotten_content_hash": original_content_hash,
    }
    await db.execute(
        update(MemoryAcquisition)
        .where(MemoryAcquisition.target_item_id == item_id)
        .values(
            title="Forgotten memory",
            content="[forgotten]",
            keywords=[],
            status="rejected",
            metadata_=forgotten_metadata,
        )
    )
    if forget_kind == "explicit":
        existing_sources = set(
            (
                await db.execute(
                    select(
                        MemoryAcquisition.source_kind,
                        MemoryAcquisition.source_ref,
                    ).where(MemoryAcquisition.target_item_id == item_id)
                )
            ).all()
        )
        for source_kind, source_ref in source_rows:
            if (source_kind, source_ref) in existing_sources:
                continue
            tombstone_key = hashlib.sha256(
                (
                    f"explicit_forget:{item_id}:{source_kind}:{source_ref}:{original_content_hash}"
                ).encode("utf-8")
            ).hexdigest()
            db.add(
                MemoryAcquisition(
                    agent_id=item.owner_agent_id,
                    action="skip",
                    target_item_id=item_id,
                    title="Forgotten memory",
                    content="[forgotten]",
                    keywords=[],
                    source_kind=source_kind,
                    source_ref=source_ref,
                    status="rejected",
                    idempotency_key=tombstone_key,
                    metadata_=forgotten_metadata,
                    resolved_at=datetime.now(timezone.utc),
                )
            )
    await db.commit()

    deleted = 0
    for provider_code, resource_id in sorted(resources):
        try:
            if await get_storage(provider_code).delete(resource_id):
                deleted += 1
        except ResourceStorageError as exc:
            logger.error(
                "Memory resource cleanup deferred: provider={} resource={} error={}",
                provider_code,
                resource_id,
                exc,
            )
            key = hashlib.sha256(
                f"resource_cleanup:{provider_code}:{resource_id}".encode()
            ).hexdigest()
            exists_job = await db.scalar(
                select(MemoryAutomationJob.id).where(MemoryAutomationJob.idempotency_key == key)
            )
            if exists_job is None:
                db.add(
                    MemoryAutomationJob(
                        kind="resource_cleanup",
                        idempotency_key=key,
                        payload={
                            "provider_code": provider_code,
                            "resource_id": resource_id,
                        },
                    )
                )
    await db.commit()
    await _emit_memory_event("delete", item)
    if item.node_kind == "document":
        await invalidate_memory_views()
    return MemoryForgetResult(memory_id=item_id, resources_deleted=deleted)


async def forget_item(
    item_id: UUID,
    *,
    actor_agent_id: int | HumanActor | None,
    administrative: bool = False,
) -> MemoryForgetResult:
    """Forget a user-managed memory after enforcing its durable protections."""

    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    _assert_not_deletion_protected(item)
    _assert_not_source_managed(item)
    owns_item = (
        item.owner_agent_id == actor_agent_id if isinstance(actor_agent_id, int)
        else isinstance(actor_agent_id, HumanActor) and item.owner_user_id == actor_agent_id.user_id
    )
    if (
        item.node_kind == "document"
        and not administrative
        and not owns_item
    ):
        raise MemoryPermissionError("Only the document owner can permanently forget it.")
    if not administrative and owns_item:
        await assert_item_access(item, actor_agent_id)
    else:
        await assert_item_access(item, actor_agent_id, write=True, administrative=administrative)
    return await _forget_item_record(item, forget_kind="explicit")


async def forget_merged_item(item_id: UUID) -> MemoryForgetResult:
    """Internal merge path after provenance and graph edges have been transferred."""

    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory to merge no longer exists.")
    _assert_not_deletion_protected(item)
    _assert_not_source_managed(item)
    return await _forget_item_record(item, forget_kind="retention")


async def forget_source_managed_item(
    *,
    source_kind: str,
    source_ref: str,
    item_id: UUID | None = None,
) -> MemoryForgetResult | None:
    """Internal source-owner path; never exposed through HTTP or MCP."""

    item: MemoryItem | None = None
    if item_id is not None:
        pointed = await _get_item_record(item_id)
        if pointed is not None:
            if not pointed.source_managed:
                raise MemoryConflictError("The source points to a user-managed memory item.")
            if (
                pointed.managed_source_kind != source_kind
                or pointed.managed_source_ref != source_ref
            ):
                raise MemoryConflictError(
                    "The source points to a different managed memory projection."
                )
            item = pointed
    if item is None:
        item = await get_db().scalar(
            select(MemoryItem)
            .options(*_item_options())
            .where(
                MemoryItem.source_managed.is_(True),
                MemoryItem.managed_source_kind == source_kind,
                MemoryItem.managed_source_ref == source_ref,
            )
        )
    if item is None:
        return None
    return await _forget_item_record(item, forget_kind="retention")


async def purge_source_managed_item(
    *,
    source_kind: str,
    source_ref: str,
    item_id: UUID | None = None,
) -> MemoryForgetResult | None:
    """Physically remove a derived projection after its canonical source is deleted.

    Ordinary governed memories retain a historized tombstone when forgotten. A derived
    projection has no independent lifetime, so its canonical source may purge that tombstone
    once payloads and audit references have been sanitized by the normal forget path.
    """

    result = await forget_source_managed_item(
        source_kind=source_kind,
        source_ref=source_ref,
        item_id=item_id,
    )
    if result is None:
        return None
    item = await get_db().get(
        MemoryItem,
        result.memory_id,
        execution_options={"include_historized": True},
    )
    if item is not None:
        await get_db().delete(item)
        await get_db().commit()
    return result


async def forget_stale_item(
    item_id: UUID,
    *,
    expected_activity_at: datetime,
    forget_after_days: int,
) -> MemoryForgetResult | None:
    """Forget one still-stale user memory after locking and rechecking it."""

    item = await get_db().scalar(
        select(MemoryItem)
        .options(*_item_options())
        .where(MemoryItem.id == item_id)
        .with_for_update()
    )
    if item is None or item.source_managed or item.node_kind == "document":
        return None
    activity_at = item.activity_at
    if activity_at != expected_activity_at:
        return None
    now = datetime.now(timezone.utc)
    expired = item.valid_until is not None and item.valid_until <= now
    inactive = forget_after_days > 0 and activity_at <= now - timedelta(days=forget_after_days)
    if not expired and not inactive:
        return None
    return await _forget_item_record(item, forget_kind="retention")


async def preview_retention(days: int) -> MemoryRetentionPreview:
    """Estimate an inactivity policy without mutating memories or access dates."""

    if days < 0 or days > 36_500:
        raise ValueError("Retention days must be between 0 and 36500.")
    now = datetime.now(timezone.utc)
    ordinary = and_(
        MemoryItem.source_managed.is_(False),
        MemoryItem.node_kind == "memory",
    )
    expired = and_(
        MemoryItem.valid_until.is_not(None),
        MemoryItem.valid_until <= now,
    )
    inactive: ColumnElement[bool]
    if days > 0:
        inactive = MemoryItem.activity_at <= now - timedelta(days=days)
        candidate = or_(expired, inactive)
    else:
        inactive = MemoryItem.id.is_(None)
        candidate = expired

    db = get_db()
    expired_count = int(
        await db.scalar(select(func.count(MemoryItem.id)).where(ordinary, expired)) or 0
    )
    inactive_count = (
        int(
            await db.scalar(
                select(func.count(MemoryItem.id)).where(
                    ordinary,
                    inactive,
                    or_(
                        MemoryItem.valid_until.is_(None),
                        MemoryItem.valid_until > now,
                    ),
                )
            )
            or 0
        )
        if days > 0
        else 0
    )
    rows = list(
        (
            await db.execute(
                select(
                    MemoryItem.memory_type,
                    func.count(MemoryItem.id),
                )
                .where(ordinary, candidate)
                .group_by(MemoryItem.memory_type)
            )
        ).all()
    )
    oldest_activity_at = await db.scalar(
        select(func.min(MemoryItem.activity_at)).where(ordinary, candidate)
    )
    allowed_types = {
        "core",
        "working",
        "episodic",
        "semantic",
        "procedural",
        "social",
    }
    by_memory_type: dict[MemoryType, int] = {}
    for memory_type, count in rows:
        key = str(memory_type)
        if key in allowed_types:
            by_memory_type[cast(MemoryType, key)] = int(count)
    return MemoryRetentionPreview(
        days=days,
        inactivity_enabled=days > 0,
        inactive_count=inactive_count,
        expired_count=expired_count,
        total_candidates=sum(by_memory_type.values()),
        oldest_activity_at=oldest_activity_at,
        by_memory_type=by_memory_type,
    )


async def set_item_grant(
    item_id: UUID,
    agent_id: int,
    data: MemoryGrantUpdate,
    *,
    actor_agent_id: int | None = None,
    actor_task_id: UUID | None = None,
) -> MemoryItem:
    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    _assert_not_source_managed(item)
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise MemoryConflictError(
            "The document changed while sharing was being edited; reload and retry."
        )
    if agent_id == item.owner_agent_id:
        raise MemoryConflictError("The owner already has direct access to this memory.")
    db = get_db()
    grant = await db.scalar(
        select(MemoryItemGrant).where(
            MemoryItemGrant.item_id == item_id,
            MemoryItemGrant.agent_id == agent_id,
        )
    )
    if grant is None:
        db.add(MemoryItemGrant(item_id=item_id, agent_id=agent_id, can_write=data.can_write))
    else:
        grant.can_write = data.can_write
    if item.visibility != "public":
        item.visibility = "shared"
    if item.node_kind == "document":
        # Grant rows are versioned independently; explicitly dirty the parent so
        # two concurrent sharing edits still contend on the document lock.
        item.lock_version += 1
    if item.node_kind != "document":
        item.revision += 1
        db.add(
            _revision_for(
                item,
                author_agent_id=actor_agent_id,
                task_id=actor_task_id,
            )
        )
    await _commit_with_conflict(
        "The document changed while sharing was being edited; reload and retry."
    )
    loaded = await _get_item_record(item_id)
    assert loaded is not None
    await _emit_memory_event("update", loaded)
    await notify_memory_item(loaded.id, "sharing")
    return loaded


async def has_document_grants(item_id: UUID) -> bool:
    return bool(await get_db().scalar(select(or_(
        exists(select(MemoryItemGrant.id).where(MemoryItemGrant.item_id == item_id)),
        exists(select(DocumentUserGrant.id).where(DocumentUserGrant.item_id == item_id)),
        exists(select(DocumentTeamGrant.id).where(DocumentTeamGrant.item_id == item_id)),
    ))))


async def set_document_global_access(
    item_id: UUID,
    data: DocumentGlobalAccessUpdate,
    *,
    actor_agent_id: int | None = None,
    actor_task_id: UUID | None = None,
) -> MemoryItem:
    """Set the durable public permission for authenticated humans and Agents."""

    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    _assert_not_source_managed(item)
    if item.node_kind != "document":
        raise MemoryConflictError("Global access is only available for documents.")
    if data.expected_revision != item.revision:
        raise MemoryConflictError(
            f"Memory revision conflict: expected {data.expected_revision}, "
            f"current revision is {item.revision}."
        )
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise MemoryConflictError(
            "The document changed while sharing was being edited; reload and retry."
        )
    if item.global_access == data.global_access and item.group_access == 0:
        return item

    has_grants = await has_document_grants(item_id)
    item.global_access = data.global_access
    item.group_access = 0
    item.visibility = "shared" if data.global_access > 0 or has_grants else "private"
    await _commit_with_conflict(
        "The document changed while sharing was being edited; reload and retry."
    )
    loaded = await _get_item_record(item_id)
    assert loaded is not None
    await _emit_memory_event("update", loaded)
    await invalidate_memory_views()
    await notify_memory_item(loaded.id, "sharing")
    return loaded


async def get_item_owner_agent_id(item_id: UUID) -> int | None:
    """Resolve an active Memory owner's Agent id for human API scoping."""

    item = await _get_item_record(item_id)
    return item.owner_agent_id if item is not None else None


async def remove_item_grant(
    item_id: UUID,
    agent_id: int,
    *,
    actor_agent_id: int | None = None,
    actor_task_id: UUID | None = None,
    expected_lock_version: int | None = None,
) -> MemoryItem:
    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    _assert_not_source_managed(item)
    if expected_lock_version is not None and expected_lock_version != item.lock_version:
        raise MemoryConflictError(
            "The document changed while sharing was being edited; reload and retry."
        )
    db = get_db()
    grant = await db.scalar(
        select(MemoryItemGrant).where(
            MemoryItemGrant.item_id == item_id,
            MemoryItemGrant.agent_id == agent_id,
        )
    )
    if grant is not None:
        await db.delete(grant)
        await db.flush()
        remaining = await has_document_grants(item_id)
        if not remaining and item.global_access == 0 and item.group_access == 0 and item.visibility == "shared":
            item.visibility = "private"
        if item.node_kind != "document":
            item.revision += 1
            db.add(
                _revision_for(
                    item,
                    author_agent_id=actor_agent_id,
                    task_id=actor_task_id,
                )
            )
        else:
            # Deleting a grant may leave visibility unchanged, so make the
            # document row participate in optimistic concurrency explicitly.
            item.lock_version += 1
        await _commit_with_conflict(
            "The document changed while sharing was being edited; reload and retry."
        )
    loaded = await _get_item_record(item_id)
    assert loaded is not None
    if grant is not None:
        await _emit_memory_event("update", loaded)
        await invalidate_memory_views()
        await notify_memory_item(loaded.id, "sharing")
    return loaded


async def record_llm_retrieval(
    *,
    agent_id: int,
    item_scores: Sequence[tuple[UUID, float]],
    query: str,
    task_id: UUID | None,
    access_kind: Literal[
        "context",
        "search",
        "experience_planning",
        "experience_execution",
    ] = "search",
) -> None:
    if not item_scores:
        return
    db = get_db()
    now = datetime.now(timezone.utc)
    ids = [item_id for item_id, _score in item_scores]
    await db.execute(
        update(MemoryItem)
        .where(MemoryItem.id.in_(ids))
        .values(
            last_accessed_at=now,
            access_count=MemoryItem.access_count + 1,
            updated_at=MemoryItem.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    for rank, (item_id, score) in enumerate(item_scores, start=1):
        usage_values = {
            "item_id": item_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "access_kind": access_kind,
            "query": query,
            "rank": rank,
            "score": score,
        }
        if task_id is None:
            db.add(MemoryUsage(**usage_values))
        else:
            await db.execute(
                pg_insert(MemoryUsage)
                .values(**usage_values)
                .on_conflict_do_nothing(constraint="uq_memory_usage_task_item")
            )
    await db.flush()


async def search_items(
    request: MemorySearchRequest, *, record_llm_access: bool = False
) -> MemorySearchPage:
    """Apply ACL/validity first, then deterministic full-text ranking."""

    db = get_db()
    now = datetime.now(timezone.utc)
    query = (
        select(MemoryItem)
        .options(*_item_options())
        .where(
            readable_item_clause(request.agent_id),
            or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
            or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
        )
    )
    if request.memory_types:
        query = query.where(MemoryItem.memory_type.in_(request.memory_types))
    if request.topic_item_id is not None and request.contact_item_id is not None:
        query = query.where(
            exists(
                select(MemoryTopicContactItem.id)
                .join(
                    MemoryTopicContactScope,
                    MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
                )
                .where(
                    MemoryTopicContactItem.item_id == MemoryItem.id,
                    MemoryTopicContactScope.owner_agent_id == request.agent_id,
                    MemoryTopicContactScope.topic_item_id == request.topic_item_id,
                    MemoryTopicContactScope.contact_item_id == request.contact_item_id,
                )
            )
        )
    elif request.topic_item_id is not None:
        query = query.where(
            exists(
                select(MemoryLink.id).where(
                    MemoryLink.source_item_id == request.topic_item_id,
                    MemoryLink.target_item_id == MemoryItem.id,
                    MemoryLink.relation_type == "topic_contains",
                    MemoryLink.suggested.is_(False),
                )
            )
        )
    elif request.contact_item_id is not None:
        directly_scoped_to_contact = exists(
            select(MemoryContactItem.id).where(
                MemoryContactItem.item_id == MemoryItem.id,
                MemoryContactItem.owner_agent_id == request.agent_id,
                MemoryContactItem.contact_item_id == request.contact_item_id,
            )
        )
        legacy_scoped_to_contact = exists(
            select(MemoryTopicContactItem.id)
            .join(
                MemoryTopicContactScope,
                MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
            )
            .where(
                MemoryTopicContactItem.item_id == MemoryItem.id,
                MemoryTopicContactScope.owner_agent_id == request.agent_id,
                MemoryTopicContactScope.contact_item_id == request.contact_item_id,
            )
        )
        if request.strict_contact_scope:
            query = query.where(or_(directly_scoped_to_contact, legacy_scoped_to_contact))
        else:
            directly_conversation_scoped = exists(
                select(MemoryContactItem.id).where(MemoryContactItem.item_id == MemoryItem.id)
            )
            legacy_conversation_scoped = exists(
                select(MemoryTopicContactItem.id).where(
                    MemoryTopicContactItem.item_id == MemoryItem.id
                )
            )
            query = query.where(
                or_(
                    directly_scoped_to_contact,
                    legacy_scoped_to_contact,
                    ~(directly_conversation_scoped | legacy_conversation_scoped),
                )
            )
    exact_scope_filters = _exact_scope_filters(
        agent_id=request.agent_id,
        topic_item_id=request.filter_topic_item_id,
        contact_item_id=request.filter_contact_item_id,
    )
    if exact_scope_filters:
        query = query.where(*exact_scope_filters)
    if request.exclude_topic_projections:
        query = query.where(
            or_(
                MemoryItem.metadata_["memory_role"].as_string().is_(None),
                MemoryItem.metadata_["memory_role"].as_string() != "topic",
            ),
            or_(
                MemoryItem.managed_source_kind.is_(None),
                MemoryItem.managed_source_kind != "messenger_contact",
            ),
        )
    if request.exclude_agent_projections:
        query = query.where(
            or_(
                MemoryItem.managed_source_kind.is_(None),
                MemoryItem.managed_source_kind != "agent",
            )
        )
    if request.exclude_source_managed:
        query = query.where(MemoryItem.source_managed.is_(False))
    if request.node_kinds:
        query = query.where(MemoryItem.node_kind.in_(request.node_kinds))
    keyword = request.keyword.strip() if request.keyword is not None else ""
    if keyword:
        query = query.where(MemoryItem.keywords.contains([keyword]))
    if request.memory_role == "experience":
        query = query.where(MemoryItem.metadata_["memory_role"].as_string() == "experience")
    elif request.memory_role == "ordinary":
        query = query.where(
            or_(
                MemoryItem.metadata_["memory_role"].as_string().is_(None),
                MemoryItem.metadata_["memory_role"].as_string() != "experience",
            )
        )

    normalized = request.query.strip()
    identity = query_identity(normalized)
    if identity is not None:
        query = query.where(MemoryItem.id == identity)
        rank_expression = case((MemoryItem.id == identity, 1.0), else_=0.0)
    elif normalized:
        prefix = relevance.prefix_query(request.recall_query) if request.recall_query is not None else ""
        ts_query = func.to_tsquery("simple", prefix) if prefix else func.websearch_to_tsquery("simple", normalized)
        rank_expression = func.ts_rank_cd(MemoryItem.search_vector, ts_query)
        literal = request.recall_query if request.recall_query is not None else normalized
        fallback = or_(
            MemoryItem.title.icontains(literal, autoescape=True),
            MemoryItem.search_text.icontains(literal, autoescape=True),
        )
        if request.recall_query is not None:
            rank_expression = case((func.lower(MemoryItem.title) == literal.lower(), 2.0), else_=rank_expression)
        query = query.where(or_(MemoryItem.search_vector.op("@@")(ts_query), fallback))
    else:
        rank_expression = case((MemoryItem.memory_type == "core", 1.0), else_=0.1)
    count_query = select(func.count(MemoryItem.id))
    if query.whereclause is not None:
        count_query = count_query.where(query.whereclause)
    total = int(await db.scalar(count_query) or 0)

    if request.sort_by is not None:
        if request.sort_by == "owner":
            query = query.outerjoin(Agent, Agent.id == MemoryItem.owner_agent_id)
        sort_expression = _memory_sort_expression(request.sort_by)
        sort_order = sort_expression.desc() if request.sort_desc else sort_expression.asc()
        if request.sort_by == "last_accessed_at":
            sort_order = sort_order.nullslast()
        query = query.add_columns(rank_expression.label("rank")).order_by(
            sort_order,
            MemoryItem.created_at.desc(),
            MemoryItem.id,
        )
    elif normalized:
        query = query.add_columns(rank_expression.label("rank"))
        query = query.order_by(
            rank_expression.desc(),
            case((MemoryItem.memory_type == "core", 0), else_=1),
            func.coalesce(
                MemoryItem.updated_at,
                MemoryItem.created_at,
            ).desc(),
            MemoryItem.created_at.desc(),
            MemoryItem.id,
        )
    else:
        query = query.add_columns(rank_expression.label("rank")).order_by(
            case((MemoryItem.memory_type == "core", 0), else_=1),
            MemoryItem.last_accessed_at.desc().nullslast(),
            MemoryItem.created_at.desc(),
            MemoryItem.id,
        )

    result = await db.execute(query.execution_options(populate_existing=True).offset(request.offset).limit(request.limit + 1))
    rows = list(result.unique().all())
    has_more = len(rows) > request.limit
    rows = rows[: request.limit]
    ranked: list[tuple[MemoryItem, float]] = [
        (cast(MemoryItem, row[0]), float(row[1] or 0.0)) for row in rows
    ]

    sources = await _source_refs_by_item([item.id for item, _score in ranked])
    hits: list[MemorySearchHit] = []
    for item, score in ranked:
        access = await effective_access(item, request.agent_id)
        if not access.can_read:
            continue
        # Search text and metadata come from the same database revision. Reading
        # the mutable storage resource here could mix two concurrent revisions.
        excerpt = lexical_excerpt(item.search_text, request.recall_query or normalized)
        hits.append(
            MemorySearchHit(
                item=item_to_public(item, access),
                excerpt=excerpt,
                score=score,
                source_refs=sources.get(item.id, []),
            )
        )
    hits = await admit_search_hits(request.agent_id, hits,
                                  scope_filters=[query.whereclause] if query.whereclause is not None else [])
    if record_llm_access:
        await record_llm_retrieval(
            agent_id=request.agent_id,
            item_scores=[(hit.item.id, hit.score) for hit in hits],
            query=request.query,
            task_id=request.task_id,
        )
    return MemorySearchPage(
        query=normalized,
        hits=hits,
        total=total,
        has_more=has_more,
    )


async def projected_topic_item_id(topic_id: UUID | None) -> UUID | None:
    """Resolve a canonical Topic UUID to its current public memory projection."""

    if topic_id is None:
        return None
    return await get_db().scalar(
        select(MemoryItem.id).where(
            MemoryItem.topic_id == topic_id,
            MemoryItem.source_managed.is_(True),
            MemoryItem.managed_source_kind == "topic",
            MemoryItem.visibility == "public",
            MemoryItem.owner_agent_id.is_(None),
        )
    )


async def managed_document_agent_ids(
    document_id: UUID,
    *,
    managed_agent_ids: Collection[int] | None,
) -> tuple[MemoryItem, tuple[int, ...], tuple[int, ...]]:
    """Load one document and resolve its effective managed-Agent access."""

    item = await _get_item_record(document_id)
    if item is None or item.node_kind != "document":
        raise MemoryNotFoundError("Document not found.")
    readable_agent_ids, writable_agent_ids = await managed_item_agent_ids(
        item,
        managed_agent_ids,
    )
    if not readable_agent_ids:
        raise MemoryNotFoundError("Document not found.")
    return item, readable_agent_ids, writable_agent_ids


async def transfer_document_owner(
    document_id: UUID,
    data: DocumentOwnerUpdate,
    *,
    actor_agent_id: int | HumanActor,
) -> MemoryItem:
    """Transfer a document while preserving the current editor's write access."""

    item = await _get_item_record(document_id)
    if item is None or item.node_kind != "document":
        raise MemoryNotFoundError("Document not found.")
    _assert_not_source_managed(item)
    await assert_item_access(item, actor_agent_id, write=True)
    if data.expected_revision != item.revision:
        raise MemoryConflictError(
            f"Memory revision conflict: expected {data.expected_revision}, "
            f"current revision is {item.revision}."
        )

    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise MemoryConflictError(
            "The document changed while ownership was being edited; reload and retry."
        )

    unchanged = (
        data.kind == "agent" and item.owner_agent_id == data.id and item.owner_user_id is None
    ) or (data.kind == "user" and item.owner_user_id == data.id and item.owner_agent_id is None)
    if unchanged:
        return item
    if _is_goal_document(item):
        raise MemoryPermissionError(
            "The title, owner, and path of a Goal document are controlled by its Goal "
            "and cannot be changed directly."
        )

    if data.kind == "agent":
        if await get_agent_record(data.id) is None:
            raise ValueError("Agent owner not found.")
    else:
        owner_user = await get_user_record(data.id)
        if owner_user is None or not owner_user.is_active:
            raise ValueError("User owner not found.")

    db = get_db()
    if data.kind == "agent":
        item.owner_agent_id = data.id
        item.owner_user_id = None
        await db.execute(
            delete(MemoryItemGrant).where(
                MemoryItemGrant.item_id == document_id,
                MemoryItemGrant.agent_id == data.id,
            )
        )
    else:
        item.owner_agent_id = None
        item.owner_user_id = data.id

    if isinstance(actor_agent_id, HumanActor):
        if data.kind != "user" or data.id != actor_agent_id.user_id:
            human_grant = await db.scalar(select(DocumentUserGrant).where(DocumentUserGrant.item_id == document_id, DocumentUserGrant.user_id == actor_agent_id.user_id))
            if human_grant is None:
                db.add(DocumentUserGrant(item_id=document_id, user_id=actor_agent_id.user_id, can_write=True))
            else:
                human_grant.can_write = True
    elif data.kind != "agent" or data.id != actor_agent_id:
        actor_grant = await db.scalar(
            select(MemoryItemGrant).where(
                MemoryItemGrant.item_id == document_id,
                MemoryItemGrant.agent_id == actor_agent_id,
            )
        )
        if actor_grant is None:
            db.add(
                MemoryItemGrant(
                    item_id=document_id,
                    agent_id=actor_agent_id,
                    can_write=True,
                )
            )
        else:
            actor_grant.can_write = True

    await db.flush()
    has_grants = await has_document_grants(document_id)
    item.visibility = "shared" if has_grants or item.global_access > 0 or item.group_access > 0 else "private"
    await _commit_with_conflict(
        "The document changed while ownership was being edited; reload and retry."
    )
    loaded = await _get_item_record(document_id)
    assert loaded is not None
    await _emit_memory_event("update", loaded)
    await notify_memory_item(loaded.id, "update")
    return loaded


async def list_document_folders(agent_id: int) -> list[str]:
    """List distinct logical folders from documents readable by one agent."""

    now = datetime.now(timezone.utc)
    result = await get_db().scalars(
        select(MemoryItem).where(
            readable_item_clause(agent_id),
            MemoryItem.node_kind == "document",
            or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
            or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
        )
    )
    folders = {
        value.strip().strip("/")
        for item in result.all()
        if isinstance((value := item.metadata_.get("document_path")), str)
        and value.strip().strip("/")
    }
    return sorted(folders, key=str.casefold)


async def list_document_folder_options(agent_id: int) -> list[DocumentFolderOption]:
    """Describe readable folders, including ancestors, from their documents' actual roles and grants."""

    now = datetime.now(timezone.utc)
    items = await get_db().scalars(
        select(MemoryItem)
        .options(selectinload(MemoryItem.grants), raiseload(MemoryItem.revisions))
        .where(
            readable_item_clause(agent_id),
            MemoryItem.node_kind == "document",
            or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
            or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
        )
    )
    folders: dict[str, DocumentFolderOption] = {}
    for item in items:
        raw_path = item.metadata_.get("document_path")
        if not isinstance(raw_path, str):
            continue
        parts = [part.strip() for part in raw_path.replace("\\", "/").split("/") if part.strip()]
        if any(part in {".", ".."} for part in parts):
            continue
        readers = {grant.agent_id for grant in item.grants}
        if item.owner_agent_id is not None:
            readers.add(item.owner_agent_id)
        shared = item.visibility == "public" or item.global_access >= 1 or len(readers) > 1
        for depth in range(1, len(parts) + 1):
            path = "/".join(parts[:depth])
            folder = folders.setdefault(path, DocumentFolderOption(path=path, kind="custom", shared=False))
            if _is_goal_document(item):
                folder.kind = "goal"
            folder.shared = folder.shared or shared
    return sorted(folders.values(), key=lambda folder: folder.path.casefold())


async def list_filter_options(agent_id: int) -> MemoryFilterOptions:
    """List the Topic and interlocutor projections usable as exact filters."""

    db = get_db()
    topic_items = list(
        (
            await db.scalars(
                select(MemoryItem)
                .where(
                    readable_item_clause(agent_id),
                    MemoryItem.source_managed.is_(True),
                    MemoryItem.managed_source_kind == "topic",
                    _topic_related_to_agent_clause(agent_id),
                )
                .order_by(func.lower(MemoryItem.title), MemoryItem.id)
                .limit(500)
            )
        ).all()
    )
    contact_items = list(
        (
            await db.scalars(
                select(MemoryItem)
                .where(
                    readable_item_clause(agent_id),
                    MemoryItem.owner_agent_id == agent_id,
                    MemoryItem.source_managed.is_(True),
                    MemoryItem.managed_source_kind == "messenger_contact",
                )
                .order_by(func.lower(MemoryItem.title), MemoryItem.id)
                .limit(500)
            )
        ).all()
    )
    return MemoryFilterOptions(
        topics=[MemoryFilterOption(id=item.id, label=item.title) for item in topic_items],
        contacts=[MemoryFilterOption(id=item.id, label=item.title) for item in contact_items],
    )


async def list_graph_roots(request: MemoryGraphRootsRequest) -> MemoryGraphPage:
    """Return one keyset page of recent graph roots and bounded visible edges."""

    db = get_db()
    now = datetime.now(timezone.utc)
    filters = _graph_item_filters(request, now=now)
    query = select(MemoryItem).where(*filters)
    if request.cursor is not None:
        query = query.where(
            or_(
                MemoryItem.activity_at < request.cursor.activity_at,
                and_(
                    MemoryItem.activity_at == request.cursor.activity_at,
                    MemoryItem.id > request.cursor.id,
                ),
            )
        )
    result = await db.scalars(
        query.order_by(MemoryItem.activity_at.desc(), MemoryItem.id).limit(request.limit + 1)
    )
    roots = list(result.all())
    has_more = len(roots) > request.limit
    roots = roots[: request.limit]
    root_ids = [item.id for item in roots]

    known_ids: list[UUID] = []
    if request.known_item_ids:
        known_result = await db.scalars(
            select(MemoryItem.id).where(
                MemoryItem.id.in_(request.known_item_ids),
                *filters,
            )
        )
        known_ids = list(known_result.all())

    visible_ids = list(dict.fromkeys([*root_ids, *known_ids]))
    links: list[MemoryLink] = []
    edges_truncated = False
    if root_ids and visible_ids:
        link_result = await db.scalars(
            select(MemoryLink)
            .where(
                or_(
                    and_(
                        MemoryLink.source_item_id.in_(root_ids),
                        MemoryLink.target_item_id.in_(visible_ids),
                    ),
                    and_(
                        MemoryLink.target_item_id.in_(root_ids),
                        MemoryLink.source_item_id.in_(visible_ids),
                    ),
                )
            )
            .order_by(MemoryLink.created_at.desc(), MemoryLink.id)
            .limit(request.edge_limit + 1)
        )
        links = list(link_result.all())
        edges_truncated = len(links) > request.edge_limit
        links = links[: request.edge_limit]

    relation_counts = await _graph_relation_counts(
        root_ids,
        request,
        now=now,
    )
    context_rows = list(
        (
            await db.execute(
                select(MemoryContextEdge, MemoryContextNode)
                .join(
                    MemoryContextNode,
                    MemoryContextNode.id == MemoryContextEdge.context_node_id,
                )
                .where(
                    MemoryContextEdge.item_id.in_(root_ids),
                    MemoryContextNode.owner_agent_id == request.agent_id,
                )
                .order_by(
                    MemoryContextNode.activity_at.desc(),
                    MemoryContextEdge.id,
                )
                .limit(request.edge_limit + 1)
            )
        ).all()
    )
    if len(context_rows) > request.edge_limit:
        edges_truncated = True
        context_rows = context_rows[: request.edge_limit]
    context_nodes: dict[UUID, MemoryContextNode] = {}
    context_edges: list[MemoryContextEdge] = []
    for context_edge, context_node in context_rows:
        typed_edge = cast(MemoryContextEdge, context_edge)
        typed_node = cast(MemoryContextNode, context_node)
        context_edges.append(typed_edge)
        context_nodes.setdefault(typed_node.id, typed_node)
    context_relation_counts: dict[UUID, int] = {}
    if context_nodes:
        context_count_rows = await db.execute(
            select(
                MemoryContextEdge.context_node_id,
                func.count(MemoryContextEdge.id),
            )
            .where(MemoryContextEdge.context_node_id.in_(list(context_nodes)))
            .group_by(MemoryContextEdge.context_node_id)
        )
        context_relation_counts = {cast(UUID, row[0]): int(row[1]) for row in context_count_rows}
    next_cursor = None
    if has_more and roots:
        last = roots[-1]
        next_cursor = MemoryGraphCursor(
            activity_at=last.activity_at,
            id=last.id,
        )
    return MemoryGraphPage(
        nodes=[
            *[
                _graph_node(
                    item,
                    relation_count=relation_counts.get(item.id, 0),
                )
                for item in roots
            ],
            *[
                _graph_context_node(
                    node,
                    relation_count=context_relation_counts.get(node.id, 0),
                )
                for node in context_nodes.values()
            ],
        ],
        edges=[
            *[_graph_edge(link) for link in links],
            *[_graph_context_edge(edge) for edge in context_edges],
        ],
        next_cursor=next_cursor,
        has_more=has_more,
        edges_truncated=edges_truncated,
    )


async def expand_graph_node(request: MemoryGraphExpandRequest) -> MemoryGraphPage:
    """Return one bounded relation page around a visible graph node."""

    db = get_db()
    now = datetime.now(timezone.utc)
    filters = _graph_item_filters(request, now=now)
    focus_id = await db.scalar(
        select(MemoryItem.id).where(
            MemoryItem.id == request.item_id,
            *filters,
        )
    )
    if focus_id is None:
        context_node = await db.scalar(
            select(MemoryContextNode).where(
                MemoryContextNode.id == request.item_id,
                MemoryContextNode.owner_agent_id == request.agent_id,
            )
        )
        if context_node is None:
            raise MemoryNotFoundError("Memory graph node not found.")
        context_query = (
            select(MemoryContextEdge, MemoryItem)
            .join(
                MemoryItem,
                MemoryItem.id == MemoryContextEdge.item_id,
            )
            .where(
                MemoryContextEdge.context_node_id == context_node.id,
                *filters,
            )
        )
        if request.known_item_ids:
            context_query = context_query.where(
                MemoryContextEdge.item_id.not_in(request.known_item_ids)
            )
        if request.cursor is not None:
            context_query = context_query.where(
                or_(
                    MemoryItem.activity_at < request.cursor.activity_at,
                    and_(
                        MemoryItem.activity_at == request.cursor.activity_at,
                        MemoryContextEdge.id > request.cursor.id,
                    ),
                )
            )
        context_result = await db.execute(
            context_query.order_by(
                MemoryItem.activity_at.desc(),
                MemoryContextEdge.id,
            ).limit(request.limit + 1)
        )
        context_rows = list(context_result.all())
        has_more = len(context_rows) > request.limit
        context_rows = context_rows[: request.limit]
        context_neighbors = {
            cast(MemoryItem, row[1]).id: cast(MemoryItem, row[1]) for row in context_rows
        }
        context_counts = await _graph_relation_counts(
            list(context_neighbors),
            request,
            now=now,
        )
        next_cursor = None
        if has_more and context_rows:
            last_edge = cast(MemoryContextEdge, context_rows[-1][0])
            last_item = cast(MemoryItem, context_rows[-1][1])
            next_cursor = MemoryGraphCursor(
                activity_at=last_item.activity_at,
                id=last_edge.id,
            )
        return MemoryGraphPage(
            nodes=[
                _graph_node(
                    item,
                    relation_count=context_counts.get(item.id, 0),
                )
                for item in context_neighbors.values()
            ],
            edges=[_graph_context_edge(cast(MemoryContextEdge, row[0])) for row in context_rows],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    neighbor_id = case(
        (
            MemoryLink.source_item_id == request.item_id,
            MemoryLink.target_item_id,
        ),
        else_=MemoryLink.source_item_id,
    )
    query = (
        select(MemoryLink, MemoryItem)
        .join(MemoryItem, MemoryItem.id == neighbor_id)
        .where(
            or_(
                MemoryLink.source_item_id == request.item_id,
                MemoryLink.target_item_id == request.item_id,
            ),
            *filters,
        )
    )
    if request.known_item_ids:
        query = query.where(neighbor_id.not_in(request.known_item_ids))
    if request.cursor is not None:
        query = query.where(
            or_(
                MemoryItem.activity_at < request.cursor.activity_at,
                and_(
                    MemoryItem.activity_at == request.cursor.activity_at,
                    MemoryLink.id > request.cursor.id,
                ),
            )
        )
    result = await db.execute(
        query.order_by(MemoryItem.activity_at.desc(), MemoryLink.id).limit(request.limit + 1)
    )
    rows = list(result.all())
    has_more = len(rows) > request.limit
    rows = rows[: request.limit]

    neighbors: dict[UUID, MemoryItem] = {}
    links: list[MemoryLink] = []
    for row in rows:
        link = cast(MemoryLink, row[0])
        neighbor = cast(MemoryItem, row[1])
        links.append(link)
        neighbors.setdefault(neighbor.id, neighbor)
    relation_counts = await _graph_relation_counts(
        list(neighbors),
        request,
        now=now,
    )
    context_rows = list(
        (
            await db.execute(
                select(MemoryContextEdge, MemoryContextNode)
                .join(
                    MemoryContextNode,
                    MemoryContextNode.id == MemoryContextEdge.context_node_id,
                )
                .where(
                    MemoryContextEdge.item_id == request.item_id,
                    MemoryContextNode.owner_agent_id == request.agent_id,
                )
            )
        ).all()
    )
    known_ids = set(request.known_item_ids)
    context_rows = [
        row for row in context_rows if cast(MemoryContextNode, row[1]).id not in known_ids
    ]

    next_cursor = None
    if has_more and rows:
        last_link = cast(MemoryLink, rows[-1][0])
        last_neighbor = cast(MemoryItem, rows[-1][1])
        next_cursor = MemoryGraphCursor(
            activity_at=last_neighbor.activity_at,
            id=last_link.id,
        )
    return MemoryGraphPage(
        nodes=[
            *[
                _graph_node(
                    item,
                    relation_count=relation_counts.get(item.id, 0),
                )
                for item in neighbors.values()
            ],
            *[
                _graph_context_node(
                    cast(MemoryContextNode, row[1]),
                    relation_count=1,
                )
                for row in context_rows
            ],
        ],
        edges=[
            *[_graph_edge(link) for link in links],
            *[_graph_context_edge(cast(MemoryContextEdge, row[0])) for row in context_rows],
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def create_link(
    data: MemoryLinkCreate, *, actor_agent_id: int | None, administrative: bool = False
) -> MemoryLink:
    assert_safe_value(data.model_dump(mode="python"))
    source = await _get_item_record(data.source_item_id)
    target = await _get_item_record(data.target_item_id)
    if source is None or target is None:
        raise MemoryNotFoundError("Linked memory not found.")
    _assert_not_source_managed(source)
    _assert_not_source_managed(target)
    await assert_item_access(source, actor_agent_id, administrative=administrative)
    await assert_item_access(target, actor_agent_id, administrative=administrative)
    existing = await get_db().scalar(
        select(MemoryLink).where(
            MemoryLink.source_item_id == data.source_item_id,
            MemoryLink.target_item_id == data.target_item_id,
            MemoryLink.relation_type == data.relation_type,
        )
    )
    if existing is not None:
        return existing
    link = MemoryLink(
        source_item_id=data.source_item_id,
        target_item_id=data.target_item_id,
        relation_type=data.relation_type.strip(),
        confidence=data.confidence,
        suggested=data.suggested,
        created_by_agent_id=actor_agent_id,
        metadata_=dict(data.metadata),
    )
    get_db().add(link)
    await get_db().commit()
    return link


async def ensure_source_managed_link(
    *,
    source_item_id: UUID,
    target_item_id: UUID,
    relation_type: str,
) -> MemoryLink:
    """Internal idempotent graph edge between two source projections."""

    relation = relation_type.strip()
    if not relation or len(relation) > 80:
        raise ValueError("A managed memory relation type is required.")
    source = await _get_item_record(source_item_id)
    target = await _get_item_record(target_item_id)
    if source is None or target is None:
        raise MemoryNotFoundError("Linked managed memory not found.")
    if not source.source_managed or not target.source_managed:
        raise MemoryConflictError("Managed projection links require two source-managed memories.")
    if source.owner_agent_id != target.owner_agent_id:
        raise MemoryConflictError("Managed projection links must stay within one owner agent.")
    if source.id == target.id:
        raise MemoryConflictError("A memory cannot link to itself.")
    db = get_db()
    existing = await db.scalar(
        select(MemoryLink).where(
            MemoryLink.source_item_id == source_item_id,
            MemoryLink.target_item_id == target_item_id,
            MemoryLink.relation_type == relation,
        )
    )
    if existing is not None:
        return existing
    # Recreated parent projections get a new UUID. Remove the now-stale edge
    # before attaching the cycle to its current Goal projection.
    await db.execute(
        delete(MemoryLink).where(
            MemoryLink.source_item_id == source_item_id,
            MemoryLink.relation_type == relation,
        )
    )
    link = MemoryLink(
        source_item_id=source_item_id,
        target_item_id=target_item_id,
        relation_type=relation,
        confidence=1.0,
        suggested=False,
        created_by_agent_id=None,
        projection_key=(
            "goal.cycle_membership"
            if relation == "cycle_of"
            else "process.result_membership"
            if relation == "result_of"
            else "memory.source_membership"
        ),
        projection_version=1,
        metadata_={"managed_projection": True},
    )
    db.add(link)
    await db.commit()
    return link


async def ensure_topic_memory_link(*, topic_item_id: UUID, memory_item_id: UUID) -> MemoryLink:
    """Attach a public Topic projection to any governed memory, without changing ACLs."""

    topic = await _get_item_record(topic_item_id)
    memory = await _get_item_record(memory_item_id)
    if topic is None or memory is None:
        raise MemoryNotFoundError("Topic or linked memory not found.")
    if not (
        topic.source_managed
        and topic.managed_source_kind == "topic"
        and topic.visibility == "public"
        and topic.owner_agent_id is None
    ):
        raise MemoryConflictError("The source is not a public Topic projection.")
    if topic.id == memory.id:
        raise MemoryConflictError("A Topic memory cannot link to itself.")
    db = get_db()
    existing = await db.scalar(
        select(MemoryLink).where(
            MemoryLink.source_item_id == topic_item_id,
            MemoryLink.target_item_id == memory_item_id,
            MemoryLink.relation_type == "topic_contains",
        )
    )
    if existing is not None:
        return existing
    link = MemoryLink(
        source_item_id=topic_item_id,
        target_item_id=memory_item_id,
        relation_type="topic_contains",
        confidence=1.0,
        suggested=False,
        created_by_agent_id=None,
        projection_key="memory.topic_membership",
        projection_version=1,
        metadata_={"managed_projection": True, "projection_kind": "topic"},
    )
    db.add(link)
    await db.commit()
    return link


async def ensure_topic_contact_memory_scope(
    *,
    owner_agent_id: int,
    topic_item_id: UUID,
    contact_item_id: UUID,
    memory_item_id: UUID,
    source_kind: str,
    source_ref: str,
) -> MemoryTopicContactScope:
    """Bind a memory to the inseparable Topic/contact scope of a human exchange."""

    await ensure_contact_memory_scope(
        owner_agent_id=owner_agent_id,
        contact_item_id=contact_item_id,
        memory_item_id=memory_item_id,
        source_kind=source_kind,
        source_ref=source_ref,
    )

    topic = await _get_item_record(topic_item_id)
    contact = await _get_item_record(contact_item_id)
    memory = await _get_item_record(memory_item_id)
    if topic is None or contact is None or memory is None:
        raise MemoryNotFoundError("Topic, contact, or linked memory not found.")
    if not (
        topic.source_managed
        and topic.managed_source_kind == "topic"
        and topic.visibility == "public"
        and topic.owner_agent_id is None
    ):
        raise MemoryConflictError("The Topic scope source is not a public projection.")
    if not (
        contact.source_managed
        and contact.managed_source_kind == "messenger_contact"
        and contact.memory_type == "social"
        and contact.visibility == "private"
        and contact.owner_agent_id == owner_agent_id
    ):
        raise MemoryConflictError("The contact scope source is not owned by this agent.")
    if memory.owner_agent_id != owner_agent_id or memory.visibility == "public":
        raise MemoryConflictError("Conversation memory must remain private to the contact owner.")
    normalized_kind = source_kind.strip()
    normalized_ref = source_ref.strip()
    if not normalized_kind or not normalized_ref:
        raise MemoryConflictError("A Topic/contact membership requires exact provenance.")

    db = get_db()
    foreign_contact = await db.scalar(
        select(MemoryTopicContactScope.id)
        .join(
            MemoryTopicContactItem,
            MemoryTopicContactItem.scope_id == MemoryTopicContactScope.id,
        )
        .where(
            MemoryTopicContactItem.item_id == memory_item_id,
            or_(
                MemoryTopicContactScope.owner_agent_id != owner_agent_id,
                MemoryTopicContactScope.contact_item_id != contact_item_id,
            ),
        )
        .limit(1)
    )
    if foreign_contact is not None:
        raise MemoryConflictError(
            "A conversational memory cannot be shared between distinct contacts."
        )
    scope_id = await db.scalar(
        pg_insert(MemoryTopicContactScope)
        .values(
            owner_agent_id=owner_agent_id,
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
        )
        .on_conflict_do_nothing(
            index_elements=[
                MemoryTopicContactScope.owner_agent_id,
                MemoryTopicContactScope.topic_item_id,
                MemoryTopicContactScope.contact_item_id,
            ]
        )
        .returning(MemoryTopicContactScope.id)
    )
    scope = await db.scalar(
        select(MemoryTopicContactScope).where(
            MemoryTopicContactScope.id == scope_id
            if scope_id is not None
            else and_(
                MemoryTopicContactScope.owner_agent_id == owner_agent_id,
                MemoryTopicContactScope.topic_item_id == topic_item_id,
                MemoryTopicContactScope.contact_item_id == contact_item_id,
            )
        )
    )
    if scope is None:
        raise MemoryConflictError("The Topic/contact scope could not be resolved.")
    await db.execute(
        pg_insert(MemoryTopicContactItem)
        .values(
            scope_id=scope.id,
            item_id=memory_item_id,
            source_kind=normalized_kind[:80],
            source_ref=normalized_ref[:1_024],
        )
        .on_conflict_do_nothing(
            index_elements=[
                MemoryTopicContactItem.scope_id,
                MemoryTopicContactItem.item_id,
            ]
        )
    )
    for source_id, relation, projection_kind in (
        (topic_item_id, "topic_contains", "topic"),
        (contact_item_id, "contact_contains", "contact"),
    ):
        await db.execute(
            pg_insert(MemoryLink)
            .values(
                source_item_id=source_id,
                target_item_id=memory_item_id,
                relation_type=relation,
                confidence=1.0,
                suggested=False,
                created_by_agent_id=None,
                projection_key=(
                    "memory.topic_membership"
                    if projection_kind == "topic"
                    else "memory.contact_membership"
                ),
                projection_version=1,
                metadata_={
                    "managed_projection": True,
                    "projection_kind": projection_kind,
                    "scope_mode": "topic_contact",
                },
            )
            .on_conflict_do_nothing(
                index_elements=[
                    MemoryLink.source_item_id,
                    MemoryLink.target_item_id,
                    MemoryLink.relation_type,
                ]
            )
        )
    await db.commit()
    return scope


async def ensure_contact_memory_scope(
    *,
    owner_agent_id: int,
    contact_item_id: UUID,
    memory_item_id: UUID,
    source_kind: str,
    source_ref: str,
) -> MemoryContactItem:
    """Seal a conversational memory to its contact before Topic classification."""

    contact = await _get_item_record(contact_item_id)
    memory = await _get_item_record(memory_item_id)
    if contact is None or memory is None:
        raise MemoryNotFoundError("Contact or linked memory not found.")
    if not (
        contact.source_managed
        and contact.managed_source_kind == "messenger_contact"
        and contact.memory_type == "social"
        and contact.visibility == "private"
        and contact.owner_agent_id == owner_agent_id
    ):
        raise MemoryConflictError("The contact scope source is not owned by this agent.")
    if memory.owner_agent_id != owner_agent_id or memory.visibility == "public":
        raise MemoryConflictError("Conversation memory must remain private to the contact owner.")
    normalized_kind = source_kind.strip()
    normalized_ref = source_ref.strip()
    if not normalized_kind or not normalized_ref:
        raise MemoryConflictError("A contact membership requires exact provenance.")

    db = get_db()
    existing = await db.scalar(
        select(MemoryContactItem).where(MemoryContactItem.item_id == memory_item_id)
    )
    if existing is not None:
        if existing.owner_agent_id != owner_agent_id or existing.contact_item_id != contact_item_id:
            raise MemoryConflictError(
                "A conversational memory cannot be shared between distinct contacts."
            )
        return existing
    await db.execute(
        pg_insert(MemoryContactItem)
        .values(
            owner_agent_id=owner_agent_id,
            contact_item_id=contact_item_id,
            item_id=memory_item_id,
            source_kind=normalized_kind[:80],
            source_ref=normalized_ref[:1_024],
        )
        .on_conflict_do_nothing(index_elements=[MemoryContactItem.item_id])
    )
    scoped = await db.scalar(
        select(MemoryContactItem).where(MemoryContactItem.item_id == memory_item_id)
    )
    if scoped is None:
        raise MemoryConflictError("The contact scope could not be persisted.")
    if scoped.owner_agent_id != owner_agent_id or scoped.contact_item_id != contact_item_id:
        raise MemoryConflictError(
            "A conversational memory cannot be shared between distinct contacts."
        )
    await db.commit()
    return scoped


async def list_topic_linked_memories(
    topic_item_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> list[TopicLinkedMemory]:
    """Return metadata for links administered through the Topic domain."""

    topic = await _get_item_record(topic_item_id)
    if topic is None or not (
        topic.source_managed
        and topic.managed_source_kind == "topic"
        and topic.visibility == "public"
        and topic.owner_agent_id is None
    ):
        raise MemoryNotFoundError("Topic projection not found.")
    query = (
        select(MemoryItem)
        .join(MemoryLink, MemoryLink.target_item_id == MemoryItem.id)
        .where(
            MemoryLink.source_item_id == topic_item_id,
            MemoryLink.relation_type == "topic_contains",
        )
        .order_by(MemoryItem.title, MemoryItem.id)
        .limit(5_000)
    )
    if agent_ids is not None:
        query = query.where(MemoryItem.owner_agent_id.in_(agent_ids))
    rows = await get_db().execute(query)
    return [
        TopicLinkedMemory(
            id=item.id,
            title=item.title,
            excerpt=" ".join(item.search_text[:800].split()),
            memory_type=item.memory_type,
            owner_agent_id=item.owner_agent_id,
            visibility=item.visibility,
            node_kind=item.node_kind,
            filename=item.filename,
            created_at=item.created_at,
        )
        for item in rows.scalars()
    ]


async def list_topics_linked_documents(
    topic_item_ids: set[UUID],
    *,
    agent_ids: Collection[int] | None = None,
) -> list[TopicLinkedDocument]:
    """Return working documents for several Topic projections in one query."""

    if not topic_item_ids:
        return []
    query = (
        select(MemoryLink.source_item_id, MemoryItem)
        .join(MemoryItem, MemoryItem.id == MemoryLink.target_item_id)
        .where(
            MemoryLink.source_item_id.in_(topic_item_ids),
            MemoryLink.relation_type == "topic_contains",
            MemoryLink.deleted_at.is_(None),
            MemoryItem.deleted_at.is_(None),
            MemoryItem.node_kind == "document",
        )
        .order_by(MemoryLink.source_item_id, MemoryItem.title, MemoryItem.id)
    )
    if agent_ids is not None:
        query = query.where(MemoryItem.owner_agent_id.in_(agent_ids))
    rows = await get_db().execute(query)
    return [
        TopicLinkedDocument(
            topic_item_id=topic_item_id,
            id=item.id,
            title=item.title,
            filename=item.filename,
        )
        for topic_item_id, item in rows
    ]


async def move_topic_memory_links(
    *,
    source_topic_item_id: UUID,
    target_topic_item_id: UUID,
    memory_item_ids: set[UUID] | None = None,
) -> int:
    """Move selected Topic edges without copying memories or changing their ACLs."""

    if source_topic_item_id == target_topic_item_id:
        raise MemoryConflictError("Source and target Topic projections must differ.")
    source = await _get_item_record(source_topic_item_id)
    target = await _get_item_record(target_topic_item_id)
    for item in (source, target):
        if item is None or not (
            item.source_managed
            and item.managed_source_kind == "topic"
            and item.visibility == "public"
            and item.owner_agent_id is None
        ):
            raise MemoryNotFoundError("Topic projection not found.")

    db = get_db()
    links = list(
        (
            await db.execute(
                select(MemoryLink)
                .where(
                    MemoryLink.source_item_id == source_topic_item_id,
                    MemoryLink.relation_type == "topic_contains",
                )
                .with_for_update()
            )
        ).scalars()
    )
    by_memory_id = {link.target_item_id: link for link in links}
    selected_ids = set(by_memory_id) if memory_item_ids is None else memory_item_ids
    missing = selected_ids.difference(by_memory_id)
    if missing:
        raise MemoryConflictError(
            "Some selected memories are no longer attached to the source Topic."
        )
    if not selected_ids:
        return 0

    existing_target_ids = set(
        (
            await db.scalars(
                select(MemoryLink.target_item_id).where(
                    MemoryLink.source_item_id == target_topic_item_id,
                    MemoryLink.target_item_id.in_(selected_ids),
                    MemoryLink.relation_type == "topic_contains",
                )
            )
        ).all()
    )
    for memory_id in selected_ids:
        link = by_memory_id[memory_id]
        if memory_id in existing_target_ids:
            await db.delete(link)
        else:
            link.source_item_id = target_topic_item_id
    await db.commit()
    return len(selected_ids)


async def move_topic_contact_memory_scopes(
    *,
    source_topic_item_id: UUID,
    target_topic_item_id: UUID,
    memory_item_ids: set[UUID] | None = None,
) -> int:
    """Move exact conversational scopes when a Topic is merged or split."""

    if source_topic_item_id == target_topic_item_id:
        raise MemoryConflictError("Source and target Topic projections must differ.")
    source = await _get_item_record(source_topic_item_id)
    target = await _get_item_record(target_topic_item_id)
    for item in (source, target):
        if item is None or not (
            item.source_managed
            and item.managed_source_kind == "topic"
            and item.visibility == "public"
            and item.owner_agent_id is None
        ):
            raise MemoryNotFoundError("Topic projection not found.")

    db = get_db()
    query = (
        select(MemoryTopicContactItem, MemoryTopicContactScope)
        .join(
            MemoryTopicContactScope,
            MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
        )
        .where(MemoryTopicContactScope.topic_item_id == source_topic_item_id)
        .with_for_update()
    )
    if memory_item_ids is not None:
        query = query.where(MemoryTopicContactItem.item_id.in_(memory_item_ids))
    rows = list((await db.execute(query)).all())
    if not rows:
        return 0

    target_scopes: dict[tuple[int, UUID], MemoryTopicContactScope] = {}
    source_scope_ids: set[UUID] = set()
    for membership, source_scope in rows:
        source_scope_ids.add(source_scope.id)
        scope_key = (source_scope.owner_agent_id, source_scope.contact_item_id)
        target_scope = target_scopes.get(scope_key)
        if target_scope is None:
            inserted_id = await db.scalar(
                pg_insert(MemoryTopicContactScope)
                .values(
                    owner_agent_id=source_scope.owner_agent_id,
                    topic_item_id=target_topic_item_id,
                    contact_item_id=source_scope.contact_item_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        MemoryTopicContactScope.owner_agent_id,
                        MemoryTopicContactScope.topic_item_id,
                        MemoryTopicContactScope.contact_item_id,
                    ]
                )
                .returning(MemoryTopicContactScope.id)
            )
            target_scope = await db.scalar(
                select(MemoryTopicContactScope).where(
                    MemoryTopicContactScope.id == inserted_id
                    if inserted_id is not None
                    else and_(
                        MemoryTopicContactScope.owner_agent_id == source_scope.owner_agent_id,
                        MemoryTopicContactScope.topic_item_id == target_topic_item_id,
                        MemoryTopicContactScope.contact_item_id == source_scope.contact_item_id,
                    )
                )
            )
            if target_scope is None:
                raise MemoryConflictError("The target Topic/contact scope could not be resolved.")
            target_scopes[scope_key] = target_scope
        duplicate = await db.scalar(
            select(MemoryTopicContactItem.id).where(
                MemoryTopicContactItem.scope_id == target_scope.id,
                MemoryTopicContactItem.item_id == membership.item_id,
            )
        )
        if duplicate is None:
            membership.scope_id = target_scope.id
        else:
            await db.delete(membership)

    await db.flush()
    await db.execute(
        delete(MemoryTopicContactScope).where(
            MemoryTopicContactScope.id.in_(source_scope_ids),
            ~exists(
                select(MemoryTopicContactItem.id).where(
                    MemoryTopicContactItem.scope_id == MemoryTopicContactScope.id
                )
            ),
        )
    )
    await db.commit()
    return len({membership.item_id for membership, _scope in rows})


async def delete_topic_contact_memory_scopes(*, topic_item_id: UUID) -> int:
    """Delete derived exact scopes before a soft-deleted Topic projection remains."""

    result = await get_db().execute(
        delete(MemoryTopicContactScope).where(
            MemoryTopicContactScope.topic_item_id == topic_item_id
        )
    )
    rowcount = getattr(result, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) else 0


async def list_links(
    item_id: UUID, *, actor_agent_id: int | None, administrative: bool = False
) -> list[MemoryLink]:
    item = await _get_item_record(item_id)
    if item is None:
        raise MemoryNotFoundError("Memory not found.")
    await assert_item_access(item, actor_agent_id, administrative=administrative)
    result = await get_db().execute(
        select(MemoryLink)
        .where(
            or_(
                MemoryLink.source_item_id == item_id,
                MemoryLink.target_item_id == item_id,
            )
        )
        .order_by(MemoryLink.relation_type, MemoryLink.created_at)
    )
    links = list(result.scalars().all())
    if administrative or actor_agent_id is None or not links:
        return links
    neighbor_ids = {
        link.target_item_id if link.source_item_id == item_id else link.source_item_id
        for link in links
    }
    visible_ids = set(
        (
            await get_db().execute(
                select(MemoryItem.id).where(
                    MemoryItem.id.in_(neighbor_ids),
                    readable_item_clause(actor_agent_id),
                )
            )
        ).scalars()
    )
    return [
        link
        for link in links
        if (link.target_item_id if link.source_item_id == item_id else link.source_item_id)
        in visible_ids
    ]


def link_to_public(link: MemoryLink) -> MemoryLinkPublic:
    return MemoryLinkPublic.model_validate(
        {
            "id": link.id,
            "source_item_id": link.source_item_id,
            "target_item_id": link.target_item_id,
            "relation_type": link.relation_type,
            "confidence": link.confidence,
            "suggested": link.suggested,
            "created_by_agent_id": link.created_by_agent_id,
            "metadata": dict(link.metadata_),
            "created_at": link.created_at,
        }
    )


__all__ = [
    "add_item_source",
    "MemoryConflictError",
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryPermissionError",
    "assert_item_access",
    "create_item",
    "create_link",
    "decode_payload",
    "ensure_source_managed_link",
    "ensure_topic_memory_link",
    "expand_graph_node",
    "forget_item",
    "forget_merged_item",
    "forget_source_managed_item",
    "purge_source_managed_item",
    "forget_stale_item",
    "get_item",
    "item_to_detail",
    "item_to_public",
    "link_to_public",
    "list_graph_roots",
    "list_filter_options",
    "list_links",
    "list_topic_linked_memories",
    "list_revisions",
    "move_topic_memory_links",
    "preview_retention",
    "remove_item_grant",
    "search_items",
    "set_item_grant",
    "set_document_global_access",
    "update_item",
    "upsert_source_managed_item",
]
