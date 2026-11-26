"""Durable state transitions for live voice sessions and canonical rounds."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from datetime import datetime, timezone
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.conversation import (
    LEASE_SECONDS, VOICE_LEASE_PREFIX, ConversationLeaseLostError, ConversationRound, ConversationRoundMessage,
    open_round_attempt, release_round_attempt, renew_round_lease,
)
from core import websocket
from core.database import get_db

from .models import VoiceConversationSession, VoiceConversationStatus, VoiceTurnStatus


@asynccontextmanager
async def keep_turn_lease(round_id: UUID, lease_token: UUID | None) -> AsyncGenerator[None]:
    """Keep the live transport's claim through model preparation and streaming."""
    if lease_token is None:
        yield
        return
    from core.database import get_db_session

    owner = asyncio.current_task()
    if owner is None:
        raise RuntimeError("Voice inference requires a live asyncio task.")
    lease_lost = False

    async def renew() -> None:
        nonlocal lease_lost
        while True:
            await asyncio.sleep(LEASE_SECONDS / 6)
            try:
                async with get_db_session():
                    renewed = await renew_round_lease(round_id, lease_token)
            except Exception:
                renewed = False
            if not renewed:
                lease_lost = True
                logger.warning("Voice round {} lost its execution lease.", round_id)
                owner.cancel()
                return

    heartbeat = asyncio.create_task(renew(), name=f"voice-round-lease:{round_id}")
    try:
        yield
    except asyncio.CancelledError:
        if lease_lost:
            raise ConversationLeaseLostError(f"Voice round lease lost for {round_id}") from None
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def save_turn_checkpoint(turn_id: UUID, checkpoint: Any) -> None:
    from core.database import get_db_session
    from core.util import get_encryption_service
    from app.services.facade import canonical_authorization_snapshot

    async with get_db_session() as db:
        round_ = await db.scalar(
            select(ConversationRound)
            .where(ConversationRound.id == turn_id, ConversationRound.voice_session_id.is_not(None))
            .with_for_update()
        )
        if round_ is None or round_.status not in ("RUNNING", "WAITING_APPROVAL"):
            raise PermissionError("The voice round is no longer owned by its runtime")
        round_.encrypted_checkpoint = get_encryption_service().encrypt(
            canonical_authorization_snapshot(checkpoint)
        )
        await db.commit()


_TERMINAL_ROUND_STATUSES = {
    VoiceTurnStatus.COMPLETED.value,
    VoiceTurnStatus.INTERRUPTED.value,
    VoiceTurnStatus.FAILED.value,
    "CANCELLED",
}


async def _authorization_context_snapshot(agent_id: int, context_key: str) -> dict[str, Any] | None:
    try:
        _, session_key, _, round_key = context_key.split(":")
        session = await get_db().get(
            VoiceConversationSession, UUID(session_key), populate_existing=True
        )
    except ValueError:
        return None
    if session is None or session.status != VoiceConversationStatus.ACTIVE.value:
        return None
    _, owner_agent, _ = await message_context(session)
    if owner_agent != agent_id:
        return None
    if round_key != "None":
        round_ = await get_db().get(ConversationRound, UUID(round_key), populate_existing=True)
        if (
            round_ is None
            or round_.voice_session_id != session.id
            or round_.status
            in (
                _TERMINAL_ROUND_STATUSES
                | {"CANCELLED", "SUPERSEDED", "SUCCEEDED", "ERROR_RESOLVED"}
            )
        ):
            return None
    return {"session": str(session.id), "round": round_key, "sequence": session.next_sequence}


async def _wake_authorization_context(agent_id: int, context_key: str) -> bool:
    if not context_key.startswith("voice:"):
        return False
    from app.services.facade import authorization_context_pending, invalidate_authorization_context
    from core.database import get_db_session
    from app.conversation import wake

    async with get_db_session() as db:
        if await _authorization_context_snapshot(agent_id, context_key) is None:
            await invalidate_authorization_context(agent_id, context_key)
            return True
        round_key = context_key.split(":")[-1]
        if round_key == "None":
            return True
        round_ = await db.scalar(
            select(ConversationRound)
            .where(ConversationRound.id == UUID(round_key))
            .with_for_update()
        )
        if round_ is not None and round_.status in ("CLAIMED", "RUNNING"):
            # Human decisions can arrive before the runtime persists its suspension.
            # Keep the outbox wake until that owner has released the turn.
            return False
        if round_ is None or round_.status != "WAITING_APPROVAL":
            return True  # A live realtime SDK owns its callback and polls without a Task lease.
        if await authorization_context_pending(agent_id, context_key):
            return False
        round_.status = "FROZEN"
        await db.commit()
    wake()
    return True


from app.services.facade import register_authorization_context_guard, register_authorization_waker

register_authorization_context_guard("voice", _authorization_context_snapshot)
register_authorization_waker("voice", _wake_authorization_context)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _combine_objective(pending: str | None, transcript: str) -> str:
    parts = [part.strip() for part in (pending, transcript) if part and part.strip()]
    return "\n".join(parts)


async def publish_session(
    action: str,
    session_id: UUID,
    *,
    status: str | None = None,
) -> None:
    """Notify authorized monitoring clients without exposing transcript contents."""

    payload = {"id": str(session_id)}
    if status is not None:
        payload["status"] = status
    await websocket.emit("voice_conversation", action, payload, None)


async def _publish_round_activity(round_id: UUID) -> None:
    """Refresh conversation projections without coupling Voice to the Chat UI."""

    from app.conversation import publish_round_activity

    await publish_round_activity(round_id)


async def start_session(
    *,
    agent_id: int,
    connection_id: int,
    transport_kind: str,
    room_id: str,
    language: str,
    contact_memory_item_id: UUID | None = None,
    call_external_id: str | None = None,
    participant_external_ids: tuple[str, ...] = (),
    conversation_room_id: UUID | None = None,
) -> VoiceConversationSession:
    """Create one live call in an existing conversation or a dedicated audio room."""

    del language, contact_memory_item_id
    session_id = uuid4()
    from app.agent import get_agent_record
    from app.messenger import open_audio_room

    agent = await get_agent_record(agent_id)
    agent_display_name = (
        f"{agent.first_name} {agent.last_name}".strip() if agent is not None else ""
    )
    messenger_room_id = conversation_room_id
    if messenger_room_id is not None:
        from app.connection import Connection
        from app.messenger import Room

        valid_room_id = await get_db().scalar(
            select(Room.id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(
                Room.id == messenger_room_id,
                Room.connection_id == connection_id,
                Connection.agent_id == agent_id,
            )
        )
        if valid_room_id is None:
            raise LookupError(
                f"Messenger conversation room {messenger_room_id} is outside the call scope."
            )
    else:
        messenger_room_id = await open_audio_room(
            connection_id=connection_id,
            transport_kind=transport_kind,
            source_room_id=room_id,
            call_external_id=(call_external_id or f"galaris:{session_id}"),
            agent_id=agent_id,
            participant_external_ids=participant_external_ids,
            agent_display_name=agent_display_name,
        )
    from app.messenger import MessengerUser, RoomUser

    human_requesters = list(
        (
            await get_db().scalars(
                select(MessengerUser.galaris_user_id)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(RoomUser.room_id == messenger_room_id, MessengerUser.is_ai.is_(False))
                .distinct()
            )
        ).all()
    )
    requester_user_id = (
        human_requesters[0]
        if len(human_requesters) == 1 and human_requesters[0] is not None
        else None
    )
    session = VoiceConversationSession(
        id=session_id,
        messenger_room_id=messenger_room_id,
        status=VoiceConversationStatus.ACTIVE.value,
        started_at=_now(),
        requester_user_id=requester_user_id,
    )
    db = get_db()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    await publish_session("create", session.id, status=session.status)
    return session


async def message_context(
    session: VoiceConversationSession,
) -> tuple[int, int, UUID]:
    from app.connection import Connection
    from app.messenger import Room

    row = (
        await get_db().execute(
            select(Room.connection_id, Connection.agent_id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(Room.id == session.messenger_room_id)
            .execution_options(include_historized=True)
        )
    ).one_or_none()
    if row is None:
        raise LookupError(f"Messenger audio room {session.messenger_room_id} not found.")
    return int(row.connection_id), int(row.agent_id), session.messenger_room_id


async def _record_message(
    *,
    session: VoiceConversationSession,
    round_: ConversationRound | None,
    role: str,
    text: str,
    response_sequence: int | None,
    sequence: int,
    occurred_at: datetime | None,
) -> UUID:
    context = await message_context(session)
    connection_id, agent_id, messenger_room_id = context
    from app.messenger import record_audio_message

    scope = (
        f"round:{round_.id}:{role}:{response_sequence or 0}:{sequence}"
        if round_ is not None
        else f"session:{role}:{sequence}"
    )
    message = await record_audio_message(
        connection_id=connection_id,
        messenger_room_id=messenger_room_id,
        agent_id=agent_id,
        external_identifier=f"voice:{session.id}:{scope}",
        role="input" if role == "input" else "output",
        text=text,
        occurred_at=occurred_at,
        contact_memory_item_id=(round_.contact_memory_item_id if round_ is not None else None),
    )
    if round_ is not None:
        if role == "input" and round_.topic_id is not None:
            from app.messenger import Message

            await get_db().execute(
                update(Message)
                .where(
                    Message.id == message.id,
                    Message.topic_id.is_(None),
                    Message.topic_overridden.is_(False),
                )
                .values(topic_id=round_.topic_id)
            )
        await get_db().execute(
            pg_insert(ConversationRoundMessage)
            .values(
                round_id=round_.id,
                message_id=message.id,
                role=role,
                response_sequence=response_sequence,
                sequence=sequence,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ConversationRoundMessage.round_id,
                    ConversationRoundMessage.message_id,
                ]
            )
        )
    return message.id


async def record_initial_greeting(
    session_id: UUID,
    text: str,
    *,
    occurred_at: datetime | None = None,
) -> UUID:
    """Persist the agent's greeting in the call room without inventing a round."""

    session = await get_db().get(VoiceConversationSession, session_id)
    if session is None:
        raise LookupError(f"Voice session {session_id} not found.")
    message_id = await _record_message(
        session=session,
        round_=None,
        role="output",
        text=text,
        response_sequence=1,
        sequence=1,
        occurred_at=occurred_at,
    )
    await get_db().commit()
    return message_id


async def _round_and_session(
    round_id: UUID,
) -> tuple[ConversationRound, VoiceConversationSession]:
    db = get_db()
    session_id = await db.scalar(
        select(ConversationRound.voice_session_id).where(
            ConversationRound.id == round_id,
        )
    )
    if session_id is None:
        raise LookupError(f"Voice conversation round {round_id} not found.")
    # Use the same session -> round lock order as deletion and admission.
    session = await db.scalar(
        select(VoiceConversationSession)
        .where(
            VoiceConversationSession.id == session_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    round_ = await db.scalar(
        select(ConversationRound)
        .where(
            ConversationRound.id == round_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if round_ is None or session is None:
        raise LookupError(f"Voice conversation round {round_id} not found.")
    if (
        round_.status in _TERMINAL_ROUND_STATUSES
        or session.status != VoiceConversationStatus.ACTIVE.value
    ):
        raise PermissionError("The voice round was administratively cancelled")
    return round_, session


async def record_turn_input(
    turn_id: UUID,
    text: str,
    *,
    occurred_at: datetime | None = None,
) -> UUID:
    """Persist one user utterance and link it to its canonical round."""

    round_, session = await _round_and_session(turn_id)
    message_id = await _record_message(
        session=session,
        round_=round_,
        role="input",
        text=text,
        response_sequence=None,
        sequence=1,
        occurred_at=occurred_at,
    )
    from app.conversation.facade import inherit_reply_topics

    await inherit_reply_topics(round_.id)
    await get_db().commit()
    return message_id


async def record_turn_outputs(
    turn_id: UUID,
    messages: Sequence[str],
    *,
    response_sequence: int = 1,
    occurred_at: datetime | None = None,
) -> tuple[UUID, ...]:
    """Persist every distinct agent message emitted for one response."""

    round_, session = await _round_and_session(turn_id)
    message_ids: list[UUID] = []
    for sequence, text in enumerate(messages, start=1):
        message_id = await _record_message(
            session=session,
            round_=round_,
            role="output",
            text=text,
            response_sequence=response_sequence,
            sequence=sequence,
            occurred_at=occurred_at,
        )
        message_ids.append(message_id)
    from app.conversation.facade import inherit_reply_topics

    await inherit_reply_topics(round_.id)
    await get_db().commit()
    return tuple(message_ids)


async def finish_session(
    session_id: UUID,
    status: VoiceConversationStatus,
    *,
    error: str | None = None,
) -> None:
    """Close a call and retire orphan execution, preserving terminal session history."""

    db = get_db()
    session = await db.scalar(
        select(VoiceConversationSession)
        .where(VoiceConversationSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        return
    if session.status == VoiceConversationStatus.ACTIVE.value:
        session.status = status.value
        session.error = (error or "").strip()[:4000] or None
        session.finished_at = _now()
    # A transport ending must not leave a direct runtime round looking active.
    active_rounds = list(
        (
            await db.scalars(
                select(ConversationRound)
                .where(
                    ConversationRound.voice_session_id == session_id,
                    ConversationRound.status.in_(
                        ("RUNNING", "CLAIMED", "WAITING_APPROVAL", "FROZEN")
                    ),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    from app.services.facade import invalidate_authorization_context

    _, owner_agent, _ = await message_context(session)
    for active_round in active_rounds:
        active_round.status = VoiceTurnStatus.INTERRUPTED.value
        active_round.finished_at = session.finished_at
        active_round.interrupted_at = session.finished_at
        if not active_round.effect_started:
            active_round.encrypted_checkpoint = None
        await release_round_attempt(active_round, "INTERRUPTED")
        await invalidate_authorization_context(
            owner_agent, f"voice:{session.id}:round:{active_round.id}"
        )
        await invalidate_authorization_context(owner_agent, f"round:{active_round.id}")
    await db.commit()
    await publish_session("update", session.id, status=session.status)


async def _pending_round(session_id: UUID) -> ConversationRound | None:
    return await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.voice_session_id == session_id,
            ConversationRound.status.in_(
                (VoiceTurnStatus.INTERRUPTED.value, VoiceTurnStatus.FAILED.value)
            ),
            ConversationRound.resolved_by_round_id.is_(None),
            ConversationRound.effective_objective.is_not(None),
            ConversationRound.effect_started.is_(False),
        )
        .order_by(ConversationRound.sequence.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def start_turn(
    *,
    session_id: UUID,
    transcript: str,
    run_id: UUID,
    language: str = "fr",
    topic_id: UUID | None = None,
    contact_memory_item_id: UUID | None = None,
) -> ConversationRound:
    """Start a round and fold any unresolved objective into the new input."""

    normalized = transcript.strip()
    if not normalized:
        raise ValueError("voice transcript must not be empty")

    db = get_db()
    session = await db.scalar(
        select(VoiceConversationSession)
        .where(VoiceConversationSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        raise LookupError(f"Voice session {session_id} not found.")
    if session.status != VoiceConversationStatus.ACTIVE.value:
        raise RuntimeError(f"Voice session {session_id} is not active.")

    from app.agent import conversation_driver_for_agent
    from app.services.facade import invalidate_authorization_context

    _, owner_agent, _ = await message_context(session)
    driver_code = await conversation_driver_for_agent(owner_agent)
    previous_status: ColumnElement[bool] = ConversationRound.status == "WAITING_APPROVAL"
    if driver_code == "claude_embedded":
        previous_status = or_(previous_status, and_(
            ConversationRound.driver_code == "claude_embedded",
            ConversationRound.status.in_(("RUNNING", "CLAIMED", "FROZEN")),
        ))
    waiting = list(
        (
            await db.scalars(
                select(ConversationRound)
                .where(
                    ConversationRound.voice_session_id == session.id,
                    previous_status,
                )
                .with_for_update()
            )
        ).all()
    )
    for previous in waiting:
        await invalidate_authorization_context(
            owner_agent, f"voice:{session.id}:round:{previous.id}"
        )
        previous.status = VoiceTurnStatus.INTERRUPTED.value
        previous.finished_at = previous.interrupted_at = _now()
        if not previous.effect_started:
            previous.encrypted_checkpoint = None
        await release_round_attempt(previous, "INTERRUPTED")
    source = await _pending_round(session.id)
    round_ = ConversationRound(
        id=run_id,
        room_id=session.messenger_room_id,
        voice_session_id=session.id,
        sequence=session.next_sequence,
        language=language,
        driver_code=driver_code,
        source_round_id=source.id if source is not None else None,
        effective_objective=_combine_objective(
            source.effective_objective if source is not None else None,
            normalized,
        ),
        topic_id=topic_id,
        contact_memory_item_id=contact_memory_item_id,
        requester_user_id=session.requester_user_id,
        status=VoiceTurnStatus.RUNNING.value,
        created_at=_now(),
    )
    session.next_sequence += 1
    db.add(round_)
    await db.flush()
    if driver_code == "claude_embedded":
        open_round_attempt(round_, f"{VOICE_LEASE_PREFIX}{session.id}")
    if source is not None:
        source.resolved_by_round_id = round_.id

    await db.commit()
    await db.refresh(round_)
    await publish_session("update", session.id, status=session.status)
    await _publish_round_activity(round_.id)
    return round_


async def start_audio_turn(
    *,
    session_id: UUID,
    run_id: UUID,
    language: str = "fr",
    topic_id: UUID | None = None,
    contact_memory_item_id: UUID | None = None,
) -> ConversationRound:
    """Start a native-audio round without inventing a transcript."""

    db = get_db()
    session = await db.scalar(
        select(VoiceConversationSession)
        .where(VoiceConversationSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        raise LookupError(f"Voice session {session_id} not found.")
    if session.status != VoiceConversationStatus.ACTIVE.value:
        raise RuntimeError(f"Voice session {session_id} is not active.")

    round_ = ConversationRound(
        id=run_id,
        room_id=session.messenger_room_id,
        voice_session_id=session.id,
        sequence=session.next_sequence,
        language=language,
        topic_id=topic_id,
        contact_memory_item_id=contact_memory_item_id,
        requester_user_id=session.requester_user_id,
        status=VoiceTurnStatus.RUNNING.value,
        created_at=_now(),
    )
    session.next_sequence += 1
    db.add(round_)
    await db.commit()
    await db.refresh(round_)
    await publish_session("update", session.id, status=session.status)
    await _publish_round_activity(round_.id)
    return round_


async def complete_turn(
    turn_id: UUID,
    *,
    assistant_response: str,
    execution_result: dict[str, object] | None = None,
    first_text_at: datetime | None = None,
    first_audio_at: datetime | None = None,
) -> None:
    """Complete a round after its output messages have been persisted."""

    del assistant_response
    if execution_result and execution_result.get("disposition") == "waiting_for_authorization":
        round_ = await get_db().scalar(
            select(ConversationRound)
            .where(ConversationRound.id == turn_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if round_ is not None and round_.status == "RUNNING":
            round_.status = VoiceTurnStatus.WAITING_APPROVAL.value
            round_.execution_result = execution_result
            await release_round_attempt(round_, "WAITING_APPROVAL")
            await get_db().commit()
            await _publish_round_activity(round_.id)
        return
    await _finish_turn(
        turn_id,
        status=VoiceTurnStatus.COMPLETED,
        execution_result=execution_result,
        first_text_at=first_text_at,
        first_audio_at=first_audio_at,
    )


async def interrupt_turn(
    turn_id: UUID,
    *,
    assistant_response: str | None = None,
    execution_result: dict[str, object] | None = None,
    first_text_at: datetime | None = None,
    first_audio_at: datetime | None = None,
) -> None:
    """Mark a barged-in response and retain its objective for the successor."""

    del assistant_response
    await _finish_turn(
        turn_id,
        status=VoiceTurnStatus.INTERRUPTED,
        execution_result=execution_result,
        first_text_at=first_text_at,
        first_audio_at=first_audio_at,
    )


async def fail_turn(
    turn_id: UUID,
    *,
    error: str,
    assistant_response: str | None = None,
    execution_result: dict[str, object] | None = None,
    first_text_at: datetime | None = None,
    first_audio_at: datetime | None = None,
) -> None:
    """Record a technical failure while keeping the objective resumable."""

    del assistant_response
    await _finish_turn(
        turn_id,
        status=VoiceTurnStatus.FAILED,
        execution_result=execution_result,
        error=error,
        first_text_at=first_text_at,
        first_audio_at=first_audio_at,
    )


async def _finish_turn(
    turn_id: UUID,
    *,
    status: VoiceTurnStatus,
    execution_result: dict[str, object] | None,
    error: str | None = None,
    first_text_at: datetime | None,
    first_audio_at: datetime | None,
) -> None:
    db = get_db()
    round_ = await db.scalar(
        select(ConversationRound)
        .where(
            ConversationRound.id == turn_id,
            ConversationRound.voice_session_id.is_not(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if round_ is None or round_.status in _TERMINAL_ROUND_STATUSES:
        return

    finished_at = _now()
    round_.status = status.value
    if status == VoiceTurnStatus.COMPLETED or not round_.effect_started:
        round_.encrypted_checkpoint = None
    round_.execution_result = execution_result
    round_.last_error = (error or "").strip()[:4000] or None
    round_.first_text_at = first_text_at
    round_.first_audio_at = first_audio_at
    round_.finished_at = finished_at
    await release_round_attempt(round_, {
        VoiceTurnStatus.COMPLETED: "SUCCESS",
        VoiceTurnStatus.INTERRUPTED: "INTERRUPTED",
        VoiceTurnStatus.FAILED: "ERROR",
    }[status], round_.last_error)
    if status == VoiceTurnStatus.INTERRUPTED:
        round_.interrupted_at = finished_at
    if status == VoiceTurnStatus.COMPLETED:
        await db.execute(
            update(ConversationRoundMessage)
            .where(
                ConversationRoundMessage.round_id == round_.id,
                ConversationRoundMessage.role == "input",
                ConversationRoundMessage.consumed_at.is_(None),
            )
            .values(consumed_at=finished_at)
        )

    session_id = round_.voice_session_id
    assert session_id is not None
    session = await db.get(VoiceConversationSession, session_id)
    session_status = session.status if session is not None else None
    await db.commit()
    await publish_session("update", session_id, status=session_status)
    await _publish_round_activity(round_.id)
