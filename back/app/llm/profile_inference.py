"""Specialized inference through explicitly selected public profile models."""

import asyncio
import base64
import struct
from typing import Annotated, Any, Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field

from core.user import get_current_user_id
from . import embedding_service, inference_execution, llm_call_service, llm_provider_service, llm_service
from .contracts import DecisionInferenceRequest
from .decision_contracts import ChoiceQuestion, DecisionResult
from .profile_gateway import resolve_profile_model, supports
from .provider_facade import openai_protocol_base_url
from .reasoning import normalize_reasoning_effort
from .resource_discovery import provider_connection
from .subscription_policy import enforce_subscription_access


EmbeddingText = Annotated[str, Field(min_length=1)]


class ProfileEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    input: EmbeddingText | Annotated[list[EmbeddingText], Field(min_length=1, max_length=2048)]
    dimensions: int | None = Field(default=None, ge=1, le=embedding_service.MAX_EMBEDDING_DIMENSIONS)
    encoding_format: Literal["float", "base64"] = "float"
    user: str | None = None


class ProfileDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    prompt: str = Field(min_length=1)
    system_prompt: str = ""
    questions: dict[str, ChoiceQuestion] = Field(min_length=1)


async def profile_decision(body: ProfileDecisionRequest) -> DecisionResult:
    async def prepare() -> DecisionInferenceRequest:
        selection = await resolve_profile_model(body.model, "decision")
        profile = selection.profile
        fallback = (await llm_service.get_llm(profile.text_standard_llm_id)
                    if profile.text_standard_llm_id is not None else None)
        allow_fallback = (profile.decision_fallback_policy == "text_on_failure"
                          and fallback is not None and supports(fallback, "chat"))
        return DecisionInferenceRequest(
            llm_id=selection.llm.id, fallback_llm_id=fallback.id if fallback and allow_fallback else None,
            allow_text_fallback=allow_fallback, prompt=body.prompt, system_prompt=body.system_prompt,
            purpose="profile.decision", correlation_ref=selection.selector,
            reasoning_effort=normalize_reasoning_effort(profile.text_standard_reasoning_effort),
            questions=body.questions, count_tokens_before_request=False, timeout_seconds=120,
        )

    request = await inference_execution.transaction(prepare)
    return (await inference_execution.run_decision(request)).output


async def profile_embeddings(body: ProfileEmbeddingRequest) -> tuple[dict[str, Any], str]:
    selection = await resolve_profile_model(body.model, "embedding")
    llm = selection.llm
    requester = await enforce_subscription_access(
        llm.provider, task_id=None, conversation_round_id=None, process_run_id=None,
    )
    endpoint = embedding_service.EmbeddingEndpoint(
        model_name=llm.llm_name,
        base_url=openai_protocol_base_url(provider_connection(llm.provider, None)),
        api_key=llm_provider_service.decrypt_api_key(llm.provider.api_key),
    )
    call = await llm_call_service.create_running_call(
        purpose="profile.embedding", task_id=None, agent_run_id=None, agent_id=None,
        llm_id=llm.id, provider_name=llm.provider.name, provider_code=llm.provider.catalog_code,
        requested_model=selection.selector, effective_model=llm.llm_name, stream=False,
        request_body=body.model_dump(mode="json"), requester_user_id=requester or get_current_user_id(),
        is_subscription=llm.is_subscription,
    )
    trace: dict[str, Any] = {}
    failure: BaseException | None = None
    try:
        result = await embedding_service.embed_many_with_usage(
            [body.input] if isinstance(body.input, str) else body.input,
            endpoint=endpoint, dimensions=body.dimensions, timeout_seconds=120,
        )
        trace = {"usage": result.usage or {}, "model": result.model}
        data: list[dict[str, Any]] = []
        for index, vector in enumerate(result.embeddings):
            encoded = (base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode()
                       if body.encoding_format == "base64" else vector)
            data.append({"object": "embedding", "index": index, "embedding": encoded})
        response: dict[str, Any] = {"object": "list", "model": selection.selector, "data": data}
        if result.usage is not None:
            response["usage"] = result.usage
        return response, str(call.id)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await llm_call_service.finalize_call(
                call.id, trace=trace, error=str(failure) if failure else None,
                status="cancelled" if isinstance(failure, asyncio.CancelledError) else "failed" if failure else "completed",
                input_rate=llm.cost_per_input_token, output_rate=llm.cost_per_output_token,
                effective_model=str(trace.get("model") or llm.llm_name),
            )
