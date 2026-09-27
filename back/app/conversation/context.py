"""Contact-scoped document continuity recovered from completed conversation rounds."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import JSONPATH

from app.agent.contracts import (
    AgentContextCandidate,
    AgentContextContribution,
    AgentContextRequest,
)
from app.connection import Connection
from app.file_share import ResourceUriError, parse_resource_uri
from app.messenger import Room
from core.database import get_db

from .models import ConversationRound
from .document_display import can_read_conversation_document
from .document_metadata import resolve_conversation_document_metadata


_RECENT_ROUNDS = 20
# Gather more candidates than the capsule's ten-resource budget so its existing
# relevance scorer can choose an older document by its current title.
_DOCUMENT_CANDIDATES = 50
_DOCUMENT_TOOL_NAMES = frozenset(
    {
        "file_create",
        "file_read",
        "file_info",
        "file_write",
        "file_append",
        "file_edit",
        "file_copy",
        "file_move",
        "document_share",
    }
)
_REFERENCE_KEYS = ("uri", "path", "source", "destination")


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _document_uri(value: object) -> str:
    raw = str(value or "").strip()
    if not raw.startswith("document://"):
        return ""
    try:
        parsed = parse_resource_uri(raw)
    except ResourceUriError:
        return ""
    return str(parsed) if parsed.scheme == "document" and parsed.locator else ""


def _document_id_uri(value: object) -> str:
    try:
        return f"document://{UUID(str(value))}"
    except (TypeError, ValueError):
        return ""


def _payload_references(value: object) -> tuple[str, ...]:
    mapping = _mapping(value)
    if mapping is None:
        return ()
    references: list[str] = []
    for key in _REFERENCE_KEYS:
        uri = _document_uri(mapping.get(key))
        if uri:
            references.append(uri)
    document_uri = _document_id_uri(mapping.get("document_id"))
    if document_uri:
        references.append(document_uri)
    nested = mapping.get("result")
    if nested is not None:
        references.extend(_payload_references(nested))
    return tuple(dict.fromkeys(references))


def conversation_document_references(
    execution_result: Mapping[str, object] | None,
    *, confirmed_only: bool = False,
) -> tuple[tuple[str, str, str], ...]:
    """Extract exact document URIs, labels and operations from successful tool traces."""

    if execution_result is None:
        return ()
    raw_messages = execution_result.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(
        raw_messages, (str, bytes)
    ):
        return ()
    found: list[tuple[str, str, str]] = []
    for raw in cast(Sequence[object], raw_messages):
        message = _mapping(raw)
        if message is None or message.get("success") is False:
            continue
        # Historical work projections keep their existing permissive display;
        # new context admission requires a confirmed tool outcome.
        if confirmed_only and (message.get("type") != "tool" or message.get("success") is not True):
            continue
        tool_name = str(message.get("tool_name") or "").strip()
        if tool_name not in _DOCUMENT_TOOL_NAMES and not tool_name.startswith(
            "document_"
        ):
            continue
        arguments = _mapping(message.get("tool_arguments")) or {}
        references = list(_payload_references(arguments))
        content = message.get("content")
        if isinstance(content, str) and content.lstrip().startswith("{"):
            try:
                payload = cast(object, json.loads(content))
            except json.JSONDecodeError:
                payload = None
            references.extend(_payload_references(payload))
        label = str(arguments.get("name") or arguments.get("title") or "").strip()
        for reference in dict.fromkeys(references):
            found.append((reference, label, tool_name))
    return tuple(found)


async def recent_conversation_document_context(
    request: AgentContextRequest,
) -> AgentContextContribution:
    """Recall document-bearing history, then recheck current access and metadata."""

    if not request.include_historical_context:
        return AgentContextContribution()
    contact_id = request.contact_memory_item_id
    if contact_id is None or request.frozen_capsule is not None:
        return AgentContextContribution()
    rounds = list(
        (
            await get_db().scalars(
                select(ConversationRound)
                .join(Room, Room.id == ConversationRound.room_id)
                .join(Connection, Connection.id == Room.connection_id)
                .where(
                    Connection.agent_id == request.agent.id,
                    ConversationRound.contact_memory_item_id == contact_id,
                    ConversationRound.execution_result.is_not(None),
                    func.jsonb_path_exists(ConversationRound.execution_result, literal(
                        '$.messages[*] ? (@.type == "tool" && @.success == true && '
                        '(@.tool_name like_regex "^(file_(create|read|info|write|append|edit|copy|move)|document_.*)$") && '
                        '(exists(@.tool_arguments.** ? (@ like_regex "^document://")) || '
                        'exists(@.tool_arguments.document_id) || @.content like_regex "document://|document_id"))', type_=JSONPATH)),
                    Room.deleted_at.is_(None),
                )
                .order_by(
                    ConversationRound.finished_at.desc().nullslast(),
                    ConversationRound.created_at.desc(),
                    ConversationRound.id.desc(),
                )
                .limit(_RECENT_ROUNDS)
            )
        ).all()
    )
    candidates: list[AgentContextCandidate] = []
    seen: set[str] = set()
    readable: dict[UUID, bool] = {}
    for round_ in rounds:
        result = (
            cast(Mapping[str, object], round_.execution_result)
            if isinstance(round_.execution_result, Mapping)
            else None
        )
        for reference, label, operation in conversation_document_references(result, confirmed_only=True):
            if len(seen) >= _DOCUMENT_CANDIDATES:
                break
            if reference in seen:
                continue
            seen.add(reference)
            document_id = UUID(parse_resource_uri(reference).locator.split("/", 1)[0])
            if document_id not in readable:
                readable[document_id] = await can_read_conversation_document(document_id, request.agent.id)
            if not readable[document_id]:
                continue
            candidates.append(
                AgentContextCandidate(
                    key=f"conversation-document:{reference}",
                    kind="resource",
                    reference=reference,
                    title=label or "Recent conversation document",
                    excerpt=f"Last conversation operation: {operation}",
                    occurred_at=round_.finished_at or round_.created_at,
                    base_score=0.95,
                    provenance=(f"galaris://{('voice' if round_.voice_session_id else 'text')}/{round_.id}",),
                    metadata={
                        "resource_type": "memory_document",
                        "last_operation": operation,
                        "source_round_id": str(round_.id),
                        "document_id": str(document_id),
                    },
                )
            )
            if len(seen) >= _DOCUMENT_CANDIDATES:
                break
        if len(seen) >= _DOCUMENT_CANDIDATES:
            break
    metadata = await resolve_conversation_document_metadata(tuple(key for key, allowed in readable.items() if allowed))
    current: list[AgentContextCandidate] = []
    for candidate in candidates:
        document = metadata.get(UUID(str(candidate.metadata["document_id"])))
        if document is None or document.deleted:
            continue
        current.append(candidate.model_copy(update={"title": document.title, "revision": document.revision}))
    return AgentContextContribution(
        candidates=tuple(current),
        metadata={"recent_conversation_document_count": len(current)},
    )


def register_recent_conversation_document_context() -> None:
    from app.agent import register_context_provider

    register_context_provider(
        "conversation_recent_documents",
        recent_conversation_document_context,
        priority=16,
    )


__all__ = [
    "conversation_document_references",
    "recent_conversation_document_context",
    "register_recent_conversation_document_context",
]
