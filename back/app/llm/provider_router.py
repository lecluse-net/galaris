"""API routes for LLM providers and configured models."""
from fastapi import APIRouter, HTTPException, status, Query
from typing import Any, List, Optional

from core.authorize import authorize, Privileges
from core.i18n import render_prompt, tr
from . import llm_provider_service
from . import llm_service
from .provider_catalog import get_provider_profile
from .provider_facade import (
    ProviderAuthenticationError,
    provider_authentication_for,
)
from .resource_discovery import provider_connection
from .provider_models import LLM
from .capabilities import AICapability
from .provider_schemas import (
    LLMProviderCreate,
    LLMProviderUpdate,
    LLMProviderResponse,
    LLMProviderDetailResponse,
    LLMModelsListResponse,
    LLMProviderTestRequest,
    LLMProviderTestResponse,
    LLMCreate,
    LLMUpdate,
    LLMResponse,
    LLMWithProviderResponse,
    ModelManageRequest,
    ModelManageResponse,
    ProviderDeviceStartResponse,
    ProviderDevicePollRequest,
    ProviderDevicePollResponse,
    ProviderCatalogConfigure,
    ProviderCatalogResponse,
    LLMModelInfo as LLMModelInfoResponse,
    LLMModalities,
)

router = APIRouter(prefix="/llm-providers", tags=["llm-providers"])


async def _message(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"llm_api.{key}"), **values)


async def _provider_authentication(provider_id: int):
    provider_data = await llm_provider_service.get_provider_with_decrypted_key(
        provider_id
    )
    if provider_data is None:
        raise ProviderAuthenticationError(
            await _message("errors.provider_not_found", provider_id=provider_id),
            code="provider_not_found",
            status_code=404,
        )
    provider, api_key = provider_data
    service = provider_authentication_for(
        provider_connection(provider, api_key)
    )
    if service is None:
        raise ProviderAuthenticationError(
            "This provider does not expose device authentication.",
            code="provider_authentication_unsupported",
            status_code=400,
        )
    return service


async def _llm_with_provider_response(llm: LLM) -> LLMWithProviderResponse:
    """Build an API response enriched with the provider name."""
    return LLMWithProviderResponse(
        **LLMResponse.model_validate(llm).model_dump(),
        provider_name=getattr(llm.provider, "name", None) or await _message("unknown_provider"),
    )


def _model_info_response(model: Any) -> LLMModelInfoResponse:
    """Convert normalized handler metadata to the public API schema."""
    return LLMModelInfoResponse(
        id=model.id,
        name=model.name,
        description=model.description,
        context_length=model.context_length,
        pricing=model.pricing,
        modalities=(
            LLMModalities.model_validate({
                **dict.fromkeys(LLMModalities.model_fields, False),
                **model.modalities,
            })
            if model.modalities
            else None
        ),
        capabilities=model.capabilities,
        known_modalities=list(model.modalities or {}),
        release_date=model.release_date,
        status=model.status,
        metadata_source=model.metadata_source,
        resource_type=model.resource_type,
        service_capabilities=model.service_capabilities,
    )


# =============================================================================
# Configured LLM routes must precede the dynamic provider-ID routes.
# =============================================================================

@router.get("/llms", response_model=List[LLMWithProviderResponse])
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def list_llms(
    provider_id: Optional[int] = Query(default=None, description="Filter by provider ID")
) -> List[LLMWithProviderResponse]:
    """List configured LLMs, optionally filtered by provider."""
    llms = await llm_service.list_llms(provider_id=provider_id)

    # Include the provider display name in each response.
    return [await _llm_with_provider_response(llm) for llm in llms]


@router.post("/llms", response_model=LLMResponse, status_code=status.HTTP_201_CREATED)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def create_llm(data: LLMCreate) -> LLMResponse:
    """Create a configured LLM.

    Missing pricing, context, and modality values are filled from normalized
    provider metadata. Explicit client values always take precedence.
    """
    provider = await llm_provider_service.get_provider(data.llm_provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message(
                "errors.provider_not_found",
                provider_id=data.llm_provider_id,
            ),
        )

    data = await llm_provider_service.apply_model_defaults(data, provider)

    try:
        llm = await llm_service.create_llm(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return LLMResponse.model_validate(llm)


@router.post("/fetch-pricing", response_model=dict)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def fetch_pricing(request: dict[str, Any]) -> dict[str, Any]:
    """Fetch normalized metadata without coupling the API to one provider."""
    model_id = request.get("model_id")
    if not model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=await _message("errors.model_id_required"),
        )

    try:
        providers = await llm_provider_service.list_providers()
        for provider in providers:
            metadata = await llm_provider_service.get_model_metadata(
                provider,
                str(model_id),
            )
            if metadata is None:
                continue
            pricing = metadata.pricing or {}
            return {
                "cost_per_input_token": pricing.get("input"),
                "cost_per_cached_input_token": pricing.get("cached_input"),
                "cost_per_output_token": pricing.get("output"),
                "modalities": metadata.modalities,
            }
        return {
            "cost_per_input_token": None,
            "cost_per_cached_input_token": None,
            "cost_per_output_token": None,
            "modalities": None,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.metadata_fetch_failed", error=e),
        )


@router.get("/llms/{llm_id}", response_model=LLMWithProviderResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def get_llm(llm_id: int) -> LLMWithProviderResponse:
    """Return details for a configured LLM."""
    llm = await llm_service.get_llm(llm_id)

    if not llm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.llm_not_found", llm_id=llm_id),
        )

    return await _llm_with_provider_response(llm)


@router.put("/llms/{llm_id}", response_model=LLMResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def update_llm(
    llm_id: int,
    data: LLMUpdate
) -> LLMResponse:
    """Update a configured LLM."""
    # Validate a changed provider reference.
    if data.llm_provider_id is not None:
        provider = await llm_provider_service.get_provider(data.llm_provider_id)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=await _message(
                    "errors.provider_not_found",
                    provider_id=data.llm_provider_id,
                ),
            )

    try:
        llm = await llm_service.update_llm(llm_id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    if not llm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.llm_not_found", llm_id=llm_id),
        )

    return LLMResponse.model_validate(llm)


@router.delete("/llms/{llm_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def delete_llm(llm_id: int) -> None:
    """Delete a configured LLM."""
    deleted = await llm_service.delete_llm(llm_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.llm_not_found", llm_id=llm_id),
        )

    return None


# =============================================================================
# LLM provider routes
# =============================================================================

@router.get("", response_model=List[LLMProviderResponse])
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def list_providers(active_only: bool = False) -> List[LLMProviderResponse]:
    """List LLM providers."""
    providers = await llm_provider_service.list_providers(active_only=active_only)
    return [LLMProviderResponse.model_validate(p) for p in providers]


@router.post("", response_model=LLMProviderResponse, status_code=status.HTTP_201_CREATED)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def create_provider(data: LLMProviderCreate) -> LLMProviderResponse:
    """Create an LLM provider."""
    try:
        provider = await llm_provider_service.create_provider(data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return LLMProviderResponse.model_validate(provider)


@router.get("/catalog", response_model=ProviderCatalogResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def get_provider_catalog() -> ProviderCatalogResponse:
    """Return fixed profiles merged with custom and configured connections."""
    return await llm_provider_service.get_provider_catalog()


@router.get("/catalog/{catalog_code}/resources", response_model=LLMModelsListResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def list_catalog_resources(
    catalog_code: str,
    capability: AICapability = Query(default="chat"),
    refresh: bool = Query(default=False, description="Refresh public model metadata"),
) -> LLMModelsListResponse:
    """Preview public resources from a fixed provider before activation."""
    profile = get_provider_profile(catalog_code)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fournisseur inconnu")
    try:
        resources = await llm_provider_service.list_catalog_resources(
            catalog_code,
            capability,
            force_refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.models_fetch_failed", error=exc),
        ) from exc
    response = [_model_info_response(resource) for resource in resources]
    return LLMModelsListResponse(
        provider_id=None,
        provider_name=profile.display_name,
        models=response,
        count=len(response),
        capability=capability,
    )


@router.put("/catalog/{catalog_code}", response_model=LLMProviderResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def configure_catalog_provider(
    catalog_code: str,
    data: ProviderCatalogConfigure,
) -> LLMProviderResponse:
    """Create or update one fixed provider connection."""
    try:
        provider = await llm_provider_service.configure_catalog_provider(catalog_code, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return LLMProviderResponse.model_validate(provider)


@router.post("/test", response_model=LLMProviderTestResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def test_provider_connection(data: LLMProviderTestRequest) -> LLMProviderTestResponse:
    """Test a provider connection without saving it."""
    api_key = data.api_key
    base_url = data.base_url
    provider_type = data.provider_type
    catalog_code = data.catalog_code
    configuration = dict(data.configuration)
    if data.provider_id is not None:
        provider_data = await llm_provider_service.get_provider_with_decrypted_key(
            data.provider_id
        )
        if provider_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=await _message(
                    "errors.provider_not_found",
                    provider_id=data.provider_id,
                ),
            )
        provider, stored_api_key = provider_data
        if not api_key:
            api_key = stored_api_key
        catalog_code = provider.catalog_code
        configuration = dict(provider.configuration)

    profile = get_provider_profile(catalog_code)
    if profile is not None:
        base_url = profile.base_url
        provider_type = profile.provider_type
        catalog_code = profile.code

    if configuration:
        result = await llm_provider_service.test_connection(
            base_url=base_url,
            api_key=api_key,
            provider_type=provider_type,
            catalog_code=catalog_code,
            configuration=configuration,
        )
    else:
        # Keep the long-standing call signature for ordinary providers and test doubles.
        result = await llm_provider_service.test_connection(
            base_url=base_url,
            api_key=api_key,
            provider_type=provider_type,
            catalog_code=catalog_code,
        )
    return LLMProviderTestResponse(**result)


@router.post(
    "/{provider_id}/oauth/device",
    response_model=ProviderDeviceStartResponse,
)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def start_provider_device_login(
    provider_id: int,
) -> ProviderDeviceStartResponse:
    """Start the registered provider's device authentication flow."""
    try:
        provider = await llm_provider_service.get_provider(provider_id)
        if provider is None:
            raise ValueError(await _message("errors.provider_not_found", provider_id=provider_id))
        await llm_provider_service.ensure_subscription_owner(provider)
        service = await _provider_authentication(provider_id)
        result = await service.start_device_login(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": str(exc),
                "code": exc.code,
                "relogin_required": exc.relogin_required,
            },
        ) from exc
    return ProviderDeviceStartResponse(**result)


@router.post(
    "/{provider_id}/oauth/device/poll",
    response_model=ProviderDevicePollResponse,
)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def poll_provider_device_login(
    provider_id: int,
    data: ProviderDevicePollRequest,
) -> ProviderDevicePollResponse:
    """Poll and complete browser-based ChatGPT authentication."""
    try:
        provider = await llm_provider_service.get_provider(provider_id)
        if provider is None:
            raise ValueError(await _message("errors.provider_not_found", provider_id=provider_id))
        await llm_provider_service.ensure_subscription_owner(provider)
        service = await _provider_authentication(provider_id)
        result = await service.poll_device_login(
            provider_id,
            device_auth_id=data.device_auth_id,
            user_code=data.user_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": str(exc),
                "code": exc.code,
                "relogin_required": exc.relogin_required,
            },
        ) from exc
    return ProviderDevicePollResponse(**result)


@router.delete("/{provider_id}/oauth", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def disconnect_provider_authentication(provider_id: int) -> None:
    """Remove credentials owned by the registered provider bridge."""
    try:
        service = await _provider_authentication(provider_id)
        await service.disconnect(provider_id)
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": str(exc),
                "code": exc.code,
                "relogin_required": exc.relogin_required,
            },
        ) from exc
    return None


@router.get("/{provider_id}", response_model=LLMProviderDetailResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def get_provider(provider_id: int) -> LLMProviderDetailResponse:
    """Return provider details without sending its stored credential."""
    provider = await llm_provider_service.get_provider(provider_id)

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    response = LLMProviderResponse.model_validate(provider).model_dump()
    return LLMProviderDetailResponse(
        **response,
        api_key=None,
    )


@router.put("/{provider_id}", response_model=LLMProviderResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def update_provider(
    provider_id: int,
    data: LLMProviderUpdate
) -> LLMProviderResponse:
    """Update an existing LLM provider."""
    try:
        provider = await llm_provider_service.update_provider(provider_id, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    return LLMProviderResponse.model_validate(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def delete_provider(provider_id: int) -> None:
    """Delete an LLM provider."""
    deleted = await llm_provider_service.delete_provider(provider_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    return None


@router.get("/{provider_id}/models", response_model=LLMModelsListResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def list_provider_models(
    provider_id: int,
    refresh: bool = Query(default=False, description="Refresh public model metadata"),
) -> LLMModelsListResponse:
    """
    Fetch the models currently available from a provider.
    """
    # Load the provider for its display name.
    provider = await llm_provider_service.get_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    try:
        models = await llm_provider_service.list_models(
            provider_id,
            force_refresh=refresh,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.models_fetch_failed", error=e),
        )

    # Report whether model installation and deletion are supported.
    supports_management = llm_provider_service.supports_model_management(
        provider_id,
        provider.base_url,
        provider.provider_type,
    )

    models_response = [_model_info_response(model) for model in models]

    return LLMModelsListResponse(
        provider_id=provider_id,
        provider_name=provider.name,
        models=models_response,
        count=len(models_response),
        supports_model_management=supports_management,
        capability="chat",
    )


@router.get("/{provider_id}/resources", response_model=LLMModelsListResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def list_provider_resources(
    provider_id: int,
    capability: AICapability = Query(default="chat"),
    refresh: bool = Query(default=False, description="Refresh public model metadata"),
) -> LLMModelsListResponse:
    """List models or voices exposed for one provider capability."""
    provider = await llm_provider_service.get_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )
    try:
        resources = await llm_provider_service.list_resources(
            provider_id,
            capability,
            force_refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.models_fetch_failed", error=exc),
        ) from exc

    resource_response = [_model_info_response(resource) for resource in resources]
    return LLMModelsListResponse(
        provider_id=provider_id,
        provider_name=provider.name,
        models=resource_response,
        count=len(resource_response),
        supports_model_management=(
            llm_provider_service.supports_model_management(
                provider_id,
                provider.base_url,
                provider.provider_type,
            )
            and capability == "chat"
        ),
        capability=capability,
    )


@router.get("/{provider_id}/transcription-models", response_model=LLMModelsListResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_ACCESS, Privileges.LLM_PROVIDER_EDIT])
async def list_provider_transcription_models(provider_id: int) -> LLMModelsListResponse:
    """List a provider's transcription models with ``input_audio`` enabled.

    A dedicated transcription URL is preferred; otherwise the chat endpoint is filtered by
    model-name heuristics.
    """
    provider = await llm_provider_service.get_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    try:
        models = await llm_provider_service.list_transcription_models(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.transcription_models_fetch_failed", error=e),
        )

    models_response = [_model_info_response(model) for model in models]

    return LLMModelsListResponse(
        provider_id=provider_id,
        provider_name=provider.name,
        models=models_response,
        count=len(models_response),
        supports_model_management=False,
        capability="transcription",
    )


@router.post("/{provider_id}/models/pull", response_model=ModelManageResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def pull_model(provider_id: int, data: ModelManageRequest) -> ModelManageResponse:
    """
    Install a model on a provider that supports model management.
    """
    provider = await llm_provider_service.get_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    try:
        message = await llm_provider_service.pull_model(provider_id, data.model_name)
        return ModelManageResponse(
            success=True,
            message=message,
            model_name=data.model_name,
            provider_id=provider_id,
            provider_name=provider.name,
        )
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.install_failed", error=e),
        )


@router.post("/{provider_id}/models/delete", response_model=ModelManageResponse)
@authorize(privileges=[Privileges.LLM_PROVIDER_EDIT])
async def delete_model(provider_id: int, data: ModelManageRequest) -> ModelManageResponse:
    """
    Delete a model from a provider that supports model management.
    """
    provider = await llm_provider_service.get_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _message("errors.provider_not_found", provider_id=provider_id),
        )

    try:
        message = await llm_provider_service.delete_model(provider_id, data.model_name)
        return ModelManageResponse(
            success=True,
            message=message,
            model_name=data.model_name,
            provider_id=provider_id,
            provider_name=provider.name,
        )
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await _message("errors.delete_failed", error=e),
        )
