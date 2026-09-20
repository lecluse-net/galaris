"""Native image generation, with provider adapters and canonical LLM accounting."""

from __future__ import annotations

from io import BytesIO
from uuid import UUID

import httpx
from PIL import Image

from . import llm_call_service, llm_provider_service, llm_service
from .provider_facade import image_generation_provider_for
from .purposes import LLMCallPurpose
from .resource_discovery import provider_connection
from .subscription_policy import enforce_subscription_access


async def generate_image_native(
    model_code: str,
    prompt: str,
    sources: list[tuple[bytes, str]],
    *,
    width: int,
    height: int,
    agent_id: int | None = None,
    task_id: UUID | None = None,
) -> tuple[bytes, str] | None:
    """Generate at a native size; None delegates providers without an adapter to their defaults."""
    if width < 1 or height < 1:
        raise ValueError("invalid image dimensions")
    llm = await llm_service.get_llm_by_code(model_code)
    if llm is None:
        raise ValueError(f"Unknown image model: {model_code}")
    provider = llm.provider
    if not provider.is_active:
        raise ValueError(f"Image provider {provider.name} is disabled")
    requester_user_id = await enforce_subscription_access(provider, task_id=task_id)
    connection = provider_connection(
        provider, llm_provider_service.decrypt_api_key(provider.api_key)
    )
    adapter = image_generation_provider_for(connection)
    if adapter is None:
        return None
    selected = adapter.select_size(llm.llm_name, width, height)
    selected_label = (
        f"{selected.width}x{selected.height} pixels"
        if selected.width is not None and selected.height is not None else "model default"
    )
    request = adapter.prepare_request(
        connection, model=llm.llm_name, prompt=prompt, sources=sources,
        width=selected.width or width, height=selected.height or height,
    )
    call = await llm_call_service.create_running_call(
        purpose=LLMCallPurpose.IMAGE_GENERATION,
        task_id=task_id,
        agent_run_id=None,
        agent_id=agent_id,
        requester_user_id=requester_user_id,
        llm_id=llm.id,
        provider_name=provider.name,
        provider_code=connection.catalog_code or connection.provider_type,
        requested_model=model_code,
        effective_model=llm.llm_name,
        stream=False,
        request_body={"messages": [{"role": "user", "content": (
            f"{prompt}\n\nPreferred image dimensions: {width}x{height} pixels. "
            f"Selected native dimensions: {selected_label}. "
            f"Reference images: {len(sources)}."
        )}]},
        is_subscription=llm.is_subscription,
    )
    trace: dict[str, object] = {}
    raw_response = ""
    try:
        async with httpx.AsyncClient(timeout=900.0) as client:
            response = await client.send(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            raw_response = response.text
        if not response.is_success:
            raise ValueError(
                f"Image provider rejected native size {selected_label} for {llm.llm_name} "
                f"(HTTP {response.status_code}): {response.text[:500]}"
            )
        result = adapter.read_response(response)
        trace = {
            "usage": result.usage,
            "finish_reason": "stop",
            "upstream_request_id": response.headers.get("x-request-id"),
        }
        with Image.open(BytesIO(result.content)) as image:
            actual_size = image.size
            media_type = Image.MIME.get(image.format or "", result.media_type)
        trace["response_text"] = (
            f"Image generated natively at {actual_size[0]}x{actual_size[1]} pixels. "
            f"Preferred: {width}x{height}; selected: {selected_label}."
        )
    except Exception as exc:
        await llm_call_service.finalize_call(
            call.id, trace=trace, raw_response=raw_response,
            status="error", error=str(exc),
            input_rate=llm.cost_per_input_token,
            cached_input_rate=llm.cost_per_cached_input_token,
            output_rate=llm.cost_per_output_token,
        )
        raise
    await llm_call_service.finalize_call(
        call.id, trace=trace, raw_response=raw_response,
        input_rate=llm.cost_per_input_token,
        cached_input_rate=llm.cost_per_cached_input_token,
        output_rate=llm.cost_per_output_token,
    )
    return result.content, media_type
