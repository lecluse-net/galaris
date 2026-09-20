"""Natural governed-memory tools shared by internal and Hermes runtimes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from loguru import logger

from app.task import Task
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.database import get_db
from core.i18n import t

from . import acquisition_service, document_service, facade, item_sharing, service
from .schemas import (
    MemoryAcquisitionCreate,
    MemoryRecallRequest,
    MemorySourceCreate,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


def _normalize_memory_keywords(keywords: list[str] | str | None) -> list[str]:
    """Accept the JSON-encoded arrays occasionally emitted by tool-calling models."""

    if keywords is None:
        return []
    if isinstance(keywords, list):
        return keywords
    value = keywords.strip()
    if not value:
        return []
    try:
        decoded: object = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if not isinstance(decoded, list):
        return [value]
    normalized: list[str] = []
    for keyword in cast(list[object], decoded):
        if not isinstance(keyword, str):
            return [value]
        normalized.append(keyword)
    return normalized


@dataclass(frozen=True, slots=True)
class _CurrentSource:
    source_kind: str
    source_ref: str


@dataclass(frozen=True, slots=True)
class _SourceAssociation:
    associated: bool
    source_kind: str | None = None
    topic_projection_pending: bool = False


def _scope_metadata(
    topic_item_id: UUID | None,
    contact_item_id: UUID | None,
) -> dict[str, str]:
    if contact_item_id is None:
        return {}
    metadata = {
        "scope_mode": "topic_contact" if topic_item_id is not None else "contact",
        "contact_item_id": str(contact_item_id),
    }
    if topic_item_id is not None:
        metadata["topic_item_id"] = str(topic_item_id)
    return metadata


async def _recall_scope(
    ctx: McpToolContext,
) -> tuple[UUID | None, UUID | None]:
    """Resolve the server-owned Topic/contact scope for the current run."""

    topic_id: UUID | None = None
    contact_item_id: UUID | None = None
    if ctx.task_id is not None:
        task = await get_db().get(Task, ctx.task_id)
        if task is not None and task.agent_id == ctx.agent_id:
            topic_id = task.topic_id
            contact_item_id = task.contact_memory_item_id
    else:
        turn = ctx.resource("conversation_turn")
        if turn is not None and getattr(turn, "agent_id", None) == ctx.agent_id:
            raw_topic_id = getattr(turn, "topic_id", None)
            raw_contact_item_id = getattr(turn, "contact_memory_item_id", None)
            topic_id = raw_topic_id if isinstance(raw_topic_id, UUID) else None
            contact_item_id = (
                raw_contact_item_id
                if isinstance(raw_contact_item_id, UUID)
                else None
            )
    return await service.projected_topic_item_id(topic_id), contact_item_id


def _current_source(ctx: McpToolContext) -> _CurrentSource:
    if ctx.task_id is not None:
        return _CurrentSource("task", f"task:{ctx.task_id}")
    turn = ctx.resource("conversation_turn")
    if turn is None or getattr(turn, "agent_id", None) != ctx.agent_id:
        return _CurrentSource("agent", "agent:manual")
    round_id = getattr(turn, "round_id", None)
    if isinstance(round_id, UUID):
        return _CurrentSource(
            "conversation_round",
            f"conversation_round:{round_id}",
        )
    return _CurrentSource("agent", "agent:manual")


async def _associate_with_current_source(
    ctx: McpToolContext,
    memory_id: UUID | None,
) -> _SourceAssociation:
    if memory_id is None:
        return _SourceAssociation(associated=False)
    source = _current_source(ctx)
    if source.source_kind == "agent":
        return _SourceAssociation(associated=False)
    if source.source_kind == "task":
        assert ctx.task_id is not None
        task = await get_db().get(Task, ctx.task_id)
        if task is None or task.agent_id != ctx.agent_id:
            return _SourceAssociation(associated=False)
    topic_item_id, contact_item_id = await _recall_scope(ctx)
    await service.add_item_source(
        memory_id,
        MemorySourceCreate(
            source_kind=source.source_kind,
            source_ref=source.source_ref,
            metadata={
                "projection_deferred_until_topic": topic_item_id is None,
            },
        ),
        actor_agent_id=ctx.agent_id,
    )
    if topic_item_id is not None and contact_item_id is not None:
        await service.ensure_topic_contact_memory_scope(
            owner_agent_id=ctx.agent_id,
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
            memory_item_id=memory_id,
            source_kind=source.source_kind,
            source_ref=source.source_ref,
        )
    elif contact_item_id is not None:
        await service.ensure_contact_memory_scope(
            owner_agent_id=ctx.agent_id,
            contact_item_id=contact_item_id,
            memory_item_id=memory_id,
            source_kind=source.source_kind,
            source_ref=source.source_ref,
        )
    elif topic_item_id is not None:
        await service.ensure_topic_memory_link(
            topic_item_id=topic_item_id,
            memory_item_id=memory_id,
        )
    return _SourceAssociation(
        associated=True,
        source_kind=source.source_kind,
        topic_projection_pending=(
            source.source_kind in {"task", "voice_turn"}
            and topic_item_id is None
        ),
    )


def _task_association_payload(
    association: _SourceAssociation,
) -> dict[str, object]:
    return {
        "source_associated": association.associated,
        "source_kind": association.source_kind,
        "task_associated": (
            association.associated and association.source_kind == "task"
        ),
        "links_created": 0,
        "topic_projection_pending": association.topic_projection_pending,
    }


async def memory_search(
    ctx: McpToolContext,
    query: str,
    limit: int | None = None,
    memory_types: list[str] | None = None,
) -> str:
    try:
        topic_item_id, contact_item_id = await _recall_scope(ctx)
        request = MemoryRecallRequest.model_validate(
            {
                "agent_id": ctx.agent_id,
                "query": query,
                "limit": (
                    max(1, min(int(limit), 50))
                    if limit is not None
                    else None
                ),
                "memory_types": memory_types or [],
                "task_id": ctx.task_id,
                "topic_item_id": topic_item_id,
                "contact_item_id": contact_item_id,
            }
        )
        page = await facade.search_memory_detailed(
            request.query,
            agent_id=request.agent_id,
            limit=request.limit,
            memory_types=request.memory_types,
            task_id=request.task_id,
            topic_item_id=request.topic_item_id,
            contact_item_id=request.contact_item_id,
            record_llm_access=True,
            telemetry_kind="search",
        )
        return _json(
            {
                "query": page.query,
                "memories": [
                    {
                        "memory_id": hit.item.id,
                        "title": hit.item.title,
                        "type": hit.item.memory_type,
                        "node_kind": hit.item.node_kind,
                        "excerpt": hit.excerpt,
                        "sources": hit.source_refs,
                        "structural_path": [step.model_dump(mode="json") for step in hit.structural_path],
                    }
                    for hit in page.hits
                ],
                "has_more": page.has_more,
                "search": {
                    "requested": "hybrid",
                    "used": page.mode,
                    "degraded": page.degraded,
                    "reason": page.degradation_reason,
                },
            }
        )
    except Exception as exc:
        logger.exception("memory_search failed")
        return _json({"error": str(exc)})


async def memory_get(ctx: McpToolContext, memory_id: str, revision: int | None = None) -> str:
    try:
        item_id = UUID(memory_id)
        item, content, access, content_type, media_type = await service.get_item(
            item_id,
            agent_id=ctx.agent_id,
            revision=revision,
            record_llm_access=True,
            task_id=ctx.task_id,
        )
        if item.node_kind == "document":
            return _json(
                {
                    "error": (
                        "This item is a working document. Use file_read with its "
                        "document:// URI to read it in bounded passages."
                    ),
                    "document_id": item.id,
                    "title": item.title,
                    "revision": item.revision,
                }
            )
        detail = await service.item_to_detail(
            item,
            content,
            access,
            content_type=content_type,
            media_type=media_type,
            revision=revision,
        )
        return detail.model_dump_json(indent=2)
    except Exception as exc:
        logger.exception("memory_get failed")
        return _json({"error": str(exc)})


async def document_read(
    ctx: McpToolContext,
    document_id: str,
    query: str = "",
    offset: int = 0,
    max_chars: int = 20_000,
) -> str:
    try:
        result = await document_service.read_document(
            UUID(document_id),
            actor_agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            query=query,
            offset=offset,
            max_chars=max_chars,
        )
        return _json(result)
    except Exception:
        logger.exception("document_read failed")
        raise


async def document_append(
    ctx: McpToolContext,
    document_id: str,
    content: str,
) -> str:
    try:
        result = await document_service.append_document(
            UUID(document_id),
            actor_agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            content=content,
        )
        return _json(result)
    except Exception:
        logger.exception("document_append failed")
        raise


@mcp_tool(
    "memory",
    name="document_share",
    description=(
        "Share your HTML or JSON Dataset document with one agent, human user or team (group). "
        "Supply exactly one of agent_id, user_id, team_id. Access is read, edit, or none to revoke "
        "that direct grant. Use memory_sharing to discover recipients and the lock_version. "
        "Only the owner can share; team membership remains live and other grants are preserved."
    ),
)
async def document_share(
    ctx: McpToolContext,
    document_id: str,
    agent_id: int | None = None,
    access: Literal["read", "edit", "none"] = "edit",
    team_id: int | None = None,
    user_id: int | None = None,
    expected_lock_version: int | None = None,
) -> str:
    try:
        identifier = _sharing_item_id(document_id, document_only=True)
        kind, target = _sharing_target(agent_id, user_id, team_id)
        state = await item_sharing.update_agent_sharing(
            identifier, agent_id=ctx.agent_id, kind=kind, target_id=target,
            access=access, expected_lock_version=expected_lock_version, document_only=True,
        )
        item = await service.item_record(identifier)
        assert item is not None
        return _json({
            "document_id": str(identifier), "uri": f"document://{identifier}",
            "revision": item.revision,
            "shared_with": [{"agent_id": grant.id, "access": "edit" if grant.can_write else "read"}
                            for grant in state.grants if grant.kind == "agent"],
            **state.model_dump(mode="json", exclude={"options"}),
        })
    except Exception:
        logger.exception("document_share failed")
        raise


def _sharing_item_id(value: str, *, document_only: bool = False) -> UUID:
    normalized = value.strip()
    schemes = ("document://",) if document_only else ("document://", "memory://")
    for scheme in schemes:
        if normalized.startswith(scheme):
            normalized = normalized.removeprefix(scheme)
            break
    return UUID(normalized)


def _sharing_target(
    agent_id: int | None, user_id: int | None, team_id: int | None,
) -> tuple[Literal["agent", "user", "team"], int]:
    targets: list[tuple[Literal["agent", "user", "team"], int]] = []
    candidates: tuple[tuple[Literal["agent", "user", "team"], int | None], ...] = (
        ("agent", agent_id), ("user", user_id), ("team", team_id),
    )
    for kind, identifier in candidates:
        if identifier is not None:
            if identifier <= 0:
                raise ValueError("Recipient identifiers must be positive")
            targets.append((kind, identifier))
    if len(targets) != 1:
        raise ValueError("Supply exactly one of agent_id, user_id, team_id")
    return targets[0]


@mcp_tool(
    "memory", name="memory_sharing",
    description=(
        "Inspect sharing of a document or memory item you own. Pass its exact document:// or memory:// "
        "URI, or UUID. Returns grants, recipient options (agents, human users, teams/groups), "
        "owner_groups and lock_version. Use the returned IDs for document_share or memory_share. "
        "Filter recipient options by search/kind and paginate with offset/limit (50 by default, "
        "500 maximum). Sharing grants are separate from the HTML content revision; do not guess recipient IDs."
    ), effect_policy="read", concurrency_policy="safe",
)
async def memory_sharing(
    ctx: McpToolContext, memory_id: str, search: str = "",
    kind: Literal["agent", "user", "team"] | None = None, offset: int = 0, limit: int = 50,
) -> str:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 500")
    state = await item_sharing.agent_sharing(_sharing_item_id(memory_id), agent_id=ctx.agent_id)
    query = search.strip().casefold()
    options = [option for option in state.options
               if (kind is None or option.kind == kind) and query in option.label.casefold()]
    payload = state.model_dump(mode="json", exclude={"options"})
    payload.update(
        options=[option.model_dump(mode="json") for option in options[offset:offset + limit]],
        total=len(options), has_more=offset + limit < len(options),
    )
    return _json(payload)


@mcp_tool(
    "memory", name="memory_share",
    description=(
        "Share your memory item or document with one agent, human user or team (group). "
        "Pass its exact memory:// or document:// URI, or UUID, and exactly one of agent_id, user_id, "
        "team_id. Use memory_sharing first for IDs and lock_version. Access read/edit grants "
        "reading/writing; none removes only that direct grant. Teams include their current human "
        "and agent members. Only the owner can share; immutable or source-managed items cannot be shared."
    ),
)
async def memory_share(
    ctx: McpToolContext, memory_id: str, agent_id: int | None = None,
    access: Literal["read", "edit", "none"] = "read", team_id: int | None = None,
    user_id: int | None = None, expected_lock_version: int | None = None,
) -> str:
    kind, target = _sharing_target(agent_id, user_id, team_id)
    state = await item_sharing.update_agent_sharing(
        _sharing_item_id(memory_id), agent_id=ctx.agent_id, kind=kind, target_id=target,
        access=access, expected_lock_version=expected_lock_version,
    )
    return _json(state.model_dump(mode="json", exclude={"options"}))


@mcp_tool(
    "memory",
    name="memory_remember",
    description=(
        "Store one durable governed memory as semantic HTML (paragraphs, lists, tables, links; no images). Storage is immediate and auditable. Keywords may be "
        "an array of strings or a JSON-encoded array string."
    ),
)
async def memory_remember(
    ctx: McpToolContext,
    content: str,
    title: str,
    memory_type: str = "semantic",
    keywords: list[str] | str | None = None,
) -> str:
    source = _current_source(ctx)
    language = await context_language(ctx)
    try:
        topic_item_id, contact_item_id = await _recall_scope(ctx)
        acquisition = await acquisition_service.acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=ctx.agent_id,
                title=title,
                content=content,
                keywords=_normalize_memory_keywords(keywords),
                source_kind=source.source_kind,
                source_ref=source.source_ref,
                metadata={
                    "media_type": "text/html",
                    "memory_type": memory_type,
                    "requested_by": "agent",
                    "language": language,
                    **_scope_metadata(topic_item_id, contact_item_id),
                },
            )
        )
        association = await _associate_with_current_source(
            ctx,
            acquisition.memory_id,
        )
        return _json(
            {
                "acquisition_id": acquisition.acquisition_id,
                "created": acquisition.created,
                "status": acquisition.status,
                "memory_id": acquisition.memory_id,
                **_task_association_payload(association),
            }
        )
    except Exception as exc:
        logger.exception("memory_remember failed")
        return _json({"error": str(exc)})


async def memory_index(
    ctx: McpToolContext,
    text: str,
    title: str = "Memory",
    source_type: str = "manual",
    source_id: str = "",
    tags: list[str] | None = None,
    replace_existing: bool = False,
) -> str:
    del replace_existing
    language = await context_language(ctx)
    resolved_title = (
        t("memory.tools.default_title", language)
        if not title.strip() or title == "Memory"
        else title
    )
    try:
        topic_item_id, contact_item_id = await _recall_scope(ctx)
        acquisition = await acquisition_service.acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=ctx.agent_id,
                title=resolved_title,
                content=text,
                keywords=tags or [],
                source_kind=source_type or "manual",
                source_ref=source_id or f"task:{ctx.task_id or 'manual'}",
                metadata={
                    "memory_type": "semantic",
                    "requested_by": "legacy_memory_index",
                    "language": language,
                    **_scope_metadata(topic_item_id, contact_item_id),
                },
            )
        )
        association = await _associate_with_current_source(
            ctx,
            acquisition.memory_id,
        )
        return _json(
            {
                "memory_id": acquisition.memory_id,
                "created": acquisition.created,
                "status": acquisition.status,
                **_task_association_payload(association),
            }
        )
    except Exception as exc:
        logger.exception("memory_index failed")
        return _json({"error": str(exc)})


@mcp_tool(
    "memory",
    name="memory_forget",
    description=(
        "Permanently forget one of your memories, including every stored revision. "
        "Use the exact UUID returned by file_search on memory:// or document://."
    ),
)
async def memory_forget(ctx: McpToolContext, memory_id: str) -> str:
    try:
        result = await service.forget_item(
            UUID(memory_id), actor_agent_id=ctx.agent_id
        )
        return result.model_dump_json()
    except Exception as exc:
        logger.exception("memory_forget failed")
        return _json({"error": str(exc)})


@mcp_tool(
    "memory",
    name="memory_summarize",
    description=(
        "Summarize up to 200 recent room messages into durable memory: attributed facts, "
        "decisions, commitments and open questions. Input is bounded to the latest 32,000 "
        "characters. Existing memories are preserved; no raw-transcript fallback on model failure. "
        "Use only when the conversation is explicitly worth retaining."
    ),
)
async def memory_summarize(
    ctx: McpToolContext,
    room_id: str,
    limit: int = 80,
    title: str = "Conversation summary",
) -> str:
    language = await context_language(ctx)
    resolved_title = (
        t("memory.tools.conversation_summary", language)
        if not title.strip() or title == "Conversation summary"
        else title
    )
    try:
        from app import messenger

        topic_item_id, contact_item_id = await _recall_scope(ctx)
        driver = await messenger.messenger_for_agent(ctx.agent_id)
        if driver is None:
            return _json({"error": "No messaging connection is configured."})
        history = await driver.history(room_id, max(1, min(int(limit or 80), 200)))
        lines: list[str] = []
        for message in history:
            sender = message.sender
            author = (
                sender.display_name
                if sender is not None and sender.display_name
                else sender.id
                if sender is not None and sender.id
                else t("memory.tools.participant", language)
            )
            text = message.text.strip()
            if text:
                lines.append(f"{author}: {text}")
        transcript = "\n".join(lines)
        if not transcript:
            return _json({"error": "The room history is empty."})
        from .conversation_summary import summarize_transcript

        truncated = len(transcript) > 32_000
        content = await summarize_transcript(
            transcript[-32_000:], agent_id=ctx.agent_id, task_id=ctx.task_id, language=language,
        )
        acquisition = await acquisition_service.acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=ctx.agent_id,
                title=resolved_title,
                content=content,
                source_kind="messenger_room",
                source_ref=f"room:{room_id}",
                metadata={
                    "room_id": room_id,
                    "message_count": len(lines),
                    "transcript_truncated": truncated,
                    "media_type": "text/html",
                    "language": language,
                    **_scope_metadata(topic_item_id, contact_item_id),
                },
            )
        )
        association = await _associate_with_current_source(
            ctx,
            acquisition.memory_id,
        )
        return _json(
            {
                "acquisition_id": acquisition.acquisition_id,
                "created": acquisition.created,
                "status": acquisition.status,
                "memory_id": acquisition.memory_id,
                **_task_association_payload(association),
            }
        )
    except Exception as exc:
        logger.exception("memory_summarize failed")
        return _json({"error": str(exc)})
