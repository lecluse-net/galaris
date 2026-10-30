"""Natural governed-memory tools shared by internal and Hermes runtimes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from loguru import logger
from app.task.facade import memory_scope_for_task
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.i18n import t

from . import acquisition_service, service
from .contact_policy import CONTACT_COORDINATE_MESSAGE
from .contact_policy import contains_contact_coordinates
from .facts import AtomicMemoryFact
from .recall_scope import resolve_recall_scope
from .schemas import (
    MemoryTemporalAnchor,
    MemoryAcquisitionCreate,
    MemoryAcquisitionResult,
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

    return await resolve_recall_scope(
        agent_id=ctx.agent_id, task_id=ctx.task_id, conversation_turn=ctx.resource("conversation_turn"),
    )


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
        if await memory_scope_for_task(ctx.task_id, agent_id=ctx.agent_id) is None:
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


@mcp_tool("memory", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="memory_remember",
    description=(
        "Store one durable governed memory as one atomic structured fact. Supply fact with "
        "subject_ref (an existing Contact or Document URI; omit for the current contact or agent), "
        "one snake_case predicate and one raw scalar value or {ref: URI}. Split independent values into separate facts. "
        "Do not narrate who said it or when: attribution and timestamps are linked by the server. "
        "Legacy content accepts a structured fact encoded as JSON, never prose or HTML. "
        "Use sparingly for an explicit memory request, a correction, or an especially important "
        "confirmed fact worth retaining immediately. Leave routine extraction and duplicate checking "
        "to Dream; skip equivalent known memories. Storage is immediate and auditable. "
        "Never store contact emails, phone numbers, postal addresses or messaging identifiers here: "
        "Contacts handles them separately. Keep a person's preferences or decisions without their coordinates. "
        "For a correction or conflicting claim about a known personal memory, supply "
        "contradicts_memory_id and its expected_revision: both claims are preserved with an explicit "
        "contradiction link. A changed target requires rereading; never guess its UUID. "
        "Keywords may be an array of strings or a JSON-encoded array string. Optional temporal contains partial "
        "year/month/day/weekday (Monday=1..Sunday=7)/hour/minute in Galaris's configured timezone. "
        "Unset components are wildcards. An anchor excludes automatic recall outside its period "
        "and forces priority inclusion when it matches, subject to access and context budgets. "
        "Use it for intended reminders, not historical timestamps or ordinary facts; never default to today."
    ),
)
async def memory_remember(
    ctx: McpToolContext,
    content: str = "",
    title: str = "",
    keywords: list[str] | str | None = None,
    temporal: MemoryTemporalAnchor | None = None,
    contradicts_memory_id: str | None = None,
    expected_revision: int | None = None,
    fact: AtomicMemoryFact | None = None,
) -> str:
    source = _current_source(ctx)
    language = await context_language(ctx)
    preserved_memory_id: UUID | None = None
    contradiction_linked = False
    try:
        topic_item_id, contact_item_id = await _recall_scope(ctx)
        target_id = UUID(contradicts_memory_id) if contradicts_memory_id else None
        if target_id is not None:
            target = await service.item_record(target_id, revisions=False, contents=False)
            if target is None or target.owner_agent_id != ctx.agent_id or target.node_kind != "memory" or target.source_managed:
                raise ValueError("A contradiction requires this agent's personal memory")
            if expected_revision is None or expected_revision != target.revision:
                raise ValueError("Read the target memory and supply its current expected_revision")
        elif expected_revision is not None:
            raise ValueError("expected_revision requires contradicts_memory_id")
        if fact is None and not contains_contact_coordinates(content=content, title=title,
                                                             keywords=_normalize_memory_keywords(keywords)):
            try:
                fact = AtomicMemoryFact.model_validate_json(content)
            except ValueError:
                return _json({"status": "rejected", "memory_id": None, "rejection_reason": "atomic_fact_required",
                    "message": "Supply fact={subject_ref, predicate, value}; one raw property per memory. "
                               "Omit subject_ref for the current contact. No narrated author, date, paragraph or HTML."})
        acquisition = await acquisition_service.acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=ctx.agent_id,
                title=title,
                content=content,
                fact=fact,
                keywords=_normalize_memory_keywords(keywords),
                temporal=temporal,
                source_kind=source.source_kind,
                source_ref=source.source_ref,
                metadata={
                    "media_type": "text/html",
                    "requested_by": "agent",
                    "language": language,
                    **_scope_metadata(topic_item_id, contact_item_id),
                },
            )
        )
        if target_id is not None and acquisition.memory_id is not None:
            preserved_memory_id = acquisition.memory_id
            if preserved_memory_id == target_id:
                raise ValueError("The proposed claim matches the target; no contradiction was linked")
            # Store the fact through normal idempotent acquisition first. Linking
            # an existing fact then holds the target lock through the link commit,
            # without a nested creation commit releasing it prematurely.
            acquisition = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(
                agent_id=ctx.agent_id, action="contradict", target_item_id=target_id,
                temporal=temporal,
                title=title, content=content, keywords=_normalize_memory_keywords(keywords),
                fact=fact,
                source_kind=source.source_kind, source_ref=source.source_ref,
                metadata={"media_type": "text/html", "requested_by": "agent", "language": language,
                    "target_revision": expected_revision, "other_item_id": str(preserved_memory_id),
                    **_scope_metadata(topic_item_id, contact_item_id)},
            ))
            contradiction_linked = True
        association = (_SourceAssociation(associated=False) if acquisition.source_backed
                       else await _associate_with_current_source(ctx, acquisition.memory_id))
        return _json(
            {
                "acquisition_id": acquisition.acquisition_id,
                "created": acquisition.created,
                "status": acquisition.status,
                "memory_id": acquisition.memory_id,
                **({"rejection_reason": acquisition.rejection_reason, "message": CONTACT_COORDINATE_MESSAGE}
                   if acquisition.rejection_reason == "contact_coordinates" else {}),
                **({"contradiction_linked": contradiction_linked} if target_id is not None else {}),
                **_task_association_payload(association),
            }
        )
    except Exception as exc:
        logger.exception("memory_remember failed")
        return _json({"error": str(exc), **({"memory_id": str(preserved_memory_id),
            "memory_preserved": True, "contradiction_linked": contradiction_linked}
            if preserved_memory_id is not None else {})})


@mcp_tool("memory", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", name="memory_upcoming", description=(
    "List accessible memories matching now or the configured upcoming time window, independently "
    "of text similarity. Use offset to read further pages. Does not schedule notifications."
))
async def memory_upcoming(ctx: McpToolContext, limit: int = 50, offset: int = 0) -> str:
    from .retrieval import temporal_hits
    if not 1 <= limit <= 500 or not 0 <= offset <= 10_000:
        return _json({"error": "Use limit 1..500 and offset 0..10000."})
    topic_item_id, contact_item_id = await _recall_scope(ctx)
    hits, has_more = await temporal_hits(MemoryRecallRequest(
        agent_id=ctx.agent_id, topic_item_id=topic_item_id, contact_item_id=contact_item_id,
        strict_contact_scope=False, exclude_agent_projections=True,
    ), limit=limit, offset=offset)
    return _json({"items": [hit.model_dump(mode="json") for hit in hits], "has_more": has_more,
                  "next_offset": offset + limit if has_more else None})


@mcp_tool("memory", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="memory_forget",
    description=(
        "Permanently forget one of your memories, including every stored revision. "
        "Use the exact UUID returned by file_search on memory://. "
        "Items directly representing Contacts, Documents, Files or other source-owned resources "
        "cannot be forgotten here. A personal fact linked to those resources remains forgettable."
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


@mcp_tool("memory", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="memory_summarize",
    description=(
        "Extract up to 12 separate atomic facts from up to 200 recent room messages: linked subjects, raw values, "
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
        facts = await summarize_transcript(
            transcript[-32_000:], agent_id=ctx.agent_id, task_id=ctx.task_id, language=language,
        )
        acquisitions: list[MemoryAcquisitionResult] = []
        association = _SourceAssociation(associated=False)
        for fact in facts:
            acquisition = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(
                agent_id=ctx.agent_id,
                fact=fact,
                source_kind="messenger_room",
                source_ref=f"room:{room_id}",
                metadata={
                    "room_id": room_id,
                    "summary_label": resolved_title,
                    "message_count": len(lines),
                    "transcript_truncated": truncated,
                    "media_type": "text/html",
                    "language": language,
                    **_scope_metadata(topic_item_id, contact_item_id),
                },
            ))
            acquisitions.append(acquisition)
            if not acquisition.source_backed:
                attached = await _associate_with_current_source(ctx, acquisition.memory_id)
                if attached.associated:
                    association = attached
        memory_ids = [item.memory_id for item in acquisitions if item.memory_id is not None]
        return _json(
            {
                "acquisition_id": acquisitions[0].acquisition_id if acquisitions else None,
                "created": any(item.created for item in acquisitions),
                "status": "stored" if memory_ids else "rejected" if acquisitions else "ignored",
                "memory_id": memory_ids[0] if memory_ids else None,
                "memory_ids": memory_ids,
                "facts": [item.model_dump(mode="json") for item in acquisitions],
                **_task_association_payload(association),
            }
        )
    except Exception as exc:
        logger.exception("memory_summarize failed")
        return _json({"error": str(exc)})
