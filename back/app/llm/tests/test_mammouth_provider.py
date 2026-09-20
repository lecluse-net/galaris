"""Mammouth public API contracts; no paid requests or real credentials."""

import base64
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm import MediaRequest, ProviderConnection
from app.llm.capabilities import infer_capabilities
from app.llm.provider_facade import (
    image_generation_provider_for,
    openai_protocol_base_url,
    responses_policy_for,
)
from bridge.mammouth import PROFILE, multimedia, resources
from bridge.mammouth.image import MammouthImageGeneration
from bridge.mammouth.multimedia import MammouthMedia
from bridge.mammouth.resources import MammouthResources, parse_catalog


def connection():
    return ProviderConnection(
        id=1, name="Mammouth", catalog_code="mammouth", provider_type="openai_compatible",
        base_url="https://api.mammouth.test", api_key="test-secret",
    )


def catalogs():
    names = ["gemini-3.1-pro-preview", "mammouth-recommended", "gemini-3-pro-image-preview",
             "gpt-image-2", "text-embedding-3-small", "plain-chat"]
    models = {"data": [{"id": name, "model_info": {
        "id": "deployment-hash", "input_cost_per_token": 0.0000025,
        "max_input_tokens": 1_000_000,
    }} for name in names]}
    details = {"data": [
        {"model_name": names[0], "model_info": {
            "key": "openrouter/google/internal-route", "mode": "chat",
            "supports_vision": True, "supports_audio_input": True, "supports_video_input": True,
            "supports_audio_output": True, "supports_function_calling": True,
            "supports_reasoning": True, "supports_response_schema": True,
            "input_cost_per_token": 0.000001, "output_cost_per_token": 0.00001,
            "cache_read_input_token_cost": 0.00000025,
        }},
        {"model_name": "text-embedding-3-small", "model_info": {"mode": "embedding", "output_cost_per_token": 0}},
        {"model_name": "plain-chat", "model_info": {"supports_audio_input": None, "supports_video_input": None}},
        {"model_name": "not-in-public-catalog", "model_info": {"mode": "chat"}},
    ]}
    return models, details


def mock_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(resources.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs,
    ))


def test_public_aliases_rates_and_positive_capability_flags():
    models, details = catalogs()
    parsed = {model.id: model for model in parse_catalog(models, details)}
    assert len(parsed) == 6
    gemini = parsed["gemini-3.1-pro-preview"]
    assert gemini.pricing == {"input": 2.5, "output": 10.0, "cached_input": 0.25}
    assert gemini.context_length == 1_000_000
    assert gemini.capabilities == {"tools": True, "reasoning": True, "structured_output": True}
    assert infer_capabilities(gemini) == ["chat", "vision", "audio_understanding", "video_understanding"]
    assert not gemini.modalities.get("output_audio")
    assert parsed["mammouth-recommended"].resource_type == "preset"
    assert parsed["plain-chat"].service_capabilities == ["chat"]
    assert parsed["plain-chat"].pricing == {"input": 2.5}  # Missing output is not free.
    assert parsed["text-embedding-3-small"].pricing["output"] == 0
    for name in ["gemini-3-pro-image-preview", "gpt-image-2"]:
        assert parsed[name].service_capabilities == ["image_generation"]
        assert parsed[name].modalities["output_image"] is True


def test_new_unimplemented_modes_and_invalid_prices_are_not_advertised():
    models = {"data": [{"id": "new-music"}, {"id": "plain"}, {"id": "plain"}, {"id": None}]}
    details = {"data": [
        {"model_name": "new-music", "model_info": {"mode": "audio_speech"}},
        {"model_name": "plain", "model_info": {"input_cost_per_token": -1, "output_cost_per_token": float("nan")}},
    ]}
    parsed = parse_catalog(models, details)
    assert [model.id for model in parsed] == ["plain"]
    assert parsed[0].pricing == {}
    with pytest.raises(ValueError, match="model list"):
        parse_catalog({"data": {}}, details)


@pytest.mark.asyncio
async def test_discovery_authenticates_without_sending_keys_to_public_endpoints(monkeypatch):
    models, details = catalogs()
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.startswith("/public/"):
            assert "authorization" not in request.headers
            return httpx.Response(200, json=models if request.url.path == "/public/models" else details)
        assert request.url.path == "/v1/models/gemini-3.1-pro-preview"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"id": "gemini-3.1-pro-preview"})

    mock_http(monkeypatch, handler)
    found = await MammouthResources().list_resources(connection(), "audio_understanding")
    assert [model.id for model in found] == ["gemini-3.1-pro-preview"]
    assert len(calls) == 3
    found = await MammouthResources().get_model_metadata(connection(), "mammouth-recommended")
    assert found.id == "mammouth-recommended"
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_public_catalog_does_not_make_an_invalid_key_pass(monkeypatch):
    models, details = catalogs()

    def handler(request):
        if request.url.path == "/public/models":
            return httpx.Response(200, json=models)
        if request.url.path == "/public/model/info":
            return httpx.Response(200, json=details)
        return httpx.Response(401, json={"error": "invalid key"})

    mock_http(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError) as error:
        await MammouthResources().list_resources(connection(), "chat")
    assert error.value.response.status_code == 401
    with pytest.raises(ValueError, match="API key"):
        await MammouthResources().list_resources(replace(connection(), api_key=None), "chat")


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["speech", "transcription", "realtime_conversation", "music_generation", "sound_generation", "video_generation"])
async def test_app_only_services_are_absent_without_network_requests(monkeypatch, capability):
    catalog = AsyncMock(side_effect=AssertionError("Must not fetch unavailable capabilities"))
    discovery = MammouthResources()
    monkeypatch.setattr(discovery, "catalog", catalog)
    assert capability not in PROFILE.capabilities
    assert await discovery.list_resources(connection(), capability) == []


@pytest.mark.asyncio
async def test_oversized_or_malformed_catalog_is_rejected(monkeypatch):
    monkeypatch.setattr(resources, "_MAX_CATALOG_BYTES", 10)
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 11))
    with pytest.raises(ValueError, match="size limit"):
        await MammouthResources().catalog(connection())


def test_protocol_responses_and_image_registration():
    assert openai_protocol_base_url(connection()) == "https://api.mammouth.test/v1"
    assert openai_protocol_base_url(replace(connection(), base_url="https://api.mammouth.test/v1/")) == "https://api.mammouth.test/v1"
    policy = responses_policy_for(connection())
    assert policy is not None and policy.supports_compaction
    assert policy.store is False and policy.send_reasoning_ids is False
    for model in ["gpt-5.4", "claude-sonnet-4-6", "gemini-3.1-pro-preview", "mammouth-recommended"]:
        assert policy.model_profile(model)["supports_inline_system_prompts"]
    assert isinstance(image_generation_provider_for(connection()), MammouthImageGeneration)


def test_image_chat_request_preserves_alias_and_references():
    provider = MammouthImageGeneration()
    request = provider.prepare_request(connection(), model="gemini-3-pro-image-preview", prompt="A bird",
        sources=[(b"reference", "image/png")], width=1280, height=720)
    body = json.loads(request.content)
    assert str(request.url) == "https://api.mammouth.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-secret"
    assert body["model"] == "gemini-3-pro-image-preview"
    assert "1280x720" in body["messages"][0]["content"][0]["text"]
    assert body["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,cmVmZXJlbmNl"
    assert provider.select_size("gemini-3-pro-image-preview", 1280, 720).width is None
    response = httpx.Response(200, json={"choices": [{"message": {"images": [
        {"image_url": {"url": "data:image/png;base64,aW1hZ2U="}},
    ]}}], "usage": {"prompt_tokens": 3}})
    result = provider.read_response(response)
    assert result.content == b"image" and result.media_type == "image/png"
    assert result.usage == {"prompt_tokens": 3}


@pytest.mark.parametrize("url", ["https://cdn.test/image.png", "data:text/html;base64,YQ==", "data:image/png,raw", "data:image/png;base64,???", "data:image/png;base64,"])
def test_invalid_image_outputs_are_rejected(url):
    with pytest.raises(ValueError):
        MammouthImageGeneration().read_response(httpx.Response(200, json={"choices": [{"message": {
            "images": [{"image_url": {"url": url}}],
        }}]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,mime,part_type", [("audio_read", "audio/wav", "input_audio"), ("video_read", "video/mp4", "video_url")])
async def test_media_analysis_encodes_canonical_materialized_bytes(monkeypatch, tmp_path, operation, mime, part_type):
    transport = AsyncMock(return_value={"choices": [{"message": {"content": "Bird singing near waves"}}]})
    monkeypatch.setattr(multimedia, "media_json", transport)
    source = tmp_path / "source"
    source.write_bytes(b"media")
    result = await MammouthMedia().analyze(connection(), MediaRequest(
        operation=operation, model="gemini-3.1-pro-preview", prompt="Identify sounds and events",
    ), source, mime)
    args = transport.await_args
    assert args.args[0].base_url == "https://api.mammouth.test/v1"
    assert args.args[2] == "chat/completions"
    part = args.kwargs["body"]["messages"][0]["content"][1]
    assert part["type"] == part_type
    encoded = base64.b64encode(b"media").decode()
    if operation == "audio_read":
        assert part["input_audio"] == {"data": encoded, "format": "wav"}
    else:
        assert part["video_url"]["url"] == f"data:video/mp4;base64,{encoded}"
    assert result.text == "Bird singing near waves" and result.cost is None


@pytest.mark.asyncio
async def test_media_refuses_unsupported_formats_and_empty_answers(monkeypatch, tmp_path):
    transport = AsyncMock(return_value={"choices": []})
    monkeypatch.setattr(multimedia, "media_json", transport)
    request = MediaRequest(operation="audio_read", model="gemini-3.1-pro-preview", prompt="Identify sounds")
    source = tmp_path / "source"
    source.write_bytes(b"audio")
    with pytest.raises(ValueError, match="WAV or MP3"):
        await MammouthMedia().analyze(connection(), request, source, "audio/ogg")
    transport.assert_not_called()
    with pytest.raises(ValueError, match="no media analysis"):
        await MammouthMedia().analyze(connection(), request, source, "audio/wav")
    for operation in ("music_generate", "sound_generate", "video_generate"):
        assert not MammouthMedia().supports(operation, "gemini-3.1-pro-preview")
