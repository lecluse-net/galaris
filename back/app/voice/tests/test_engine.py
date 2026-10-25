from __future__ import annotations

import asyncio
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

# pyright: reportPrivateUsage=false

from app.agent.contracts import AgentEvent, AIMessage, ExecutionResult
from app.voice import engine as engine_module
from app.voice import conversation_service
from app.voice.engine import (
    AgentVoiceEngine,
    _requests_hangup,
    _SentenceBuffer,
    prepare_spoken_text,
)
from app.voice.interface import CallTransport
from app.voice.models import AudioFrame
from app.voice.turn_detection import SpeechUtterance


class _Transport(CallTransport):
    kind = "test"

    def __init__(self) -> None:
        self.interrupts = 0
        self.input_ready = 0
        self.output_ready = 0
        self.output_drained = 0

    async def join(self, room_id: str) -> object:
        return object()

    async def leave(self, handle: Any) -> None:
        return None

    async def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
        if False:
            yield AudioFrame(b"")

    async def send_audio(
        self,
        handle: Any,
        frames: AsyncIterator[AudioFrame],
    ) -> None:
        async for _frame in frames:
            pass

    async def interrupt_output(self, handle: Any) -> None:
        self.interrupts += 1

    async def wait_output_ready(self, handle: Any) -> None:
        self.output_ready += 1

    async def wait_input_ready(self, handle: Any) -> None:
        self.input_ready += 1

    async def wait_output_drained(self, handle: Any) -> None:
        self.output_drained += 1


def test_voice_history_uses_canonical_speaker_names() -> None:
    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
        agent_name="Aster",
        caller_external_id="nicolas",
        caller_name="Nicolas",
    )

    voice._append_user_message("Bonjour", 1)
    voice._append_assistant_message("Bonjour Nicolas", 1)

    assert [message.sender_display_name for message in voice._history] == [
        "Nicolas",
        "Aster",
    ]
    assert [message.sender_external_id for message in voice._history] == [
        "nicolas",
        "voice-agent-7",
    ]


@pytest.mark.asyncio
async def test_speech_start_publishes_human_transcription_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.voice import transcription_events

    room_id = uuid4()
    publish = AsyncMock()
    monkeypatch.setattr(transcription_events, "publish_voice_transcription", publish)
    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
        conversation_room_id=room_id,
    )

    await voice._on_speech_start()

    publish.assert_awaited_once()
    event = publish.await_args.args[0]
    assert event.room_id == room_id
    assert event.status == "started"
    assert event.message_id is None
    assert voice._pending_transcription_id == event.transcription_id


@asynccontextmanager
async def _db_session() -> AsyncIterator[None]:
    yield None


@pytest.mark.asyncio
@pytest.mark.parametrize("transcript", ["", "   "])
async def test_no_speech_finishes_progress_without_retry_or_conversation(
    monkeypatch: pytest.MonkeyPatch,
    transcript: str,
) -> None:
    from app.llm import transcription_service

    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
    )
    transcribe = AsyncMock()
    start_turn = AsyncMock(side_effect=AssertionError("No speech must not start a conversation"))
    finish_progress = AsyncMock()
    monkeypatch.setattr(transcription_service, "transcribe_audio", transcribe)
    monkeypatch.setattr(conversation_service, "start_turn", start_turn)
    monkeypatch.setattr(voice, "_finish_transcription_progress", finish_progress)
    transcription_id = uuid4()

    await voice._respond(
        SpeechUtterance(
            pcm=b"\x00\x00" * 960,
            duration_s=0.02,
            voiced_s=0.0,
            reason="silence",
        ),
        generation=0,
        turn_index=1,
        transcript=transcript,
        transcription_id=transcription_id,
    )

    transcribe.assert_not_awaited()
    start_turn.assert_not_awaited()
    assert voice._history == []
    assert voice._outbound.empty()
    finish_progress.assert_awaited_once_with(transcription_id, status="completed")


@pytest.fixture(autouse=True)
def _mock_voice_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.conversation as conversation
    from app.voice.realtime_engine import RealtimeAgentVoiceEngine
    from app.voice import runtime_control

    @asynccontextmanager
    async def ownership(_session_id: UUID) -> AsyncIterator[None]:
        # These unit tests mock persistence; real admission/locks are tested separately.
        yield

    monkeypatch.setattr(runtime_control, "own_session", ownership)

    async def start_turn(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid4(),
            room_id=uuid4(),
            effective_objective=kwargs["transcript"],
            topic_id=kwargs.get("topic_id"),
            contact_memory_item_id=kwargs.get("contact_memory_item_id"),
        )

    monkeypatch.setattr(
        RealtimeAgentVoiceEngine,
        "create",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        conversation,
        "linked_work_snapshot",
        AsyncMock(return_value=()),
    )
    monkeypatch.setattr(conversation_service, "start_turn", start_turn)
    monkeypatch.setattr(
        conversation_service,
        "record_initial_greeting",
        AsyncMock(),
    )
    monkeypatch.setattr(
        conversation_service,
        "record_turn_input",
        AsyncMock(side_effect=lambda *_args: uuid4()),
    )
    monkeypatch.setattr(
        conversation_service,
        "record_turn_outputs",
        AsyncMock(),
    )
    monkeypatch.setattr(conversation_service, "complete_turn", AsyncMock())
    monkeypatch.setattr(conversation_service, "interrupt_turn", AsyncMock())
    monkeypatch.setattr(conversation_service, "fail_turn", AsyncMock())


def test_sentence_buffer_emits_short_speakable_segments() -> None:
    buffer = _SentenceBuffer()

    assert buffer.feed("Bonjour. Comment ") == ["Bonjour."]
    assert buffer.feed("allez-vous ?") == ["Comment allez-vous ?"]
    assert buffer.flush() == []
    assert prepare_spoken_text("**Bien sûr** 😀 — [ouvrez ce lien](https://example.test)") == (
        "Bien sûr — ouvrez ce lien"
    )


def test_long_reply_can_start_speaking_before_the_sentence_is_complete() -> None:
    from app.voice.realtime_engine import _TextSegmenter

    text = " ".join(["A useful answer can start speaking while the rest is still being written"] * 4)
    for buffer in (_SentenceBuffer(), _TextSegmenter()):
        segments = buffer.feed(text[:80])
        assert segments
        assert " ".join(segments) in text[:80]
        segments.extend(buffer.feed(text[80:]))
        segments.extend(buffer.flush())
        assert " ".join(segments) == text


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("Merci ma chérie. À tout de suite. Tu peux raccrocher.", True),
        ("Raccroche maintenant.", True),
        ("Please hang up.", True),
        ("Ne raccroche surtout pas.", False),
        ("Au revoir et à bientôt.", False),
        ("Si tu raccroches, rappelle-moi.", False),
    ],
)
def test_hangup_detection_requires_an_explicit_instruction(
    transcript: str,
    expected: bool,
) -> None:
    assert _requests_hangup(transcript) is expected


@pytest.mark.asyncio
async def test_configured_realtime_mode_bypasses_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.voice.realtime_engine import RealtimeAgentVoiceEngine

    transport = _Transport()
    conversation_room_id = uuid4()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-realtime",
        conversation_room_id=conversation_room_id,
    )
    realtime = SimpleNamespace(run=AsyncMock())
    create = AsyncMock(return_value=realtime)
    pipeline_turns = AsyncMock()
    monkeypatch.setattr(RealtimeAgentVoiceEngine, "create", create)
    monkeypatch.setattr(voice, "_consume_speech_turns", pipeline_turns)

    await voice.run()

    create.assert_awaited_once()
    assert create.await_args.kwargs["room_id"] == "room-realtime"
    assert create.await_args.kwargs["conversation_id"] == str(
        conversation_room_id
    )
    realtime.run.assert_awaited_once()
    pipeline_turns.assert_not_awaited()


@pytest.mark.asyncio
async def test_graceful_stop_waits_for_response_and_transport_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport()
    stop_requested = asyncio.Event()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
        stop_requested=stop_requested,
    )
    response_started = asyncio.Event()
    response_finished = asyncio.Event()

    async def greeting(_generation: int) -> None:
        response_started.set()
        await response_finished.wait()

    async def hold_turns() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(voice, "_speak_initial_greeting", greeting)
    monkeypatch.setattr(voice, "_consume_speech_turns", hold_turns)

    running = asyncio.create_task(voice.run())
    await response_started.wait()
    stop_requested.set()
    await asyncio.sleep(0)

    assert not running.done()

    response_finished.set()
    await asyncio.wait_for(running, timeout=1)

    assert transport.output_drained == 1


@pytest.mark.asyncio
async def test_response_uses_configured_agent_and_tts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent as agent_module
    from app.llm import transcription_service, tts_service
    from app.conversation import facade

    publish = AsyncMock()
    monkeypatch.setattr(facade, "publish_runtime_event", publish)

    transport = _Transport()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        connection_id=19,
        room_id="room-1",
        language="fr",
    )
    transcribe = AsyncMock(return_value="Bonjour")
    synthesize = AsyncMock(
        return_value=SimpleNamespace(content=b"encoded-audio")
    )
    realtime_speech = AsyncMock(return_value=None)
    calls: list[dict[str, Any]] = []

    async def stream_turn(**kwargs: Any) -> AsyncIterator[AgentEvent]:
        calls.append(kwargs)
        yield AgentEvent.from_message(AIMessage(type="text", content="Bonjour. ", stream_id="answer"))
        # The chat receives the first fragment before generation or TTS completes.
        assert publish.await_args.args[1].message.content == "Bonjour. "
        conversation_service.complete_turn.assert_not_awaited()
        yield AgentEvent.from_message(
            AIMessage(type="text", content="Comment allez-vous ?", stream_id="answer")
        )

    async def decode(_content: bytes) -> AsyncIterator[AudioFrame]:
        yield AudioFrame(pcm=b"\x01\x00" * 960)

    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(transcription_service, "transcribe_audio", transcribe)
    monkeypatch.setattr(tts_service, "generate_for_agent", synthesize)
    monkeypatch.setattr(
        tts_service,
        "create_realtime_speech_stream_for_agent",
        realtime_speech,
    )
    monkeypatch.setattr(agent_module, "stream_conversation_turn_events", stream_turn)
    monkeypatch.setattr(engine_module, "encoded_audio_frames", decode)

    await voice._respond(
        SpeechUtterance(
            pcm=b"\x01\x00" * 960 * 20,
            duration_s=0.4,
            voiced_s=0.4,
            reason="silence",
        ),
        generation=0,
        turn_index=1,
    )

    transcribe.assert_awaited_once()
    assert calls[0]["agent_id"] == 7
    assert calls[0]["messenger_connection_id"] == 19
    assert str(UUID(str(calls[0]["conversation_id"]))) == calls[0]["conversation_id"]
    assert calls[0]["room_locator"] == "room-1"
    assert calls[0]["transport_kind"] == "test"
    assert calls[0]["objective"] == "Bonjour"
    assert calls[0]["conversation_history"] == ()
    assert isinstance(calls[0]["current_message_id"], UUID)
    assert calls[0]["excluded_message_ids"] == (calls[0]["current_message_id"],)
    assert calls[0]["run_id"] is not None
    assert calls[0]["conversation_round_id"] is not None
    assert [call.args[1] for call in synthesize.await_args_list] == [
        "Bonjour.",
        "Comment allez-vous ?",
    ]
    assert [message.text for message in voice._history] == [
        "Bonjour",
        "Bonjour. Comment allez-vous ?",
    ]
    assert voice._outbound.qsize() == 2
    persistence = conversation_service.complete_turn
    assert isinstance(persistence, AsyncMock)
    persistence.assert_awaited_once()
    input_persistence = conversation_service.record_turn_input
    assert isinstance(input_persistence, AsyncMock)
    input_persistence.assert_awaited_once()
    assert input_persistence.await_args.args[1] == "Bonjour"
    assert transcribe.await_args.kwargs["voice_dialogue"] is True
    output_persistence = conversation_service.record_turn_outputs
    assert isinstance(output_persistence, AsyncMock)
    output_persistence.assert_awaited_once()
    assert output_persistence.await_args.args[1] == (
        "Bonjour. Comment allez-vous ?",
    )
    events = [call.args[1] for call in publish.await_args_list]
    assert [event.kind for event in events] == ["started", "message", "message", "finished"]
    assert events[-1].result.messages[0].stream_id == "answer"
    assert events[-1].result.messages[0].content == "Bonjour. Comment allez-vous ?"
    assert events[-1].success


@pytest.mark.asyncio
async def test_failed_agent_message_persists_the_leaf_error_without_task_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent as agent_module
    from app.llm import tts_service

    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
    )

    async def stream_turn(**_kwargs: Any) -> AsyncIterator[AgentEvent]:
        yield AgentEvent.from_message(
            AIMessage(
                type="text",
                content="LookupError: Tâche voice-run introuvable",
                success=False,
            )
        )

    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(agent_module, "stream_conversation_turn_events", stream_turn)
    monkeypatch.setattr(
        tts_service,
        "create_realtime_speech_stream_for_agent",
        AsyncMock(return_value=None),
    )

    await voice._respond(
        SpeechUtterance(
            pcm=b"\x01\x00" * 960,
            duration_s=0.1,
            voiced_s=0.1,
            reason="silence",
        ),
        generation=0,
        turn_index=1,
        transcript="Bonjour",
    )

    persistence = conversation_service.fail_turn
    assert isinstance(persistence, AsyncMock)
    persistence.assert_awaited_once()
    assert persistence.await_args.kwargs["error"] == (
        "LookupError: Tâche voice-run introuvable"
    )


@pytest.mark.asyncio
async def test_message_journal_failure_marks_the_created_voice_turn_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
    )
    record_input = conversation_service.record_turn_input
    assert isinstance(record_input, AsyncMock)
    record_input.side_effect = RuntimeError("Messenger journal unavailable")
    monkeypatch.setattr(engine_module, "get_db_session", _db_session)

    await voice._respond(
        SpeechUtterance(
            pcm=b"\x01\x00" * 960,
            duration_s=0.1,
            voiced_s=0.1,
            reason="silence",
        ),
        generation=0,
        turn_index=1,
        transcript="Bonjour",
    )

    failed = conversation_service.fail_turn
    assert isinstance(failed, AsyncMock)
    failed.assert_awaited_once()
    assert failed.await_args.kwargs["error"] == (
        "RuntimeError: Messenger journal unavailable"
    )


@pytest.mark.asyncio
async def test_explicit_hangup_transcript_requests_call_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent as agent_module
    from app.llm import tts_service

    stop_requested = asyncio.Event()
    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
        stop_requested=stop_requested,
    )

    async def stream_turn(**_kwargs: Any) -> AsyncIterator[AgentEvent]:
        yield AgentEvent.from_message(
            AIMessage(type="text", content="D'accord, à tout de suite.")
        )

    async def decode(_content: bytes) -> AsyncIterator[AudioFrame]:
        yield AudioFrame(pcm=b"\x01\x00" * 960)

    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(agent_module, "stream_conversation_turn_events", stream_turn)
    monkeypatch.setattr(
        tts_service,
        "create_realtime_speech_stream_for_agent",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        tts_service,
        "generate_for_agent",
        AsyncMock(return_value=SimpleNamespace(content=b"encoded-audio")),
    )
    monkeypatch.setattr(engine_module, "encoded_audio_frames", decode)

    await voice._respond(
        SpeechUtterance(
            pcm=b"\x01\x00" * 960,
            duration_s=0.1,
            voiced_s=0.1,
            reason="silence",
        ),
        generation=0,
        turn_index=1,
        transcript="Merci ma chérie. À tout de suite. Tu peux raccrocher.",
    )

    assert stop_requested.is_set()


@pytest.mark.asyncio
async def test_response_streams_pcm_without_batch_stt_or_audio_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent as agent_module
    from app.llm import transcription_service, tts_service

    class _SpeechStream:
        sample_rate = 24_000
        channels = 1

        def __init__(self) -> None:
            self.segments: list[str] = []

        async def stream(
            self,
            segments: AsyncIterator[str],
        ) -> AsyncIterator[bytes]:
            async for segment in segments:
                self.segments.append(segment)
                yield b"\x01\x00" * 240
                yield b"\x02\x00" * 240

    transport = _Transport()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
        language="fr",
    )
    speech_stream = _SpeechStream()
    transcribe = AsyncMock(return_value="should not be used")
    synthesize = AsyncMock()
    create_stream = AsyncMock(return_value=speech_stream)

    async def stream_turn(**_kwargs: Any) -> AsyncIterator[AgentEvent]:
        yield AgentEvent.from_message(
            AIMessage(type="text", content="Réponse immédiate.")
        )

    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(transcription_service, "transcribe_audio", transcribe)
    monkeypatch.setattr(tts_service, "generate_for_agent", synthesize)
    monkeypatch.setattr(
        tts_service,
        "create_realtime_speech_stream_for_agent",
        create_stream,
    )
    monkeypatch.setattr(agent_module, "stream_conversation_turn_events", stream_turn)

    await voice._respond(
        SpeechUtterance(
            pcm=b"\x01\x00" * 960 * 20,
            duration_s=0.4,
            voiced_s=0.4,
            reason="silence",
        ),
        generation=0,
        turn_index=1,
        transcript="Bonjour",
    )

    transcribe.assert_not_awaited()
    synthesize.assert_not_awaited()
    assert speech_stream.segments == ["Réponse immédiate."]
    assert voice._outbound.qsize() == 1
    outbound = voice._outbound.get_nowait()
    assert outbound is not None
    assert len(outbound.frame.pcm) == 1_920
    assert [message.text for message in voice._history] == [
        "Bonjour",
        "Réponse immédiate.",
    ]


@pytest.mark.asyncio
async def test_initial_greeting_uses_agent_tts_and_enters_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import tts_service

    transport = _Transport()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
        language="fr",
    )
    synthesize = AsyncMock(return_value=SimpleNamespace(content=b"encoded-audio"))

    async def decode(_content: bytes) -> AsyncIterator[AudioFrame]:
        yield AudioFrame(pcm=b"\x01\x00" * 960)

    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(tts_service, "generate_for_agent", synthesize)
    monkeypatch.setattr(engine_module, "encoded_audio_frames", decode)

    await voice._speak_initial_greeting(generation=0)

    synthesize.assert_awaited_once()
    assert transport.input_ready == 1
    assert transport.output_ready == 1
    assert synthesize.await_args.args[1] == "allo?"
    assert voice._outbound.qsize() == 1
    assert [message.text for message in voice._history] == ["allo?"]


@pytest.mark.asyncio
async def test_continuous_speech_chunks_start_one_complete_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import transcription_service

    transport = _Transport()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
    )
    chunks = [
        SpeechUtterance(
            pcm=b"first",
            duration_s=20.0,
            voiced_s=19.0,
            reason="max_duration",
        ),
        SpeechUtterance(
            pcm=b"last",
            duration_s=3.0,
            voiced_s=2.0,
            reason="silence",
        ),
    ]

    async def speech_turns(
        _frames: AsyncIterator[AudioFrame],
        **_kwargs: Any,
    ) -> AsyncIterator[SpeechUtterance]:
        for chunk in chunks:
            yield chunk

    responses: list[SpeechUtterance] = []

    async def start_response(utterance: SpeechUtterance, **_kwargs: Any) -> bool:
        responses.append(utterance)
        return True

    monkeypatch.setattr(engine_module, "detect_speech_turns", speech_turns)
    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(
        transcription_service,
        "create_realtime_transcriber",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(voice, "_start_response", start_response)
    monkeypatch.setattr(voice, "_transcribe", AsyncMock(return_value="One complete thought"))

    await voice._consume_speech_turns()

    assert len(responses) == 1
    assert responses[0].pcm == b"firstlast"
    assert responses[0].duration_s == pytest.approx(23.0)
    assert responses[0].voiced_s == pytest.approx(21.0)
    assert responses[0].reason == "silence"


@pytest.mark.asyncio
async def test_barge_in_cancels_response_and_clears_playback() -> None:
    transport = _Transport()
    voice = AgentVoiceEngine(
        transport=transport,
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
    )
    voice._outbound.put_nowait(
        engine_module._OutboundFrame(0, AudioFrame(pcm=b"\x00\x00" * 960))
    )
    response = asyncio.create_task(asyncio.Event().wait())
    voice._response_task = response

    await voice._on_speech_start()
    await asyncio.sleep(0)

    assert response.cancelled()
    assert transport.interrupts == 1
    assert voice._outbound.empty()
    assert voice._generation == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_listening_continues_during_stt_and_late_text_is_preserved(
    monkeypatch: pytest.MonkeyPatch, streaming: bool,
) -> None:
    from app.llm import transcription_service
    from app.voice.audio import pcm_rms
    from app.voice.turn_detection import detect_speech_turns

    class Transport(_Transport):
        def __init__(self) -> None:
            super().__init__()
            self.incoming: asyncio.Queue[AudioFrame | None] = asyncio.Queue()

        async def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
            while (frame := await self.incoming.get()) is not None:
                yield frame

    transport = Transport()
    voice = AgentVoiceEngine(
        transport=transport, handle=object(), agent_id=7,
        session_id=uuid4(), room_id="room-1",
    )
    blocked = asyncio.Event()
    release = asyncio.Event()
    second_onset = asyncio.Event()
    audio_sent: list[bytes] = []
    commits = 0

    async def recognize(*_args: object, **_kwargs: object) -> str:
        nonlocal commits
        commits += 1
        if commits == 1:
            blocked.set()
            await release.wait()
            return "The first sentence"
        return "and its continuation"

    provider = SimpleNamespace(send_audio=AsyncMock(side_effect=lambda pcm, **_kwargs: audio_sent.append(pcm)),
                               commit=recognize, close=AsyncMock())
    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(transcription_service, "create_realtime_transcriber",
                        AsyncMock(return_value=provider if streaming else None))
    monkeypatch.setattr(transcription_service, "transcribe_audio", recognize)
    start_response = AsyncMock(return_value=True)
    monkeypatch.setattr(voice, "_start_response", start_response)
    original_onset = voice._on_speech_start

    async def on_speech_start() -> None:
        await original_onset()
        if voice._generation == 2:
            second_onset.set()

    monkeypatch.setattr(voice, "_on_speech_start", on_speech_start)

    async def detected(frames: AsyncIterator[AudioFrame], **kwargs: Any) -> AsyncIterator[SpeechUtterance]:
        async for turn in detect_speech_turns(
            frames, speech_detector=lambda pcm: pcm_rms(pcm) >= 80, **kwargs,
        ):
            yield turn

    monkeypatch.setattr(engine_module, "detect_speech_turns", detected)
    running = asyncio.create_task(voice._consume_speech_turns())

    def say_turn() -> None:
        for pcm in [b"\x00\x10" * 960] * 30 + [b"\x00\x00" * 960] * 45:
            transport.incoming.put_nowait(AudioFrame(pcm))

    try:
        say_turn()
        await asyncio.wait_for(blocked.wait(), 3)
        sent_before = len(audio_sent)
        say_turn()
        await asyncio.wait_for(second_onset.wait(), 3)
        assert transport.interrupts == 2
        start_response.assert_not_awaited()
        # Next-turn audio remains behind the first commit boundary.
        assert len(audio_sent) == sent_before
        transport.incoming.put_nowait(None)
        release.set()
        await asyncio.wait_for(running, 3)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
    start_response.assert_awaited_once()
    assert start_response.await_args.kwargs["transcript"] == "The first sentence\nand its continuation"
    assert start_response.await_args.kwargs["generation"] == 2
    assert commits == 2
    if streaming:
        provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_audio_backlog_is_bounded_and_closes_the_transcriber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import transcription_service

    class Transport(_Transport):
        async def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
            yield AudioFrame(b"\x00\x00" * (48_000 * 31))

    async def blocked_send(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    provider = SimpleNamespace(send_audio=blocked_send, close=AsyncMock())
    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(transcription_service, "create_realtime_transcriber", AsyncMock(return_value=provider))
    voice = AgentVoiceEngine(
        transport=Transport(), handle=object(), agent_id=7,
        session_id=uuid4(), room_id="room-1",
    )
    with pytest.raises(RuntimeError, match="30 seconds behind"):
        await asyncio.wait_for(voice._consume_speech_turns(), 3)
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_stop_cancels_inflight_stt_and_releases_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import transcription_service

    closed = asyncio.Event()
    transcribing = asyncio.Event()
    with wave.open(str(Path(__file__).parent / "fixtures" / "speech.wav")) as wav:
        pcm_speech = wav.readframes(wav.getnframes()) + b"\x00\x00" * 48_000

    class Transport(_Transport):
        async def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
            try:
                for offset in range(0, len(pcm_speech), 1920):
                    yield AudioFrame(pcm_speech[offset:offset + 1920])
                await asyncio.Event().wait()
            finally:
                closed.set()

    async def commit() -> str:
        transcribing.set()
        await asyncio.Event().wait()
        return ""

    provider = SimpleNamespace(send_audio=AsyncMock(), commit=commit, close=AsyncMock())
    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(transcription_service, "create_realtime_transcriber", AsyncMock(return_value=provider))

    voice = AgentVoiceEngine(
        transport=Transport(), handle=object(), agent_id=7,
        session_id=uuid4(), room_id="room-1",
    )
    running = asyncio.create_task(voice._consume_speech_turns())
    try:
        await asyncio.wait_for(transcribing.wait(), 3)
    finally:
        running.cancel()
        await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 3)
    assert closed.is_set()
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_response_preempted_during_cleanup_cannot_start_late() -> None:
    cleaning = asyncio.Event()
    release = asyncio.Event()

    async def previous_response() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    voice = AgentVoiceEngine(
        transport=_Transport(), handle=object(), agent_id=7,
        session_id=uuid4(), room_id="room-1",
    )
    previous = asyncio.create_task(previous_response())
    voice._response_task = previous
    await asyncio.sleep(0)
    previous.cancel()
    await asyncio.wait_for(cleaning.wait(), 3)
    starting = asyncio.create_task(voice._start_response(
        SpeechUtterance(pcm=b"", duration_s=1, voiced_s=1, reason="silence"),
        transcript="Earlier speech", generation=0,
    ))
    await asyncio.sleep(0)
    voice._generation = 1
    release.set()
    assert await asyncio.wait_for(starting, 3) is False
    assert voice._response_task is previous
    assert voice._turn_index == 0


@pytest.mark.asyncio
async def test_cancelled_response_persists_interrupted_turn_for_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import agent as agent_module
    from app.llm import tts_service

    voice = AgentVoiceEngine(
        transport=_Transport(),
        handle=object(),
        agent_id=7,
        session_id=uuid4(),
        room_id="room-1",
    )
    started = asyncio.Event()
    blocked = asyncio.Event()
    calls: list[dict[str, Any]] = []

    async def stream_turn(**kwargs: Any) -> AsyncIterator[AgentEvent]:
        calls.append(kwargs)
        started.set()
        await blocked.wait()
        yield AgentEvent.from_result(
            ExecutionResult(prompt=kwargs["objective"], result="Terminé")
        )

    monkeypatch.setattr(engine_module, "get_db_session", _db_session)
    monkeypatch.setattr(agent_module, "stream_conversation_turn_events", stream_turn)
    monkeypatch.setattr(
        tts_service,
        "create_realtime_speech_stream_for_agent",
        AsyncMock(return_value=None),
    )

    response = asyncio.create_task(
        voice._respond(
            SpeechUtterance(
                pcm=b"\x01\x00" * 960,
                duration_s=0.1,
                voiced_s=0.1,
                reason="silence",
            ),
            generation=0,
            turn_index=1,
            transcript="J'ai envie de me reposer.",
        )
    )
    await started.wait()
    response.cancel()

    with pytest.raises(asyncio.CancelledError):
        await response

    persistence = conversation_service.interrupt_turn
    assert isinstance(persistence, AsyncMock)
    persistence.assert_awaited_once()
    completion = conversation_service.complete_turn
    assert isinstance(completion, AsyncMock)
    completion.assert_not_awaited()
    assert voice._pending_turn_indexes == {1}
    assert [message.text for message in voice._history] == [
        "J'ai envie de me reposer."
    ]
    blocked.set()
    for turn_index, transcript in ((2, "Et demain ?"), (3, "Merci")):
        await voice._respond(
            SpeechUtterance(
                pcm=b"\x01\x00" * 960,
                duration_s=0.1,
                voiced_s=0.1,
                reason="silence",
            ),
            generation=0,
            turn_index=turn_index,
            transcript=transcript,
        )
    assert set(calls[1]["excluded_message_ids"]) == {
        calls[0]["current_message_id"], calls[1]["current_message_id"],
    }
    assert calls[2]["excluded_message_ids"] == (calls[2]["current_message_id"],)
    assert completion.await_count == 2
