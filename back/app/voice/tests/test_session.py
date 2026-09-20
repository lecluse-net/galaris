import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.voice import conversation_service
from app.voice import session as session_module
from app.voice.interface import CallTransport
from app.voice.models import AudioFrame
from app.voice.session import VoiceSession


class _LifecycleTransport(CallTransport):
    kind = "test"

    def __init__(self) -> None:
        self.left = 0
        self.terminated = 0

    async def join(self, room_id: str) -> object:
        return room_id

    async def leave(self, handle: Any) -> None:
        del handle
        self.left += 1

    async def terminate(self, handle: Any) -> None:
        del handle
        self.terminated += 1

    async def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
        del handle
        if False:
            yield AudioFrame(pcm=b"")

    async def send_audio(
        self,
        handle: Any,
        frames: AsyncIterator[AudioFrame],
    ) -> None:
        del handle
        async for _frame in frames:
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_stop", [False, True])
async def test_agent_session_terminates_only_after_explicit_stop(
    monkeypatch: pytest.MonkeyPatch,
    explicit_stop: bool,
) -> None:
    @asynccontextmanager
    async def db_session() -> AsyncIterator[None]:
        yield

    stop_requested = asyncio.Event()

    class Engine:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self) -> None:
            if explicit_stop:
                stop_requested.set()

    monkeypatch.setattr(session_module, "get_db_session", db_session)
    monkeypatch.setattr(session_module, "AgentVoiceEngine", Engine)
    conversation_room_id = uuid4()
    start_session = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid4(),
            messenger_room_id=conversation_room_id,
        )
    )
    monkeypatch.setattr(
        conversation_service,
        "start_session",
        start_session,
    )
    monkeypatch.setattr(
        conversation_service,
        "finish_session",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.messenger.get_audio_room_speakers",
        AsyncMock(
            return_value=SimpleNamespace(
                agent=None,
                participants=(),
            )
        ),
    )
    transport = _LifecycleTransport()
    session = VoiceSession(
        transport,
        "room",
        connection_id=11,
        conversation_room_id=conversation_room_id,
    )

    await session.run_agent(agent_id=1, stop_requested=stop_requested)

    assert transport.terminated == int(explicit_stop)
    assert transport.left == int(not explicit_stop)
    assert start_session.await_args.kwargs["conversation_room_id"] == conversation_room_id
