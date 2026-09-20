"""Tests for provider-neutral agent speech generation."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Optional, Self
from urllib.parse import parse_qs, urlsplit

import pytest

from app.llm import tts_service
from app.llm.provider_models import LLM, LLMProvider
from app.llm.resource_discovery import provider_connection
from bridge.elevenlabs import speech as elevenlabs_speech
from bridge.google import speech as google_speech


class _FakeResponse:
    def __init__(self, content: bytes = b"", payload: Optional[dict[str, Any]] = None) -> None:
        self.content = content
        self._payload = payload or {}
        self.headers = {}

    async def aiter_bytes(self, chunk_size=65536):
        yield json.dumps(self._payload).encode() if self._payload else self.content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    response = _FakeResponse()
    requests: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float, follow_redirects: bool = False) -> None:
        assert timeout == 90.0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return self.response

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        assert method == "POST"
        yield await self.post(url, **kwargs)


class _RealtimeConnection:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.incoming.put_nowait(
            json.dumps(
                {
                    "audio": base64.b64encode(b"\x01\x00" * 960).decode(),
                    "is_final": False,
                }
            )
        )
        self.incoming.put_nowait(json.dumps({"is_final": True}))
        self.closed = False

    async def recv(self) -> str:
        return await self.incoming.get()

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


def _resource(
    provider_type: str,
    llm_name: str,
    *,
    resource_type: str = "voice",
    catalog_code: Optional[str] = None,
    configuration: Optional[dict[str, Any]] = None,
) -> LLM:
    provider = LLMProvider(
        name=provider_type,
        provider_type=provider_type,
        catalog_code=catalog_code,
        base_url={
            "elevenlabs": "https://eleven.example/v1",
            "google_cloud_tts": "https://google.example/v1",
            "azure_speech": "https://{region}.azure.example/cognitiveservices",
            "openai_compatible": "https://openai.example/v1",
        }[provider_type],
        api_key="secret",
        configuration=configuration or {},
        is_active=True,
    )
    return LLM(
        code="voice-test",
        llm_name=llm_name,
        label="Test voice",
        resource_type=resource_type,
        primary_capability="speech",
        service_capabilities=["speech"],
        provider=provider,
    )


@pytest.fixture(autouse=True)
def fake_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.requests = []
    _FakeAsyncClient.response = _FakeResponse(content=b"ID3-audio")
    monkeypatch.setattr(tts_service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(tts_service.llm_provider_service, "decrypt_api_key", lambda _: "key")


@pytest.mark.asyncio
async def test_elevenlabs_generates_mp3_with_agent_selected_voice_settings() -> None:
    resource = _resource(
        "elevenlabs",
        "voice:configured-voice",
        catalog_code="elevenlabs",
    )
    generated = await elevenlabs_speech.ElevenLabsSpeech().synthesize(
        provider_connection(resource.provider, "key"),
        model=resource.llm_name,
        resource_type=resource.resource_type,
        text="Bonjour tout le monde",
        options=tts_service.TTSOptions(
            voice="chosen-voice",
            model="eleven_flash_v2_5",
            language="fr",
            speed=1.1,
            stability=0.7,
            similarity_boost=0.8,
            style=0.2,
            use_speaker_boost=True,
        ),
    )

    request = _FakeAsyncClient.requests[0]
    assert request["url"].endswith("/text-to-speech/chosen-voice")
    assert request["params"] == {"output_format": "mp3_44100_128"}
    assert request["json"] == {
        "text": "Bonjour tout le monde",
        "model_id": "eleven_flash_v2_5",
        "language_code": "fr",
        "voice_settings": {
            "speed": 1.1,
            "stability": 0.7,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True,
        },
    }
    assert generated.content == b"ID3-audio"
    assert generated.voice == "chosen-voice"


@pytest.mark.asyncio
async def test_google_cloud_decodes_mp3_and_maps_common_voice_controls() -> None:
    _FakeAsyncClient.response = _FakeResponse(
        payload={"audioContent": base64.b64encode(b"google-mp3").decode()}
    )

    resource = _resource(
        "google_cloud_tts",
        "voice:fr-FR-Neural2-A",
        catalog_code="google-cloud-tts",
    )
    generated = await google_speech.GoogleCloudSpeech().synthesize(
        provider_connection(resource.provider, "key"),
        model=resource.llm_name,
        resource_type=resource.resource_type,
        text="Le texte",
        options=tts_service.TTSOptions(speed=1.25, pitch=2.0),
    )

    request = _FakeAsyncClient.requests[0]
    assert request["headers"] == {"X-Goog-Api-Key": "key", "Accept-Encoding": "identity"}
    assert not request.get("params")
    assert request["json"]["voice"] == {
        "name": "fr-FR-Neural2-A",
        "languageCode": "fr-FR",
    }
    assert request["json"]["audioConfig"] == {
        "audioEncoding": "MP3",
        "speakingRate": 1.25,
        "pitch": 2.0,
    }
    assert generated.content == b"google-mp3"


@pytest.mark.asyncio
async def test_generate_for_agent_requires_configured_tts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service

    async def get_agent(agent_id: int) -> object:
        return SimpleNamespace(id=agent_id, voice=None)

    monkeypatch.setattr(agent_service, "get", get_agent)

    with pytest.raises(tts_service.TTSNotConfigured):
        await tts_service.generate_for_agent(7, "Bonjour")


@pytest.mark.asyncio
async def test_elevenlabs_realtime_streams_flash_pcm_as_text_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service

    resource = _resource(
        "elevenlabs",
        "voice:configured-voice",
        catalog_code="elevenlabs",
    )
    connection = _RealtimeConnection()
    connection_args: list[dict[str, Any]] = []

    async def get_agent(_agent_id: int) -> object:
        return SimpleNamespace(voice="tts:11")

    async def get_llm(_voice_model_id: int) -> LLM:
        return resource

    async def connect(url: str, **kwargs: Any) -> _RealtimeConnection:
        connection_args.append({"url": url, **kwargs})
        return connection

    async def segments() -> AsyncIterator[str]:
        yield "Bonjour."
        yield "Comment allez-vous ?"

    monkeypatch.setattr(agent_service, "get", get_agent)
    monkeypatch.setattr(tts_service.llm_service, "get_llm", get_llm)
    monkeypatch.setattr(elevenlabs_speech, "connect", connect)

    stream = await tts_service.create_realtime_speech_stream_for_agent(
        7,
        tts_service.TTSOptions(language="fr"),
    )

    assert stream is not None
    chunks = [chunk async for chunk in stream.stream(segments())]

    parsed = urlsplit(connection_args[0]["url"])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "wss"
    assert parsed.path.endswith(
        "/v1/text-to-speech/configured-voice/stream-input"
    )
    assert query["model_id"] == ["eleven_flash_v2_5"]
    assert query["output_format"] == ["pcm_24000"]
    assert query["auto_mode"] == ["true"]
    assert connection_args[0]["additional_headers"] == {"xi-api-key": "key"}
    assert connection.sent[0] == {
        "text": " ",
        "voice_settings": {"speed": 1.0},
    }
    assert [message["text"] for message in connection.sent[1:]] == [
        "Bonjour. ",
        "Comment allez-vous ? ",
        "",
    ]
    assert chunks == [b"\x01\x00" * 960]
    assert stream.sample_rate == 24_000
    assert stream.channels == 1
    assert connection.closed is True


def test_rejects_out_of_range_elevenlabs_speed() -> None:
    with pytest.raises(ValueError, match="speed"):
        tts_service._validate("Bonjour", tts_service.TTSOptions(speed=5.0))
