"""ChatGPT Fast aliases remain distinct resources and use the real inference model."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from bridge.openai import codex_oauth
from bridge.openai.codex import CodexBridge


@pytest.fixture
def connection():
    return ProviderConnection(id=7, name="Synthetic ChatGPT", catalog_code="openai-codex",
        provider_type="openai_codex", base_url="https://chatgpt.com/backend-api/codex")


@pytest.mark.asyncio
async def test_account_catalog_offers_fast_only_when_advertised(monkeypatch, connection):
    monkeypatch.setattr(codex_oauth, "get_access_token", AsyncMock(return_value="synthetic-token"))
    monkeypatch.setattr(codex_oauth, "current_language", AsyncMock(return_value="en"))
    rows = [
        {"slug": "synthetic-sol", "display_name": "Synthetic Sol", "priority": 1,
         "context_window": 200_000, "supports_image_input": True,
         "service_tiers": [{"id": "priority", "name": "Fast"}]},
        {"slug": "synthetic-standard", "priority": 2, "service_tiers": []},
        {"slug": "synthetic-legacy", "priority": 3, "additional_speed_tiers": ["fast"]},
        {"slug": "synthetic-unknown", "priority": 4},
        {"slug": "synthetic-hidden", "visibility": "hidden",
         "service_tiers": [{"id": "priority"}]},
        {"slug": "synthetic-ultrafast", "priority": 5, "service_tiers": [{"id": "ultrafast"}]},
        {"slug": "synthetic-disabled", "priority": 6,
         "service_tiers": [], "additional_speed_tiers": ["fast"]},
    ]
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(**kwargs,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": rows}))))
    models = await codex_oauth.list_models(SimpleNamespace(id=7, base_url=connection.base_url))
    assert [model.id for model in models] == [
        "synthetic-sol", "synthetic-sol:fast", "synthetic-standard",
        "synthetic-legacy", "synthetic-legacy:fast", "synthetic-unknown",
        "synthetic-ultrafast", "synthetic-disabled",
    ]
    standard, fast = models[:2]
    assert fast.name == "Synthetic Sol Fast"
    assert fast.context_length == standard.context_length == 200_000
    assert fast.modalities == standard.modalities
    assert "usage" in fast.description.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["chat", "responses", "compact"])
@pytest.mark.parametrize("fast", [False, True])
async def test_fast_alias_routes_to_real_model_with_tier(monkeypatch, connection, protocol, fast):
    monkeypatch.setattr(codex_oauth, "get_access_token", AsyncMock(return_value="synthetic-token"))
    model = "synthetic-sol:fast" if fast else "synthetic-sol"
    body = {"model": model, "service_tier": "default"}
    bridge = CodexBridge()
    if protocol == "chat":
        body.update(messages=[{"role": "user", "content": "Synthetic request"}], reasoning_effort="high")
        prepared = await bridge.prepare_request(7, connection, body, force_refresh=True)
        assert prepared.body["reasoning"]["effort"] == "high"
    else:
        body.update(input="Synthetic request", reasoning={"effort": "high"})
        prepared = await bridge.prepare_responses_request(7, connection, body,
            operation="compact" if protocol == "compact" else "create", force_refresh=True)
        assert prepared.body["reasoning"]["effort"] == "high"
    assert prepared.body["model"] == "synthetic-sol"
    if protocol == "compact" and fast:
        assert "service_tier" not in prepared.body
    else:
        assert prepared.body["service_tier"] == ("priority" if fast else "default")
    assert body["model"] == model
    assert body["service_tier"] == "default"


@pytest.mark.asyncio
async def test_fast_discovery_and_metadata_inherit_base_capabilities(monkeypatch, connection):
    from bridge.openai import codex

    base = LLMModelInfo(id="synthetic-sol", name="Synthetic Sol", context_length=200_000,
        modalities={"input_text": True, "input_image": True, "output_text": True})
    fast = replace(base, id="synthetic-sol:fast", name="Synthetic Sol Fast")
    monkeypatch.setattr(codex_oauth, "get_provider", AsyncMock(return_value=object()))
    monkeypatch.setattr(codex_oauth, "list_models", AsyncMock(return_value=[base, fast]))

    async def enrich(_connection, models, **kwargs):
        assert [model.id for model in models] == [base.id, base.id]
        return [replace(model, capabilities={"reasoning": True, "tools": True}) for model in models]

    metadata = replace(base, capabilities={"reasoning": True, "tools": True})
    catalog = SimpleNamespace(enrich_models=enrich, get_model_metadata=AsyncMock(return_value=metadata))
    monkeypatch.setattr(codex, "model_catalog_metadata", lambda: catalog)
    bridge = CodexBridge()
    models = await bridge.list_resources(connection, "chat")
    assert [model.id for model in models] == [base.id, fast.id]
    assert models[1].name == "Synthetic Sol Fast"
    assert models[1].capabilities == models[0].capabilities == metadata.capabilities
    found = await bridge.get_model_metadata(connection, fast.id)
    catalog.get_model_metadata.assert_awaited_once_with(connection, base.id)
    assert found.id == fast.id and found.context_length == base.context_length


def test_fast_alias_uses_base_sdk_profile():
    from app.llm.provider_facade import request_parameter_policy_for, responses_policy_for
    from pydantic_ai.profiles.openai_codex import openai_codex_model_profile

    connection = ProviderConnection(id=7, name="Synthetic ChatGPT", catalog_code="openai-codex",
        provider_type="openai_codex", base_url="https://chatgpt.com/backend-api/codex")
    assert request_parameter_policy_for(connection, "gpt-6-sol:fast") == request_parameter_policy_for(connection, "gpt-6-sol")
    assert responses_policy_for(connection).model_profile("gpt-6-sol:fast") == openai_codex_model_profile("gpt-6-sol")


@pytest.mark.asyncio
async def test_discover_configure_and_reopen_fast_alongside_standard(db, monkeypatch):
    from app.llm import llm_provider_service, llm_service, provider_router
    from app.llm.provider_models import LLMProvider
    from app.llm.provider_schemas import LLMCreate
    from bridge.models_dev import service as metadata_service

    provider = LLMProvider(name="Synthetic variant provider", catalog_code="openai-codex",
        provider_type="openai_codex", base_url="https://chatgpt.com/backend-api/codex",
        is_active=False, subscription_acknowledged=True)
    db.add(provider)
    await db.commit()
    monkeypatch.setattr(codex_oauth, "get_access_token", AsyncMock(return_value="synthetic-token"))

    def respond(request):
        if request.url.host == "models.dev":
            return httpx.Response(200, json={"openai": {"models": {"synthetic-sol": {
                "name": "Synthetic Sol", "reasoning": True, "tool_call": True,
                "limit": {"context": 200_000},
                "modalities": {"input": ["text", "image"], "output": ["text"]},
            }}}})
        assert request.url.path.endswith("/codex/models")
        return httpx.Response(200, json={"models": [{"slug": "synthetic-sol",
            "display_name": "Synthetic Sol", "supports_image_input": True,
            "service_tiers": [{"id": "priority", "name": "Fast"}]}]})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(**kwargs,
        transport=httpx.MockTransport(respond)))
    metadata_service.clear_cache()
    try:
        models = await llm_provider_service.list_models(provider.id, force_refresh=True)
        assert [model.id for model in models] == ["synthetic-sol", "synthetic-sol:fast"]
        saved = []
        for index, discovered in enumerate(models):
            model = provider_router._model_info_response(discovered)
            assert model.capabilities["tools"] is True
            assert model.capabilities["reasoning"] is True
            data = await llm_provider_service.apply_model_defaults(LLMCreate(
                llm_provider_id=provider.id, code=f"synthetic-sol-{index}",
                llm_name=model.id, label=model.name, is_subscription=True,
            ), provider)
            configured = await llm_service.create_llm(data)
            saved.append(configured.id)
            db.expunge(configured)
        standard, fast = [await llm_service.get_llm(key) for key in saved]
        assert standard.id != fast.id
        assert standard.llm_name == "synthetic-sol" and fast.llm_name == "synthetic-sol:fast"
        assert fast.label == "Synthetic Sol Fast"
        assert fast.context_length == standard.context_length == 200_000
        assert fast.input_image is standard.input_image is True
        assert fast.is_subscription is standard.is_subscription is True
    finally:
        metadata_service.clear_cache()
