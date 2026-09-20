from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse

from app.image import image_service
from app.llm import LLMCallPurpose


@pytest.mark.asyncio
async def test_image_proxy_keeps_trace_context_without_executor_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    received: dict[str, object] = {}

    async def fake_proxy(
        body: dict[str, object],
        *,
        purpose: object,
        task_id: object,
        agent_id: int,
        route_executor_model: bool,
    ) -> JSONResponse:
        received.update({
            "body": body,
            "purpose": purpose,
            "task_id": task_id,
            "agent_id": agent_id,
            "route_executor_model": route_executor_model,
        })
        return JSONResponse({"choices": []})

    monkeypatch.setattr(image_service, "proxy_chat_completion", fake_proxy)
    body: dict[str, object] = {
        "model": "image-model",
        "messages": [{"role": "user", "content": "Une affiche"}],
    }

    result = await image_service._proxy_completion_json(  # pyright: ignore[reportPrivateUsage]
        body,
        "provider/image-model",
        "image",
        "fr",
        task_id=task_id,
        agent_id=17,
    )

    assert result == {"choices": []}
    assert received == {
        "body": body,
        "purpose": LLMCallPurpose.IMAGE_GENERATION,
        "task_id": task_id,
        "agent_id": 17,
        "route_executor_model": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("dimensions", [{}, {"width": 100000, "height": 100000}])
async def test_generate_image_requests_only_the_image_output_modality(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: dict[str, int],
) -> None:
    received: dict[str, object] = {}

    async def fake_resolve(
        resolver: object,
        missing_key: str,
        language: str,
    ) -> tuple[str, str]:
        del resolver
        assert missing_key == "generation_model_missing"
        assert language == "en"
        return "flux", "openrouter/flux"

    async def fake_completion(
        body: dict[str, object],
        model: str,
        kind: str,
        language: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        received.update(body=body, model=model, kind=kind, language=language)
        return {
            "choices": [{
                "message": {
                    "images": [{
                        "image_url": {"url": "data:image/png;base64,aW1hZ2U="}
                    }]
                }
            }]
        }

    monkeypatch.setattr(image_service, "_resolve_llm_config", fake_resolve)
    monkeypatch.setattr(image_service, "_proxy_completion_json", fake_completion)
    native = AsyncMock(return_value=None)
    monkeypatch.setattr(image_service, "generate_image_native", native)

    data, mime = await image_service.generate_image_bytes("Create an image", language="en", **dimensions)

    assert (data, mime) == (b"image", "image/png")
    body = received["body"]
    assert isinstance(body, dict)
    assert body["modalities"] == ["image"]
    assert "image_config" not in body
    assert "size" not in body
    assert native.await_count == bool(dimensions)


@pytest.mark.asyncio
@pytest.mark.parametrize("sources", [None, [(b"source", "image/png")]])
async def test_generate_image_sends_dimensions_to_native_generation(
    monkeypatch: pytest.MonkeyPatch,
    sources: list[tuple[bytes, str]] | None,
) -> None:
    task_id = uuid4()
    native = AsyncMock(return_value=(b"original-provider-image", "image/jpeg"))
    completion = AsyncMock(side_effect=AssertionError("The chat endpoint must not be used"))
    monkeypatch.setattr(
        image_service, "_resolve_llm_config",
        AsyncMock(return_value=("image-code", "any-provider/image-model")),
    )
    monkeypatch.setattr(image_service, "_proxy_completion_json", completion)
    monkeypatch.setattr(image_service, "generate_image_native", native)

    data, result_mime = await image_service.generate_image_bytes(
        "A blue square", sources, width=1024, height=1024, agent_id=17, task_id=task_id,
    )

    assert (data, result_mime) == (b"original-provider-image", "image/jpeg")
    native.assert_awaited_once_with(
        "image-code", "A blue square", sources or [], width=1024, height=1024,
        agent_id=17, task_id=task_id,
    )
    completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_rejects_unpaired_dimensions_before_model_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve = AsyncMock()
    monkeypatch.setattr(image_service, "_resolve_llm_config", resolve)

    with pytest.raises(ValueError, match="supplied together"):
        await image_service.generate_image_bytes("A poster", width=1024)

    resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mime", ["video/mp4", "audio/mpeg", "application/pdf", ""])
async def test_describe_image_rejects_non_image_mime_before_model_resolution(
    monkeypatch: pytest.MonkeyPatch,
    mime: str,
) -> None:
    resolved = False

    async def fake_resolve(*args: object, **kwargs: object) -> tuple[str, str]:
        nonlocal resolved
        resolved = True
        return "vision-model", "provider/vision-model"

    monkeypatch.setattr(image_service, "_resolve_llm_config", fake_resolve)

    with pytest.raises(RuntimeError, match="image_read"):
        await image_service.describe_image(b"not-an-image", mime, language="en")

    assert resolved is False


@pytest.mark.asyncio
async def test_describe_image_uses_only_the_configured_vision_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    vision_resolver = AsyncMock(return_value=None)

    async def fake_resolve(
        resolver: object,
        missing_key: str,
        language: str,
    ) -> tuple[str, str]:
        await resolver()  # type: ignore[operator]
        received.update({
            "resolver": resolver,
            "missing_key": missing_key,
            "language": language,
        })
        return "vision-code", "provider/vision-model"

    async def fake_completion(
        body: dict[str, object],
        model: str,
        kind: str,
        language: str,
        *,
        task_id: object = None,
        agent_id: int | None = None,
    ) -> dict[str, object]:
        received.update({
            "body": body,
            "model": model,
            "kind": kind,
            "proxy_language": language,
            "task_id": task_id,
            "agent_id": agent_id,
        })
        return {"choices": [{"message": {"content": "A test image"}}]}

    monkeypatch.setattr(image_service, "_resolve_llm_config", fake_resolve)
    monkeypatch.setattr(image_service, "_proxy_completion_json", fake_completion)
    monkeypatch.setattr(image_service.llm_service, "get_vision_llm", vision_resolver)

    result = await image_service.describe_image(
        b"image-bytes",
        "IMAGE/JPEG; charset=binary",
        instruction="Inspect",
        language="en",
        agent_id=17,
    )

    assert result == "A test image"
    vision_resolver.assert_awaited_once_with(agent_id=17)
    assert received["missing_key"] == "vision_model_missing"
    assert received["kind"] == "vision"
    assert received["model"] == "provider/vision-model"
    assert received["agent_id"] == 17
    assert received["body"] == {
        "model": "vision-code",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,aW1hZ2UtYnl0ZXM="
                    },
                },
            ],
        }],
    }


@pytest.mark.asyncio
async def test_describe_image_errors_when_no_vision_model_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_vision_model(*, agent_id: int | None = None) -> None:
        assert agent_id is None
        return None

    async def unexpected_proxy(*args: object, **kwargs: object) -> None:
        pytest.fail("The provider must not be called without a configured vision model")

    monkeypatch.setattr(image_service.llm_service, "get_vision_llm", no_vision_model)
    monkeypatch.setattr(image_service, "proxy_chat_completion", unexpected_proxy)

    with pytest.raises(RuntimeError, match="current profile"):
        await image_service.describe_image(b"image", "image/png", language="en")
