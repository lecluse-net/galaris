"""Tests for the shared provider-neutral transcription service."""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

import pytest

from app.llm import transcription_service
from app.llm.purposes import LLMCallPurpose
from bridge.elevenlabs import transcription as elevenlabs_transcription
from bridge.openrouter import transcription as openrouter_transcription


class _Response:
    headers = {"x-request-id": "stt-request-1"}
    content = (
        b'{"text":"Bonjour","usage":{"prompt_tokens":100,'
        b'"completion_tokens":5,"total_tokens":105,"cost":0.012}}'
    )

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "text": "Bonjour",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 5,
                "total_tokens": 105,
                "cost": 0.012,
            },
        }


class _Client:
    requests: list[dict[str, Any]] = []
    timeouts: list[float] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeouts.append(timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append({"url": url, **kwargs})
        return _Response()


class _LLMCalls:
    created: list[dict[str, Any]] = []
    finalized: list[tuple[object, dict[str, Any]]] = []


class _RealtimeConnection:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.incoming.put_nowait(
            json.dumps(
                {
                    "message_type": "session_started",
                    "session_id": "session-1",
                }
            )
        )
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def recv(self) -> str:
        return await self.incoming.get()

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload.get("commit") is True:
            self.incoming.put_nowait(
                json.dumps(
                    {
                        "message_type": "committed_transcript",
                        "text": "Bonjour en direct",
                    }
                )
            )
        else:
            self.incoming.put_nowait(
                json.dumps(
                    {
                        "message_type": "partial_transcript",
                        "text": "Bonjour",
                    }
                )
            )

    async def close(self) -> None:
        self.closed = True


def _resource(provider_type: str, *, openrouter: bool = False) -> SimpleNamespace:
    provider = SimpleNamespace(
        id=1,
        name=provider_type,
        catalog_code=(
            "openrouter"
            if openrouter
            else "elevenlabs" if provider_type == "elevenlabs" else None
        ),
        provider_type=provider_type,
        base_url="https://speech.example/v1",
        configuration={},
        is_active=True,
        api_key="encrypted",
    )
    return SimpleNamespace(
        id=7,
        llm_name="openai/whisper-large-v3" if openrouter else "whisper-1",
        cost_per_input_token=2.0,
        cost_per_cached_input_token=1.0,
        cost_per_output_token=4.0,
        is_subscription=False,
        provider=provider,
    )


@pytest.fixture(autouse=True)
def fake_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.requests = []
    _Client.timeouts = []
    _LLMCalls.created = []
    _LLMCalls.finalized = []

    async def create_running_call(**kwargs: Any) -> SimpleNamespace:
        _LLMCalls.created.append(kwargs)
        return SimpleNamespace(id="stt-call-1")

    async def finalize_call(call_id: object, **kwargs: Any) -> None:
        _LLMCalls.finalized.append((call_id, kwargs))

    monkeypatch.setattr(
        transcription_service.llm_call_service,
        "create_running_call",
        create_running_call,
    )
    monkeypatch.setattr(
        transcription_service.llm_call_service,
        "finalize_call",
        finalize_call,
    )
    monkeypatch.setattr(transcription_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        elevenlabs_transcription.httpx,
        "AsyncClient",
        _Client,
    )
    monkeypatch.setattr(
        openrouter_transcription.httpx,
        "AsyncClient",
        _Client,
    )
    monkeypatch.setattr(
        transcription_service.llm_provider_service,
        "decrypt_api_key",
        lambda _value: "provider-token",
    )
    monkeypatch.setattr(
        transcription_service.llm_provider_service,
        "transcription_base_url",
        lambda _provider: "https://speech.example/v1",
    )


@pytest.mark.asyncio
async def test_openrouter_sends_base64_audio_and_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def selected(_agent_id: int | None = None) -> SimpleNamespace:
        return _resource("openai_compatible", openrouter=True)

    monkeypatch.setattr(transcription_service.llm_service, "get_transcription_llm", selected)

    text = await transcription_service.transcribe_audio(
        b"RIFF-audio",
        filename="turn.wav",
        mime_type="audio/wav",
        language="fr-FR",
    )

    request = _Client.requests[0]
    assert text == "Bonjour"
    assert request["url"] == "https://speech.example/v1/audio/transcriptions"
    assert request["headers"] == {"Authorization": "Bearer provider-token"}
    assert request["json"] == {
        "model": "openai/whisper-large-v3",
        "input_audio": {"data": "UklGRi1hdWRpbw==", "format": "wav"},
        "language": "fr",
    }
    assert _LLMCalls.created == [
        {
            "purpose": LLMCallPurpose.AUDIO_TRANSCRIPTION,
            "requester_user_id": None,
            "task_id": None,
            "agent_run_id": None,
            "agent_id": None,
            "llm_id": 7,
            "provider_name": "openai_compatible",
            "provider_code": "openrouter",
            "requested_model": "openai/whisper-large-v3",
            "effective_model": "openai/whisper-large-v3",
            "stream": False,
            "request_body": {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Audio transcription request\n"
                            "filename: turn.wav\n"
                            "mime_type: audio/wav\n"
                            "size_bytes: 10\n"
                            "language: fr-FR"
                        ),
                    }
                ]
            },
            "is_subscription": False,
        }
    ]
    assert _LLMCalls.finalized == [
        (
            "stt-call-1",
            {
                "trace": {
                    "response_text": "Bonjour",
                    "finish_reason": "stop",
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 5,
                        "total_tokens": 105,
                        "cost": 0.012,
                        "audio_bytes": 10,
                    },
                    "upstream_request_id": "stt-request-1",
                },
                "raw_response": _Response.content.decode(),
                "input_rate": 2.0,
                "cached_input_rate": 1.0,
                "output_rate": 4.0,
            },
        )
    ]


@pytest.mark.asyncio
async def test_openai_compatible_sends_multipart_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def selected(_agent_id: int | None = None) -> SimpleNamespace:
        return _resource("openai_compatible")

    monkeypatch.setattr(transcription_service.llm_service, "get_transcription_llm", selected)

    await transcription_service.transcribe_audio(
        b"audio",
        filename="turn.ogg",
        mime_type="audio/ogg",
        language="fr",
    )

    request = _Client.requests[0]
    assert request["data"] == {"model": "whisper-1", "language": "fr"}
    assert request["files"] == {"file": ("turn.ogg", b"audio", "audio/ogg")}


@pytest.mark.asyncio
async def test_disk_audio_uses_streaming_multipart_and_batch_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def selected(_agent_id: int | None = None) -> SimpleNamespace:
        return _resource("openai_compatible")

    monkeypatch.setattr(transcription_service.llm_service, "get_transcription_llm", selected)
    source = tmp_path / "meeting.m4a"
    source.write_bytes(b"large-audio-placeholder")

    text = await transcription_service.transcribe_audio_file(
        source,
        mime_type="audio/m4a",
    )

    request = _Client.requests[0]
    uploaded = request["files"]["file"]
    assert text == "Bonjour"
    assert _Client.timeouts == [900.0]
    assert uploaded[0] == "meeting.m4a"
    assert uploaded[1].closed is True
    assert not isinstance(uploaded[1], bytes)
    assert uploaded[2] == "audio/m4a"


@pytest.mark.asyncio
async def test_elevenlabs_uses_batch_model_and_language_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = _resource("elevenlabs")
    resource.llm_name = "scribe_v2_realtime"

    async def selected(_agent_id: int | None = None) -> SimpleNamespace:
        return resource

    monkeypatch.setattr(transcription_service.llm_service, "get_transcription_llm", selected)

    await transcription_service.transcribe_audio(b"audio", language="fr")

    request = _Client.requests[0]
    assert request["url"] == "https://speech.example/v1/speech-to-text"
    assert request["headers"] == {"xi-api-key": "provider-token"}
    assert request["data"] == {"model_id": "scribe_v2", "language_code": "fr"}


@pytest.mark.asyncio
async def test_elevenlabs_realtime_streams_native_pcm_and_manual_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = _resource("elevenlabs")
    resource.llm_name = "scribe_v2_realtime"
    connection = _RealtimeConnection()
    connection_args: list[dict[str, Any]] = []

    async def selected(_agent_id: int | None = None) -> SimpleNamespace:
        return resource

    async def connect(url: str, **kwargs: Any) -> _RealtimeConnection:
        connection_args.append({"url": url, **kwargs})
        return connection

    monkeypatch.setattr(transcription_service.llm_service, "get_transcription_llm", selected)
    monkeypatch.setattr(elevenlabs_transcription, "connect", connect)

    realtime = await transcription_service.create_realtime_transcriber(
        language="fr-FR",
        sample_rate=48_000,
    )

    assert realtime is not None
    await realtime.send_audio(b"\x01\x00" * 2_400)
    assert connection.sent == []
    await realtime.send_audio(b"\x02\x00" * 2_400)
    transcript = await realtime.commit()
    await realtime.close()

    parsed = urlsplit(connection_args[0]["url"])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "wss"
    assert parsed.path == "/v1/speech-to-text/realtime"
    assert query == {
        "audio_format": ["pcm_48000"],
        "commit_strategy": ["manual"],
        "language_code": ["fr"],
        "model_id": ["scribe_v2_realtime"],
    }
    assert connection_args[0]["additional_headers"] == {
        "xi-api-key": "provider-token"
    }
    assert len(connection.sent) == 2
    assert connection.sent[0]["message_type"] == "input_audio_chunk"
    assert len(base64.b64decode(connection.sent[0]["audio_base_64"])) == 9_600
    assert connection.sent[1]["commit"] is True
    assert transcript == "Bonjour en direct"
    assert connection.closed is True
