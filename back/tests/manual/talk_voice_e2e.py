"""Validate the complete Talk → STT → agent → TTS → Talk audio loop.

This creates two genuine WebRTC/HPB media sessions with the configured Talk
account. One runs the selected Galaris agent; the other speaks a synthetic
utterance and retranscribes the received answer.

Usage:
    TALK_ROOM_TOKEN=<token> docker compose exec backend \
        python scripts/manual_test.py tests/manual/talk_voice_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import unicodedata
from collections.abc import AsyncIterator
from typing import Any

from app.llm import transcription_service, tts_service
from app.voice.audio import encoded_audio_frames, pcm_to_wav
from app.voice import conversation_service
from app.voice.engine import AgentVoiceEngine
from app.voice.models import AudioFrame, VoiceConversationStatus
from app.voice.turn_detection import detect_speech_turns
from bridge.nextcloud.call import TalkCall


CONNECTION_ID = int(os.getenv("TALK_CONNECTION_ID", "1"))
AGENT_ID = int(os.getenv("TALK_AGENT_ID", "1"))
ROOM_TOKEN = os.getenv("TALK_ROOM_TOKEN", "").strip()
PROMPT = os.getenv(
    "TALK_E2E_PROMPT",
    "Réponds uniquement par les mots : test audio réussi.",
).strip()
SECOND_PROMPT = os.getenv(
    "TALK_E2E_SECOND_PROMPT",
    "Réponds uniquement par les mots : test audio réussi.",
).strip()
# The full agent may naturally paraphrase despite the prompt; the transport
# assertion only needs a stable semantic marker that proves the round trip.
EXPECTED = os.getenv("TALK_E2E_EXPECTED", "réussi").strip()
SECOND_EXPECTED = os.getenv(
    "TALK_E2E_SECOND_EXPECTED",
    "réussi",
).strip()
FORCE_RESUME = os.getenv("TALK_E2E_FORCE_RESUME", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}


async def _spoken_frames(content: bytes) -> AsyncIterator[AudioFrame]:
    silence = AudioFrame(pcm=b"\x00\x00" * 960)
    for _ in range(50):
        yield silence
    async for frame in encoded_audio_frames(content):
        yield frame
    for _ in range(40):
        yield silence


def _media_connected(handle: Any) -> bool:
    subscribers = getattr(handle, "subs", {})
    return bool(subscribers) and any(
        getattr(peer, "connectionState", "") in {"connected", "completed"}
        for peer in subscribers.values()
    )


async def _wait_for_media(*handles: Any) -> None:
    async with asyncio.timeout(30.0):
        while not all(_media_connected(handle) for handle in handles):
            await asyncio.sleep(0.1)


async def _force_hpb_resume(handle: Any) -> None:
    old_ws = handle.ws
    old_session = handle.sig_session
    await old_ws.close()
    async with asyncio.timeout(15.0):
        while handle.ws is old_ws or not handle.ws_ready.is_set():
            await asyncio.sleep(0.1)
    if handle.sig_session != old_session:
        raise AssertionError("HPB resume changed the signaling session")


def _normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


async def main() -> None:
    if not ROOM_TOKEN:
        raise ValueError("TALK_ROOM_TOKEN is required")

    probes = (
        (PROMPT, EXPECTED),
        (SECOND_PROMPT, SECOND_EXPECTED),
    )
    sources = [
        await tts_service.generate_for_agent(
            AGENT_ID,
            prompt,
            tts_service.TTSOptions(language="fr"),
        )
        for prompt, _ in probes
    ]
    agent_transport = await TalkCall.from_connection_id(
        CONNECTION_ID,
        start_call=False,
    )
    peer_transport = await TalkCall.from_connection_id(
        CONNECTION_ID,
        start_call=False,
    )
    agent_handle: Any = None
    peer_handle: Any = None
    engine_task: asyncio.Task[None] | None = None
    turns: Any = None
    answer_task: asyncio.Task[Any] | None = None
    conversation_id = None
    try:
        agent_handle = await agent_transport.join(ROOM_TOKEN)
        conversation = await conversation_service.start_session(
            agent_id=AGENT_ID,
            connection_id=CONNECTION_ID,
            transport_kind=agent_transport.kind,
            room_id=ROOM_TOKEN,
            language="fr",
        )
        conversation_id = conversation.id
        engine = AgentVoiceEngine(
            transport=agent_transport,
            handle=agent_handle,
            agent_id=AGENT_ID,
            session_id=conversation.id,
            room_id=ROOM_TOKEN,
            language="fr",
        )
        engine_task = asyncio.create_task(engine.run(), name="talk_voice_e2e_agent")

        peer_handle = await peer_transport.join(ROOM_TOKEN)
        await _wait_for_media(agent_handle, peer_handle)
        if FORCE_RESUME:
            await _force_hpb_resume(agent_handle)
        # Let the automatic greeting finish, then discard it. Its level after
        # two Opus hops is deliberately not used as the E2E detector baseline.
        await asyncio.sleep(4.0)
        while True:
            try:
                peer_handle.in_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # The peer receives an already encoded/decoded Talk stream, whose RMS
        # is lower than a local microphone capture. Use a sensitive threshold
        # here so the transport probe can segment the synthetic TTS reliably.
        turns = detect_speech_turns(
            peer_transport.inbound_audio(peer_handle),
            rms_threshold=50,
        )
        for turn_index, (source, (_, expected)) in enumerate(
            zip(sources, probes, strict=True),
            start=1,
        ):
            answer_task = asyncio.create_task(
                anext(turns),
                name=f"talk_voice_e2e_answer:{turn_index}",
            )
            await peer_transport.send_audio(
                peer_handle,
                _spoken_frames(source.content),
            )
            utterance = await asyncio.wait_for(answer_task, timeout=45.0)
            answer_task = None
            transcript = await transcription_service.transcribe_audio(
                pcm_to_wav(utterance.pcm),
                filename=f"talk-e2e-answer-{turn_index}.wav",
                mime_type="audio/wav",
                language="fr",
            )
            print(f"TALK_VOICE_E2E_RESULT_{turn_index}={transcript}")
            if _normalized(expected) not in _normalized(transcript):
                raise AssertionError(
                    f"Turn {turn_index}: expected {expected!r} in the received "
                    f"answer, got {transcript!r}"
                )
    finally:
        if answer_task is not None and not answer_task.done():
            answer_task.cancel()
            await asyncio.gather(answer_task, return_exceptions=True)
        if turns is not None:
            await turns.aclose()
        if engine_task is not None:
            engine_task.cancel()
            await asyncio.gather(engine_task, return_exceptions=True)
        if peer_handle is not None:
            await peer_transport.leave(peer_handle)
        if agent_handle is not None:
            await agent_transport.leave(agent_handle)
        if conversation_id is not None:
            await conversation_service.finish_session(
                conversation_id,
                VoiceConversationStatus.COMPLETED,
            )
