"""Provider-neutral realtime audio conversation engine."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from loguru import logger
from app.agent import AIMessage
from app.conversation import ConversationRuntimeStream

from app.llm.provider_facade import (
    RealtimeConversationProvider,
    RealtimeConversationSession,
    realtime_conversation_provider_for,
)
from core.database import get_db_session
from core.i18n import render_prompt, t

from .audio import (
    FRAME_BYTES,
    downsample_pcm_48k_to_24k,
    pcm_audio_frames,
    upsample_pcm_24k_to_48k,
)
from .interface import CallTransport
from .models import AudioFrame
from .realtime_tools import (
    RealtimeTool,
    execute_realtime_tool,
    realtime_tools,
)


@dataclass(frozen=True, slots=True)
class _RealtimeConfiguration:
    service: RealtimeConversationProvider
    connection: Any
    model: str
    voice: str
    voice_resource_id: int | None
    native_audio: bool


@dataclass(frozen=True, slots=True)
class _OutboundFrame:
    generation: int
    frame: AudioFrame


class _TextSegmenter:
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
            boundary: int | None = None
            match = re.search(r"[.!?;:\n]+(?:\s+|$)", self._text)
            if match is not None:
                boundary = match.end()
            elif len(self._text) >= self._max_chars:
                split = self._text.rfind(" ", 0, self._max_chars)
                boundary = split if split >= self._max_chars // 2 else self._max_chars
            elif force:
                boundary = len(self._text)
            if boundary is None:
                break
            text = " ".join(self._text[:boundary].split()).strip()
            self._text = self._text[boundary:]
            if text:
                segments.append(text)
        return segments


async def _configuration_for_agent(
    agent_id: int,
) -> _RealtimeConfiguration | None:
    from app.agent import agent_service
    from app.agent.voice import parse_voice_selection
    from app.llm import llm_provider_service, llm_service
    from app.llm.resource_discovery import provider_connection

    agent = await agent_service.get(agent_id)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")
    selection = parse_voice_selection(getattr(agent, "voice", None))
    if selection is None or selection.mode != "realtime":
        return None
    model_resource = await llm_service.get_llm(selection.model_id)
    if (
        model_resource is None
        or "realtime_conversation" not in model_resource.service_capabilities
        or not model_resource.provider.is_active
    ):
        raise RuntimeError("the configured realtime model is unavailable")
    connection = provider_connection(
        model_resource.provider,
        llm_provider_service.decrypt_api_key(model_resource.provider.api_key),
    )
    service = realtime_conversation_provider_for(connection)
    if service is None:
        raise RuntimeError(
            f"provider {model_resource.provider.name} has no realtime conversation bridge"
        )
    assert selection.voice_code is not None
    return _RealtimeConfiguration(
        service=service,
        connection=connection,
        model=model_resource.llm_name,
        voice=selection.voice_code,
        voice_resource_id=None,
        native_audio=True,
    )


async def realtime_voice_available_for_agent(agent_id: int) -> bool:
    """Return whether an agent's native audio conversation selection is usable."""

    try:
        return await _configuration_for_agent(agent_id) is not None
    except (RuntimeError, ValueError):
        return False


class RealtimeAgentVoiceEngine:
    """Stream transport audio through one stateful provider conversation."""

    def __init__(
        self,
        *,
        transport: CallTransport,
        handle: Any,
        agent_id: int,
        session_id: UUID,
        room_id: str,
        connection_id: int | None,
        topic_id: UUID | None,
        contact_memory_item_id: UUID | None,
        language: str,
        stop_requested: asyncio.Event,
        configuration: _RealtimeConfiguration,
        conversation_id: str | None = None,
    ) -> None:
        self._transport = transport
        self._handle = handle
        self._agent_id = agent_id
        self._session_id = session_id
        self._room_id = room_id
        self._conversation_id = conversation_id or room_id
        self._connection_id = connection_id
        self._topic_id = topic_id
        self._contact_memory_item_id = contact_memory_item_id
        self._language = language
        self._stop_requested = stop_requested
        self._hangup_requested = asyncio.Event()
        self._configuration = configuration
        self._provider: RealtimeConversationSession | None = None
        self._tools: tuple[RealtimeTool, ...] = realtime_tools(
            agent_id=agent_id,
            conversation_id=self._conversation_id,
            transport_kind=transport.kind,
            language=language,
            topic_id=topic_id,
            contact_memory_item_id=contact_memory_item_id,
            voice_session_id=session_id,
            current_round_id=lambda: self._current_turn_id,
            hangup_requested=self._hangup_requested,
        )
        self._generation = 0
        self._outbound: asyncio.Queue[_OutboundFrame] = asyncio.Queue(maxsize=4000)
        self._outbound_idle = asyncio.Event()
        self._outbound_idle.set()
        self._current_turn_id: UUID | None = None
        self._live_stream: ConversationRuntimeStream | None = None
        self._current_response_id = ""
        self._current_output_item_id = ""
        self._response_text: list[str] = []
        self._tool_response_ids: set[str] = set()
        self._first_text_at: datetime | None = None
        self._first_audio_at: datetime | None = None
        self._playback_started: float | None = None
        self._queued_audio_ms = 0
        self._native_pcm_carry = bytearray()
        self._text_queue: asyncio.Queue[str | None] | None = None
        self._text_segmenter: _TextSegmenter | None = None
        self._tts_task: asyncio.Task[None] | None = None
        self._greeting_recorded = False

    @classmethod
    async def create(
        cls,
        *,
        transport: CallTransport,
        handle: Any,
        agent_id: int,
        session_id: UUID,
        room_id: str,
        connection_id: int | None,
        language: str,
        stop_requested: asyncio.Event,
        topic_id: UUID | None = None,
        contact_memory_item_id: UUID | None = None,
        conversation_id: str | None = None,
    ) -> RealtimeAgentVoiceEngine | None:
        async with get_db_session():
            configuration = await _configuration_for_agent(agent_id)
        if configuration is None:
            return None
        return cls(
            transport=transport,
            handle=handle,
            agent_id=agent_id,
            session_id=session_id,
            room_id=room_id,
            connection_id=connection_id,
            topic_id=topic_id,
            contact_memory_item_id=contact_memory_item_id,
            language=language,
            stop_requested=stop_requested,
            configuration=configuration,
            conversation_id=conversation_id,
        )

    async def run(self) -> None:
        from app.agent import build_realtime_agent_context

        async with get_db_session():
            from app.conversation import linked_work_snapshot

            try:
                conversation_room_id = UUID(self._conversation_id)
            except ValueError:
                linked_work = ()
            else:
                linked_work = await linked_work_snapshot(conversation_room_id)
            context = await build_realtime_agent_context(
                agent_id=self._agent_id,
                conversation_id=self._conversation_id,
                transport_kind=self._transport.kind,
                language=self._language,
                messenger_connection_id=self._connection_id,
                topic_id=self._topic_id,
                contact_memory_item_id=self._contact_memory_item_id,
                linked_work=linked_work,
            )
        self._provider = await self._configuration.service.create_realtime_session(
            self._configuration.connection,
            model=self._configuration.model,
            voice=(
                self._configuration.voice
                if self._configuration.native_audio
                else None
            ),
            instructions=context.instructions,
            tools=tuple(tool.definition for tool in self._tools),
            output_audio=self._configuration.native_audio,
        )
        logger.info(
            "Voice agent: realtime session ready room={} model={} voice={} native_audio={}",
            self._room_id,
            self._configuration.model,
            self._configuration.voice,
            self._configuration.native_audio,
        )
        inbound = asyncio.create_task(
            self._send_inbound_audio(),
            name="voice_realtime_audio_input",
        )
        tasks: list[asyncio.Task[Any]] = [inbound]
        try:
            # Consume remote media before prompting the caller. This also keeps
            # everything spoken during startup in the provider's input buffer.
            await self._transport.wait_input_ready(self._handle)
            await self._transport.wait_output_ready(self._handle)
            await self._provider.request_response(
                render_prompt(t("voice.initial_greeting", self._language))
            )

            sender = asyncio.create_task(
                self._transport.send_audio(self._handle, self._outbound_frames()),
                name="voice_realtime_audio_sender",
            )
            receiver = asyncio.create_task(
                self._receive_events(),
                name="voice_realtime_events",
            )
            stop_waiter = asyncio.create_task(
                self._stop_requested.wait(),
                name="voice_realtime_stop_requested",
            )
            tasks.extend((sender, receiver, stop_waiter))
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is stop_waiter or task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._cancel_tts()
            if self._current_turn_id is not None:
                await self._interrupt_current_turn()
            await self._provider.close()
            self._provider = None

    async def _send_inbound_audio(self) -> None:
        assert self._provider is not None
        async for frame in self._transport.inbound_audio(self._handle):
            if frame.sample_rate != 48_000 or frame.channels != 1:
                raise ValueError("realtime voice input must use canonical 48 kHz mono PCM")
            await self._provider.send_audio(downsample_pcm_48k_to_24k(frame.pcm))

    async def _receive_events(self) -> None:
        assert self._provider is not None
        while True:
            event = await self._provider.receive()
            if event.kind == "speech_started":
                await self._on_speech_started()
            elif event.kind == "input_committed":
                await self._start_audio_turn()
            elif event.kind == "response_started":
                await self._start_response(event.response_id)
            elif event.kind == "output_item":
                if event.item_id:
                    self._current_output_item_id = event.item_id
            elif event.kind == "audio_delta":
                await self._on_native_audio(event.audio, event.item_id)
            elif event.kind == "text_delta":
                await self._on_text(event.text)
            elif event.kind == "audio_transcript_delta":
                await self._on_assistant_transcript(event.text)
            elif event.kind == "function_call":
                await self._on_function_call(
                    response_id=event.response_id,
                    call_id=event.call_id,
                    name=event.tool_name,
                    arguments=event.arguments,
                )
            elif event.kind == "response_done":
                await self._finish_response(event.response_id)
            elif event.kind == "response_cancelled":
                if event.response_id and event.response_id != self._current_response_id:
                    continue
                await self._finish_external_tts()
                await self._interrupt_current_turn()
            elif event.kind == "error":
                raise RuntimeError(event.error or "the Realtime provider failed")

    async def _on_speech_started(self) -> None:
        provider = self._provider
        if provider is None:
            return
        played_ms = self._estimated_played_ms()
        item_id = self._current_output_item_id
        self._generation += 1
        self._drain_outbound()
        self._native_pcm_carry.clear()
        await self._transport.interrupt_output(self._handle)
        await self._cancel_tts()
        if item_id:
            await provider.truncate(item_id, played_ms)
        if self._current_turn_id is not None:
            await self._interrupt_current_turn()
        self._reset_response_state()

    async def _start_audio_turn(self) -> None:
        from . import conversation_service

        if self._current_turn_id is not None:
            await self._interrupt_current_turn()
        async with get_db_session():
            turn = await conversation_service.start_audio_turn(
                session_id=self._session_id,
                run_id=uuid4(),
                language=self._language,
                topic_id=self._topic_id,
                contact_memory_item_id=self._contact_memory_item_id,
            )
            self._current_turn_id = turn.id
        self._live_stream = ConversationRuntimeStream(
            room_id=turn.room_id, round_id=turn.id, topic_id=turn.topic_id,
        )
        await self._live_stream.start()

    async def _start_response(self, response_id: str) -> None:
        self._current_response_id = response_id
        self._response_text = []
        self._first_text_at = None
        self._first_audio_at = None
        self._current_output_item_id = ""
        self._playback_started = None
        self._queued_audio_ms = 0
        self._native_pcm_carry.clear()
        if not self._configuration.native_audio:
            self._text_queue = asyncio.Queue()
            self._text_segmenter = _TextSegmenter()
            generation = self._generation
            self._tts_task = asyncio.create_task(
                self._synthesize_external_voice(generation, self._text_queue),
                name=f"voice_realtime_tts:{response_id}",
            )

    async def _on_native_audio(self, pcm: bytes, item_id: str) -> None:
        if item_id:
            self._current_output_item_id = item_id
        if not pcm:
            return
        self._native_pcm_carry.extend(upsample_pcm_24k_to_48k(pcm))
        while len(self._native_pcm_carry) >= FRAME_BYTES:
            frame = AudioFrame(pcm=bytes(self._native_pcm_carry[:FRAME_BYTES]))
            del self._native_pcm_carry[:FRAME_BYTES]
            await self._queue_outbound(self._generation, frame)

    async def _on_text(self, delta: str) -> None:
        if not delta:
            return
        await self._on_assistant_transcript(delta)
        queue = self._text_queue
        segmenter = self._text_segmenter
        if queue is None or segmenter is None:
            return
        for segment in segmenter.feed(delta):
            await queue.put(segment)

    async def _on_assistant_transcript(self, delta: str) -> None:
        if not delta:
            return
        if self._first_text_at is None:
            self._first_text_at = datetime.now(timezone.utc)
        self._response_text.append(delta)
        if self._live_stream is not None:
            await self._live_stream.append(AIMessage(
                type="text", content=delta,
                stream_id=f"voice:{self._current_response_id}",
            ))

    async def _on_function_call(
        self,
        *,
        response_id: str,
        call_id: str,
        name: str,
        arguments: str,
    ) -> None:
        assert self._provider is not None
        self._tool_response_ids.add(response_id)
        output = await execute_realtime_tool(
            self._tools,
            name=name,
            arguments=arguments,
        )
        await self._provider.send_function_output(call_id, output)
        logger.info(
            "Voice agent: realtime tool executed room={} tool={} call_id={}",
            self._room_id,
            name,
            call_id,
        )

    async def _finish_response(self, response_id: str) -> None:
        assert self._provider is not None
        await self._finish_external_tts()
        if response_id in self._tool_response_ids:
            self._tool_response_ids.discard(response_id)
            await self._provider.request_response()
            return
        if self._current_turn_id is not None:
            from . import conversation_service

            turn_id = self._current_turn_id
            response = "".join(self._response_text).strip()
            async with get_db_session():
                await conversation_service.record_turn_outputs(
                    turn_id,
                    (response,),
                    occurred_at=self._first_text_at,
                )
                await conversation_service.complete_turn(
                    turn_id,
                    assistant_response=response,
                    execution_result=(self._live_stream.snapshot().model_dump(mode="json")
                                      if self._live_stream else None),
                    first_text_at=self._first_text_at,
                    first_audio_at=self._first_audio_at,
                )
            if self._live_stream is not None:
                await self._live_stream.finish(success=True)
                self._live_stream = None
            self._current_turn_id = None
        elif not self._greeting_recorded:
            from . import conversation_service

            response = "".join(self._response_text).strip()
            async with get_db_session():
                await conversation_service.record_initial_greeting(
                    self._session_id,
                    response,
                    occurred_at=self._first_text_at,
                )
            self._greeting_recorded = True
        self._reset_response_state()
        if self._hangup_requested.is_set():
            await self._outbound_idle.wait()
            await self._transport.wait_output_drained(self._handle)
            self._stop_requested.set()
            logger.info(
                "Voice agent: realtime graceful hangup ready room={}",
                self._room_id,
            )

    async def _synthesize_external_voice(
        self,
        generation: int,
        queue: asyncio.Queue[str | None],
    ) -> None:
        from app.llm import tts_service

        voice_resource_id = self._configuration.voice_resource_id
        if voice_resource_id is None:
            raise RuntimeError("the external realtime voice resource is missing")

        async def segments() -> AsyncIterator[str]:
            while True:
                segment = await queue.get()
                if segment is None:
                    return
                yield segment

        async with get_db_session():
            stream = await tts_service.create_realtime_speech_stream_for_resource(
                voice_resource_id,
                tts_service.TTSOptions(language=self._language),
            )
        if stream is None:
            raise RuntimeError(
                "the selected external voice does not support realtime streaming"
            )
        async for frame in pcm_audio_frames(
            stream.stream(segments()),
            sample_rate=stream.sample_rate,
            channels=stream.channels,
        ):
            if generation != self._generation:
                return
            await self._queue_outbound(generation, frame)

    async def _finish_external_tts(self) -> None:
        queue = self._text_queue
        segmenter = self._text_segmenter
        task = self._tts_task
        self._text_queue = None
        self._text_segmenter = None
        self._tts_task = None
        if queue is not None:
            if segmenter is not None:
                for segment in segmenter.flush():
                    await queue.put(segment)
            await queue.put(None)
        if task is not None:
            await task

    async def _cancel_tts(self) -> None:
        task = self._tts_task
        self._tts_task = None
        self._text_queue = None
        self._text_segmenter = None
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _interrupt_current_turn(self) -> None:
        from . import conversation_service

        turn_id = self._current_turn_id
        self._current_turn_id = None
        progress = self._live_stream
        self._live_stream = None
        if turn_id is None:
            return
        try:
            async with get_db_session():
                try:
                    await conversation_service.record_turn_outputs(
                        turn_id,
                        ("".join(self._response_text).strip(),),
                        occurred_at=self._first_text_at,
                    )
                finally:
                    await conversation_service.interrupt_turn(
                        turn_id,
                        assistant_response="".join(self._response_text).strip(),
                        execution_result=progress.snapshot().model_dump(mode="json") if progress else None,
                        first_text_at=self._first_text_at,
                        first_audio_at=self._first_audio_at,
                    )
        finally:
            if progress is not None:
                await progress.finish(success=False)

    async def _outbound_frames(self) -> AsyncIterator[AudioFrame]:
        while True:
            item = await self._outbound.get()
            if item.generation == self._generation:
                yield item.frame
            if self._outbound.empty():
                self._outbound_idle.set()

    async def _queue_outbound(self, generation: int, frame: AudioFrame) -> None:
        if self._first_audio_at is None:
            self._first_audio_at = datetime.now(timezone.utc)
            self._playback_started = time.monotonic()
        self._queued_audio_ms += 20
        self._outbound_idle.clear()
        try:
            await self._outbound.put(_OutboundFrame(generation, frame))
        except BaseException:
            if self._outbound.empty():
                self._outbound_idle.set()
            raise

    def _estimated_played_ms(self) -> int:
        if self._playback_started is None:
            return 0
        elapsed = int((time.monotonic() - self._playback_started) * 1000)
        return max(0, min(self._queued_audio_ms, elapsed))

    def _drain_outbound(self) -> None:
        while True:
            try:
                self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                self._outbound_idle.set()
                return

    def _reset_response_state(self) -> None:
        self._current_response_id = ""
        self._current_output_item_id = ""
        self._response_text = []
        self._first_text_at = None
        self._first_audio_at = None
        self._playback_started = None
        self._queued_audio_ms = 0
        self._native_pcm_carry.clear()


__all__ = ["RealtimeAgentVoiceEngine", "realtime_voice_available_for_agent"]
