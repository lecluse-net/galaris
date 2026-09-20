import asyncio
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import app.voice as voice_module
from app.connection import connection_service
from app.conversation import ConversationTurn
from app.tools import McpToolContext
from app.tools import tool_service
from app.voice import mcp as voice_mcp
from app.voice.call_manager import VoiceCallInfo, VoiceCallManager
from app.voice.interface import CallTransport
from app.voice.models import AudioFrame


class _HoldingTransport(CallTransport):
    kind = "test"

    async def join(self, room_id: str) -> object:
        return room_id

    async def leave(self, handle: object) -> None:
        del handle

    async def inbound_audio(self, handle: object) -> AsyncIterator[AudioFrame]:
        del handle
        if False:
            yield AudioFrame(pcm=b"", sample_rate=16_000, channels=1)

    async def send_audio(
        self,
        handle: object,
        frames: AsyncIterator[AudioFrame],
    ) -> None:
        del handle
        async for _frame in frames:
            pass


@pytest.mark.asyncio
async def test_call_provider_comes_from_exact_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = object()
    connection = SimpleNamespace(id=42, agent_id=7, tool_id=5, active=True)
    tool = SimpleNamespace(
        code="custom-matrix",
        messenger=SimpleNamespace(service="matrix"),
    )
    monkeypatch.setattr(
        connection_service,
        "get_connection",
        AsyncMock(return_value=connection),
    )
    monkeypatch.setattr(tool_service, "get_tool_by_id", AsyncMock(return_value=tool))
    monkeypatch.setattr(
        voice_module,
        "get_call_provider",
        lambda kind: provider if kind == "matrix" else None,
    )

    resolved = await voice_mcp._call_provider_for_connection(7, 42, "en")

    assert resolved is provider


@pytest.mark.asyncio
async def test_stop_orchestration_requests_a_graceful_hangup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_stop = AsyncMock(return_value=1)
    immediate_stop = AsyncMock(return_value=1)
    monkeypatch.setattr(
        voice_module.voice_call_manager,
        "request_stop_calls",
        request_stop,
    )
    monkeypatch.setattr(
        voice_module.voice_call_manager,
        "stop_calls",
        immediate_stop,
    )

    await voice_mcp._stop_call(
        agent_id=7,
        room_id="room-1",
        connection_id=11,
        language="fr",
    )

    request_stop.assert_awaited_once_with(
        agent_id=7,
        room_id="room-1",
        connection_id=11,
    )
    immediate_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_stop_uses_the_server_owned_conversation_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_stop = AsyncMock(return_value=1)
    request_stop_by_id = AsyncMock(return_value=True)
    monkeypatch.setattr(
        voice_module.voice_call_manager,
        "request_stop_calls",
        request_stop,
    )
    monkeypatch.setattr(
        voice_module.voice_call_manager,
        "request_stop_call",
        request_stop_by_id,
    )
    canonical_room_id = uuid4()
    turn = ConversationTurn(
        room_id=canonical_room_id,
        round_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="Raccroche.",
        messages=(),
        messaging_context={
            "room_id": str(canonical_room_id),
            "room_locator": "chat:direct:7:42",
            "connection_id": 11,
        },
        origin="voice",
    )

    result = await voice_mcp.mcp_stop_voice_call(
        McpToolContext(
            agent_id=7,
            runtime="internal",
            resources={"conversation_turn": turn},
        ),
        call_id="model-selected-other-call",
        room_id=str(canonical_room_id),
    )

    request_stop_by_id.assert_not_awaited()
    request_stop.assert_awaited_once_with(
        agent_id=7,
        room_id="chat:direct:7:42",
        connection_id=11,
    )
    assert result == "1 appel(s) vocal(aux) arrêté(s)."


@pytest.mark.asyncio
async def test_voice_stop_ends_live_call_when_model_supplies_canonical_room_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = VoiceCallManager()

    async def hold_until_stopped(
        _info: object,
        _session: object,
        _language: str | None,
        stop_requested: asyncio.Event,
    ) -> None:
        await stop_requested.wait()

    monkeypatch.setattr(manager, "_run_agent", hold_until_stopped)
    monkeypatch.setattr(voice_module, "voice_call_manager", manager)
    canonical_room_id = uuid4()
    info, created = manager.start_agent_call(
        agent_id=7,
        connection_id=11,
        room_id="chat:direct:7:42",
        transport=_HoldingTransport(),
        conversation_room_id=canonical_room_id,
    )
    assert manager.active_transport(info.call_id) is not None
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="Raccroche.",
        messages=(),
        messaging_context={
            "room_id": str(canonical_room_id),
            "room_locator": "chat:direct:7:42",
            "connection_id": 11,
        },
        origin="voice",
    )

    try:
        result = await voice_mcp.mcp_stop_voice_call(
            McpToolContext(
                agent_id=7,
                runtime="internal",
                resources={"conversation_turn": turn},
            ),
            room_id=str(canonical_room_id),
        )
        for _ in range(10):
            if not manager.active_calls(agent_id=7):
                break
            await asyncio.sleep(0)

        assert created is True
        assert info.room_id == "chat:direct:7:42"
        assert result == "1 appel(s) vocal(aux) arrêté(s)."
        assert manager.active_calls(agent_id=7) == []
    finally:
        await manager.stop_all_calls()


@pytest.mark.asyncio
async def test_stop_calls_isolates_same_room_on_two_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = VoiceCallManager()

    async def hold(
        _info: object,
        _session: object,
        _language: str | None,
        _stop_requested: asyncio.Event,
    ) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "_run_agent", hold)
    first, _ = manager.start_agent_call(
        agent_id=7,
        connection_id=11,
        room_id="same-room",
        transport=_HoldingTransport(),
    )
    second, _ = manager.start_agent_call(
        agent_id=7,
        connection_id=22,
        room_id="same-room",
        transport=_HoldingTransport(),
    )
    await asyncio.sleep(0)

    stopped = await manager.stop_calls(
        agent_id=7,
        connection_id=11,
        room_id="same-room",
    )

    assert stopped == 1
    assert [call.call_id for call in manager.active_calls(agent_id=7)] == [
        second.call_id
    ]
    assert first.call_id != second.call_id
    await manager.stop_all_calls()


@pytest.mark.asyncio
async def test_requested_stop_is_graceful_and_connection_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = VoiceCallManager()
    stopped_gracefully: list[str] = []

    async def hold(
        info: object,
        _session: object,
        _language: str | None,
        stop_requested: asyncio.Event,
    ) -> None:
        await stop_requested.wait()
        stopped_gracefully.append(str(getattr(info, "call_id")))

    monkeypatch.setattr(manager, "_run_agent", hold)
    first, _ = manager.start_agent_call(
        agent_id=7,
        connection_id=11,
        room_id="same-room",
        transport=_HoldingTransport(),
    )
    second, _ = manager.start_agent_call(
        agent_id=7,
        connection_id=22,
        room_id="same-room",
        transport=_HoldingTransport(),
    )
    await asyncio.sleep(0)

    requested = await manager.request_stop_calls(
        agent_id=7,
        connection_id=11,
        room_id="same-room",
    )
    await asyncio.sleep(0)

    assert requested == 1
    assert stopped_gracefully == [first.call_id]
    assert [call.call_id for call in manager.active_calls(agent_id=7)] == [
        second.call_id
    ]
    await manager.stop_all_calls()


def test_call_id_does_not_collapse_distinct_room_identifiers() -> None:
    manager = VoiceCallManager()

    slash = manager.call_id_for(7, 11, "room/a")
    underscore = manager.call_id_for(7, 11, "room_a")
    long_a = manager.call_id_for(7, 11, "x" * 100 + "a")
    long_b = manager.call_id_for(7, 11, "x" * 100 + "b")

    assert len({slash, underscore, long_a, long_b}) == 4
    assert "room" not in slash


@pytest.mark.asyncio
async def test_terminal_call_notifies_adapters_after_leaving_active_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = VoiceCallManager()
    conversation_room_id = uuid4()
    ended: list[VoiceCallInfo] = []

    async def notify(info: VoiceCallInfo) -> None:
        assert manager.active_calls(agent_id=info.agent_id) == []
        ended.append(info)

    async def run_until_hangup(
        _session: object,
        *,
        agent_id: int,
        language: str,
        stop_requested: asyncio.Event,
    ) -> None:
        del agent_id, language
        await stop_requested.wait()

    monkeypatch.setattr("app.voice.session.VoiceSession.run_agent", run_until_hangup)
    manager.register_call_ended_listener(notify)

    info, created = manager.start_agent_call(
        agent_id=7,
        connection_id=11,
        room_id="provider-room",
        transport=_HoldingTransport(),
        conversation_room_id=conversation_room_id,
    )
    assert await manager.request_stop_call(info.call_id) is True
    for _ in range(10):
        if ended:
            break
        await asyncio.sleep(0)

    assert created is True
    assert ended == [info]
    assert info.conversation_room_id == conversation_room_id
