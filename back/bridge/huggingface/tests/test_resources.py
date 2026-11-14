"""Hugging Face discovery and inference contracts (synthetic catalogs only)."""

from bridge.huggingface import PROFILE


def test_specialist_capabilities_are_available():
    assert {"chat", "vision", "embedding", "transcription", "speech", "image_generation"} <= set(PROFILE.capabilities)
    assert PROFILE.supports_transcription

import httpx
import pytest

from app.llm import llm_provider_service, resource_discovery
from app.llm.embedding_service import EmbeddingEndpoint, EmbeddingError, embed_many_with_usage
from app.llm.provider_facade import (
    ProviderConnection, ProviderTranscriptionError, SpeechOptions,
    embedding_provider_for, image_generation_provider_for, speech_provider_for,
    transcription_provider_for,
)
from app.llm.provider_models import LLMProvider
from bridge.huggingface.resources import HUB, ROUTER, HuggingFaceResources


def connection(**kwargs):
    return ProviderConnection(id=1, name="Hugging Face", catalog_code="huggingface",
        provider_type="openai_compatible", base_url=PROFILE.base_url, api_key="synthetic-token", **kwargs)


def mapping(provider, task, *, status="live", model="vendor/mapped"):
    return {"provider": provider, "task": task, "status": status, "providerId": model}


def row(name="synthetic/model", task="automatic-speech-recognition", provider="hf-inference", **kwargs):
    return {"id": name, "inferenceProviderMapping": [mapping(provider, task)], **kwargs}


@pytest.fixture
def http(monkeypatch):
    requests = []
    respond = [lambda request: httpx.Response(500)]
    client_type = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-token"
        return respond[0](request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handle)))
    return requests, respond


@pytest.mark.asyncio
@pytest.mark.parametrize("capability,task,provider", [
    ("transcription", "automatic-speech-recognition", "hf-inference"),
    ("speech", "text-to-speech", "deepinfra"),
    ("embedding", "feature-extraction", "hf-inference"),
    ("image_generation", "text-to-image", "hf-inference"),
])
async def test_public_service_discovers_only_callable_specialists(http, monkeypatch, capability, task, provider):
    requests, respond = http
    rows = [row(task=task, provider=provider),
        row("synthetic/offline", task=task, provider=provider),
        row("synthetic/unsupported", task=task, provider="unknown"),
        row("synthetic/wrong-task", task="text-generation", provider=provider)]
    rows[1]["inferenceProviderMapping"][0]["status"] = "staging"
    respond[0] = lambda request: httpx.Response(200, json=rows)
    model = LLMProvider(name="Hugging Face", catalog_code="huggingface",
        provider_type="openai_compatible", base_url=PROFILE.base_url)

    async def enrich(_provider, models, **kwargs):
        return models

    monkeypatch.setattr(llm_provider_service, "enrich_models", enrich)
    found = await llm_provider_service._list_provider_resources(model, "synthetic-token", capability, force_refresh=True)
    assert [item.id for item in found] == ["synthetic/model"]
    assert found[0].service_capabilities == [capability]
    assert found[0].modalities["input_audio"] is (capability == "transcription")
    assert found[0].modalities["output_audio"] is (capability == "speech")
    assert str(requests[0].url).startswith(HUB)
    assert requests[0].url.params["pipeline_tag"] == task


@pytest.mark.asyncio
async def test_pagination_and_sentence_transformer_embedding_tasks(http):
    requests, respond = http

    def handle(request):
        if request.url.params.get("pipeline_tag") == "feature-extraction":
            return httpx.Response(200, json=[row(task="feature-extraction")], headers={
                "Link": f'<{HUB}?cursor=next>; rel="next"'})
        if request.url.params.get("cursor"):
            return httpx.Response(200, json=[row("synthetic/page-two", task="feature-extraction")])
        sentence = row("synthetic/sentences", task="sentence-similarity", tags=["feature-extraction"])
        invalid = row("synthetic/similarity-only", task="sentence-similarity")
        return httpx.Response(200, json=[sentence, invalid, row(task="feature-extraction")])

    respond[0] = handle
    found = await HuggingFaceResources().list_resources(connection(), "embedding")
    assert [item.id for item in found] == ["synthetic/model", "synthetic/page-two", "synthetic/sentences"]
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("continuation", ["https://untrusted.example/api/models", f"{HUB}?again=1"])
async def test_catalog_rejects_unsafe_or_cyclic_pagination(http, continuation):
    requests, respond = http
    respond[0] = lambda request: httpx.Response(200, json=[], headers={
        "Link": f'<{continuation}>; rel="next"'})
    with pytest.raises(ValueError, match="continuation|pagination"):
        await HuggingFaceResources().list_resources(connection(), "transcription")
    assert len(requests) <= 2
    assert all(request.url.host == "huggingface.co" for request in requests)


@pytest.mark.asyncio
async def test_chat_and_vision_use_existing_router_catalog(http):
    requests, respond = http
    respond[0] = lambda request: httpx.Response(200, json={"data": [
        {"id": "synthetic/chat", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
        {"id": "synthetic/vision", "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
    ]})
    discovery = HuggingFaceResources()
    assert [item.id for item in await discovery.list_resources(connection(), "chat")] == ["synthetic/chat", "synthetic/vision"]
    assert [item.id for item in await discovery.list_resources(connection(), "vision")] == ["synthetic/vision"]
    assert all(str(request.url) == f"{PROFILE.base_url}/models" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_discovery_preserves_http_failures(http, status):
    requests, respond = http
    respond[0] = lambda request: httpx.Response(status, json={"error": "synthetic upstream failure"})
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await HuggingFaceResources().list_resources(connection(), "transcription")
    assert caught.value.response.status_code == status
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["hf-inference", "deepinfra"])
async def test_embeddings_use_native_route_and_common_validation(http, provider):
    import json
    requests, respond = http

    def handle(request):
        if request.method == "GET":
            # Single-model Hub responses use a mapping object instead of the list shape.
            return httpx.Response(200, json={"inferenceProviderMapping": {
                provider: {"task": "feature-extraction", "status": "live", "providerId": "vendor/mapped"}}})
        body = json.loads(request.content)
        if provider == "hf-inference":
            assert str(request.url) == f"{ROUTER}/hf-inference/models/synthetic/model/pipeline/feature-extraction"
            assert body == {"inputs": ["first", "second"]}
            return httpx.Response(200, json=[[1, 0], [0, 1]])
        assert str(request.url) == f"{ROUTER}/deepinfra/v1/openai/embeddings"
        assert body == {"input": ["first", "second"], "model": "vendor/mapped", "encoding_format": "float"}
        return httpx.Response(200, json={"model": "vendor/mapped", "usage": {"prompt_tokens": 2}, "data": [
            {"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})

    respond[0] = handle
    result = await embed_many_with_usage([" first ", "second"], endpoint=EmbeddingEndpoint(
        "synthetic/model", PROFILE.base_url, "synthetic-token", connection()), timeout_seconds=5)
    assert result.embeddings == [[1.0, 0.0], [0.0, 1.0]]
    assert (result.usage == {"prompt_tokens": 2}) is (provider == "deepinfra")
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[[1, 2]], [[1], [1, 2]], [[[1, 2]], [[3, 4]]], [["bad"], [2]]])
async def test_native_embedding_malformed_vectors_fail(http, vectors):
    requests, respond = http
    respond[0] = lambda request: httpx.Response(200, json=(
        row(task="feature-extraction") if request.method == "GET" else vectors))
    with pytest.raises(EmbeddingError):
        await embed_many_with_usage(["first", "second"], endpoint=EmbeddingEndpoint(
            "synthetic/model", PROFILE.base_url, "synthetic-token"), timeout_seconds=5)


@pytest.mark.asyncio
async def test_embedding_http_failure_preserves_retry_classification(http):
    requests, respond = http
    respond[0] = lambda request: httpx.Response(503, json={"error": "unavailable"})
    with pytest.raises(EmbeddingError) as caught:
        await embed_many_with_usage(["first"], endpoint=EmbeddingEndpoint(
            "synthetic/model", PROFILE.base_url, "synthetic-token"), timeout_seconds=5)
    assert isinstance(caught.value.__cause__, httpx.HTTPStatusError)
    assert caught.value.__cause__.response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["hf-inference", "deepinfra"])
@pytest.mark.parametrize("language", ["", "fr-FR"])
async def test_transcription_uploads_files_to_mapped_route(http, tmp_path, provider, language):
    import base64
    import json
    requests, respond = http
    source = tmp_path / "synthetic.wav"
    source.write_bytes(b"synthetic audio bytes")

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=row(provider=provider))
        if provider == "hf-inference":
            assert str(request.url) == f"{ROUTER}/hf-inference/models/synthetic/model"
            if language:
                body = json.loads(request.content)
                assert base64.b64decode(body["inputs"]) == source.read_bytes()
                assert body["parameters"] == {"generation_parameters": {"language": "fr"}}
            else:
                assert request.content == source.read_bytes()
        else:
            assert str(request.url) == f"{ROUTER}/deepinfra/v1/openai/audio/transcriptions"
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert b"vendor/mapped" in request.content and source.read_bytes() in request.content
            assert (b'name="language"' in request.content) is bool(language)
        return httpx.Response(200, json={"text": "synthetic transcript", "usage": {"seconds": 2}}, headers={"x-request-id": "synthetic-request"})

    respond[0] = handle
    result = await transcription_provider_for(connection()).transcribe(connection(), model="synthetic/model",
        source=source, filename=source.name, mime_type="audio/wav", language=language, timeout=5)
    assert result.text == "synthetic transcript"
    assert result.usage == {"seconds": 2}
    assert "synthetic transcript" in result.raw_response
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [({"text": ""}, 200), ({"text": 123}, 200), ({"error": "denied"}, 403)])
async def test_transcription_failures_are_domain_errors(http, payload, status):
    requests, respond = http
    respond[0] = lambda request: httpx.Response(200, json=row()) if request.method == "GET" else httpx.Response(status, json=payload)
    with pytest.raises(ProviderTranscriptionError):
        await transcription_provider_for(connection()).transcribe(connection(), model="synthetic/model",
            source=b"audio", filename="test.wav", mime_type="audio/wav", language="", timeout=5)


@pytest.mark.asyncio
async def test_speech_uses_mp3_and_selected_voice_without_realtime(http):
    import json
    requests, respond = http

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=row(task="text-to-speech", provider="deepinfra"))
        assert str(request.url) == f"{ROUTER}/deepinfra/v1/openai/audio/speech"
        assert json.loads(request.content) == {"model": "vendor/mapped", "input": "synthetic speech",
            "response_format": "mp3", "speed": 1.1, "voice": "synthetic-voice"}
        return httpx.Response(200, content=b"ID3synthetic audio", headers={"content-type": "audio/mpeg"})

    respond[0] = handle
    service = speech_provider_for(connection())
    options = SpeechOptions(voice="synthetic-voice", speed=1.1)
    result = await service.synthesize(connection(), model="synthetic/model", resource_type="model", text="synthetic speech", options=options)
    assert result.content == b"ID3synthetic audio"
    assert result.voice == "synthetic-voice"
    assert await service.create_realtime_stream(connection(), model="synthetic/model", resource_type="model", options=options) is None


@pytest.mark.asyncio
async def test_live_route_is_rechecked_and_never_falls_back_after_post(http):
    requests, respond = http
    live = [True]

    def handle(request):
        if request.method == "GET":
            model = row(task="text-to-speech", provider="deepinfra")
            if not live[0]:
                model["inferenceProviderMapping"][0]["status"] = "staging"
            return httpx.Response(200, json=model)
        return httpx.Response(503, json={"error": "unavailable"})

    respond[0] = handle
    service = speech_provider_for(connection())
    kwargs = dict(model="synthetic/model", resource_type="model", text="test", options=SpeechOptions())
    with pytest.raises(httpx.HTTPStatusError):
        await service.synthesize(connection(), **kwargs)
    assert sum(request.method == "POST" for request in requests) == 1
    live[0] = False
    with pytest.raises(ValueError, match="no supported live"):
        await service.synthesize(connection(), **kwargs)
    assert sum(request.method == "POST" for request in requests) == 1


def test_native_image_generation_uses_binary_protocol_and_rejects_editing():
    import json
    service = image_generation_provider_for(connection())
    kwargs = dict(model="synthetic/image", prompt="synthetic scenery", width=1024, height=1024)
    request = service.prepare_request(connection(), sources=[], **kwargs)
    assert str(request.url) == f"{ROUTER}/hf-inference/models/synthetic/image"
    assert json.loads(request.content) == {"inputs": "synthetic scenery"}
    result = service.read_response(httpx.Response(200, content=b"synthetic image", headers={"content-type": "image/png"}))
    assert result.content == b"synthetic image" and result.media_type == "image/png"
    with pytest.raises(ValueError, match="editing"):
        service.prepare_request(connection(), sources=[(b"image", "image/png")], **kwargs)
    with pytest.raises(ValueError, match="no supported image"):
        service.read_response(httpx.Response(200, json={"error": "invalid image"}))


@pytest.mark.asyncio
async def test_invalid_model_or_missing_key_never_sends_credentials(http):
    requests, respond = http
    for model in ["https://untrusted.example/model", "../secret", "synthetic/model:unknown"]:
        with pytest.raises(EmbeddingError):
            await embed_many_with_usage(["first"], endpoint=EmbeddingEndpoint(
                model, PROFILE.base_url, "synthetic-token"), timeout_seconds=5)
    with pytest.raises(ValueError, match="token"):
        await HuggingFaceResources().list_resources(ProviderConnection(
            id=None, name="HF", catalog_code="huggingface", provider_type="openai_compatible",
            base_url=PROFILE.base_url), "transcription")
    assert requests == []


@pytest.mark.asyncio
async def test_embedding_deadline_includes_native_route_resolution(http):
    import asyncio
    requests, respond = http

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=row(task="feature-extraction"))

    respond[0] = slow
    with pytest.raises(EmbeddingError, match="timed out") as caught:
        await embed_many_with_usage(["first"], endpoint=EmbeddingEndpoint(
            "synthetic/model", PROFILE.base_url, "synthetic-token"), timeout_seconds=0.01)
    assert isinstance(caught.value.__cause__, httpx.ReadTimeout)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_cancelling_transcription_releases_native_audio_buffers(http):
    import asyncio
    from core.util import buffered_io_budget
    requests, respond = http
    entered = asyncio.Event()

    async def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=row())
        entered.set()
        await asyncio.Future()

    respond[0] = handle
    before = (buffered_io_budget.used, buffered_io_budget.active)
    task = asyncio.create_task(transcription_provider_for(connection()).transcribe(
        connection(), model="synthetic/model", source=b"audio", filename="test.wav",
        mime_type="audio/wav", language="fr", timeout=5))
    await asyncio.wait_for(entered.wait(), timeout=5)
    assert buffered_io_budget.used > before[0]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (buffered_io_budget.used, buffered_io_budget.active) == before
