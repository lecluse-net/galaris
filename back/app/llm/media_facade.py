"""Resolve specialist models without exposing ORM or credentials to agents."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from . import llm_provider_service, llm_service, model_usages
from .media_contracts import MediaOperation, MediaProvider, MediaRequest, MediaResult, media_provider_for
from .provider_facade import ProviderConnection
from .resource_discovery import provider_connection

MEDIA_USAGES: dict[MediaOperation, tuple[str, str]] = {
    "audio_read": (model_usages.AUDIO, "audio_understanding"),
    "video_read": (model_usages.VIDEO, "video_understanding"),
    "sound_generate": (model_usages.SOUND_GENERATION, "sound_generation"),
    "music_generate": (model_usages.MUSIC_GENERATION, "music_generation"),
    "video_generate": (model_usages.VIDEO_GENERATION, "video_generation"),
}


@dataclass(frozen=True)
class SelectedMediaResource:
    llm_id: int
    model: str
    connection: ProviderConnection
    provider: MediaProvider


async def resolve_media_resource(
    agent_id: int, operation: MediaOperation, *, llm_id: int | None = None,
) -> SelectedMediaResource:
    usage, capability = MEDIA_USAGES[operation]
    resource = (
        await llm_service.get_llm(llm_id) if llm_id is not None
        else await llm_service.get_profile_llm_for_agent_id(usage, agent_id)
    )
    if resource is None or not resource.provider.is_active:
        raise ValueError(f"No active resource configured for {operation}.")
    capabilities = {resource.primary_capability, *resource.service_capabilities}
    # Existing Gemini selections predate the specialist taxonomy.
    legacy_understanding = resource.primary_capability == "chat" and resource.output_text and (
        (operation == "audio_read" and resource.input_audio)
        or (operation == "video_read" and resource.input_video)
    )
    if capability not in capabilities and not legacy_understanding:
        raise ValueError(f"The selected resource does not support {operation}.")
    connection = provider_connection(
        resource.provider, llm_provider_service.decrypt_api_key(resource.provider.api_key),
    )
    provider = media_provider_for(connection)
    if not connection.api_key or provider is None or not provider.supports(operation, resource.llm_name):
        raise ValueError(f"No usable provider configured for {operation}.")
    return SelectedMediaResource(resource.id, resource.llm_name, connection, provider)


async def available_media_functions(agent_id: int) -> frozenset[str]:
    available: set[str] = set()
    for operation in MEDIA_USAGES:
        try:
            await resolve_media_resource(agent_id, operation)
        except ValueError:
            continue
        available.add(operation)
    return frozenset(available)


async def start_media_call(
    selected: SelectedMediaResource, request: MediaRequest, *, agent_id: int,
    task_id: UUID | None = None, process_run_id: UUID | None = None,
) -> UUID:
    from . import llm_call_service

    call = await llm_call_service.create_running_call(
        purpose=f"multimedia.{request.operation}", agent_id=agent_id, task_id=task_id,
        agent_run_id=None, process_run_id=process_run_id, llm_id=selected.llm_id,
        provider_name=selected.connection.name, provider_code=selected.connection.catalog_code,
        requested_model=selected.model, effective_model=selected.model, stream=False,
        request_body=request.model_dump(mode="json"),
    )
    return call.id


async def finish_media_call(call_id: UUID, result: MediaResult) -> None:
    from . import llm_call_service

    await llm_call_service.finalize_call(
        call_id, status="completed" if result.state == "success" else "error",
        preserve_completed=True,
        error=result.error or ("Provider result is unknown" if result.state == "unknown" else None),
        trace={"response_text": result.text, "usage": {"cost": result.cost} if result.cost is not None else {},
               "finish_reason": result.state},
    )
