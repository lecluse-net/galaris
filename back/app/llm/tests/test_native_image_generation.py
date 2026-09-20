import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.llm import image_generation_service as service
from app.llm.provider_facade import ProviderConnection, image_generation_provider_for
from bridge.google.image import native_image_config
from bridge.google.image import GeminiImageGeneration
from bridge.fireworks.image import FireworksImageGeneration
from app.llm import nearest_image_size
from bridge.openai.image import OpenAIImageGeneration
from bridge.openrouter.image import OpenRouterImageGeneration


def image_bytes(width=1024, height=1024, image_format="PNG"):
    output = BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
def model_context(monkeypatch):
    provider = SimpleNamespace(
        id=5, name="Image provider", catalog_code="openai-api", provider_type="openai_compatible",
        base_url="https://provider.example/v1", api_key=None, configuration={}, is_active=True,
    )
    model = SimpleNamespace(
        id=8, provider=provider, llm_name="gpt-image-1", is_subscription=False,
        cost_per_input_token=0, cost_per_cached_input_token=0, cost_per_output_token=0,
    )
    monkeypatch.setattr(service.llm_service, "get_llm_by_code", AsyncMock(return_value=model))
    monkeypatch.setattr(service, "enforce_subscription_access", AsyncMock(return_value=None))
    monkeypatch.setattr(service.llm_provider_service, "decrypt_api_key", lambda _: "test-api-key")
    create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    finalize = AsyncMock()
    monkeypatch.setattr(service.llm_call_service, "create_running_call", create)
    monkeypatch.setattr(service.llm_call_service, "finalize_call", finalize)
    return model, create, finalize


def mock_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx, "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_code,model_name,endpoint,dimensions", [
    ("openai-api", "gpt-image-1", "/v1/images/generations", (1024, 1024)),
    (None, "custom-image", "/v1/images/generations", (800, 600)),
    ("openrouter", "google/gemini-3.1-flash-image", "/v1/images", (1376, 768)),
    ("gemini", "gemini-2.5-flash-image", "/v1/models/gemini-2.5-flash-image:generateContent", (1344, 768)),
    ("fireworks", "accounts/fireworks/models/stable-diffusion-xl-1024-v1-0",
     "/v1/image_generation/accounts/fireworks/models/stable-diffusion-xl-1024-v1-0", (1024, 1024)),
])
async def test_native_dimensions_reach_each_provider_and_bytes_are_preserved(
    monkeypatch, model_context, provider_code, model_name, endpoint, dimensions,
):
    model, create, finalize = model_context
    model.provider.catalog_code = provider_code
    model.llm_name = model_name
    if provider_code == "gemini":
        model.provider.base_url += "/openai"
    original = image_bytes(*dimensions)
    encoded = base64.b64encode(original).decode("ascii")
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == endpoint
        payload = json.loads(request.content)
        if provider_code == "gemini":
            assert request.headers["x-goog-api-key"] == "test-api-key"
            assert payload["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9"}
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"inlineData": {"data": encoded, "mimeType": "image/png"}},
            ]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 10}})
        assert request.headers["authorization"] == "Bearer test-api-key"
        if provider_code == "fireworks":
            assert (payload["width"], payload["height"]) == dimensions
            return httpx.Response(200, content=original, headers={"content-type": "image/png"})
        if provider_code == "openrouter":
            assert payload["aspect_ratio"] == "16:9"
            assert payload["resolution"] == "1K"
            assert "size" not in payload
        elif provider_code is None:
            assert "size" not in payload
        else:
            assert payload["size"] == f"{dimensions[0]}x{dimensions[1]}"
        assert "image_config" not in payload
        return httpx.Response(200, json={"data": [{"b64_json": encoded}], "usage": {"total_tokens": 15}})

    mock_http(monkeypatch, handler)
    task_id = uuid4()
    result = await service.generate_image_native(
        "selected-model-code", "A blue image", [], width=dimensions[0], height=dimensions[1],
        agent_id=17, task_id=task_id,
    )

    assert result == (original, "image/png")
    assert len(requests) == 1
    assert create.call_args.kwargs["task_id"] == task_id
    assert create.call_args.kwargs["agent_id"] == 17
    assert create.call_args.kwargs["purpose"] == "image.generation"
    assert finalize.call_args.kwargs.get("status", "completed") == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_code", ["openai-api", "openrouter", "gemini"])
async def test_native_edits_forward_every_source_and_dimensions(monkeypatch, model_context, provider_code):
    model, _, _ = model_context
    model.provider.catalog_code = provider_code
    if provider_code == "gemini":
        model.llm_name = "gemini-3.1-flash-image"
    elif provider_code == "openrouter":
        model.llm_name = "openai/gpt-image-1"
    original = image_bytes()
    encoded = base64.b64encode(original).decode("ascii")
    sources = [(b"first-image", "image/png"), (b"second-image", "image/jpeg")]

    def handler(request):
        if provider_code == "openai-api":
            assert request.url.path.endswith("/images/edits")
            assert request.headers["content-type"].startswith("multipart/form-data")
            assert b'name="size"\r\n\r\n1024x1024' in request.content
            assert b"first-image" in request.content and b"second-image" in request.content
            assert request.content.count(b'name="image[]"') == 2
        else:
            payload = json.loads(request.content)
            if provider_code == "gemini":
                assert payload["generationConfig"]["imageConfig"] == {"aspectRatio": "1:1", "imageSize": "1K"}
                parts = payload["contents"][0]["parts"]
                assert [base64.b64decode(part["inlineData"]["data"]) for part in parts[1:]] == [s[0] for s in sources]
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                    {"inlineData": {"data": encoded, "mimeType": "image/png"}},
                ]}}]})
            assert payload["size"] == "1024x1024"
            assert len(payload["input_references"]) == 2
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})

    mock_http(monkeypatch, handler)
    assert await service.generate_image_native(
        "selected", "Compose", sources, width=1024, height=1024,
    ) == (original, "image/png")


@pytest.mark.asyncio
async def test_different_native_dimensions_are_accepted_without_transform_or_retry(monkeypatch, model_context):
    _, _, finalize = model_context
    original = image_bytes(800, 600)
    encoded = base64.b64encode(original).decode("ascii")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": encoded}], "usage": {"total_tokens": 15}})

    mock_http(monkeypatch, handler)
    result = await service.generate_image_native("selected", "Image", [], width=1024, height=1024)
    assert result == (original, "image/png")
    assert len(requests) == 1
    assert finalize.call_args.kwargs.get("status", "completed") == "completed"
    assert "800x600" in finalize.call_args.kwargs["trace"]["response_text"]
    assert finalize.call_args.kwargs["trace"]["usage"]["total_tokens"] == 15


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(400, {"error": {"message": "Unsupported size"}}), (200, {"data": []})])
async def test_provider_errors_are_recorded(monkeypatch, model_context, status, payload):
    _, _, finalize = model_context
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=payload))
    with pytest.raises(ValueError):
        await service.generate_image_native("selected", "Image", [], width=1024, height=1024)
    assert finalize.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,model,size", [
    ("fireworks", "accounts/fireworks/models/flux-kontext-pro", (1920, 1080)),
])
async def test_unsupported_native_sizes_fail_before_http(monkeypatch, model_context, code, model, size):
    resource, create, _ = model_context
    resource.provider.catalog_code = code
    resource.llm_name = model
    mock_http(monkeypatch, lambda request: pytest.fail("No inference request is allowed"))
    with pytest.raises(ValueError):
        await service.generate_image_native("selected", "Image", [], width=size[0], height=size[1])
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_without_size_adapter_delegates_to_default_generation(monkeypatch, model_context):
    model, create, _ = model_context
    model.provider.catalog_code = "unknown-provider"
    mock_http(monkeypatch, lambda request: pytest.fail("The default generation path owns this request"))
    assert await service.generate_image_native("selected", "Image", [], width=100000, height=100000) is None
    create.assert_not_awaited()


@pytest.mark.parametrize("model,width,height,expected", [
    ("gemini-2.5-flash-image", 1344, 768, {"aspectRatio": "16:9"}),
    ("gemini-3-pro-image-preview", 2752, 1536, {"aspectRatio": "16:9", "imageSize": "2K"}),
    ("gemini-3.1-flash-image", 4096, 4096, {"aspectRatio": "1:1", "imageSize": "4K"}),
    ("gemini-3.1-flash-image", 512, 512, {"aspectRatio": "1:1", "imageSize": "512"}),
])
def test_gemini_uses_exact_native_combinations(model, width, height, expected):
    assert native_image_config(model, width, height) == expected


@pytest.mark.parametrize("model,width,height,expected", [
    ("google/gemini-2.5-flash-image", 1184, 864, {"aspect_ratio": "4:3", "resolution": "1K"}),
    ("google/gemini-3.1-flash-image", 600, 448, {"aspect_ratio": "4:3", "resolution": "512"}),
    ("google/gemini-3.1-flash-image", 1200, 896, {"aspect_ratio": "4:3", "resolution": "1K"}),
    ("google/gemini-3.1-flash-image", 2400, 1792, {"aspect_ratio": "4:3", "resolution": "2K"}),
    ("google/gemini-3.1-flash-image", 4800, 3584, {"aspect_ratio": "4:3", "resolution": "4K"}),
    ("openai/gpt-image-1", 1536, 1024, {"size": "1536x1024"}),
    ("other/custom-image", 640, 480, {}),
])
def test_router_preserves_model_native_resolution_and_references(model, width, height, expected):
    connection = ProviderConnection(1, "Router", "openrouter", "openai_compatible", "https://example.com/v1")
    request = OpenRouterImageGeneration().prepare_request(
        connection, model=model, prompt="Image", sources=[(b"reference", "image/png")],
        width=width, height=height,
    )
    payload = json.loads(request.content)
    assert {k: payload[k] for k in ("size", "aspect_ratio", "resolution") if k in payload} == expected
    assert payload["model"] == model
    assert payload["input_references"][0]["image_url"]["url"] == "data:image/png;base64,cmVmZXJlbmNl"


def test_gpt_image_2_accepts_native_arbitrary_sizes():
    connection = ProviderConnection(1, "OpenAI", "openai-api", "openai_compatible", "https://example.com/v1")
    request = OpenAIImageGeneration().prepare_request(
        connection, model="gpt-image-2", prompt="Image", sources=[], width=1536, height=864,
    )
    assert json.loads(request.content)["size"] == "1536x864"
    adjusted = OpenAIImageGeneration().prepare_request(
        connection, model="gpt-image-2", prompt="Image", sources=[], width=1920, height=1080,
    )
    assert json.loads(adjusted.content)["size"] == "1920x1088"


@pytest.mark.parametrize("adapter,model,target,expected", [
    (GeminiImageGeneration(), "gemini-3.1-flash-image", (640, 480), (1200, 896)),
    (GeminiImageGeneration(), "gemini-3.1-flash-image", (480, 640), (896, 1200)),
    (GeminiImageGeneration(), "gemini-3.1-flash-image", (100000, 100000), (4096, 4096)),
    (OpenRouterImageGeneration(), "google/gemini-3.1-flash-image", (640, 480), (1200, 896)),
    (OpenRouterImageGeneration(), "google/gemini-3.1-flash-image:free", (100000, 100000), (4096, 4096)),
    (OpenAIImageGeneration(), "gpt-image-1", (640, 480), (1024, 1024)),
    (OpenAIImageGeneration(), "gpt-image-1", (1920, 1080), (1536, 1024)),
    (OpenAIImageGeneration(), "gpt-image-2", (100000, 100000), (2880, 2880)),
    (OpenAIImageGeneration(), "dall-e-2", (100000, 100000), (1024, 1024)),
    (OpenRouterImageGeneration(), "openai/gpt-image-1", (100000, 100000), (1024, 1536)),
    (FireworksImageGeneration(), "accounts/fireworks/models/stable-diffusion-xl-1024-v1-0", (100000, 100000), (1024, 1024)),
])
def test_best_effort_native_selection(adapter, model, target, expected):
    selected = adapter.select_size(model, *target)
    assert (selected.width, selected.height) == expected


def test_nearest_native_size_prefers_above_then_falls_back_at_limits():
    sizes = [(600, 448), (1200, 896), (2400, 1792)]
    assert nearest_image_size(600, 448, sizes) == (600, 448)
    assert nearest_image_size(640, 480, sizes) == (1200, 896)
    assert nearest_image_size(100000, 100000, sizes) == (2400, 1792)


@pytest.mark.asyncio
@pytest.mark.parametrize("target,selected", [((640, 480), (1200, 896)), ((100000, 100000), (4096, 4096))])
async def test_best_effort_router_generation_succeeds_once_and_records_real_size(monkeypatch, model_context, target, selected):
    model, create, finalize = model_context
    model.provider.catalog_code = "openrouter"
    model.llm_name = "google/gemini-3.1-flash-image"
    original = image_bytes(*selected)
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert "size" not in payload
        assert payload["resolution"] == ("1K" if target == (640, 480) else "4K")
        assert payload["aspect_ratio"] == ("4:3" if target == (640, 480) else "1:1")
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(original).decode()}]})

    mock_http(monkeypatch, handler)
    result = await service.generate_image_native("selected", "Image", [], width=target[0], height=target[1])
    assert result == (original, "image/png")
    assert len(requests) == 1
    assert finalize.call_args.kwargs.get("status", "completed") == "completed"
    assert f"{selected[0]}x{selected[1]}" in finalize.call_args.kwargs["trace"]["response_text"]
    prompt = create.call_args.kwargs["request_body"]["messages"][0]["content"]
    assert f"Preferred image dimensions: {target[0]}x{target[1]}" in prompt
    assert f"Selected native dimensions: {selected[0]}x{selected[1]}" in prompt


def test_custom_compatible_fallback_does_not_override_known_provider():
    custom = ProviderConnection(1, "Custom", None, "openai_compatible", "https://example.com/v1")
    unsupported = ProviderConnection(2, "Known", "unsupported", "openai_compatible", "https://example.com/v1")
    assert isinstance(image_generation_provider_for(custom), OpenAIImageGeneration)
    assert image_generation_provider_for(unsupported) is None


def test_legacy_provider_url_selects_its_own_protocol():
    connection = ProviderConnection(1, "Legacy router", None, "openai_compatible", "https://openrouter.ai/api/v1")
    assert isinstance(image_generation_provider_for(connection), OpenRouterImageGeneration)


@pytest.mark.asyncio
async def test_native_image_preserves_jpeg_bytes_and_reports_actual_format(monkeypatch, model_context):
    original = image_bytes(image_format="JPEG")
    encoded = base64.b64encode(original).decode("ascii")
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"b64_json": encoded}]}))

    result = await service.generate_image_native("selected", "Image", [], width=1024, height=1024)

    assert result == (original, "image/jpeg")


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["disabled", "subscription"])
async def test_native_generation_keeps_provider_authorization(monkeypatch, model_context, denial):
    model, create, _ = model_context
    if denial == "disabled":
        model.provider.is_active = False
    else:
        monkeypatch.setattr(service, "enforce_subscription_access", AsyncMock(side_effect=ValueError("Access denied")))
    mock_http(monkeypatch, lambda request: pytest.fail("No unauthorized inference request"))

    with pytest.raises(ValueError):
        await service.generate_image_native("selected", "Image", [], width=1024, height=1024)

    create.assert_not_awaited()
