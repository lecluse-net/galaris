from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest


def _load_script() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "default-agent"
        / "data"
        / "scripts"
        / "galaris_tts.py"
    )
    spec = importlib.util.spec_from_file_location("galaris_tts_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_elevenlabs_adapter_calls_rest_api_without_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    request: dict[str, Any] = {}

    def fake_post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        request.update(url=url, body=json.loads(body), headers=headers)
        return b"mp3-audio"

    monkeypatch.setattr(module, "_post", fake_post)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret-key")
    monkeypatch.setenv(
        "GALARIS_ELEVENLABS_TTS_BASE_URL",
        "https://eleven.example/v1/",
    )

    generate = cast(Any, getattr(module, "_elevenlabs"))
    result = generate("Bonjour", "voice/42", "eleven_multilingual_v2")

    assert result == b"mp3-audio"
    assert request == {
        "url": (
            "https://eleven.example/v1/text-to-speech/voice%2F42"
            "?output_format=mp3_44100_128"
        ),
        "body": {
            "text": "Bonjour",
            "model_id": "eleven_multilingual_v2",
        },
        "headers": {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": "secret-key",
        },
    }
