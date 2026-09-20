"""Transport-neutral voice-call session orchestration."""

from __future__ import annotations

import asyncio
from uuid import UUID

from loguru import logger
from core.database import get_db_session

from .audio_devices import PulseAudioBridge, PulseAudioConfig, PulseAudioDevices
from .interface import CallTransport
from .engine import AgentVoiceEngine
from .models import VoiceConversationSession, VoiceConversationStatus
from .relay import relay_call_audio


class VoiceSession:
    """Call lifecycle: join, relay audio, and leave."""

    def __init__(
        self,
        transport: CallTransport,
        room_id: str,
        *,
        connection_id: int | None = None,
        remote_user_ids: tuple[str, ...] = (),
        conversation_room_id: UUID | None = None,
    ) -> None:
        self._transport = transport
        self._room_id = room_id
        self._connection_id = connection_id
        self._remote_user_ids = remote_user_ids
        self._conversation_room_id = conversation_room_id

    async def run_echo(self) -> None:
        """Loop inbound audio back to the caller for pipeline validation."""
        handle = await self._transport.join(self._room_id)
        logger.info("Voice[{}]: joined echo call in {}", self._transport.kind, self._room_id)
        try:
            # ``inbound_audio`` is directly consumable by ``send_audio``.
            await self._wait_relay_or_call_end(
                handle,
                [
                    asyncio.create_task(
                        self._transport.send_audio(handle, self._transport.inbound_audio(handle)),
                        name="voice_echo",
                    )
                ],
            )
        finally:
            await self._transport.leave(handle)
            logger.info("Voice[{}]: left call ({})", self._transport.kind, self._room_id)

    async def run_pulseaudio(
        self,
        *,
        devices: PulseAudioDevices | None = None,
        config: PulseAudioConfig | None = None,
    ) -> None:
        """Relay a call through virtual PulseAudio source and sink devices."""
        if devices is not None:
            await self._run_with_pulse_devices(devices)
            return

        async with PulseAudioBridge(self._room_id, config=config) as created:
            await self._run_with_pulse_devices(created)

    async def _run_with_pulse_devices(self, devices: PulseAudioDevices) -> None:
        handle = await self._transport.join(self._room_id)
        logger.info(
            "Voice[{}]: joined PulseAudio call in {} source={} sink={}",
            self._transport.kind,
            self._room_id,
            devices.source_name,
            devices.sink_name,
        )
        try:
            await self._wait_relay_or_call_end(
                handle,
                [
                    asyncio.create_task(
                        relay_call_audio(self._transport, handle, devices),
                        name="voice_pulse_relay",
                    )
                ],
            )
        finally:
            await self._transport.leave(handle)
            logger.info("Voice[{}]: left call ({})", self._transport.kind, self._room_id)

    async def run_agent(
        self,
        *,
        agent_id: int,
        language: str = "fr",
        stop_requested: asyncio.Event | None = None,
    ) -> None:
        """Run a direct STT → configured agent → TTS conversation."""
        from . import conversation_service

        stop_event = stop_requested or asyncio.Event()
        handle = await self._transport.join(self._room_id)
        logger.info(
            "Voice[{}]: joined direct agent call room={} agent={}",
            self._transport.kind,
            self._room_id,
            agent_id,
        )
        conversation: VoiceConversationSession | None = None
        try:
            if self._connection_id is None:
                raise RuntimeError("An agent voice call requires a Messenger connection.")
            async with get_db_session():
                contact_memory_item_id = None
                remote_user_ids = tuple(
                    dict.fromkeys(
                        (*self._remote_user_ids, *self._transport.remote_user_ids(handle))
                    )
                )
                if len(remote_user_ids) == 1:
                    from app.memory import (
                        MessengerContactObservation,
                        observe_messenger_contact,
                    )

                    try:
                        contact_memory_item_id = await observe_messenger_contact(
                            MessengerContactObservation(
                                owner_agent_id=agent_id,
                                messaging_id=self._transport.kind,
                                user_id=remote_user_ids[0],
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Voice contact projection failed; private memory capture "
                            "will remain disabled room={}",
                            self._room_id,
                        )
                elif len(remote_user_ids) > 1:
                    logger.warning(
                        "Voice conversation has multiple remote contacts; private memory capture "
                        "will remain disabled room={} contact_count={}",
                        self._room_id,
                        len(remote_user_ids),
                    )
                conversation = await conversation_service.start_session(
                    agent_id=agent_id,
                    connection_id=self._connection_id,
                    transport_kind=self._transport.kind,
                    room_id=self._room_id,
                    language=language,
                    contact_memory_item_id=contact_memory_item_id,
                    call_external_id=(
                        self._transport.call_external_id(handle).strip() or None
                    ),
                    participant_external_ids=remote_user_ids,
                    conversation_room_id=self._conversation_room_id,
                )
                from app.messenger import get_audio_room_speakers

                speakers = await get_audio_room_speakers(
                    room_id=conversation.messenger_room_id,
                    agent_id=agent_id,
                )
                participant = (
                    speakers.participants[0]
                    if len(speakers.participants) == 1
                    else None
                )
            engine = AgentVoiceEngine(
                transport=self._transport,
                handle=handle,
                agent_id=agent_id,
                session_id=conversation.id,
                connection_id=self._connection_id,
                topic_id=None,
                contact_memory_item_id=contact_memory_item_id,
                room_id=self._room_id,
                conversation_room_id=conversation.messenger_room_id,
                language=language,
                stop_requested=stop_event,
                agent_name=(
                    speakers.agent.display_name
                    if speakers.agent is not None
                    else "Agent"
                ),
                caller_external_id=(
                    participant.external_id
                    if participant is not None
                    else "voice-caller"
                ),
                caller_name=(
                    participant.display_name
                    if participant is not None
                    else "Caller"
                ),
            )
            await self._wait_relay_or_call_end(
                handle,
                [asyncio.create_task(engine.run(), name="voice_direct_agent")],
            )
        except asyncio.CancelledError:
            if conversation is not None:
                async with get_db_session():
                    await conversation_service.finish_session(
                        conversation.id,
                        VoiceConversationStatus.CANCELLED,
                    )
            raise
        except Exception as exc:
            if conversation is not None:
                async with get_db_session():
                    await conversation_service.finish_session(
                        conversation.id,
                        VoiceConversationStatus.ERROR,
                        error=str(exc).strip() or type(exc).__name__,
                    )
            raise
        else:
            async with get_db_session():
                await conversation_service.finish_session(
                    conversation.id,
                    VoiceConversationStatus.COMPLETED,
                )
        finally:
            if stop_event.is_set():
                await self._transport.terminate(handle)
                logger.info(
                    "Voice[{}]: terminated call ({})",
                    self._transport.kind,
                    self._room_id,
                )
            else:
                await self._transport.leave(handle)
                logger.info(
                    "Voice[{}]: left call ({})",
                    self._transport.kind,
                    self._room_id,
                )

    async def _wait_relay_or_call_end(
        self,
        handle: object,
        tasks: list[asyncio.Task[None]],
    ) -> None:
        end_task = asyncio.create_task(
            self._transport.wait_ended(handle),
            name="voice_call_remote_end",
        )
        watched: list[asyncio.Task[None]] = [*tasks, end_task]
        try:
            done, _pending = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            if end_task in done:
                if not end_task.cancelled():
                    exc = end_task.exception()
                    if exc is not None:
                        raise exc
                logger.info("Voice[{}]: remote call end detected ({})", self._transport.kind, self._room_id)
                return
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    raise exc
        finally:
            for task in watched:
                task.cancel()
            await asyncio.gather(*watched, return_exceptions=True)
