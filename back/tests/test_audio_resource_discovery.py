"""Tests for provider-reported TTS voices."""

from __future__ import annotations

from typing import Any, Optional, Self

import pytest

from app.llm import resource_discovery
from app.llm.provider_models import LLMProvider
from bridge.azure_speech import resources as azure_speech_resources
from bridge.elevenlabs import resources as elevenlabs_resources
from bridge.google import resources as google_resources


class _FakeResponse:
    def __init__(self, payload: Any, *, text: str = "") -> None:
        self.payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class _FakeAsyncClient:
    responses: list[_FakeResponse] = []
    requests: list[tuple[str, Optional[dict[str, str]]]] = []

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 30.0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: Optional[dict[str, str]] = None,
    ) -> _FakeResponse:
        assert headers
        self.requests.append((url, params))
        return self.responses.pop(0)


def _provider(
    provider_type: str,
    base_url: str,
    *,
    catalog_code: Optional[str] = None,
    configuration: Optional[dict[str, Any]] = None,
) -> LLMProvider:
    return LLMProvider(
        name=provider_type,
        provider_type=provider_type,
        base_url=base_url,
        catalog_code=catalog_code,
        configuration=configuration or {},
    )


@pytest.fixture(autouse=True)
def fake_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.requests = []
    azure_speech_resources._public_voice_cache = None
    google_resources._public_voice_cache = None
    monkeypatch.setattr(
        elevenlabs_resources.httpx,
        "AsyncClient",
        _FakeAsyncClient,
    )


@pytest.mark.asyncio
async def test_elevenlabs_lists_every_voice_page_as_tts_resources() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(
            [
                {
                    "model_id": "eleven_flash_v2_5",
                    "name": "Eleven Flash v2.5",
                    "can_do_text_to_speech": True,
                }
            ]
        ),
        _FakeResponse(
            {
                "voices": [
                    {
                        "voice_id": "voice-1",
                        "name": "Alice",
                        "category": "premade",
                        "labels": {"accent": "French"},
                    }
                ],
                "has_more": True,
                "next_page_token": "page-2",
            }
        ),
        _FakeResponse(
            {
                "voices": [{"voice_id": "voice-2", "name": "Bob"}],
                "has_more": False,
            }
        ),
    ]

    resources = await resource_discovery.list_resources(
        _provider(
            "elevenlabs",
            "https://api.elevenlabs.io/v1",
            catalog_code="elevenlabs",
        ),
        "secret",
        "speech",
    )

    assert [resource.id for resource in resources] == [
        "eleven_flash_v2_5",
        "voice:voice-1",
        "voice:voice-2",
    ]
    assert resources[1].resource_type == "voice"
    assert resources[1].service_capabilities == ["speech"]
    assert resources[1].description == "premade · accent: French"
    assert _FakeAsyncClient.requests[2][1] == {
        "page_size": "100",
        "include_total_count": "false",
        "next_page_token": "page-2",
    }


@pytest.mark.asyncio
async def test_google_cloud_lists_voices_as_tts_resources() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(
            {
                "voices": [
                    {
                        "name": "fr-FR-Neural2-A",
                        "languageCodes": ["fr-FR"],
                        "ssmlGender": "FEMALE",
                    }
                ]
            }
        )
    ]

    resources = await resource_discovery.list_resources(
        _provider(
            "google_cloud_tts",
            "https://texttospeech.googleapis.com/v1",
            catalog_code="google-cloud-tts",
        ),
        "secret",
        "speech",
    )

    assert [resource.id for resource in resources] == ["voice:fr-FR-Neural2-A"]
    assert resources[0].resource_type == "voice"
    assert resources[0].service_capabilities == ["speech"]


@pytest.mark.asyncio
async def test_azure_speech_lists_regional_voices_as_tts_resources() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(
            [
                {
                    "ShortName": "fr-FR-DeniseNeural",
                    "DisplayName": "Denise",
                    "LocaleName": "Français (France)",
                    "StyleList": ["cheerful"],
                }
            ]
        )
    ]

    resources = await resource_discovery.list_resources(
        _provider(
            "azure_speech",
            "https://{region}.tts.speech.microsoft.com/cognitiveservices",
            catalog_code="azure-speech",
            configuration={"region": "FranceCentral"},
        ),
        "secret",
        "speech",
    )

    assert [resource.id for resource in resources] == ["voice:fr-FR-DeniseNeural"]
    assert resources[0].name == "Denise"
    assert resources[0].resource_type == "voice"
    assert _FakeAsyncClient.requests[0][0].startswith(
        "https://francecentral.tts.speech.microsoft.com/"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_type", "catalog_code", "documented_voice"),
    [
        ("google_cloud_tts", "google-cloud-tts", "fr-FR-Neural2-F"),
        ("azure_speech", "azure-speech", "fr-FR-DeniseNeural"),
    ],
)
async def test_cloud_tts_provider_lists_public_catalog_without_api_key(
    provider_type: str,
    catalog_code: str,
    documented_voice: str,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse({}, text=f"<table><code>{documented_voice}</code></table>")
    ]

    resources = await resource_discovery.list_resources(
        _provider(
            provider_type,
            "https://unused.example/v1",
            catalog_code=catalog_code,
        ),
        None,
        "speech",
    )

    assert [resource.id for resource in resources] == [f"voice:{documented_voice}"]
    assert resources[0].metadata_source == "public-catalog"
    assert resources[0].resource_type == "voice"
