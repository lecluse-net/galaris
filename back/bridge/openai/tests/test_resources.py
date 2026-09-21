from __future__ import annotations

import pytest

from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from app.llm.provider_router import _model_info_response
from bridge.openai.resources import OpenAIResourceDiscovery


@pytest.mark.asyncio
async def test_openai_discovery_exposes_realtime_models_and_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def list_models(
        _self: object,
        _base_url: str,
        _api_key: str | None = None,
    ) -> list[LLMModelInfo]:
        return [
            LLMModelInfo(id="gpt-realtime-2.1", name="GPT Realtime 2.1"),
            LLMModelInfo(id="gpt-4.1", name="GPT 4.1"),
            LLMModelInfo(id="gpt-4o-mini-tts", name="GPT 4o mini TTS"),
        ]

    monkeypatch.setattr(
        "bridge.openai.resources.OpenAICompatibleHandler.list_models",
        list_models,
    )
    connection = ProviderConnection(
        id=1,
        name="OpenAI",
        catalog_code="openai-api",
        provider_type="openai_compatible",
        base_url="https://api.openai.com/v1",
        api_key="test",
    )
    discovery = OpenAIResourceDiscovery()

    realtime = await discovery.list_resources(
        connection,
        "realtime_conversation",
    )
    speech = await discovery.list_resources(connection, "speech")

    assert [resource.id for resource in realtime] == ["gpt-realtime-2.1"]
    # Unknown inputs must remain enrichable internally; the public catalog
    # still supplies the complete, conservative directional boolean contract.
    response = _model_info_response(realtime[0])
    assert "input_image" not in response.known_modalities
    assert response.modalities is not None
    assert response.modalities.model_dump() == {
        "input_text": True,
        "input_image": False,
        "input_file": False,
        "input_video": False,
        "input_audio": True,
        "output_text": True,
        "output_image": False,
        "output_file": False,
        "output_video": False,
        "output_audio": True,
    }
    voices = [resource for resource in speech if resource.resource_type == "voice"]
    assert {resource.id for resource in voices} >= {"voice:marin", "voice:cedar"}
    assert all(resource.service_capabilities == ["speech"] for resource in voices)
