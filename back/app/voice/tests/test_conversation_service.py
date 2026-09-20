from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.conversation import ConversationRound, ConversationRoundMessage
from app.messenger import voice_journal
from app.messenger.models import (
    ConversationType,
    Message,
    MessengerUser,
    Room,
    RoomUser,
)
from app.tools.models import Tool
from app.voice import conversation_service
from app.voice.models import (
    VoiceConversationSession,
    VoiceConversationStatus,
    VoiceTurnStatus,
)
from core import websocket


async def _agent_id(db: AsyncSession) -> int:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Voice {suffix}", gender="F")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Voice",
        last_name="Tester",
        code=f"voice-tester-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    return agent.id


async def _messenger_connection(
    db: AsyncSession,
    *,
    agent_id: int,
) -> Connection:
    suffix = uuid4().hex[:10]
    tool = Tool(
        code=f"voice-messenger-{suffix}",
        label="Voice Messenger test",
        description="",
        connection_schema={},
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent_id, active=True)
    db.add(connection)
    await db.flush()
    return connection


async def _start_test_session(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_id: int,
    room_id: str,
) -> VoiceConversationSession:
    connection = await _messenger_connection(db, agent_id=agent_id)
    monkeypatch.setattr(
        voice_journal,
        "get_messenger",
        AsyncMock(
            return_value=SimpleNamespace(
                tool_id=connection.tool_id,
                self_id="voice-agent",
                kind="test",
            )
        ),
    )
    return await conversation_service.start_session(
        agent_id=agent_id,
        connection_id=connection.id,
        transport_kind="test",
        room_id=room_id,
        language="fr",
    )


@pytest.mark.asyncio
async def test_audio_call_is_journaled_as_distinct_canonical_messages(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = await _agent_id(db)
    connection = await _messenger_connection(db, agent_id=agent_id)
    messenger = SimpleNamespace(
        tool_id=connection.tool_id,
        self_id="voice-agent",
        kind="nextcloud_talk",
    )
    monkeypatch.setattr(
        voice_journal,
        "get_messenger",
        AsyncMock(return_value=messenger),
    )
    known_caller = MessengerUser(
        tool_id=connection.tool_id,
        external_id="caller-42",
        display_name="Nicolas",
        is_ai=False,
    )
    db.add(known_caller)
    await db.flush()

    session = await conversation_service.start_session(
        agent_id=agent_id,
        connection_id=connection.id,
        transport_kind="nextcloud_talk",
        room_id="talk-room",
        language="fr",
        call_external_id="call-123",
        participant_external_ids=("caller-42",),
    )
    assert session.messenger_room_id is not None
    messenger_room_id = session.messenger_room_id
    room = await db.get(Room, messenger_room_id)
    assert room is not None
    assert room.external_id == "nextcloud_talk:call:call-123"
    assert room.conversation_type == ConversationType.AUDIO.value
    members = list(
        (
            await db.scalars(
                select(MessengerUser)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(RoomUser.room_id == messenger_room_id)
            )
        ).all()
    )
    assert {(member.external_id, member.display_name) for member in members} == {
        ("voice-agent", "Voice Tester"),
        ("caller-42", "Nicolas"),
    }

    await conversation_service.record_initial_greeting(
        session.id,
        "Bonjour, je vous écoute.",
    )
    turn = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Bonjour Dream.",
        run_id=uuid4(),
    )
    assert turn.room_id == messenger_room_id
    await conversation_service.record_turn_input(turn.id, "Bonjour Dream.")
    await conversation_service.record_turn_outputs(
        turn.id,
        ("Bonjour. ", "Que puis-je faire pour vous ?"),
    )
    # Retries update the same local rows and links instead of duplicating them.
    await conversation_service.record_turn_input(turn.id, "Bonjour Dream.")
    await conversation_service.record_turn_outputs(
        turn.id,
        ("Bonjour. ", "Que puis-je faire pour vous ?"),
    )

    messages = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.messenger_room_id == messenger_room_id)
                .order_by(Message.created_at, Message.id)
            )
        ).all()
    )
    assert {(message.direction, message.text) for message in messages} == {
        ("outbound", "Bonjour, je vous écoute."),
        ("inbound", "Bonjour Dream."),
        ("outbound", "Bonjour. "),
        ("outbound", "Que puis-je faire pour vous ?"),
    }
    links = list(
        (
            await db.scalars(
                select(ConversationRoundMessage)
                .where(ConversationRoundMessage.round_id == turn.id)
                .order_by(
                    ConversationRoundMessage.role,
                    ConversationRoundMessage.sequence,
                )
            )
        ).all()
    )
    assert [
        (link.role, link.response_sequence, link.sequence) for link in links
    ] == [
        ("input", None, 1),
        ("output", 1, 1),
        ("output", 1, 2),
    ]

    first_output = next(
        message for message in messages if message.text == "Bonjour. "
    )
    first_output_id = first_output.id
    turn_id = turn.id
    await db.delete(first_output)
    await db.commit()
    db.expire_all()
    assert await db.get(
        ConversationRoundMessage,
        (turn_id, first_output_id),
    ) is None

    await db.delete(turn)
    await db.commit()
    remaining_links = list(
        (
            await db.scalars(
                select(ConversationRoundMessage).where(
                    ConversationRoundMessage.round_id == turn_id
                )
            )
        ).all()
    )
    assert remaining_links == []
    remaining_messages = list(
        (
            await db.scalars(
                select(Message).where(
                    Message.messenger_room_id == messenger_room_id
                )
            )
        ).all()
    )
    assert len(remaining_messages) == 3


@pytest.mark.asyncio
async def test_calls_reuse_an_existing_messenger_conversation(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = await _agent_id(db)
    connection = await _messenger_connection(db, agent_id=agent_id)
    monkeypatch.setattr(
        voice_journal,
        "get_messenger",
        AsyncMock(
            return_value=SimpleNamespace(
                tool_id=connection.tool_id,
                self_id="voice-agent",
                kind="internal",
            )
        ),
    )
    agent_identity = MessengerUser(
        tool_id=connection.tool_id,
        external_id="voice-agent",
        display_name="Voice Tester",
        agent_id=agent_id,
        is_ai=True,
    )
    caller = MessengerUser(
        tool_id=connection.tool_id,
        external_id="user:42",
        display_name="Nicolas",
        is_ai=False,
    )
    room = Room(
        connection_id=connection.id,
        external_id="internal:direct:test:42",
        label="Voice Tester",
        kind="direct",
        conversation_type=ConversationType.TEXT.value,
    )
    db.add_all([agent_identity, caller, room])
    await db.flush()
    db.add_all(
        [
            RoomUser(room_id=room.id, user_id=agent_identity.id),
            RoomUser(room_id=room.id, user_id=caller.id, role="owner"),
        ]
    )
    await db.flush()

    first = await conversation_service.start_session(
        agent_id=agent_id,
        connection_id=connection.id,
        transport_kind="webrtc",
        room_id=room.external_id,
        language="fr",
        participant_external_ids=(caller.external_id,),
        conversation_room_id=room.id,
    )
    second = await conversation_service.start_session(
        agent_id=agent_id,
        connection_id=connection.id,
        transport_kind="webrtc",
        room_id=room.external_id,
        language="fr",
        participant_external_ids=(caller.external_id,),
        conversation_room_id=room.id,
    )
    await conversation_service.record_initial_greeting(
        second.id,
        "Bonjour, je reprends notre discussion.",
    )

    await db.refresh(room)
    assert first.messenger_room_id == room.id
    assert second.messenger_room_id == room.id
    assert room.conversation_type == ConversationType.TEXT.value
    assert await db.scalar(
        select(Message.id).where(
            Message.messenger_room_id == room.id,
            Message.text == "Bonjour, je reprends notre discussion.",
        )
    ) is not None


@pytest.mark.asyncio
async def test_interrupted_turns_are_accumulated_and_resolved_by_successor(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = await _agent_id(db)

    session = await _start_test_session(
        db,
        monkeypatch,
        agent_id=agent_id,
        room_id="room-voice",
    )
    session_id = session.id
    first = await conversation_service.start_turn(
        session_id=session.id,
        transcript="J'ai envie de me reposer, ma chérie.",
        run_id=uuid4(),
    )
    first_id = first.id
    await conversation_service.interrupt_turn(first.id)

    second = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Avec toi.",
        run_id=uuid4(),
    )

    assert second.sequence == 2
    assert second.source_round_id == first.id
    assert second.effective_objective == (
        "J'ai envie de me reposer, ma chérie.\nAvec toi."
    )

    second_id = second.id
    db.expire_all()
    persisted_first = await db.get(ConversationRound, first_id)
    assert persisted_first is not None
    assert persisted_first.status == VoiceTurnStatus.INTERRUPTED.value
    assert persisted_first.resolved_by_round_id == second_id
    assert persisted_first.interrupted_at is not None
    assert persisted_first.last_error is None

    await conversation_service.interrupt_turn(second_id)
    third = await conversation_service.start_turn(
        session_id=session_id,
        transcript="Et au calme.",
        run_id=uuid4(),
    )
    assert third.effective_objective == (
        "J'ai envie de me reposer, ma chérie.\nAvec toi.\nEt au calme."
    )
    assert third.source_round_id == second_id

    third_id = third.id
    await conversation_service.complete_turn(
        third_id,
        assistant_response="Alors repose-toi avec moi, tout doucement.",
        execution_result={
            "prompt": third.effective_objective or "",
            "system_prompt": "Tu es Voice Tester.",
            "messages": [],
            "result": "Alors repose-toi avec moi, tout doucement.",
            "success": True,
        },
    )
    await conversation_service.finish_session(
        session_id,
        VoiceConversationStatus.COMPLETED,
    )

    db.expire_all()
    persisted_session = await db.get(VoiceConversationSession, session_id)
    persisted_third = await db.get(ConversationRound, third_id)
    assert persisted_session is not None
    assert persisted_session.status == VoiceConversationStatus.COMPLETED.value
    assert persisted_third is not None
    assert persisted_third.status == VoiceTurnStatus.COMPLETED.value
    assert persisted_third.execution_result is not None
    assert persisted_third.execution_result["success"] is True


@pytest.mark.asyncio
async def test_failed_turn_remains_pending_without_becoming_a_task_error(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = await _agent_id(db)

    session = await _start_test_session(
        db,
        monkeypatch,
        agent_id=agent_id,
        room_id="room-failure",
    )
    failed = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Réponds-moi.",
        run_id=uuid4(),
    )
    failed_id = failed.id
    await conversation_service.fail_turn(
        failed.id,
        error="RuntimeError: provider unavailable",
    )

    successor = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Je t'écoute.",
        run_id=uuid4(),
    )
    assert successor.effective_objective == "Réponds-moi.\nJe t'écoute."

    db.expire_all()
    persisted = await db.get(ConversationRound, failed_id)
    assert persisted is not None
    assert persisted.status == VoiceTurnStatus.FAILED.value
    assert persisted.last_error == "RuntimeError: provider unavailable"


@pytest.mark.asyncio
async def test_session_failure_is_persisted_before_any_turn(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = await _agent_id(db)
    session = await _start_test_session(
        db,
        monkeypatch,
        agent_id=agent_id,
        room_id="room-handshake-failure",
    )
    session_id = session.id

    await conversation_service.finish_session(
        session_id,
        VoiceConversationStatus.ERROR,
        error="OpenAI Realtime error: insufficient_quota",
    )

    db.expire_all()
    persisted = await db.get(VoiceConversationSession, session_id)
    assert persisted is not None
    assert persisted.status == VoiceConversationStatus.ERROR.value
    assert persisted.error == "OpenAI Realtime error: insufficient_quota"
    assert persisted.finished_at is not None


@pytest.mark.asyncio
async def test_native_audio_turn_does_not_require_or_persist_a_transcript(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = await _agent_id(db)
    session = await _start_test_session(
        db,
        monkeypatch,
        agent_id=agent_id,
        room_id="room-native-audio",
    )

    turn = await conversation_service.start_audio_turn(
        session_id=session.id,
        run_id=uuid4(),
    )
    turn_id = turn.id
    await conversation_service.complete_turn(
        turn_id,
        assistant_response="Je t'écoute.",
    )

    db.expire_all()
    persisted = await db.get(ConversationRound, turn_id)
    assert persisted is not None
    assert persisted.effective_objective is None
    assert persisted.status == VoiceTurnStatus.COMPLETED.value
    links = list(
        (
            await db.scalars(
                select(ConversationRoundMessage).where(
                    ConversationRoundMessage.round_id == turn_id
                )
            )
        ).all()
    )
    assert links == []


@pytest.mark.asyncio
async def test_voice_transitions_publish_realtime_monitoring_events(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str, dict[str, Any]]] = []

    async def emit(
        subject: str,
        action: str,
        data: dict[str, Any],
        room: websocket.BaseRoom | None = None,
    ) -> None:
        assert room is None
        events.append((subject, action, data))

    monkeypatch.setattr(conversation_service.websocket, "emit", emit)
    agent_id = await _agent_id(db)
    session = await _start_test_session(
        db,
        monkeypatch,
        agent_id=agent_id,
        room_id="room-realtime",
    )
    turn = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Peux-tu m'entendre ?",
        run_id=uuid4(),
    )
    await conversation_service.complete_turn(
        turn.id,
        assistant_response="Oui, parfaitement.",
    )
    await conversation_service.finish_session(
        session.id,
        VoiceConversationStatus.COMPLETED,
    )

    assert events == [
        (
            "voice_conversation",
            "create",
            {"id": str(session.id), "status": VoiceConversationStatus.ACTIVE.value},
        ),
        (
            "voice_conversation",
            "update",
            {"id": str(session.id), "status": VoiceConversationStatus.ACTIVE.value},
        ),
        (
            "voice_conversation",
            "update",
            {"id": str(session.id), "status": VoiceConversationStatus.ACTIVE.value},
        ),
        (
            "voice_conversation",
            "update",
            {"id": str(session.id), "status": VoiceConversationStatus.COMPLETED.value},
        ),
    ]
