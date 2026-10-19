from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# pyright: reportPrivateUsage=false

from app.voice import realtime_engine
from app.voice import conversation_service
from app.llm.provider_facade import RealtimeConversationEvent, RealtimeToolDefinition
from app.voice.realtime_tools import RealtimeTool


@asynccontextmanager
async def _db_session() -> AsyncIterator[None]:
    yield None


@asynccontextmanager
async def _running_realtime(monkeypatch, tool):
    from app import agent
    from app.conversation import facade

    events = asyncio.Queue()
    interrupted = asyncio.Event()
    resumed = asyncio.Event()
    output_sent = asyncio.Event()
    provider = MagicMock()
    provider.receive = events.get
    provider.send_function_output = AsyncMock(side_effect=lambda *_: output_sent.set())

    async def request_response(instructions=None):
        if instructions is None:
            resumed.set()

    provider.request_response = AsyncMock(side_effect=request_response)
    provider.close = AsyncMock()
    provider.truncate = AsyncMock()
    transport = MagicMock()
    transport.kind = "test"
    transport.wait_input_ready = AsyncMock()
    transport.wait_output_ready = AsyncMock()
    transport.interrupt_output = AsyncMock(side_effect=lambda _: interrupted.set())
    transport.audio_sent = asyncio.Event()

    async def inbound(_handle):
        await asyncio.Event().wait()
        yield  # Never ends before the engine is stopped.

    async def send_audio(_handle, frames):
        async for _ in frames:
            transport.audio_sent.set()

    transport.inbound_audio = inbound
    transport.send_audio = send_audio
    configuration = realtime_engine._RealtimeConfiguration(
        service=SimpleNamespace(create_realtime_session=AsyncMock(return_value=provider)),
        connection=object(), model="synthetic-model", voice="synthetic-voice",
        voice_resource_id=None, native_audio=True,
    )
    engine = realtime_engine.RealtimeAgentVoiceEngine(
        transport=transport, handle=object(), agent_id=7, session_id=uuid4(),
        room_id="synthetic-room", connection_id=None, topic_id=None,
        contact_memory_item_id=None, language="fr", stop_requested=asyncio.Event(),
        configuration=configuration,
    )
    engine._tools = (RealtimeTool(
        definition=RealtimeToolDefinition(name="synthetic_lookup", description="Test lookup", parameters={}),
        execute=tool,
    ),)
    engine._greeting_recorded = True
    monkeypatch.setattr(realtime_engine, "get_db_session", _db_session)
    monkeypatch.setattr(agent, "build_realtime_agent_context", AsyncMock(return_value=SimpleNamespace(instructions="Synthetic context")))
    monkeypatch.setattr(facade, "active_work_snapshot", AsyncMock(return_value=()))
    running = asyncio.create_task(engine._run_owned())
    try:
        yield engine, provider, events, interrupted, resumed, output_sent
    finally:
        engine._stop_requested.set()
        await asyncio.wait_for(running, timeout=1)
        provider.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["speech_started", "response_cancelled"])
async def test_slow_realtime_tool_does_not_delay_barge_in(monkeypatch, interruption):
    started, release = asyncio.Event(), asyncio.Event()
    executed = []

    async def lookup(_arguments):
        executed.append(True)
        started.set()
        await release.wait()
        return {"found": True}

    async with _running_realtime(monkeypatch, lookup) as runtime:
        engine, provider, events, interrupted, resumed, output_sent = runtime
        events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="response-1"))
        events.put_nowait(RealtimeConversationEvent(
            kind="function_call", response_id="response-1", call_id="lookup-1",
            tool_name="synthetic_lookup", arguments="{}",
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            events.put_nowait(RealtimeConversationEvent(
                kind="function_call", response_id="response-1", call_id="queued-lookup",
                tool_name="synthetic_lookup", arguments="{}",
            ))
            events.put_nowait(RealtimeConversationEvent(kind="response_done", response_id="response-1"))
            events.put_nowait(RealtimeConversationEvent(kind=interruption, response_id="response-1"))
            await asyncio.wait_for(interrupted.wait(), timeout=0.1)
            assert not release.is_set()
            assert engine._tool_calls.empty()
            events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="response-2"))
            events.put_nowait(RealtimeConversationEvent(
                kind="function_call", response_id="response-1", call_id="late-lookup",
                tool_name="synthetic_lookup", arguments="{}",
            ))
            events.put_nowait(RealtimeConversationEvent(kind="response_done", response_id="response-1"))
            events.put_nowait(RealtimeConversationEvent(
                kind="audio_delta", response_id="response-2", item_id="new-audio",
                audio=b"\x01\x00" * 480,
            ))
            await asyncio.wait_for(engine._transport.audio_sent.wait(), 0.1)
            assert not release.is_set()
            release.set()
            await asyncio.wait_for(output_sent.wait(), timeout=1)
            await asyncio.wait_for(engine._tool_calls.join(), timeout=1)
            assert not resumed.is_set()
            assert executed == [True]
            assert engine._current_response_id == "response-2"
        finally:
            release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_first", [True, False])
async def test_realtime_tool_batch_resumes_once_after_all_ordered_results(monkeypatch, terminal_first):
    started, release, outputs = asyncio.Event(), asyncio.Event(), asyncio.Event()
    order = []

    async def lookup(arguments):
        order.append(arguments["index"])
        started.set()
        await release.wait()
        return {"index": arguments["index"]}

    async with _running_realtime(monkeypatch, lookup) as runtime:
        engine, provider, events, _, resumed, _ = runtime

        def sent(*_args):
            if provider.send_function_output.await_count == 2:
                outputs.set()

        provider.send_function_output.side_effect = sent
        events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="tools"))
        for index in range(2):
            events.put_nowait(RealtimeConversationEvent(
                kind="function_call", response_id="tools", call_id=f"call-{index}",
                tool_name="synthetic_lookup", arguments=json.dumps({"index": index}),
            ))
        await asyncio.wait_for(started.wait(), 1)
        if terminal_first:
            events.put_nowait(RealtimeConversationEvent(kind="response_done", response_id="tools"))
        assert not resumed.is_set()
        release.set()
        await asyncio.wait_for(outputs.wait(), 1)
        if not terminal_first:
            assert not resumed.is_set()
            events.put_nowait(RealtimeConversationEvent(kind="response_done", response_id="tools"))
        await asyncio.wait_for(resumed.wait(), 1)
        assert order == [0, 1]
        assert provider.request_response.await_count == 2  # Greeting and one continuation.
        assert [json.loads(call.args[1])["result"] for call in provider.send_function_output.await_args_list] == [
            {"index": 0}, {"index": 1},
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting_approval", [False, True])
async def test_realtime_tool_backlog_is_bounded_and_shutdown_cancels_active_tool(monkeypatch, waiting_approval):
    from app.tools.facade import AuthorizationRequired

    started, cancelled = asyncio.Event(), asyncio.Event()

    async def lookup(_arguments):
        started.set()
        if waiting_approval:
            raise AuthorizationRequired(uuid4())
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with _running_realtime(monkeypatch, lookup) as runtime:
        engine, provider, events, _, _, _ = runtime
        events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="tools"))
        events.put_nowait(RealtimeConversationEvent(
            kind="function_call", response_id="tools", call_id="active",
            tool_name="synthetic_lookup", arguments="{}",
        ))
        await asyncio.wait_for(started.wait(), 1)
        if waiting_approval:
            await asyncio.wait_for(engine._tool_calls.join(), 1)
            assert len(engine._authorization_tasks) == 1
        assert engine._tool_calls.maxsize > 0
        with pytest.raises(RuntimeError, match="too many pending"):
            for index in range(engine._tool_calls.maxsize + 1):
                engine._queue_function_call(RealtimeConversationEvent(
                    kind="function_call", response_id="tools", call_id=f"queued-{index}",
                    tool_name="synthetic_lookup", arguments="{}",
                ))
    if waiting_approval:
        assert not engine._authorization_tasks
    else:
        assert cancelled.is_set()
    assert engine._tool_calls.empty()
    assert not engine._pending_tool_calls
    provider.send_function_output.assert_not_awaited()


@pytest.mark.asyncio
async def test_realtime_authorizations_resume_only_after_all_results(monkeypatch):
    from app.tools.facade import AuthorizationRequired

    attempts = [0, 0]
    checking = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    first_output = asyncio.Event()

    async def lookup(arguments):
        index = arguments["index"]
        attempts[index] += 1
        if attempts[index] == 1:
            raise AuthorizationRequired(uuid4())
        checking[index].set()
        await release[index].wait()
        return {"index": index}

    async with _running_realtime(monkeypatch, lookup) as runtime:
        _, provider, events, _, resumed, _ = runtime
        provider.send_function_output.side_effect = lambda *_: first_output.set()
        events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="tools"))
        for index in range(2):
            events.put_nowait(RealtimeConversationEvent(
                kind="function_call", response_id="tools", call_id=f"call-{index}",
                tool_name="synthetic_lookup", arguments=json.dumps({"index": index}),
            ))
        events.put_nowait(RealtimeConversationEvent(kind="response_done", response_id="tools"))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in checking)), 3)
        assert not resumed.is_set()
        release[0].set()
        await asyncio.wait_for(first_output.wait(), 1)
        assert not resumed.is_set()
        release[1].set()
        await asyncio.wait_for(resumed.wait(), 1)
        assert provider.send_function_output.await_count == 2
        assert provider.request_response.await_count == 2


@pytest.mark.asyncio
async def test_barge_in_cancels_authorization_continuations(monkeypatch):
    from app.tools.facade import AuthorizationRequired

    checked = asyncio.Event()

    async def lookup(_arguments):
        checked.set()
        raise AuthorizationRequired(uuid4())

    async with _running_realtime(monkeypatch, lookup) as runtime:
        engine, provider, events, interrupted, resumed, _ = runtime
        events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="tools"))
        events.put_nowait(RealtimeConversationEvent(
            kind="function_call", response_id="tools", call_id="pending-approval",
            tool_name="synthetic_lookup", arguments="{}",
        ))
        await asyncio.wait_for(checked.wait(), 1)
        await asyncio.wait_for(engine._tool_calls.join(), 1)
        pending = tuple(engine._authorization_tasks)
        assert len(pending) == 1
        events.put_nowait(RealtimeConversationEvent(kind="speech_started"))
        await asyncio.wait_for(interrupted.wait(), 0.1)
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 1)
        assert all(task.cancelled() for task in pending)
        assert not resumed.is_set()
        provider.send_function_output.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_realtime_tools_keep_the_original_round_authority(monkeypatch):
    from app.voice import realtime_tools as tool_api

    started, release = asyncio.Event(), asyncio.Event()
    rounds = []
    original_round = uuid4()

    async def lookup(_arguments):
        rounds.append(tool_api._bound_round.get())
        started.set()
        await release.wait()
        return {"found": True}

    async with _running_realtime(monkeypatch, lookup) as runtime:
        engine, _, events, _, _, _ = runtime
        engine._current_turn_id = original_round
        try:
            events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="tools"))
            events.put_nowait(RealtimeConversationEvent(
                kind="function_call", response_id="tools", call_id="first",
                tool_name="synthetic_lookup", arguments="{}",
            ))
            await asyncio.wait_for(started.wait(), 1)
            engine._queue_function_call(RealtimeConversationEvent(
                kind="function_call", response_id="tools", call_id="second",
                tool_name="synthetic_lookup", arguments="{}",
            ))
            engine._current_turn_id = None
            release.set()
            await asyncio.wait_for(engine._tool_calls.join(), 1)
            assert rounds == [(original_round,), (original_round,)]
        finally:
            engine._current_turn_id = None
            release.set()


@pytest.mark.asyncio
async def test_realtime_tool_delivery_failure_closes_the_session(monkeypatch):
    closed = asyncio.Event()

    async def lookup(_arguments):
        return {"found": True}

    with pytest.raises(RuntimeError, match="provider send failed"):
        async with _running_realtime(monkeypatch, lookup) as runtime:
            _, provider, events, _, _, _ = runtime
            provider.close.side_effect = closed.set
            provider.send_function_output.side_effect = RuntimeError("provider send failed")
            events.put_nowait(RealtimeConversationEvent(kind="response_started", response_id="tools"))
            events.put_nowait(RealtimeConversationEvent(
                kind="function_call", response_id="tools", call_id="failed-delivery",
                tool_name="synthetic_lookup", arguments="{}",
            ))
            await asyncio.wait_for(closed.wait(), 1)
    provider.close.assert_awaited_once()


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
async def test_realtime_stop_waits_for_audio_drain_then_ends_call(monkeypatch) -> None:
    from app.tools import facade
    monkeypatch.setattr(facade, "bind_native_action", AsyncMock(return_value=object()))
    monkeypatch.setattr(facade, "claim_action", AsyncMock(return_value=None))
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
