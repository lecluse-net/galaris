"""Public, sanitized room-activity projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy import func, select

from core.database import get_db

from .contracts import (
    ConversationActivity,
    ConversationActivityDetail,
    ConversationActivityInteraction,
    ConversationActivityPage,
)
from .models import (
    ConversationProcessLink,
    ConversationRound,
    ConversationRoundMessage,
)
from .trace_projection import public_mapping, public_number, public_text
from .runtime import room_runtime_snapshot


def _tools(result: Mapping[str, object]) -> list[str]:
    raw_tools = result.get("tools_used")
    if not isinstance(raw_tools, list):
        return []
    return [str(item)[:200] for item in cast(list[object], raw_tools)[:100]]


def _interactions(result: Mapping[str, object]) -> list[ConversationActivityInteraction]:
    raw_messages = result.get("messages")
    if not isinstance(raw_messages, list):
        raw_messages = []
    interactions: list[ConversationActivityInteraction] = []
    for index, raw_message in enumerate(cast(list[object], raw_messages)[:500]):
        if not isinstance(raw_message, Mapping):
            continue
        message = cast(Mapping[str, object], raw_message)
        message_type = str(message.get("type") or "")
        tool_name = str(message.get("tool_name") or "")[:200] or None
        success = message.get("success") is not False
        if message_type != "tool":
            # Only the confirmed terminal answer is projected below. Intermediate
            # narration can be rejected after a tool call or corrective retry.
            continue
        thinking = tool_name == "thinking"
        interactions.append(
            ConversationActivityInteraction(
                sequence=index,
                kind="thinking" if thinking else "tool_call",
                content=(
                    public_text(message.get("content"), limit=40_000)
                ),
                tool_name=tool_name,
                arguments=(
                    {} if thinking else public_mapping(message.get("tool_arguments"))
                ),
                result=(
                    {} if thinking else public_mapping(message.get("tool_result"))
                ),
                success=success,
                execution_time=public_number(message.get("execution_time")),
                cost=public_number(message.get("cost")),
            )
        )
    final_text = public_text(result.get("result"), limit=100_000).strip()
    if final_text:
        interactions.append(
            ConversationActivityInteraction(
                sequence=len(interactions),
                kind="ai_message",
                content=final_text,
                success=result.get("success") is not False,
            )
        )
    error = ""
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        safe_metadata = cast(Mapping[str, object], metadata)
        error = public_text(safe_metadata.get("error"), limit=10_000).strip()
    if error:
        interactions.append(
            ConversationActivityInteraction(
                sequence=len(interactions),
                kind="error",
                content=error,
                success=False,
            )
        )
    return interactions


async def list_room_activity(
    room_id: UUID, *, page: int = 1, page_size: int = 50
) -> ConversationActivityPage:
    total = int(
        await get_db().scalar(
            select(func.count(ConversationRound.id)).where(
                ConversationRound.room_id == room_id
            )
        )
        or 0
    )
    rows = list(
        (
            await get_db().scalars(
                select(ConversationRound)
                .where(ConversationRound.room_id == room_id)
                .order_by(ConversationRound.created_at.desc(), ConversationRound.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    process_round_ids: set[UUID] = set(
        (
            await get_db().scalars(
                select(ConversationProcessLink.round_id).where(
                    ConversationProcessLink.round_id.in_([row.id for row in rows])
                )
            )
        ).all()
    ) if rows else set()
    response_message_ids: dict[UUID, UUID] = {}
    message_ids_by_round: dict[UUID, list[UUID]] = {}
    if rows:
        message_rows = (
            await get_db().execute(
                select(
                    ConversationRoundMessage.round_id,
                    ConversationRoundMessage.message_id,
                    ConversationRoundMessage.role,
                )
                .where(
                    ConversationRoundMessage.round_id.in_([row.id for row in rows]),
                )
                .order_by(
                    ConversationRoundMessage.round_id,
                    ConversationRoundMessage.response_sequence,
                    ConversationRoundMessage.sequence,
                )
            )
        ).all()
        for message_round_id, message_id, role in message_rows:
            message_ids_by_round.setdefault(message_round_id, []).append(message_id)
            if role == "output":
                response_message_ids[message_round_id] = message_id
    items: list[ConversationActivity] = []
    for row in rows:
        result: Mapping[str, object]
        if isinstance(row.execution_result, Mapping):
            result = cast(Mapping[str, object], row.execution_result)
        else:
            result = {}
        items.append(
            ConversationActivity(
                id=row.id,
                response_message_id=response_message_ids.get(row.id),
                message_ids=message_ids_by_round.get(row.id, []),
                topic_id=row.topic_id,
                status=row.status,
                effect_started=row.effect_started,
                tools_used=_tools(result),
                execution_time=public_number(result.get("execution_time")),
                cost=public_number(result.get("cost")),
                process_started=row.id in process_round_ids,
                created_at=row.created_at,
                finished_at=row.finished_at,
            )
        )
    return ConversationActivityPage(
        items=items, total=total, page=page, page_size=page_size,
        runtime=room_runtime_snapshot(room_id),
    )


async def get_room_activity_detail(
    room_id: UUID, round_id: UUID
) -> ConversationActivityDetail | None:
    row = await get_db().scalar(
        select(ConversationRound).where(
            ConversationRound.id == round_id,
            ConversationRound.room_id == room_id,
        )
    )
    if row is None:
        return None
    result: Mapping[str, object]
    if isinstance(row.execution_result, Mapping):
        result = cast(Mapping[str, object], row.execution_result)
    else:
        result = {}
    interactions = _interactions(result)
    if row.last_error and not any(item.kind == "error" for item in interactions):
        interactions.append(
            ConversationActivityInteraction(
                sequence=len(interactions),
                kind="error",
                content=public_text(row.last_error, limit=10_000),
                success=False,
            )
        )
    return ConversationActivityDetail(
        id=row.id,
        status=row.status,
        success=(
            result.get("success") is not False
            and row.status not in {"FAILED", "ERROR_RESOLVED", "CANCELLED"}
        ),
        execution_time=public_number(result.get("execution_time")),
        cost=public_number(result.get("cost")),
        result=public_text(result.get("result"), limit=100_000),
        tools_used=_tools(result),
        interactions=interactions,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


__all__ = ["get_room_activity_detail", "list_room_activity"]
