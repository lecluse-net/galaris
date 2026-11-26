"""Exercise the live transcription protocol separately from provider conversations."""

import base64
import json

import pytest

from app.llm.provider_facade import ProviderConnection
from bridge.openai.transcription import OpenAITranscription
from bridge.openai.tests.test_realtime import _Socket


@pytest.fixture
def socket(monkeypatch):
    websocket = _Socket()

    async def connect(uri, **kwargs):
        assert uri == "wss://provider.test/v1/realtime?intent=transcription"
        assert kwargs["additional_headers"] == {"Authorization": "Bearer synthetic-openai"}
        return websocket

    monkeypatch.setattr("bridge.openai.transcription.connect", connect)
    return websocket


async def open_transcriber(*, on_partial=None):
    connection = ProviderConnection(1, "Synthetic OpenAI", "openai-api", "openai_compatible",
                                    "https://provider.test/v1", "synthetic-openai")
    transcriber = await OpenAITranscription().create_realtime_transcriber(
        connection, model="gpt-live-transcribe", language="fr-CA", sample_rate=48_000, channels=1,
        on_partial=on_partial,
    )
    assert transcriber is not None
    return transcriber


@pytest.mark.asyncio
async def test_openai_live_stt_commits_only_local_turns_and_matches_each_item(socket):
    partials = []

    async def update(text):
        partials.append(text)

    transcriber = await open_transcriber(on_partial=update)
    assert socket.sent[0] == {"type": "session.update", "session": {"type": "transcription", "audio": {"input": {
        "format": {"type": "audio/pcm", "rate": 24_000},
        "transcription": {"model": "gpt-live-transcribe", "language": "fr"}, "turn_detection": None,
    }}}}
    await transcriber.send_audio(b"\0\0" * 960, speech_detected=False)
    assert await transcriber.commit() == "" and len(socket.sent) == 1

    socket.received.extend(json.dumps(event) for event in (
        {"type": "conversation.item.input_audio_transcription.delta", "item_id": "first", "delta": "Bon"},
        {"type": "input_audio_buffer.committed", "item_id": "first"},
        {"type": "conversation.item.input_audio_transcription.delta", "item_id": "first", "delta": "jour"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "first", "transcript": "Bonjour"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "first", "transcript": "Ancien"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "second", "transcript": "Suite"},
        {"type": "input_audio_buffer.committed", "item_id": "second"},
    ))
    # Odd frame boundaries must not shift the 48 kHz → 24 kHz sample phase.
    await transcriber.send_audio(b"\x01\x00")
    await transcriber.send_audio(b"\x02\x00\x03\x00" * 2_400)
    assert await transcriber.commit() == "Bonjour"
    assert base64.b64decode(socket.sent[1]["audio"]) == b"\x01\x00"
    assert base64.b64decode(socket.sent[2]["audio"]) == b"\x03\x00" * 2_400
    await transcriber.send_audio(b"\x04\x00" * 4_800)
    assert await transcriber.commit() == "Suite"
    assert partials == ["Bon", "Bonjour"]
    assert [event["type"] for event in socket.sent[1:]] == [
        "input_audio_buffer.append", "input_audio_buffer.append", "input_audio_buffer.commit",
        "input_audio_buffer.append", "input_audio_buffer.commit",
    ]
    await transcriber.close()
    assert socket.closed


@pytest.mark.asyncio
async def test_openai_live_stt_closes_a_rejected_handshake(socket):
    socket.received[-1] = json.dumps({"type": "error", "error": {"code": "unsupported_model"}})
    with pytest.raises(RuntimeError, match="unsupported_model"):
        await open_transcriber()
    assert socket.closed
