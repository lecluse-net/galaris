from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from app.agent import AIMessage
from app.conversation import ConversationRuntimeEvent, public_ai_message
from app.chat import events
from app.messenger import Message
from app.voice import VoiceCallInfo, VoiceTranscriptionEvent


@pytest.mark.asyncio
async def test_publish_releases_room_touch_before_the_next_signal_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
    room_id = uuid4()

    @asynccontextmanager
    async def independent_session() -> AsyncIterator[None]:
        order.append("session-enter")
        try:
            yield
        finally:
            order.append("session-exit")

    async def touch(current_room_id: object) -> None:
        assert current_room_id == room_id
        order.append("touch")

    async def emit(*args: object, **kwargs: object) -> None:
        order.append("emit")
        emitted.append((args, kwargs))

    monkeypatch.setattr(events, "get_db_session", independent_session)
    monkeypatch.setattr(events, "touch_chat_room", touch)
    monkeypatch.setattr(events.websocket, "emit", emit)
    message = cast(
        Message,
        SimpleNamespace(
            platform="nextcloud_talk",
            messenger_room_id=room_id,
            id=uuid4(),
        ),
    )

    await events._publish(message)

    assert order == ["session-enter", "touch", "session-exit", "emit"]
    assert len(emitted) == 1
    args, kwargs = emitted[0]
    assert args == (
        "chat",
        "message",
        {
            "room_id": str(room_id),
            "message_id": str(message.id),
            "is_new": True,
        },
    )
    room = kwargs["room"]
    assert isinstance(room, events.ChatRoom)
    assert room.resource_id == room_id


@pytest.mark.asyncio
async def test_runtime_event_emits_only_the_bounded_public_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
    room_id = uuid4()
    round_id = uuid4()

    async def emit(*args: object, **kwargs: object) -> None:
        emitted.append((args, kwargs))

    monkeypatch.setattr(events.websocket, "emit", emit)
    event = ConversationRuntimeEvent(
        round_id=round_id,
        kind="message",
        sequence=3,
        message=public_ai_message(
            AIMessage(
                type="tool",
                tool_name="thinking",
                content="Je vérifie token=abcdefghijklmnop",
                tool_arguments={"authorization": "Bearer should-not-leak"},
                execution_time=0.25,
            )
        ),
    )

    await events._publish_runtime(room_id, event)

    assert len(emitted) == 1
    args, kwargs = emitted[0]
    assert args == (
        "chat",
        "runtime",
        {
            "room_id": str(room_id),
            "round_id": str(round_id),
            "kind": "message",
            "sequence": 3,
            "attempt": 1,
            "topic_id": None,
            "message": {
                "type": "tool",
                "content": "Je vérifie token=[redacted]",
                "tool_name": "thinking",
                "tool_arguments": {"authorization": "[redacted]"},
                "tool_result": {},
                "tool_call_external_id": None,
                "tool_retry_number": None,
                "tool_retry_limit": None,
                "execution_time": 0.25,
                "cost": 0.0,
                "success": True,
                "usage": None,
                "stream_id": None,
                "stream_mode": "delta",
                "stream_complete": None,
            },
            "result": None,
            "success": True,
        },
    )
    room = kwargs["room"]
    assert isinstance(room, events.ChatRoom)
    assert room.resource_id == room_id


@pytest.mark.asyncio
async def test_call_ended_refreshes_the_canonical_chat_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
    room_id = uuid4()

    async def emit(*args: object, **kwargs: object) -> None:
        emitted.append((args, kwargs))

    monkeypatch.setattr(events.websocket, "emit", emit)
    call = VoiceCallInfo(
        call_id="voice-7-11-test",
        agent_id=7,
        connection_id=11,
        room_id="provider-room",
        transport_kind="internal",
        started_at=123.0,
        conversation_room_id=room_id,
    )

    await events._publish_call_ended(call)

    assert len(emitted) == 1
    args, kwargs = emitted[0]
    assert args == (
        "chat",
        "call",
        {
            "room_id": str(room_id),
            "call_id": call.call_id,
            "status": "ended",
        },
    )
    room = kwargs["room"]
    assert isinstance(room, events.ChatRoom)
    assert room.resource_id == room_id


@pytest.mark.asyncio
async def test_voice_transcription_progress_is_scoped_to_the_chat_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
    room_id = uuid4()
    transcription_id = uuid4()
    started_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    async def emit(*args: object, **kwargs: object) -> None:
        emitted.append((args, kwargs))

    monkeypatch.setattr(events.websocket, "emit", emit)
    event = VoiceTranscriptionEvent(
        room_id=room_id,
        transcription_id=transcription_id,
        status="started",
        started_at=started_at,
    )

    await events._publish_voice_transcription(event)

    assert len(emitted) == 1
    args, kwargs = emitted[0]
    assert args == (
        "chat",
        "voice_transcription",
        {
            "room_id": str(room_id),
            "transcription_id": str(transcription_id),
            "status": "started",
            "started_at": started_at.isoformat(),
            "message_id": None,
        },
    )
    room = kwargs["room"]
    assert isinstance(room, events.ChatRoom)
    assert room.resource_id == room_id
