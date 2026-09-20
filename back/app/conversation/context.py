"""Contact-scoped document continuity recovered from completed conversation rounds."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import select

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


_RECENT_ROUNDS = 20
_RECENT_DOCUMENTS = 10
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
    """Offer recent direct-conversation documents to every contact-scoped runtime."""

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
    for round_ in rounds:
        result = (
            cast(Mapping[str, object], round_.execution_result)
            if isinstance(round_.execution_result, Mapping)
            else None
        )
        for reference, label, operation in conversation_document_references(result):
            if reference in seen:
                continue
            seen.add(reference)
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
                    },
                )
            )
            if len(candidates) >= _RECENT_DOCUMENTS:
                return AgentContextContribution(
                    candidates=tuple(candidates),
                    metadata={"recent_conversation_document_count": len(candidates)},
                )
    return AgentContextContribution(
        candidates=tuple(candidates),
        metadata={"recent_conversation_document_count": len(candidates)},
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
