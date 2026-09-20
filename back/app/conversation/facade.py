"""Public admission and runtime facade for conversation transports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from loguru import logger
from sqlalchemy import Select, select

from core.database import get_db, get_db_session
from app.messenger import Message

from .contracts import ConversationRuntimeEvent


ConversationActivityListener = Callable[[UUID, UUID], Awaitable[None]]
ConversationRuntimeListener = Callable[
    [UUID, ConversationRuntimeEvent], Awaitable[None]
]
_activity_listeners: set[ConversationActivityListener] = set()
_runtime_listeners: set[ConversationRuntimeListener] = set()


async def admit_messenger_input(
    message: Message,
    *,
    agent_id: int,
    connection_id: int,
    language: str | None = None,
) -> bool:
    """Persist one human input and wake its independent scheduler."""

    from .service import admit_message

    admitted = await admit_message(
        message,
        agent_id=agent_id,
        connection_id=connection_id,
        language=language,
    )
    if admitted:
        wake()
    return admitted


def register_runtime() -> None:
    """Initialize the conversation runtime after every dependent module is loaded.

    Background Tasks retain their normal Messenger contract and therefore publish their own
    progress, questions, approvals, planner messages, and terminal result. Conversation keeps
    lineage for status inspection but must not proxy or duplicate Task output.
    """
    from app.process import register_retention_guard
    from app.llm import register_trace_release

    register_retention_guard("conversation", _process_results_still_needed)
    register_trace_release("conversation_round", _released_trace_ids)


def _released_trace_ids() -> Select[tuple[UUID]]:
    from .models import ConversationRound, ConversationTaskLink, ConversationProcessLink
    from .service import TERMINAL_ROUND_STATUSES
    from app.task import protected_task_ids

    pending_tasks = select(ConversationTaskLink.round_id).where(
        (ConversationTaskLink.notification_state.not_in(("DELIVERED", "SKIPPED")))
        | ConversationTaskLink.task_id.in_(protected_task_ids())
    )
    pending_processes = select(ConversationProcessLink.round_id).where(
        ConversationProcessLink.notification_state.not_in(("DELIVERED", "SKIPPED"))
    )
    return select(ConversationRound.id).where(
        ConversationRound.status.in_(TERMINAL_ROUND_STATUSES),
        ConversationRound.finished_at.is_not(None),
        ConversationRound.delivery_state.in_(("DELIVERED", "SKIPPED")),
        ConversationRound.id.not_in(pending_tasks),
        ConversationRound.id.not_in(pending_processes),
    )


def _process_results_still_needed() -> Select[tuple[UUID]]:
    from .models import ConversationProcessLink

    return select(ConversationProcessLink.process_run_id).where(
        ConversationProcessLink.notification_state.not_in(("DELIVERED", "SKIPPED")),
    )


def wake() -> None:
    from . import scheduler

    scheduler.wake()


def register_activity_listener(listener: ConversationActivityListener) -> None:
    """Subscribe an application adapter to sanitized round refresh signals."""

    _activity_listeners.add(listener)


def register_runtime_listener(listener: ConversationRuntimeListener) -> None:
    """Subscribe an adapter to the bounded ephemeral round stream."""

    _runtime_listeners.add(listener)


async def publish_runtime_event(
    room_id: UUID,
    event: ConversationRuntimeEvent,
) -> None:
    """Publish one safe live event without reopening the durable round."""

    for listener in tuple(_runtime_listeners):
        try:
            async with asyncio.timeout(2.0):
                await listener(room_id, event)
        except Exception:
            logger.exception(
                "Conversation runtime listener failed round={} room={} kind={}",
                event.round_id,
                room_id,
                event.kind,
            )


async def publish_round_activity(round_id: UUID) -> None:
    """Notify adapters after a durable transition, without exposing execution data."""

    from .models import ConversationRound

    async with get_db_session():
        room_id = await get_db().scalar(
            select(ConversationRound.room_id).where(ConversationRound.id == round_id)
        )
    if room_id is None:
        return
    for listener in tuple(_activity_listeners):
        try:
            await listener(round_id, room_id)
        except Exception:
            logger.exception(
                "Conversation activity listener failed round={} room={}",
                round_id,
                room_id,
            )


__all__ = [
    "ConversationActivityListener",
    "ConversationRuntimeListener",
    "admit_messenger_input",
    "publish_round_activity",
    "publish_runtime_event",
    "register_activity_listener",
    "register_runtime_listener",
    "register_runtime",
    "wake",
]
