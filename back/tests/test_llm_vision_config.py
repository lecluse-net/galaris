from types import SimpleNamespace

import pytest

from app.llm import llm_service, model_usages


ANALYSIS_RESOLVERS = (
    ("get_vision_llm", model_usages.VISION, "input_image"),
    ("get_document_llm", model_usages.DOCUMENT, "input_file"),
    ("get_audio_llm", model_usages.AUDIO, "input_audio"),
    ("get_video_llm", model_usages.VIDEO, "input_video"),
)


@pytest.mark.asyncio
async def test_get_vision_llm_uses_dedicated_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = SimpleNamespace(
        id=42,
        input_image=True,
        output_text=True,
    )

    async def resolve_standin(param_name: str) -> SimpleNamespace:
        assert param_name == model_usages.VISION
        return configured

    monkeypatch.setattr(llm_service, "get_profile_llm", resolve_standin)

    assert await llm_service.get_vision_llm() is configured


@pytest.mark.asyncio
async def test_get_vision_llm_rejects_incompatible_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = SimpleNamespace(
        id=42,
        input_image=False,
        output_text=True,
    )

    async def resolve_standin(param_name: str) -> SimpleNamespace:
        assert param_name == model_usages.VISION
        return configured

    monkeypatch.setattr(llm_service, "get_profile_llm", resolve_standin)

    assert await llm_service.get_vision_llm() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("resolver_name", "param_name", "input_field"), ANALYSIS_RESOLVERS)
async def test_analysis_llm_uses_its_dedicated_parameter(
    monkeypatch: pytest.MonkeyPatch,
    resolver_name: str,
    param_name: str,
    input_field: str,
) -> None:
    configured = SimpleNamespace(
        id=42,
        input_image=False,
        input_file=False,
        input_audio=False,
        input_video=False,
        output_text=True,
    )
    setattr(configured, input_field, True)

    async def resolve_standin(requested_param: str) -> SimpleNamespace:
        assert requested_param == param_name
        return configured

    monkeypatch.setattr(llm_service, "get_profile_llm", resolve_standin)

    resolver = getattr(llm_service, resolver_name)
    assert await resolver() is configured


@pytest.mark.asyncio
@pytest.mark.parametrize(("resolver_name", "param_name", "input_field"), ANALYSIS_RESOLVERS)
async def test_analysis_llm_rejects_incompatible_configured_model(
    monkeypatch: pytest.MonkeyPatch,
    resolver_name: str,
    param_name: str,
    input_field: str,
) -> None:
    configured = SimpleNamespace(
        id=42,
        input_image=False,
        input_file=False,
        input_audio=False,
        input_video=False,
        output_text=True,
    )

    async def resolve_standin(requested_param: str) -> SimpleNamespace:
        assert requested_param == param_name
        return configured

    monkeypatch.setattr(llm_service, "get_profile_llm", resolve_standin)

    resolver = getattr(llm_service, resolver_name)
    assert getattr(configured, input_field) is False
    assert await resolver() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("resolver_name", "param_name", "input_field"), ANALYSIS_RESOLVERS)
async def test_analysis_llm_honors_excluded_model(
    monkeypatch: pytest.MonkeyPatch,
    resolver_name: str,
    param_name: str,
    input_field: str,
) -> None:
    configured = SimpleNamespace(
        id=42,
        input_image=False,
        input_file=False,
        input_audio=False,
        input_video=False,
        output_text=True,
    )
    setattr(configured, input_field, True)

    async def resolve_standin(requested_param: str) -> SimpleNamespace:
        assert requested_param == param_name
        return configured

    monkeypatch.setattr(llm_service, "get_profile_llm", resolve_standin)

    resolver = getattr(llm_service, resolver_name)
    assert await resolver(exclude_llm_id=configured.id) is None
