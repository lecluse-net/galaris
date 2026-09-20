from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# pyright: reportPrivateUsage=false

from app.voice import realtime_engine
from app.voice import conversation_service


@asynccontextmanager
async def _db_session() -> AsyncIterator[None]:
    yield None


@pytest.mark.asyncio
async def test_realtime_audio_journals_input_output_and_greeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conversation import facade

    publish = AsyncMock()
    monkeypatch.setattr(facade, "publish_runtime_event", publish)
    turn_id = uuid4()
    configuration = realtime_engine._RealtimeConfiguration(
        service=MagicMock(),
        connection=MagicMock(),
        model="realtime-model",
        voice="native-voice",
        voice_resource_id=None,
        native_audio=True,
    )
    transport = MagicMock()
    transport.kind = "test"
    engine = realtime_engine.RealtimeAgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="audio-room",
        connection_id=12,
        topic_id=None,
        contact_memory_item_id=None,
        language="fr",
        stop_requested=asyncio.Event(),
        configuration=configuration,
    )
    engine._provider = MagicMock()
    start_turn = AsyncMock(return_value=SimpleNamespace(id=turn_id, room_id=uuid4(), topic_id=None))
    record_input = AsyncMock()
    record_outputs = AsyncMock()
    complete_turn = AsyncMock()
    greeting = AsyncMock()
    monkeypatch.setattr(realtime_engine, "get_db_session", _db_session)
    monkeypatch.setattr(conversation_service, "start_audio_turn", start_turn)
    monkeypatch.setattr(conversation_service, "record_turn_input", record_input)
    monkeypatch.setattr(conversation_service, "record_turn_outputs", record_outputs)
    monkeypatch.setattr(conversation_service, "complete_turn", complete_turn)
    monkeypatch.setattr(conversation_service, "record_initial_greeting", greeting)

    engine._response_text = ["Bonjour."]
    await engine._finish_response("greeting")
    greeting.assert_awaited_once()

    await engine._start_audio_turn()
    record_input.assert_not_awaited()
    await engine._start_response("response-1")
    await engine._on_assistant_transcript("Première partie. ")
    assert publish.await_args.args[1].message.content == "Première partie. "
    record_outputs.assert_not_awaited()
    await engine._on_assistant_transcript("Seconde partie.")
    await engine._finish_response("response-1")
    assert record_outputs.await_args.args == (
        turn_id,
        ("Première partie. Seconde partie.",),
    )
    complete_turn.assert_awaited_once()
    events = [call.args[1] for call in publish.await_args_list]
    assert [event.kind for event in events] == ["started", "message", "message", "finished"]
    assert len(events[-1].result.messages) == 1
    assert events[-1].result.messages[0].content == "Première partie. Seconde partie."
    assert complete_turn.await_args.kwargs["execution_result"]["messages"][0]["stream_id"] == "voice:response-1"


@pytest.mark.asyncio
async def test_realtime_stop_waits_for_audio_drain_then_ends_call() -> None:
    configuration = realtime_engine._RealtimeConfiguration(
        service=MagicMock(),
        connection=MagicMock(),
        model="realtime-model",
        voice="native-voice",
        voice_resource_id=None,
        native_audio=True,
    )
    transport = MagicMock()
    transport.kind = "test"
    transport.wait_output_drained = AsyncMock()
    stop_requested = asyncio.Event()
    engine = realtime_engine.RealtimeAgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="audio-room",
        connection_id=12,
        topic_id=None,
        contact_memory_item_id=None,
        language="fr",
        stop_requested=stop_requested,
        configuration=configuration,
    )
    provider = MagicMock()
    provider.send_function_output = AsyncMock()
    provider.request_response = AsyncMock()
    engine._provider = provider
    engine._greeting_recorded = True

    await engine._on_function_call(
        response_id="tool-response",
        call_id="call-1",
        name="voice_call_stop",
        arguments="{}",
    )
    assert not stop_requested.is_set()

    await engine._finish_response("tool-response")
    provider.request_response.assert_awaited_once()
    assert not stop_requested.is_set()

    await engine._finish_response("final-response")

    transport.wait_output_drained.assert_awaited_once()
    assert stop_requested.is_set()


@pytest.mark.asyncio
async def test_native_sts_voice_does_not_require_a_configured_voice_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service
    from app.llm import llm_provider_service, llm_service, resource_discovery

    provider = SimpleNamespace(
        id=4,
        name="OpenAI",
        is_active=True,
        api_key="encrypted",
    )
    model = SimpleNamespace(
        id=12,
        llm_provider_id=4,
        llm_name="gpt-realtime-2.1",
        service_capabilities=["realtime_conversation"],
        provider=provider,
    )
    get_llm = AsyncMock(return_value=model)
    service = MagicMock()
    connection = MagicMock()

    monkeypatch.setattr(
        agent_service,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                voice="realtime:12:voice%3Amarin",
            )
        ),
    )
    monkeypatch.setattr(llm_service, "get_llm", get_llm)
    monkeypatch.setattr(
        llm_provider_service,
        "decrypt_api_key",
        MagicMock(return_value="secret"),
    )
    monkeypatch.setattr(
        resource_discovery,
        "provider_connection",
        MagicMock(return_value=connection),
    )
    monkeypatch.setattr(
        realtime_engine,
        "realtime_conversation_provider_for",
        MagicMock(return_value=service),
    )

    configuration = await realtime_engine._configuration_for_agent(7)

    assert configuration is not None
    assert configuration.model == "gpt-realtime-2.1"
    assert configuration.voice == "voice:marin"
    assert configuration.voice_resource_id is None
    assert configuration.native_audio is True
    get_llm.assert_awaited_once_with(12)
