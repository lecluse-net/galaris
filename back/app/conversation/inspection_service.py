"""Complete administrative projection for one canonical conversation round."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from app.agent import Agent
from app.connection import Connection
from app.llm import LLMCall, llm_call_service
from app.messenger import Message, Room
from core.database import get_db

from .models import (
    ConversationProcessLink,
    ConversationRound,
    ConversationRoundAttempt,
    ConversationRoundMessage,
    ConversationTaskLink,
)


def _date(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


async def inspect_round(
    round_id: UUID,
    *,
    actor_agent_id: int | None = None,
) -> dict[str, Any] | None:
    """Return the run, canonical messages, lineage, attempts, and LLM calls."""

    statement = (
        select(ConversationRound, Room, Connection, Agent)
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .join(Agent, Agent.id == Connection.agent_id)
        .where(ConversationRound.id == round_id)
    )
    if actor_agent_id is not None:
        statement = statement.where(Agent.id == actor_agent_id)
    row = (
        await get_db().execute(statement)
    ).one_or_none()
    if row is None:
        return None
    round_, room, _connection, agent = row
    message_rows = (
        await get_db().execute(
            select(ConversationRoundMessage, Message)
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .where(ConversationRoundMessage.round_id == round_id)
            .order_by(
                ConversationRoundMessage.role,
                ConversationRoundMessage.response_sequence.nullsfirst(),
                ConversationRoundMessage.sequence,
                Message.created_at,
            )
        )
    ).all()
    attempts = list(
        (
            await get_db().scalars(
                select(ConversationRoundAttempt)
                .where(ConversationRoundAttempt.round_id == round_id)
                .order_by(ConversationRoundAttempt.attempt_number)
            )
        ).all()
    )
    task_links = list(
        (
            await get_db().scalars(
                select(ConversationTaskLink)
                .where(ConversationTaskLink.round_id == round_id)
                .order_by(ConversationTaskLink.created_at)
            )
        ).all()
    )
    from app.task import list_task_amendments_by_source, task_startup_timings

    task_amendments = await list_task_amendments_by_source(
        (
            f"text:{round_id}",
            f"conversation_round:{round_id}",
        )
    )
    process_links = list(
        (
            await get_db().scalars(
                select(ConversationProcessLink)
                .where(ConversationProcessLink.round_id == round_id)
                .order_by(ConversationProcessLink.created_at)
            )
        ).all()
    )
    calls = list(
        (
            await get_db().scalars(
                select(LLMCall)
                .where(LLMCall.conversation_round_id == round_id)
                .order_by(LLMCall.started_at, LLMCall.id)
            )
        ).all()
    )
    serialized_calls = await llm_call_service.serialize_calls(calls)
    return {
        "task_startup_timings": [item.model_dump(mode="json") for item in
                                 await task_startup_timings([link.task_id for link in task_links], agent_id=agent.id)],
        "round": {
            "id": str(round_.id),
            "room_id": str(room.id),
            "voice_session_id": _uuid(round_.voice_session_id),
            "topic_id": _uuid(round_.topic_id),
            "contact_memory_item_id": _uuid(round_.contact_memory_item_id),
            "language": round_.language,
            "status": round_.status,
            "execution_result": round_.execution_result,
            "delivery_state": round_.delivery_state,
            "effect_started": round_.effect_started,
            "effect_started_at": _date(round_.effect_started_at),
            "lease_token": _uuid(round_.lease_token),
            "lease_owner": round_.lease_owner,
            "lease_expires_at": _date(round_.lease_expires_at),
            "attempt_count": round_.attempt_count,
            "last_error": round_.last_error,
            "created_at": _date(cast(datetime, round_.created_at)),
            "finished_at": _date(round_.finished_at),
        },
        "room": {
            "id": str(room.id),
            "connection_id": room.connection_id,
            "external_id": room.external_id,
            "label": room.label,
            "kind": room.kind,
            "conversation_type": room.conversation_type,
        },
        "agent": {
            "id": agent.id,
            "code": agent.code,
            "first_name": agent.first_name,
            "last_name": agent.last_name,
            "job_title": agent.job_title,
            "personality": agent.personality,
            "job_description": agent.job_description,
            "driver": agent.agent_driver,
        },
        "messages": [
            {
                "id": str(message.id),
                "role": link.role,
                "sequence": link.sequence,
                "response_sequence": link.response_sequence,
                "consumed_at": _date(link.consumed_at),
                "direction": message.direction,
                "platform": message.platform,
                "messenger_user_id": _uuid(message.messenger_user_id),
                "topic_id": _uuid(message.topic_id),
                "contact_memory_item_id": _uuid(message.contact_memory_item_id),
                "text": message.text,
                "status": message.status,
                "created_at": _date(message.created_at),
            }
            for link, message in message_rows
        ],
        "attempts": [
            {
                "id": str(item.id),
                "round_id": str(item.round_id),
                "attempt_number": item.attempt_number,
                "worker_id": item.worker_id,
                "lease_token": str(item.lease_token),
                "status": item.status,
                "error": item.error,
                "started_at": _date(item.started_at),
                "finished_at": _date(item.finished_at),
            }
            for item in attempts
        ],
        "task_links": [
            {
                "id": str(item.id),
                "round_id": str(item.round_id),
                "task_id": str(item.task_id),
                "task_uri": f"galaris://task/{item.task_id}",
                "action_key": item.action_key,
                "notification_state": item.notification_state,
                "notification_message_id": _uuid(item.notification_message_id),
                "notification_task_attempt_count": (
                    item.notification_task_attempt_count
                ),
                "notification_error": item.notification_error,
                "created_at": _date(item.created_at),
            }
            for item in task_links
        ],
        "task_amendments": task_amendments,
        "process_links": [
            {
                "id": str(item.id),
                "round_id": str(item.round_id),
                "process_run_id": str(item.process_run_id),
                "action_key": item.action_key,
                "notification_state": item.notification_state,
                "notification_message_id": _uuid(item.notification_message_id),
                "notification_error": item.notification_error,
                "created_at": _date(item.created_at),
            }
            for item in process_links
        ],
        "llm_calls": [item.model_dump(mode="json") for item in serialized_calls],
    }


__all__ = ["inspect_round"]
