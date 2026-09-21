"""Provider catalog, connection, and model-discovery services."""

from __future__ import annotations

from typing import Any, Optional, TypedDict

import httpx
from loguru import logger
from sqlalchemy import select

from core.database import get_db
from core.i18n import render_prompt, tr
from core.util import EncryptionService, get_encryption_service
from .handlers import LLMModelInfo
from .model_metadata_service import enrich_models, get_model_metadata
from .provider_catalog import (
    PROVIDER_CATALOG,
    ProviderProfile,
    get_provider_profile,
    match_provider_profile,
)
from .provider_models import LLMProvider
from .subscription_policy import (
    ensure_subscription_confirmation,
    update_subscription_confirmation,
)
from .capabilities import AICapability, with_capability
from .resource_discovery import list_resources as discover_resources
from .resource_discovery import provider_connection
from .provider_facade import (
    ProviderConnection,
    model_management_for,
    model_metadata_for,
)
from .provider_schemas import (
    LLMCreate,
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    ProviderCatalogConfigure,
    ProviderCatalogItem,
    ProviderCatalogResponse,
    ProviderUserOption,
    ProviderConfigurationFieldResponse,
)


class TestConnectionResult(TypedDict):
    """Result of testing an LLM provider connection."""

    success: bool
    message: str
    provider_name: Optional[str]
    models_count: Optional[int]
    error_details: Optional[str]


# ==========================================================================
# Encryption helpers
# ==========================================================================


def _get_encryption() -> EncryptionService:
    """Return the application encryption service."""
    return get_encryption_service()


def _encrypt_api_key(api_key: Optional[str]) -> Optional[str]:
    """Encrypt an API key unless it is empty or already encrypted."""
    if not api_key:
        return None
    encryption = _get_encryption()
    if encryption.is_encrypted(api_key):
        return api_key
    return encryption.encrypt(api_key)


def _decrypt_api_key(api_key: Optional[str]) -> Optional[str]:
    """Decrypt an API key when needed."""
    if not api_key:
        return None
    encryption = _get_encryption()
    if not encryption.is_encrypted(api_key):
        return api_key
    return encryption.decrypt(api_key)


def decrypt_api_key(api_key: Optional[str]) -> Optional[str]:
    """Public wrapper used by transcription and compatibility integrations."""
    return _decrypt_api_key(api_key)


def _clean_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().rstrip("/")
    return cleaned or None


# ==========================================================================
# Connection CRUD
# ==========================================================================


async def _available_provider_name(preferred: str) -> str:
    """Return a unique database display name without changing the catalog label."""
    db = get_db()
    names = set(
        (await db.execute(select(LLMProvider.name))).scalars().all()
    )
    if preferred not in names:
        return preferred
    suffix = 2
    while f"{preferred} ({suffix})" in names:
        suffix += 1
    return f"{preferred} ({suffix})"


async def _validated_subscription_owner(
    *,
    catalog_code: str | None,
    user_id: int | None,
    is_active: bool,
) -> int | None:
    """Validate the owner field without extending it to API-key providers."""

    if catalog_code != "openai-codex":
        if user_id is not None:
            raise ValueError(await tr("llm_api.errors.subscription_owner_unsupported"))
        return None
    if user_id is None:
        if is_active:
            raise ValueError(await tr("llm_api.errors.subscription_owner_required"))
        return None

    from core.user import UserModel

    user = await get_db().get(UserModel, user_id)
    if user is None or not user.is_active:
        raise ValueError(await tr("llm_api.errors.subscription_owner_invalid"))
    return user.id


async def ensure_subscription_owner(provider: LLMProvider) -> int | None:
    """Return the active owner required before a personal-subscription OAuth operation."""

    if provider.catalog_code != "openai-codex":
        return None

    await ensure_subscription_confirmation(provider)

    owner = await _validated_subscription_owner(
        catalog_code=provider.catalog_code,
        user_id=provider.user_id,
        is_active=True,
    )
    if owner is None:  # Defensive: the catalog guard above makes this unreachable.
        raise ValueError(await tr("llm_api.errors.subscription_owner_required"))
    return owner


async def create_provider(data: LLMProviderCreate) -> LLMProvider:
    """Create a custom connection or route a registered provider type to its profile."""
    if data.catalog_code:
        configured = ProviderCatalogConfigure(
            api_key=data.api_key,
            is_active=data.is_active,
            configuration=data.configuration,
            user_id=data.user_id,
            **data.model_dump(include={"subscription_acknowledged"}, exclude_unset=True),
        )
        return await configure_catalog_provider(data.catalog_code, configured)

    registered = next(
        (
            profile
            for profile in PROVIDER_CATALOG
            if profile.provider_type == data.provider_type
            and profile.provider_type != "openai_compatible"
        ),
        None,
    )
    if registered is not None:
        configured = ProviderCatalogConfigure(
            api_key=data.api_key,
            is_active=data.is_active,
            configuration=data.configuration,
            user_id=data.user_id,
            **data.model_dump(include={"subscription_acknowledged"}, exclude_unset=True),
        )
        return await configure_catalog_provider(registered.code, configured)

    db = get_db()
    provider = LLMProvider(
        name=data.name.strip(),
        catalog_code=None,
        provider_type=data.provider_type,
        base_url=_clean_url(data.base_url) or data.base_url,
        # A dedicated Whisper server is represented as its own custom provider. Keep the legacy
        # database column empty instead of growing one URL field per AI capability.
        transcription_base_url=None,
        api_key=_encrypt_api_key(data.api_key),
        configuration=dict(data.configuration),
        is_active=data.is_active,
        subscription_acknowledged=data.subscription_acknowledged,
        user_id=await _validated_subscription_owner(
            catalog_code=None,
            user_id=data.user_id,
            is_active=data.is_active,
        ),
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    logger.info("Custom LLM provider created: {} ({})", provider.name, provider.provider_type)
    return provider


async def get_provider(provider_id: int) -> Optional[LLMProvider]:
    """Return a provider connection by ID."""
    db = get_db()
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    return result.scalar_one_or_none()


async def get_provider_by_catalog_code(catalog_code: str) -> Optional[LLMProvider]:
    """Return the single connection attached to a fixed catalog entry."""
    db = get_db()
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.catalog_code == catalog_code)
    )
    return result.scalar_one_or_none()


async def get_provider_with_decrypted_key(
    provider_id: int,
) -> Optional[tuple[LLMProvider, Optional[str]]]:
    """Return a provider together with its decrypted API key."""
    provider = await get_provider(provider_id)
    if not provider:
        return None
    return provider, _decrypt_api_key(provider.api_key)


async def list_providers(active_only: bool = False) -> list[LLMProvider]:
    """List persisted provider connections."""
    db = get_db()
    query = select(LLMProvider)
    if active_only:
        query = query.where(LLMProvider.is_active.is_(True))
    result = await db.execute(query.order_by(LLMProvider.name))
    return list(result.scalars().all())


async def configure_catalog_provider(
    catalog_code: str,
    data: ProviderCatalogConfigure,
) -> LLMProvider:
    """Upsert the connection for a built-in provider profile."""
    profile = get_provider_profile(catalog_code)
    if profile is None:
        raise ValueError(f"Unknown provider catalog code: {catalog_code}")

    db = get_db()
    provider = await get_provider_by_catalog_code(catalog_code)
    creating = provider is None
    if creating:
        provider = LLMProvider(
            name=await _available_provider_name(profile.display_name),
            catalog_code=profile.code,
            provider_type=profile.provider_type,
            base_url=profile.base_url,
            configuration=dict(data.configuration),
            is_active=data.is_active,
            user_id=await _validated_subscription_owner(
                catalog_code=profile.code,
                user_id=data.user_id,
                is_active=data.is_active,
            ),
        )
        db.add(provider)

    provider.provider_type = profile.provider_type
    provider.is_active = data.is_active
    previous_user_id = provider.user_id
    provider.user_id = await _validated_subscription_owner(
        catalog_code=profile.code,
        user_id=(data.user_id if "user_id" in data.model_fields_set else provider.user_id),
        is_active=data.is_active,
    )
    if "subscription_acknowledged" in data.model_fields_set:
        provider.subscription_acknowledged = data.subscription_acknowledged
    elif provider.user_id != previous_user_id:
        provider.subscription_acknowledged = False
    provider.base_url = profile.base_url
    provider.transcription_base_url = None

    if "configuration" in data.model_fields_set:
        provider.configuration = dict(data.configuration)
    missing_configuration = [
        field.label
        for field in profile.configuration_fields
        if field.required and not str(provider.configuration.get(field.key, "")).strip()
    ]
    if data.is_active and missing_configuration:
        raise ValueError(
            "Configuration requise : " + ", ".join(missing_configuration)
        )

    if profile.auth_type == "oauth_device":
        provider.api_key = None
    elif "api_key" in data.model_fields_set:
        provider.api_key = _encrypt_api_key(data.api_key)

    await db.commit()
    update_subscription_confirmation(provider.catalog_code, provider.subscription_acknowledged)
    await db.refresh(provider)
    logger.info("LLM catalog provider configured: {} active={}", catalog_code, data.is_active)
    return provider


async def update_provider(
    provider_id: int,
    data: LLMProviderUpdate,
) -> Optional[LLMProvider]:
    """Update an existing connection without changing its catalog identity."""
    db = get_db()
    provider = await get_provider(provider_id)
    if not provider:
        return None

    update_data = data.model_dump(exclude_unset=True)
    previous_profile = get_provider_profile(provider.catalog_code)
    profile = get_provider_profile(provider.catalog_code)
    next_profile = profile or next(
        (
            candidate
            for candidate in PROVIDER_CATALOG
            if candidate.provider_type == update_data.get("provider_type")
        ),
        None,
    )

    if "api_key" in update_data:
        update_data["api_key"] = _encrypt_api_key(update_data["api_key"])
    for url_field in ("base_url", "transcription_base_url"):
        if url_field in update_data:
            update_data[url_field] = _clean_url(update_data[url_field])

    if profile:
        update_data = {
            field: value
            for field, value in update_data.items()
            if field in {"api_key", "is_active", "configuration", "user_id", "subscription_acknowledged"}
        }
        provider.provider_type = profile.provider_type
        provider.base_url = profile.base_url
        provider.transcription_base_url = None

    next_is_active = bool(update_data.get("is_active", provider.is_active))
    next_user_id = update_data.get("user_id", provider.user_id)
    update_data["user_id"] = await _validated_subscription_owner(
        catalog_code=provider.catalog_code,
        user_id=next_user_id,
        is_active=next_is_active,
    )
    if next_user_id != provider.user_id and "subscription_acknowledged" not in update_data:
        update_data["subscription_acknowledged"] = False

    if next_profile is not None and next_profile.auth_type == "oauth_device":
        update_data["base_url"] = next_profile.base_url
        update_data["api_key"] = None
        update_data["transcription_base_url"] = None
        if previous_profile is None or previous_profile.auth_type != "oauth_device":
            provider.oauth_credentials = None
    elif previous_profile is not None and previous_profile.auth_type == "oauth_device":
        provider.oauth_credentials = None

    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.commit()
    update_subscription_confirmation(provider.catalog_code, provider.subscription_acknowledged)
    await db.refresh(provider)
    return provider


async def delete_provider(provider_id: int) -> bool:
    """Soft-delete a provider connection and its configured LLMs."""
    provider = await get_provider(provider_id)
    if not provider:
        return False
    provider.soft_delete()

    from . import llm_service

    await llm_service.soft_delete_provider_llms(provider.id)
    update_subscription_confirmation(provider.catalog_code, False)
    return True


# ==========================================================================
# Catalog projection
# ==========================================================================


def _fixed_catalog_item(
    profile: ProviderProfile,
    provider: Optional[LLMProvider],
) -> ProviderCatalogItem:
    connection = LLMProviderResponse.model_validate(provider) if provider else None
    return ProviderCatalogItem(
        key=f"catalog:{profile.code}",
        code=profile.code,
        display_name=profile.display_name,
        provider_type=profile.provider_type,
        auth_type=profile.auth_type,
        default_base_url=profile.base_url,
        token_url=profile.token_url,
        documentation_url=profile.documentation_url,
        icon=profile.icon,
        color=profile.color,
        api_key_required=profile.api_key_required,
        supports_transcription=profile.supports_transcription,
        capabilities=list(profile.capabilities),
        configuration_fields=[
            ProviderConfigurationFieldResponse(
                key=field.key,
                label=field.label,
                required=field.required,
                placeholder=field.placeholder,
            )
            for field in profile.configuration_fields
        ],
        supports_model_management=False,
        is_custom=False,
        connection=connection,
    )


def _custom_catalog_item(provider: LLMProvider) -> ProviderCatalogItem:
    connection = provider_connection(provider, None)
    manages_models = model_management_for(connection) is not None
    return ProviderCatalogItem(
        key=f"custom:{provider.id}",
        display_name=provider.name,
        provider_type=provider.provider_type,
        auth_type="optional_api_key" if manages_models else "api_key",
        default_base_url=provider.base_url,
        token_url=None,
        documentation_url=None,
        icon="dns" if manages_models else "lan",
        color="blue-grey" if manages_models else "grey-8",
        api_key_required=not manages_models,
        supports_transcription=not manages_models,
        capabilities=(
            ["chat", "vision", "embedding"]
            if manages_models
            else [
                "chat",
                "vision",
                "image_generation",
                "embedding",
                "transcription",
                "speech",
            ]
        ),
        configuration_fields=[],
        supports_model_management=manages_models,
        is_custom=True,
        connection=LLMProviderResponse.model_validate(provider),
    )


async def get_provider_catalog() -> ProviderCatalogResponse:
    """Return every fixed profile plus every custom provider connection."""
    providers = await list_providers()
    fixed_connections = {
        provider.catalog_code: provider
        for provider in providers
        if provider.catalog_code
    }
    items = [
        _fixed_catalog_item(profile, fixed_connections.get(profile.code))
        for profile in PROVIDER_CATALOG
    ]
    items.extend(
        _custom_catalog_item(provider)
        for provider in providers
        if provider.catalog_code is None
    )
    from core.user import UserModel

    users = list(
        (
            await get_db().scalars(
                select(UserModel)
                .where(UserModel.is_active.is_(True))
                .order_by(UserModel.display_name, UserModel.email)
            )
        ).all()
    )
    return ProviderCatalogResponse(
        items=items,
        users=[
            ProviderUserOption(id=user.id, label=user.display_name or user.email)
            for user in users
        ],
        active_user_count=len(users),
    )


# ==========================================================================
# Model discovery and defaults
# ==========================================================================


async def _active_provider_data(
    provider_id: int,
) -> tuple[LLMProvider, Optional[str]]:
    provider_data = await get_provider_with_decrypted_key(provider_id)
    if not provider_data:
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.provider_not_found"),
                provider_id=provider_id,
            )
        )
    provider, api_key = provider_data
    if not provider.is_active:
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.provider_inactive"),
                provider_name=provider.name,
            )
        )
    return provider, api_key


async def _provider_data(
    provider_id: int,
) -> tuple[LLMProvider, Optional[str]]:
    """Return a provider connection for read-only catalog discovery."""
    provider_data = await get_provider_with_decrypted_key(provider_id)
    if not provider_data:
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.provider_not_found"),
                provider_id=provider_id,
            )
        )
    return provider_data


async def list_models(
    provider_id: int,
    *,
    force_refresh: bool = False,
) -> list[LLMModelInfo]:
    """Compatibility wrapper returning conversation resources."""
    return await list_resources(provider_id, "chat", force_refresh=force_refresh)


async def list_resources(
    provider_id: int,
    capability: AICapability,
    *,
    force_refresh: bool = False,
) -> list[LLMModelInfo]:
    """Fetch resources for a connection, including when it is currently inactive."""
    provider, api_key = await _provider_data(provider_id)
    return await _list_provider_resources(
        provider,
        api_key,
        capability,
        force_refresh=force_refresh,
    )


async def list_catalog_resources(
    catalog_code: str,
    capability: AICapability,
    *,
    force_refresh: bool = False,
) -> list[LLMModelInfo]:
    """Preview a built-in public catalog before its connection is configured."""
    profile = get_provider_profile(catalog_code)
    if profile is None:
        raise ValueError(f"Unknown provider catalog code: {catalog_code}")
    provider = await get_provider_by_catalog_code(catalog_code)
    api_key: Optional[str] = None
    if provider is not None:
        provider_data = await get_provider_with_decrypted_key(provider.id)
        if provider_data is not None:
            provider, api_key = provider_data
    else:
        if profile.api_key_required:
            raise ValueError(
                f"{profile.display_name} doit être configuré avant de consulter ses ressources"
            )
        provider = LLMProvider(
            name=profile.display_name,
            catalog_code=profile.code,
            provider_type=profile.provider_type,
            base_url=profile.base_url,
            configuration={},
            is_active=False,
        )
    return await _list_provider_resources(
        provider,
        api_key,
        capability,
        force_refresh=force_refresh,
    )


async def _list_provider_resources(
    provider: LLMProvider,
    api_key: Optional[str],
    capability: AICapability,
    *,
    force_refresh: bool,
) -> list[LLMModelInfo]:
    """Discover and normalize one capability for an explicit provider instance."""
    profile = get_provider_profile(provider.catalog_code)
    supported = list(profile.capabilities) if profile else (
        ["chat", "vision", "embedding"]
        if model_management_for(provider_connection(provider, api_key)) is not None
        else ["chat", "vision", "image_generation", "embedding", "transcription", "speech"]
    )
    if capability not in supported:
        raise ValueError(
            f"{provider.name} ne prend pas en charge la capacité {capability}"
        )
    models = await discover_resources(provider, api_key, capability)
    enriched = await enrich_models(provider, models, force_refresh=force_refresh)
    return [with_capability(model, capability) for model in enriched]


async def list_transcription_models(provider_id: int) -> list[LLMModelInfo]:
    """Compatibility wrapper returning speech-to-text resources."""
    return await list_resources(provider_id, "transcription")


def transcription_base_url(provider: LLMProvider) -> str:
    """Return the provider STT base URL for the runtime compatibility adapter."""
    return provider.base_url.strip().rstrip("/")


def supports_model_management(
    provider_id: int,
    base_url: str,
    provider_type: str = "openai_compatible",
) -> bool:
    """Return whether a bridge registered model-management operations."""
    connection = ProviderConnection(
        id=provider_id,
        name="provider",
        catalog_code=None,
        provider_type=provider_type,
        base_url=base_url,
    )
    return model_management_for(connection) is not None


async def pull_model(provider_id: int, model_name: str) -> str:
    """Download or install a model on a provider that supports it."""
    provider, api_key = await _active_provider_data(provider_id)
    connection = provider_connection(provider, api_key)
    service = model_management_for(connection)
    if service is None:
        raise NotImplementedError(
            render_prompt(
                await tr("llm_api.errors.provider_install_unsupported"),
                provider_name=provider.name,
            )
        )
    return await service.pull_model(connection, model_name)


async def delete_model(provider_id: int, model_name: str) -> str:
    """Delete a model from a provider that supports it."""
    provider, api_key = await _active_provider_data(provider_id)
    connection = provider_connection(provider, api_key)
    service = model_management_for(connection)
    if service is None:
        raise NotImplementedError(
            render_prompt(
                await tr("llm_api.errors.provider_delete_unsupported"),
                provider_name=provider.name,
            )
        )
    return await service.delete_model(connection, model_name)


async def apply_model_defaults(data: LLMCreate, provider: LLMProvider) -> LLMCreate:
    """Fill omitted configured-LLM values without changing the LLM domain model."""
    updates: dict[str, Any] = {}
    if not data.service_capabilities:
        updates["service_capabilities"] = [data.primary_capability]
    if not data.pricing:
        updates["pricing"] = {}
    if model_management_for(
        provider_connection(provider, _decrypt_api_key(provider.api_key))
    ) is not None:
        if data.cost_per_input_token is None:
            updates["cost_per_input_token"] = 0.0
        if data.cost_per_cached_input_token is None:
            updates["cost_per_cached_input_token"] = 0.0
        if data.cost_per_output_token is None:
            updates["cost_per_output_token"] = 0.0
        return data.model_copy(update=updates) if updates else data

    metadata = await get_model_metadata(provider, data.llm_name)
    connection = provider_connection(provider, _decrypt_api_key(provider.api_key))
    metadata_service = model_metadata_for(connection)
    if metadata_service is not None:
        bridge_metadata = await metadata_service.get_model_metadata(
            connection,
            data.llm_name,
        )
        if bridge_metadata is not None:
            metadata = bridge_metadata

    if metadata:
        pricing = metadata.pricing or {}
        if not data.pricing:
            updates["pricing"] = pricing
        if data.cost_per_input_token is None and pricing.get("input") is not None:
            updates["cost_per_input_token"] = pricing["input"]
        if data.cost_per_cached_input_token is None and pricing.get("cached_input") is not None:
            updates["cost_per_cached_input_token"] = pricing["cached_input"]
        if data.cost_per_output_token is None and pricing.get("output") is not None:
            updates["cost_per_output_token"] = pricing["output"]
        if data.context_length is None and metadata.context_length:
            updates["context_length"] = metadata.context_length
        for field, value in (metadata.modalities or {}).items():
            if getattr(data, field, None) is None:
                updates[field] = value
    return data.model_copy(update=updates) if updates else data


# ==========================================================================
# Connection testing
# ==========================================================================


async def test_connection(
    base_url: str,
    api_key: Optional[str] = None,
    *,
    provider_type: str = "openai_compatible",
    catalog_code: Optional[str] = None,
    configuration: Optional[dict[str, Any]] = None,
) -> TestConnectionResult:
    """Test a provider without persisting credentials."""
    try:
        profile = get_provider_profile(catalog_code) or match_provider_profile(base_url)
        effective_type = profile.provider_type if profile else provider_type
        if profile is not None and profile.auth_type != "oauth_device":
            candidate = LLMProvider(
                name=profile.display_name,
                catalog_code=profile.code,
                provider_type=profile.provider_type,
                base_url=profile.base_url,
                api_key=None,
                configuration=configuration or {},
                is_active=True,
            )
            models = await discover_resources(
                candidate,
                api_key,
                profile.capabilities[0],
            )
        elif profile is None:
            candidate = LLMProvider(
                name=profile.display_name if profile else "LLM provider",
                catalog_code=profile.code if profile else None,
                provider_type=effective_type,
                base_url=profile.base_url if profile else base_url,
                api_key=None,
                configuration=configuration or {},
                is_active=True,
            )
            models = await discover_resources(candidate, api_key, "chat")
        else:
            models = []
        provider_name = profile.display_name if profile else _detect_provider_name(base_url)
        return {
            "success": True,
            "message": render_prompt(
                await tr("llm_api.connection.success"),
                provider_name=provider_name,
            ),
            "provider_name": provider_name,
            "models_count": len(models),
            "error_details": None,
        }
    except httpx.HTTPStatusError as exc:
        error_msg = render_prompt(
            await tr("llm_api.connection.http_error"),
            status=exc.response.status_code,
        )
        if exc.response.status_code == 401:
            error_msg = await tr("llm_api.connection.invalid_key")
        elif exc.response.status_code == 403:
            error_msg = await tr("llm_api.connection.access_denied")
        elif exc.response.status_code == 404:
            error_msg = await tr("llm_api.connection.endpoint_not_found")
        elif exc.response.status_code >= 500:
            error_msg = await tr("llm_api.connection.server_error")
        return {
            "success": False,
            "message": await tr("llm_api.connection.failed"),
            "provider_name": None,
            "models_count": None,
            "error_details": error_msg,
        }
    except httpx.ConnectError as exc:
        logger.error("LLM provider connection error: {}", exc)
        return {
            "success": False,
            "message": await tr("llm_api.connection.failed"),
            "provider_name": None,
            "models_count": None,
            "error_details": await tr("llm_api.connection.cannot_connect"),
        }
    except httpx.TimeoutException as exc:
        logger.error("LLM provider timeout: {}", exc)
        return {
            "success": False,
            "message": await tr("llm_api.connection.failed"),
            "provider_name": None,
            "models_count": None,
            "error_details": await tr("llm_api.connection.timeout"),
        }
    except Exception as exc:
        logger.error("Unexpected LLM provider test error: {}: {}", type(exc).__name__, exc)
        return {
            "success": False,
            "message": await tr("llm_api.connection.failed"),
            "provider_name": None,
            "models_count": None,
            "error_details": str(exc),
        }


def _detect_provider_name(base_url: str) -> str:
    profile = match_provider_profile(base_url)
    if profile:
        return profile.display_name
    return "LLM provider"
