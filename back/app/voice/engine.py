"""Transport-neutral conversational voice engine with human barge-in."""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal, cast
from uuid import UUID, uuid4

from loguru import logger

from app.agent.contracts import TaskMessage as Message
from app.agent import AIResult
from app.conversation import ConversationRuntimeStream
from core.database import get_db_session
from core.i18n import render_prompt, t

from .audio import encoded_audio_frames, pcm_audio_frames, pcm_to_wav
from .interface import CallTransport
from .models import AudioFrame
from .turn_detection import SpeechUtterance, detect_speech_turns


@dataclass(frozen=True, slots=True)
class _OutboundFrame:
    generation: int
    frame: AudioFrame


class _SentenceBuffer:
    """Turn streamed text into short, speakable TTS requests."""

    def __init__(self, max_chars: int = 160) -> None:
        self._text = ""
        self._max_chars = max_chars

    def feed(self, delta: str) -> list[str]:
        self._text += delta
        return self._ready(force=False)

    def flush(self) -> list[str]:
        return self._ready(force=True)

    def _ready(self, *, force: bool) -> list[str]:
        segments: list[str] = []
        while self._text:
            boundary = self._sentence_boundary()
            if boundary is None and len(self._text) >= self._max_chars:
                boundary = self._text.rfind(" ", 0, self._max_chars)
                if boundary < self._max_chars // 2:
                    boundary = self._max_chars
            if boundary is None:
                if force:
                    boundary = len(self._text)
                else:
                    break
            raw = self._text[:boundary]
            self._text = self._text[boundary:]
            spoken = prepare_spoken_text(raw)
            if spoken:
                segments.append(spoken)
        return segments

    def _sentence_boundary(self) -> int | None:
        for match in re.finditer(r"[.!?;:\n]+(?:\s+|$)", self._text):
            if match.end() >= 3:
                return match.end()
        return None


def _is_emoji_codepoint(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint
        in {
            0x00A9,
            0x00AE,
            0x200D,
            0x203C,
            0x2049,
            0x20E3,
            0x2122,
            0x2139,
            0x3030,
            0x303D,
            0x3297,
            0x3299,
            0xFE0F,
        }
        or 0x2300 <= codepoint <= 0x23FF
        or 0x25A0 <= codepoint <= 0x27BF
        or 0x1F000 <= codepoint <= 0x1FAFF
    )


def prepare_spoken_text(text: str) -> str:
    """Remove emoji and lightweight Markdown that should not be pronounced."""
    clean = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    clean = re.sub(r"`([^`]*)`", r"\1", clean)
    clean = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"^[\s>*#-]+", "", clean, flags=re.MULTILINE)
    clean = clean.replace("**", "").replace("__", "").replace("*", "")
    clean = "".join(" " if _is_emoji_codepoint(character) else character for character in clean)
    return " ".join(clean.split()).strip()


def _requests_hangup(text: str) -> bool:
    """Recognize explicit hangup instructions without treating farewells as commands."""

    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = " ".join(normalized.replace("’", "'").split())

    negative_patterns = (
        r"\bne\s+(?:me\s+)?raccroche(?:z)?\s+(?:surtout\s+)?pas\b",
        r"\bne\s+pas\s+raccrocher\b",
        r"\bdo\s+not\s+hang\s+up\b",
        r"\bdon't\s+hang\s+up\b",
    )
    if any(re.search(pattern, normalized) for pattern in negative_patterns):
        return False

    request_patterns = (
        r"\b(?:tu\s+peux|peux[- ]tu|vous\s+pouvez|pouvez[- ]vous|on\s+peut)"
        r"\s+(?:maintenant\s+)?raccrocher\b",
        r"\b(?:merci\s+de|veuillez)\s+raccrocher\b",
        r"(?:^|[.!?]\s*)raccroche(?:z)?(?:\s+maintenant)?(?:[.!?]|$)",
        r"\b(?:mets|mettez|mettre)\s+fin\s+a\s+(?:cet|l')appel\b",
        r"\b(?:termine|terminez|coupe|coupez)\s+(?:maintenant\s+)?l'appel\b",
        r"\b(?:you\s+can|can\s+you|please)\s+hang\s+up\b",
        r"\b(?:end|disconnect)\s+the\s+call\b",
    )
    return any(re.search(pattern, normalized) for pattern in request_patterns)


class _AgentResponseError(RuntimeError):
    """Preserve the internal harness's sanitized terminal error through TaskGroup."""


def _format_turn_exception(exc: Exception) -> str:
    """Unwrap concurrent Voice failures into useful, bounded persistence text."""

    leaves: list[str] = []

    def collect(error: BaseException) -> None:
        if isinstance(error, BaseExceptionGroup):
            group = cast("BaseExceptionGroup[BaseException]", error)
            for nested in group.exceptions:
                collect(nested)
            return
        detail = str(error).strip()
        if isinstance(error, _AgentResponseError):
            rendered = detail or "the configured agent failed during the voice turn"
        else:
            rendered = f"{type(error).__name__}: {detail}" if detail else type(error).__name__
        if rendered not in leaves:
            leaves.append(rendered)

    collect(exc)
    return "\n".join(leaves) or f"{type(exc).__name__}: {exc}"


def _merge_utterance_chunks(
    chunks: list[SpeechUtterance],
) -> SpeechUtterance:
    """Reassemble one continuous human turn split by the detector's size cap."""
    if not chunks:
        raise ValueError("at least one speech chunk is required")
    if len(chunks) == 1:
        return chunks[0]

    sample_rate = chunks[0].sample_rate
    channels = chunks[0].channels
    if any(
        chunk.sample_rate != sample_rate or chunk.channels != channels
        for chunk in chunks[1:]
    ):
        raise ValueError("speech chunks use incompatible PCM formats")

    return SpeechUtterance(
        pcm=b"".join(chunk.pcm for chunk in chunks),
        duration_s=sum(chunk.duration_s for chunk in chunks),
        voiced_s=sum(chunk.voiced_s for chunk in chunks),
        reason=chunks[-1].reason,
        sample_rate=sample_rate,
        channels=channels,
    )


class AgentVoiceEngine:
    """Run STT, the internal conversation executor, and TTS over one live call."""

    def __init__(
        self,
        *,
        transport: CallTransport,
        handle: Any,
        agent_id: int,
        session_id: UUID,
        room_id: str,
        connection_id: int | None = None,
        topic_id: UUID | None = None,
        contact_memory_item_id: UUID | None = None,
        language: str = "fr",
        stop_requested: asyncio.Event | None = None,
        agent_name: str = "Agent",
        caller_external_id: str = "voice-caller",
        caller_name: str = "Caller",
        conversation_room_id: UUID | None = None,
    ) -> None:
        self._transport = transport
        self._handle = handle
        self._agent_id = agent_id
        self._session_id = session_id
        self._connection_id = connection_id
        self._topic_id = topic_id
        self._contact_memory_item_id = contact_memory_item_id
        self._room_id = room_id
        self._conversation_id = str(conversation_room_id or room_id)
        self._conversation_room_id = conversation_room_id
        self._language = language
        self._agent_name = agent_name.strip() or "Agent"
        self._caller_external_id = caller_external_id.strip() or "voice-caller"
        self._caller_name = caller_name.strip() or self._caller_external_id
        self._generation = 0
        self._outbound: asyncio.Queue[_OutboundFrame | None] = asyncio.Queue(maxsize=4000)
        self._outbound_idle = asyncio.Event()
        self._outbound_idle.set()
        self._stop_requested = stop_requested or asyncio.Event()
        self._response_task: asyncio.Task[None] | None = None
        self._history: list[Message] = []
        self._turn_index = 0
        self._pending_turn_indexes: set[int] = set()
        self._pending_message_ids: set[UUID] = set()
        self._pending_transcription_id: UUID | None = None

    async def run(self) -> None:
        from .realtime_engine import RealtimeAgentVoiceEngine

        realtime_engine = await RealtimeAgentVoiceEngine.create(
            transport=self._transport,
            handle=self._handle,
            agent_id=self._agent_id,
            session_id=self._session_id,
            room_id=self._room_id,
            conversation_id=self._conversation_id,
            connection_id=self._connection_id,
            topic_id=self._topic_id,
            contact_memory_item_id=self._contact_memory_item_id,
            language=self._language,
            stop_requested=self._stop_requested,
        )
        if realtime_engine is not None:
            await realtime_engine.run()
            return

        sender = asyncio.create_task(
            self._transport.send_audio(self._handle, self._outbound_frames()),
            name="voice_agent_audio_sender",
        )
        turns = asyncio.create_task(
            self._consume_speech_turns(),
            name="voice_agent_turn_detector",
        )
        stop_waiter = asyncio.create_task(
            self._stop_requested.wait(),
            name="voice_agent_stop_requested",
        )
        self._response_task = asyncio.create_task(
            self._speak_initial_greeting(self._generation),
            name="voice_agent_initial_greeting",
        )
        try:
            done, _ = await asyncio.wait(
                {sender, turns, stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                if task is stop_waiter:
                    continue
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
            if stop_waiter in done:
                await asyncio.gather(
                    self._response_task,
                    return_exceptions=True,
                )
                await self._outbound_idle.wait()
                await self._transport.wait_output_drained(self._handle)
                logger.info(
                    "Voice agent: graceful hangup ready room={}",
                    self._room_id,
                )
        finally:
            await self._interrupt_response()
            for task in (sender, turns, stop_waiter):
                task.cancel()
            await asyncio.gather(sender, turns, stop_waiter, return_exceptions=True)
            if self._pending_transcription_id is not None:
                await self._finish_transcription_progress(
                    self._pending_transcription_id,
                    status="failed",
                )
                self._pending_transcription_id = None

    async def _speak_initial_greeting(self, generation: int) -> None:
        """Acknowledge the answered call while remaining immediately interruptible."""
        from app.llm import tts_service

        greeting = render_prompt(t("voice.initial_greeting", self._language))
        started_at = time.monotonic()
        try:
            async with get_db_session():
                speech = await tts_service.generate_for_agent(
                    self._agent_id,
                    greeting,
                    tts_service.TTSOptions(language=self._language),
                )
            # TTS generation overlaps the transport's normal connection setup.
            # If a remote subscriber is still attaching, retain the encoded
            # greeting instead of losing its first (or only) audio frames.
            await self._transport.wait_input_ready(self._handle)
            await self._transport.wait_output_ready(self._handle)
            async for frame in encoded_audio_frames(speech.content):
                if generation != self._generation:
                    return
                await self._queue_outbound(generation, frame)
            if generation != self._generation:
                return
            self._append_assistant_message(greeting, 0)
            async with get_db_session():
                from . import conversation_service

                await conversation_service.record_initial_greeting(
                    self._session_id,
                    greeting,
                )
            logger.info(
                "Voice agent: initial greeting ready room={} latency={:.2f}s",
                self._room_id,
                time.monotonic() - started_at,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.opt(exception=True).warning(
                "Voice agent: initial greeting failed room={} (call kept alive)",
                self._room_id,
            )

    async def _consume_speech_turns(self) -> None:
        from app.llm import transcription_service

        realtime: transcription_service.RealtimeTranscriber | None = None
        try:
            try:
                async with get_db_session():
                    realtime = (
                        await transcription_service.create_realtime_transcriber(
                            agent_id=self._agent_id,
                            language=self._language,
                        )
                    )
                if realtime is not None:
                    logger.info(
                        "Voice agent: realtime transcription ready room={}",
                        self._room_id,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.opt(exception=True).warning(
                    "Voice agent: realtime transcription unavailable room={} "
                    "(using complete-audio fallback)",
                    self._room_id,
                )

            async def stream_speech_audio(pcm: bytes) -> None:
                nonlocal realtime
                if realtime is None:
                    return
                try:
                    await realtime.send_audio(pcm)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    failed = realtime
                    realtime = None
                    logger.opt(exception=True).warning(
                        "Voice agent: realtime transcription stream failed room={} "
                        "(using complete-audio fallback)",
                        self._room_id,
                    )
                    await failed.close()

            chunks: list[SpeechUtterance] = []
            async for utterance in detect_speech_turns(
                self._transport.inbound_audio(self._handle),
                on_speech_start=self._on_speech_start,
                on_audio=stream_speech_audio,
            ):
                chunks.append(utterance)
                if utterance.reason == "max_duration":
                    continue

                transcript: str | None = None
                if realtime is not None:
                    committed_at = time.monotonic()
                    try:
                        transcript = await realtime.commit()
                        logger.info(
                            "Voice agent: realtime transcript committed room={} "
                            "latency={:.2f}s",
                            self._room_id,
                            time.monotonic() - committed_at,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        failed = realtime
                        realtime = None
                        logger.opt(exception=True).warning(
                            "Voice agent: realtime transcript commit failed room={} "
                            "(using complete-audio fallback)",
                            self._room_id,
                        )
                        await failed.close()

                merged = _merge_utterance_chunks(chunks)
                if transcript is None:
                    await self._start_response(merged)
                else:
                    await self._start_response(merged, transcript=transcript)
                chunks.clear()
        finally:
            if realtime is not None:
                await realtime.close()

    async def _on_speech_start(self) -> None:
        """Cut playback immediately, without waiting for provider cleanup."""
        await self._start_transcription_progress()
        self._generation += 1
        self._drain_outbound()
        await self._transport.interrupt_output(self._handle)
        if self._response_task is not None and not self._response_task.done():
            self._response_task.cancel()
            logger.info(
                "Voice agent: barge-in interrupted generation={} room={}",
                self._generation - 1,
                self._room_id,
            )

    async def _start_response(
        self,
        utterance: SpeechUtterance,
        *,
        transcript: str | None = None,
    ) -> None:
        previous = self._response_task
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        generation = self._generation
        self._turn_index += 1
        transcription_id = self._pending_transcription_id
        self._pending_transcription_id = None
        self._response_task = asyncio.create_task(
            self._respond(
                utterance,
                generation,
                self._turn_index,
                transcript=transcript,
                transcription_id=transcription_id,
            ),
            name=f"voice_agent_response:{self._turn_index}",
        )

    async def _respond(
        self,
        utterance: SpeechUtterance,
        generation: int,
        turn_index: int,
        *,
        transcript: str | None = None,
        transcription_id: UUID | None = None,
    ) -> None:
        started_at = time.monotonic()
        response_parts: list[str] = []
        first_text_at: float | None = None
        first_audio_at: float | None = None
        first_text_timestamp: datetime | None = None
        first_audio_timestamp: datetime | None = None
        conversation_round_id: UUID | None = None
        execution_result: dict[str, object] | None = None
        hangup_after_response = False
        transcription_finished = False
        progress: ConversationRuntimeStream | None = None
        completed_successfully = False
        try:
            transcription_mode = "realtime" if transcript is not None else "batch"
            if transcript is None:
                transcript = await self._transcribe(utterance)
            if generation != self._generation:
                return
            hangup_after_response = _requests_hangup(transcript)
            logger.info(
                "Voice agent: transcribed turn={} room={} chars={} "
                "audio={:.2f}s voiced={:.2f}s endpoint={} mode={} latency={:.2f}s",
                turn_index,
                self._room_id,
                len(transcript),
                utterance.duration_s,
                utterance.voiced_s,
                utterance.reason,
                transcription_mode,
                time.monotonic() - started_at,
            )
            self._append_user_message(transcript, turn_index)
            run_id = uuid4()
            from . import conversation_service

            async with get_db_session():
                conversation_round = await conversation_service.start_turn(
                    session_id=self._session_id,
                    transcript=transcript,
                    run_id=run_id,
                    language=self._language,
                    topic_id=self._topic_id,
                    contact_memory_item_id=self._contact_memory_item_id,
                )
                conversation_round_id = conversation_round.id
                message_id = await conversation_service.record_turn_input(
                    conversation_round.id,
                    transcript,
                )
            self._pending_message_ids.add(message_id)
            await self._finish_transcription_progress(
                transcription_id,
                status="completed",
                message_id=message_id,
            )
            transcription_finished = True
            live_progress = ConversationRuntimeStream(
                room_id=conversation_round.room_id, round_id=conversation_round.id,
                topic_id=conversation_round.topic_id,
            )
            progress = live_progress
            await live_progress.start()
            objective = conversation_round.effective_objective or transcript
            conversation_history = self._conversation_history_for_turn(turn_index)

            text_queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def produce_text() -> None:
                from app.agent import stream_conversation_turn_events

                nonlocal first_text_at, first_text_timestamp, execution_result
                segmenter = _SentenceBuffer()
                driver_error = ""
                try:
                    async with get_db_session():
                        from app.conversation import linked_work_snapshot

                        linked_work = await linked_work_snapshot(
                            conversation_round.room_id
                        )
                        async for event in stream_conversation_turn_events(
                            agent_id=self._agent_id,
                            objective=objective,
                            messenger_connection_id=self._connection_id,
                            conversation_id=str(conversation_round.room_id),
                            room_locator=self._room_id,
                            conversation_history=conversation_history,
                            current_message_id=message_id,
                            excluded_message_ids=tuple(self._pending_message_ids),
                            linked_work=linked_work,
                            language=self._language,
                            transport_kind=self._transport.kind,
                            run_id=run_id,
                            conversation_round_id=conversation_round_id,
                            topic_id=conversation_round.topic_id,
                            contact_memory_item_id=getattr(
                                conversation_round,
                                "contact_memory_item_id",
                                None,
                            ),
                        ):
                            if generation != self._generation:
                                return
                            if event.kind == "result" and event.result is not None:
                                execution_result = live_progress.snapshot(event.result).model_dump(mode="json")
                                continue
                            message = event.message
                            if message is None:
                                continue
                            await live_progress.append(message)
                            if message.type != "text":
                                continue
                            if not message.success:
                                driver_error = (
                                    message.content.strip()
                                    or "the configured agent failed during the voice turn"
                                )
                                continue
                            if first_text_at is None:
                                first_text_at = time.monotonic()
                                first_text_timestamp = datetime.now(timezone.utc)
                                logger.info(
                                    "Voice agent: first text turn={} room={} latency={:.2f}s",
                                    turn_index,
                                    self._room_id,
                                    first_text_at - started_at,
                                )
                            response_parts.append(message.content)
                            for segment in segmenter.feed(message.content):
                                await text_queue.put(segment)
                    if driver_error:
                        raise _AgentResponseError(driver_error)
                finally:
                    for segment in segmenter.flush():
                        await text_queue.put(segment)
                    await text_queue.put(None)

            async def synthesize_text() -> None:
                from app.llm import tts_service

                streamed_segments: list[str] = []

                async def segments() -> AsyncIterator[str]:
                    while True:
                        segment = await text_queue.get()
                        if segment is None:
                            return
                        streamed_segments.append(segment)
                        yield segment

                async def enqueue(frame: AudioFrame) -> None:
                    nonlocal first_audio_at, first_audio_timestamp
                    if generation != self._generation:
                        return
                    if first_audio_at is None:
                        first_audio_at = time.monotonic()
                        first_audio_timestamp = datetime.now(timezone.utc)
                        logger.info(
                            "Voice agent: first audio turn={} room={} latency={:.2f}s",
                            turn_index,
                            self._room_id,
                            first_audio_at - started_at,
                        )
                    await self._queue_outbound(generation, frame)

                speech_stream = None
                try:
                    async with get_db_session():
                        speech_stream = (
                            await tts_service.create_realtime_speech_stream_for_agent(
                                self._agent_id,
                                tts_service.TTSOptions(language=self._language),
                            )
                        )
                except tts_service.TTSStreamingUnavailable:
                    logger.opt(exception=True).warning(
                        "Voice agent: realtime TTS setup unavailable turn={} room={} "
                        "(using encoded-audio fallback)",
                        turn_index,
                        self._room_id,
                    )

                if speech_stream is not None:
                    try:
                        async for frame in pcm_audio_frames(
                            speech_stream.stream(segments()),
                            sample_rate=speech_stream.sample_rate,
                            channels=speech_stream.channels,
                        ):
                            if generation != self._generation:
                                return
                            await enqueue(frame)
                        return
                    except tts_service.TTSStreamingUnavailable:
                        logger.opt(exception=True).warning(
                            "Voice agent: realtime TTS connection unavailable "
                            "turn={} room={} (using encoded-audio fallback)",
                            turn_index,
                            self._room_id,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if first_audio_at is not None:
                            raise
                        logger.opt(exception=True).warning(
                            "Voice agent: realtime TTS failed before playback "
                            "turn={} room={} (using encoded-audio fallback)",
                            turn_index,
                            self._room_id,
                        )

                async def batch_segments() -> AsyncIterator[str]:
                    for segment in streamed_segments:
                        yield segment
                    async for segment in segments():
                        yield segment

                async for segment in batch_segments():
                    if generation != self._generation:
                        return
                    async with get_db_session():
                        speech = await tts_service.generate_for_agent(
                            self._agent_id,
                            segment,
                            tts_service.TTSOptions(language=self._language),
                        )
                    async for frame in encoded_audio_frames(speech.content):
                        if generation != self._generation:
                            return
                        await enqueue(frame)

            async with asyncio.TaskGroup() as group:
                group.create_task(produce_text(), name="voice_agent_llm")
                group.create_task(synthesize_text(), name="voice_agent_tts")

            response = "".join(response_parts).strip()
            if execution_result is None:
                execution_result = live_progress.snapshot().model_dump(mode="json")
            async with get_db_session():
                await conversation_service.record_turn_outputs(
                    conversation_round_id,
                    (response,) if response else (),
                    occurred_at=first_text_timestamp,
                )
                await conversation_service.complete_turn(
                    conversation_round_id,
                    assistant_response=response,
                    execution_result=execution_result,
                    first_text_at=first_text_timestamp,
                    first_audio_at=first_audio_timestamp,
                )
            completed_successfully = True
            self._pending_turn_indexes.clear()
            self._pending_message_ids.clear()
            if response:
                self._append_assistant_message(response, turn_index)
                logger.info(
                    "Voice agent: response ready turn={} room={} chars={} latency={:.2f}s",
                    turn_index,
                    self._room_id,
                    len(response),
                    time.monotonic() - started_at,
                )
            if hangup_after_response:
                self._request_graceful_stop(turn_index)
        except asyncio.CancelledError:
            partial = "".join(response_parts).strip()
            if conversation_round_id is not None:
                self._pending_turn_indexes.add(turn_index)
                await asyncio.shield(
                    self._interrupt_voice_turn(
                        conversation_round_id,
                        partial=partial,
                        execution_result=execution_result,
                        first_text_at=first_text_timestamp,
                        first_audio_at=first_audio_timestamp,
                    )
                )
            raise
        except Exception as exc:
            if conversation_round_id is not None:
                self._pending_turn_indexes.add(turn_index)
                await asyncio.shield(
                    self._fail_voice_turn(
                        conversation_round_id,
                        error=_format_turn_exception(exc),
                        partial="".join(response_parts).strip(),
                        execution_result=execution_result,
                        first_text_at=first_text_timestamp,
                        first_audio_at=first_audio_timestamp,
                    )
                )
            logger.opt(exception=True).warning(
                "Voice agent: turn failed turn={} room={} (call kept alive)",
                turn_index,
                self._room_id,
            )
            if hangup_after_response:
                self._request_graceful_stop(turn_index)
        finally:
            if progress is not None:
                await asyncio.shield(progress.finish(
                    success=completed_successfully,
                    result=AIResult.model_validate(execution_result) if execution_result else None,
                ))
            if not transcription_finished:
                await asyncio.shield(
                    self._finish_transcription_progress(
                        transcription_id,
                        status="failed",
                    )
                )

    async def _transcribe(self, utterance: SpeechUtterance) -> str:
        from app.llm import transcription_service

        wav = pcm_to_wav(
            utterance.pcm,
            sample_rate=utterance.sample_rate,
            channels=utterance.channels,
        )
        async with get_db_session():
            return await transcription_service.transcribe_audio(
                wav,
                filename=f"call-turn-{self._turn_index}.wav",
                mime_type="audio/wav",
                language=self._language,
                agent_id=self._agent_id,
            )

    async def _start_transcription_progress(self) -> None:
        room_id = self._conversation_room_id
        if room_id is None:
            return
        if self._pending_transcription_id is not None:
            await self._finish_transcription_progress(
                self._pending_transcription_id,
                status="failed",
            )
        from .transcription_events import (
            VoiceTranscriptionEvent,
            publish_voice_transcription,
        )

        transcription_id = uuid4()
        self._pending_transcription_id = transcription_id
        await publish_voice_transcription(
            VoiceTranscriptionEvent(
                room_id=room_id,
                transcription_id=transcription_id,
                status="started",
                started_at=datetime.now(timezone.utc),
            )
        )

    async def _finish_transcription_progress(
        self,
        transcription_id: UUID | None,
        *,
        status: Literal["completed", "failed"],
        message_id: UUID | None = None,
    ) -> None:
        room_id = self._conversation_room_id
        if room_id is None or transcription_id is None:
            return
        from .transcription_events import (
            VoiceTranscriptionEvent,
            publish_voice_transcription,
        )

        await publish_voice_transcription(
            VoiceTranscriptionEvent(
                room_id=room_id,
                transcription_id=transcription_id,
                status=status,
                started_at=datetime.now(timezone.utc),
                message_id=message_id,
            )
        )

    async def _outbound_frames(self) -> AsyncIterator[AudioFrame]:
        while True:
            item = await self._outbound.get()
            if item is None:
                self._outbound_idle.set()
                return
            if item.generation == self._generation:
                yield item.frame
            if self._outbound.empty():
                self._outbound_idle.set()

    async def _queue_outbound(self, generation: int, frame: AudioFrame) -> None:
        self._outbound_idle.clear()
        try:
            await self._outbound.put(_OutboundFrame(generation, frame))
        except BaseException:
            if self._outbound.empty():
                self._outbound_idle.set()
            raise

    def _request_graceful_stop(self, turn_index: int) -> None:
        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        logger.info(
            "Voice agent: explicit hangup requested turn={} room={}",
            turn_index,
            self._room_id,
        )

    async def _interrupt_response(self) -> None:
        self._generation += 1
        self._drain_outbound()
        await self._transport.interrupt_output(self._handle)
        task = self._response_task
        self._response_task = None
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def _drain_outbound(self) -> None:
        while True:
            try:
                self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                self._outbound_idle.set()
                return

    def _append_user_message(self, transcript: str, turn_index: int) -> None:
        self._history.append(
            Message(
                external_message_id=f"voice-user-{turn_index}",
                timestamp=int(time.time()),
                text=transcript,
                sender_external_id=self._caller_external_id,
                sender_display_name=self._caller_name,
            )
        )
        self._trim_history()

    def _append_assistant_message(self, response: str, turn_index: int) -> None:
        self._history.append(
            Message(
                external_message_id=f"voice-agent-{turn_index}",
                timestamp=int(time.time()),
                text=response,
                sender_external_id=f"voice-agent-{self._agent_id}",
                sender_display_name=self._agent_name,
                sender_agent_id=self._agent_id,
                sender_is_ai=True,
            )
        )
        self._trim_history()

    def _conversation_history_for_turn(
        self,
        current_turn_index: int,
    ) -> tuple[Message, ...]:
        """Exclude unanswered fragments already represented by the effective objective."""

        excluded = {
            *(f"voice-user-{index}" for index in self._pending_turn_indexes),
            f"voice-user-{current_turn_index}",
        }
        return tuple(
            message
            for message in self._history
            if message.external_message_id not in excluded
        )

    async def _interrupt_voice_turn(
        self,
        turn_id: UUID,
        *,
        partial: str,
        execution_result: dict[str, object] | None,
        first_text_at: datetime | None,
        first_audio_at: datetime | None,
    ) -> None:
        from . import conversation_service

        async with get_db_session():
            try:
                await conversation_service.record_turn_outputs(
                    turn_id,
                    (partial,) if partial else (),
                    occurred_at=first_text_at,
                )
            finally:
                await conversation_service.interrupt_turn(
                    turn_id,
                    assistant_response=partial,
                    execution_result=execution_result,
                    first_text_at=first_text_at,
                    first_audio_at=first_audio_at,
                )

    async def _fail_voice_turn(
        self,
        turn_id: UUID,
        *,
        error: str,
        partial: str,
        execution_result: dict[str, object] | None,
        first_text_at: datetime | None,
        first_audio_at: datetime | None,
    ) -> None:
        from . import conversation_service

        async with get_db_session():
            try:
                await conversation_service.record_turn_outputs(
                    turn_id,
                    (partial,) if partial else (),
                    occurred_at=first_text_at,
                )
            finally:
                await conversation_service.fail_turn(
                    turn_id,
                    error=error,
                    assistant_response=partial,
                    execution_result=execution_result,
                    first_text_at=first_text_at,
                    first_audio_at=first_audio_at,
                )

    def _trim_history(self) -> None:
        if len(self._history) > 20:
            del self._history[:-20]
