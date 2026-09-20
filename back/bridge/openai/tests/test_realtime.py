from __future__ import annotations

import json
from typing import Any

import pytest

from app.llm.provider_facade import ProviderConnection, RealtimeToolDefinition
from bridge.openai.realtime import OpenAIRealtimeSession


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.received: list[str] = [
            json.dumps({"type": "session.created", "session": {"id": "sess_1"}}),
            json.dumps({"type": "session.updated", "session": {"id": "sess_1"}}),
        ]
        self.closed = False

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        assert isinstance(payload, dict)
        self.sent.append(payload)

    async def recv(self) -> str:
        return self.received.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_openai_realtime_session_uses_native_audio_without_input_stt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = _Socket()

    async def connect(*_args: object, **_kwargs: object) -> _Socket:
        return socket

    monkeypatch.setattr("bridge.openai.realtime.connect", connect)
    connection = ProviderConnection(
        id=1,
        name="OpenAI",
        catalog_code="openai-api",
        provider_type="openai_compatible",
        base_url="https://api.openai.com/v1",
        api_key="secret",
    )

    session = await OpenAIRealtimeSession.open(
        connection,
        model="gpt-realtime-2.1",
        voice="voice:marin",
        instructions="Stay concise.",
        tools=(
            RealtimeToolDefinition(
                name="memory_search",
                description="Search memory.",
                parameters={"type": "object"},
            ),
        ),
        output_audio=True,
    )

    update = socket.sent[0]
    configured = update["session"]
    assert configured["output_modalities"] == ["audio"]
    assert configured["audio"]["input"]["format"] == {
        "type": "audio/pcm",
        "rate": 24_000,
    }
    assert "transcription" not in configured["audio"]["input"]
    assert configured["audio"]["output"]["format"] == {
        "type": "audio/pcm",
        "rate": 24_000,
    }
    assert configured["audio"]["output"]["voice"] == "marin"
    assert configured["tools"][0]["name"] == "memory_search"

    await session.send_audio(b"\x00\x00")
    assert socket.sent[-1]["type"] == "input_audio_buffer.append"
    await session.close()
    assert socket.closed


@pytest.mark.asyncio
async def test_openai_realtime_text_output_supports_external_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = _Socket()

    async def connect(*_args: object, **_kwargs: object) -> _Socket:
        return socket

    monkeypatch.setattr("bridge.openai.realtime.connect", connect)
    connection = ProviderConnection(
        id=2,
        name="OpenAI",
        catalog_code="openai-api",
        provider_type="openai_compatible",
        base_url="https://api.openai.com/v1",
        api_key="secret",
    )

    await OpenAIRealtimeSession.open(
        connection,
        model="gpt-realtime-2.1",
        voice=None,
        instructions="Stay concise.",
        tools=(),
        output_audio=False,
    )

    configured = socket.sent[0]["session"]
    assert configured["output_modalities"] == ["text"]
    assert "output" not in configured["audio"]


@pytest.mark.asyncio
async def test_openai_realtime_session_surfaces_provider_handshake_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = _Socket()
    socket.received = [
        json.dumps(
            {
                "type": "error",
                "error": {
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                    "message": "You exceeded your current quota.",
                },
            }
        )
    ]

    async def connect(*_args: object, **_kwargs: object) -> _Socket:
        return socket

    monkeypatch.setattr("bridge.openai.realtime.connect", connect)
    connection = ProviderConnection(
        id=3,
        name="OpenAI",
        catalog_code="openai-api",
        provider_type="openai_compatible",
        base_url="https://api.openai.com/v1",
        api_key="secret",
    )

    with pytest.raises(
        RuntimeError,
        match=r"OpenAI Realtime error: insufficient_quota: "
        r"You exceeded your current quota\.",
    ):
        await OpenAIRealtimeSession.open(
            connection,
            model="gpt-realtime-2.1",
            voice="voice:marin",
            instructions="Stay concise.",
            tools=(),
            output_audio=True,
        )

    assert socket.closed
