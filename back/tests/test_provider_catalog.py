"""Provider-catalog and connection-regression tests."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import llm_provider_service, provider_router, resource_discovery
from app.llm.handlers import LLMModelInfo
from app.llm import model_metadata_service
from app.llm.provider_catalog import PROVIDER_CATALOG, get_provider_profile
from app.llm.provider_models import LLMProvider
from app.llm.provider_facade import (
    ProviderConnection,
    openai_protocol_base_url,
    provider_authentication_for,
    resource_discovery_for,
    responses_policy_for,
    responses_transport_for,
    speech_provider_for,
    transcription_provider_for,
)
from app.llm.provider_schemas import (
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    LLMProviderTestRequest,
    ProviderCatalogConfigure,
)
from bridge.models_dev import service as models_dev_service
from core.util import get_encryption_service
from modules import LLM_PROVIDER_MODULES


def _connection(code: str, provider_type: str = "openai_compatible") -> ProviderConnection:
    return ProviderConnection(
        id=1,
        name=code,
        catalog_code=code,
        provider_type=provider_type,
        base_url="https://provider.example/v1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_code", [None, "openai-api", "openai-codex"])
async def test_provider_acknowledgement_survives_reload_and_partial_updates(
    db: AsyncSession, catalog_code: str | None,
) -> None:
    provider = await llm_provider_service.create_provider(LLMProviderCreate(
        name="Acknowledged provider", catalog_code=catalog_code,
        base_url="https://provider.example/v1", is_active=False,
        subscription_acknowledged=True,
    ))
    provider_id = provider.id
    db.expunge(provider)
    reloaded = await llm_provider_service.get_provider(provider_id)
    assert LLMProviderResponse.model_validate(reloaded).subscription_acknowledged is True

    updated = await llm_provider_service.update_provider(
        provider_id, LLMProviderUpdate(is_active=False),
    )
    assert LLMProviderResponse.model_validate(updated).subscription_acknowledged is True
    if catalog_code:
        updated = await llm_provider_service.configure_catalog_provider(
            catalog_code, ProviderCatalogConfigure(is_active=False),
        )
        assert updated.subscription_acknowledged is True
        updated = await llm_provider_service.configure_catalog_provider(
            catalog_code, ProviderCatalogConfigure(is_active=False, subscription_acknowledged=False),
        )
    else:
        updated = await llm_provider_service.update_provider(
            provider_id, LLMProviderUpdate(subscription_acknowledged=False),
        )
    assert updated is not None
    await db.refresh(updated)
    assert LLMProviderResponse.model_validate(updated).subscription_acknowledged is False


def test_provider_bridges_register_profiles_and_service_facades() -> None:
    assert "bridge.openrouter" in LLM_PROVIDER_MODULES
    assert "bridge.openai" in LLM_PROVIDER_MODULES
    assert "bridge.elevenlabs" in LLM_PROVIDER_MODULES
    assert "bridge.models_dev" in LLM_PROVIDER_MODULES

    assert resource_discovery_for(_connection("openrouter")) is not None
    assert transcription_provider_for(_connection("openrouter")) is not None
    assert speech_provider_for(_connection("elevenlabs", "elevenlabs")) is not None
    assert provider_authentication_for(
        _connection("openai-codex", "openai_codex")
    ) is not None
    assert responses_policy_for(_connection("openrouter")) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["anthropic-api", "ollama", "openrouter"])
@pytest.mark.parametrize("api_key", [None, "catalog-test-key"])
@pytest.mark.parametrize("status", [200, 401, 503])
async def test_provider_catalog_discovers_usable_resources_and_preserves_http_errors(
    monkeypatch: pytest.MonkeyPatch, code: str, api_key: str | None, status: int,
) -> None:
    """Discovery uses each registered bridge's endpoint, auth and capability filter."""
    provider = LLMProvider(
        name=code, catalog_code=None if code == "ollama" else code,
        provider_type="ollama" if code == "ollama" else "openai_compatible",
        base_url="https://catalog.example" if code == "ollama" else "https://catalog.example/v1",
        configuration={},
    )
    capability = "vision" if code == "openrouter" else "chat"
    expected_id = "opaque-vision" if code == "openrouter" else "opaque-chat"
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == ("/api/tags" if code == "ollama" else "/v1/models")
        assert request.headers.get("authorization") == (f"Bearer {api_key}" if api_key else None)
        if code == "anthropic-api":
            assert request.headers.get("x-api-key") == api_key
            assert request.headers.get("anthropic-version") == ("2023-06-01" if api_key else None)
        if code == "openrouter":
            assert request.url.params["output_modalities"] == "text"
        if status != 200:
            return httpx.Response(status, json={"error": "Catalog unavailable"})
        if code == "ollama":
            payload = {"models": [None, {}, {"name": "opaque-chat", "details": {"description": "Local model"}}, {"name": "nomic-embed-text"}]}
        else:
            payload = {"data": [
                {},
                {"id": "opaque-chat", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
                {"id": "opaque-vision", "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
                {"id": "opaque-vector", "architecture": {"input_modalities": ["text"], "output_modalities": ["embeddings"]}},
            ]}
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    if status != 200:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await resource_discovery.list_resources(provider, api_key, capability)
        assert caught.value.response.status_code == status
    else:
        models = await resource_discovery.list_resources(provider, api_key, capability)
        expected = ["opaque-chat", "opaque-vision"] if code == "anthropic-api" else [expected_id]
        assert [model.id for model in models] == expected
        assert all(capability in (model.service_capabilities or []) for model in models)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_xai_compaction_embeds_instructions_in_the_supported_input_shape() -> None:
    connection = _connection("xai")
    transport = responses_transport_for(connection)
    assert transport is not None

    prepared = await transport.prepare_responses_request(
        1,
        connection,
        {
            "model": "grok-4.6",
            "instructions": "Keep the governing prompt.",
            "input": [{"role": "user", "content": "Long history"}],
        },
        operation="compact",
    )

    assert prepared.endpoint == "https://provider.example/v1/responses/compact"
    assert "instructions" not in prepared.body
    assert prepared.body["input"][0] == {
        "role": "system",
        "content": "Keep the governing prompt.",
    }


@pytest.mark.asyncio
async def test_catalog_codes_are_unique_and_api_keys_have_acquisition_links() -> None:
    codes = [profile.code for profile in PROVIDER_CATALOG]

    assert len(codes) == len(set(codes))
    assert {"openrouter", "openai-api", "openai-codex", "anthropic-api", "deepseek", "fireworks"} <= set(codes)
    assert all(
        profile.token_url
        for profile in PROVIDER_CATALOG
        if profile.auth_type == "api_key"
    )
    codex = get_provider_profile("openai-codex")
    assert codex is not None
    assert codex.auth_type == "oauth_device"
    assert codex.supports_responses is True
    openai_api = get_provider_profile("openai-api")
    assert openai_api is not None
    assert openai_api.supports_responses is True
    responses_codes = {
        profile.code for profile in PROVIDER_CATALOG if profile.supports_responses
    }
    assert responses_codes == {
        "deepseek",
        "fireworks",
        "groq",
        "huggingface",
        "mammouth",
        "nvidia",
        "openai-api",
        "openai-codex",
        "openrouter",
        "perplexity",
        "xai",
    }
    assert all(
        responses_policy_for(_connection(profile.code, profile.provider_type))
        is not None
        for profile in PROVIDER_CATALOG
        if profile.supports_responses
    )
    together = get_provider_profile("together")
    assert together is not None
    assert together.supports_responses is False

    legacy_perplexity = ProviderConnection(
        id=1,
        name="Perplexity",
        catalog_code="perplexity",
        provider_type="openai_compatible",
        base_url="https://api.perplexity.ai",
    )
    assert openai_protocol_base_url(legacy_perplexity) == (
        "https://api.perplexity.ai/v1"
    )

    # The global test engine may retain a connection from a preceding module's
    # event loop. Leave a clean pool before this module starts DB-backed tests.
    from core.database import engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_configuration_is_an_encrypted_upsert(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await llm_provider_service.configure_catalog_provider(
        "openai-api",
        ProviderCatalogConfigure(
            api_key="sk-secret",
            is_active=True,
        ),
    )

    assert created.catalog_code == "openai-api"
    assert created.base_url == "https://api.openai.com/v1"
    assert created.transcription_base_url is None
    assert created.api_key != "sk-secret"
    assert get_encryption_service().decrypt(created.api_key or "") == "sk-secret"

    created.base_url = "https://gateway.example/v1"
    created.transcription_base_url = "https://speech.example/v1"
    await db.commit()

    updated = await llm_provider_service.configure_catalog_provider(
        "openai-api",
        ProviderCatalogConfigure(is_active=False),
    )

    assert updated.id == created.id
    assert updated.api_key == created.api_key
    assert updated.is_active is False
    assert updated.base_url == "https://api.openai.com/v1"
    assert updated.transcription_base_url is None

    updated = await llm_provider_service.update_provider(
        created.id,
        LLMProviderUpdate(
            name="Renamed fixed provider",
            provider_type="ollama",
            base_url="https://other.example/v1",
            transcription_base_url="https://other.example/speech",
        ),
    )
    assert updated is not None
    assert updated.name != "Renamed fixed provider"
    assert updated.provider_type == "openai_compatible"
    assert updated.base_url == "https://api.openai.com/v1"
    assert updated.transcription_base_url is None

    detail = await provider_router.get_provider(created.id)
    assert detail.api_key is None
    assert detail.api_key_configured is True

    captured: dict[str, Any] = {}

    async def fake_test_connection(
        base_url: str,
        api_key: str | None = None,
        *,
        provider_type: str = "openai_compatible",
        catalog_code: str | None = None,
    ) -> llm_provider_service.TestConnectionResult:
        captured.update(
            base_url=base_url,
            api_key=api_key,
            provider_type=provider_type,
            catalog_code=catalog_code,
        )
        return {
            "success": True,
            "message": "ok",
            "provider_name": "OpenAI API",
            "models_count": 1,
            "error_details": None,
        }

    monkeypatch.setattr(llm_provider_service, "test_connection", fake_test_connection)
    response = await provider_router.test_provider_connection(LLMProviderTestRequest(
        provider_id=created.id,
        base_url="https://other.example/v1",
        provider_type="ollama",
    ))

    assert response.success is True
    assert captured["api_key"] == "sk-secret"
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["provider_type"] == "openai_compatible"
    assert captured["catalog_code"] == "openai-api"


@pytest.mark.asyncio
async def test_multiple_custom_ollama_connections_remain_independent(
    db: AsyncSession,
) -> None:
    first = await llm_provider_service.create_provider(LLMProviderCreate(
        name="Ollama GPU",
        provider_type="ollama",
        base_url="http://ollama-gpu:11434",
    ))
    second = await llm_provider_service.create_provider(LLMProviderCreate(
        name="Ollama CPU",
        provider_type="ollama",
        base_url="http://ollama-cpu:11434",
        is_active=False,
    ))

    catalog = await llm_provider_service.get_provider_catalog()
    custom_items = [item for item in catalog.items if item.is_custom]

    assert first.id != second.id
    assert {item.key for item in custom_items} >= {
        f"custom:{first.id}",
        f"custom:{second.id}",
    }
    assert all(item.supports_model_management for item in custom_items)


@pytest.mark.asyncio
async def test_multiple_custom_openai_compatible_connections_remain_independent(
    db: AsyncSession,
) -> None:
    first = await llm_provider_service.create_provider(LLMProviderCreate(
        name="OpenAI-compatible Production",
        provider_type="openai_compatible",
        base_url="https://production.example/v1",
        api_key="production-token",
    ))
    second = await llm_provider_service.create_provider(LLMProviderCreate(
        name="OpenAI-compatible Lab",
        provider_type="openai_compatible",
        base_url="https://lab.example/v1",
        api_key="lab-token",
    ))

    catalog = await llm_provider_service.get_provider_catalog()
    custom_items = {
        item.connection.id: item
        for item in catalog.items
        if item.is_custom and item.connection is not None
    }

    assert first.id != second.id
    assert custom_items[first.id].default_base_url == "https://production.example/v1"
    assert custom_items[second.id].default_base_url == "https://lab.example/v1"
    assert not custom_items[first.id].supports_model_management
    assert not custom_items[second.id].supports_model_management
    assert get_encryption_service().decrypt(first.api_key or "") == "production-token"
    assert get_encryption_service().decrypt(second.api_key or "") == "lab-token"


@pytest.mark.asyncio
async def test_models_dev_fills_prices_context_modalities_and_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: dict[str, Any] = {
        "fireworks-ai": {
            "models": {
                "accounts/fireworks/models/example": {
                    "name": "Example",
                    "tool_call": True,
                    "reasoning": True,
                    "attachment": True,
                    "structured_output": True,
                    "modalities": {"input": ["text", "image", "pdf"], "output": ["text"]},
                    "limit": {"context": 131072},
                    "cost": {
                        "input": 0.2,
                        "cache_read": 0.05,
                        "cache_write": 0.3,
                        "output": 0.8,
                    },
                    "release_date": "2026-01-01",
                }
            }
        }
    }

    async def fake_registry(*, force_refresh: bool = False) -> dict[str, Any]:
        del force_refresh
        return registry

    monkeypatch.setattr(models_dev_service, "_registry", fake_registry)
    provider = LLMProvider(
        name="Fireworks",
        catalog_code="fireworks",
        provider_type="openai_compatible",
        base_url="https://api.fireworks.ai/inference/v1",
        is_active=True,
    )

    models = await model_metadata_service.enrich_models(
        provider,
        [LLMModelInfo(id="accounts/fireworks/models/example")],
    )
    model = models[0]

    assert model.context_length == 131072
    assert model.pricing == {
        "input": 0.2,
        "cached_input": 0.05,
        "cache_write": 0.3,
        "output": 0.8,
    }
    assert model.modalities and model.modalities["input_file"] is True
    assert model.capabilities and model.capabilities["tools"] is True
    assert model.metadata_source == "models.dev"
