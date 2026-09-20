from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, Literal, Optional, cast
from uuid import UUID

import httpx
import httpx2
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.messages import (
    BinaryContent, ModelMessage, ModelMessagesTypeAdapter, ModelRequest,
    ModelResponse, UserContent, UserPromptPart,
)
from openai.types.chat import ChatCompletionContentPartParam
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.openai import OpenAIModelProfile, openai_model_profile
from pydantic_ai.providers import Provider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from app.llm import LLM
from app.llm.purposes import LLMCallPurpose
from app.llm.provider_facade import (
    ProviderResponsesPolicy,
    ReasoningEffort,
    request_parameter_policy_for,
    responses_policy_for,
)
from app.llm.provider_catalog import resolve_provider_profile
from app.llm.resource_discovery import provider_connection
from app.llm.costing import token_cost
from app.llm.proxy_service import PROXY_TIMEOUT, proxy_chat_completion, proxy_responses
from .native_media import native_audio_format, native_media_requires_chat, supports_native_input


def _compatible_model_profile(llm: LLM, profile: ModelProfile | None) -> ModelProfile | None:
    """Project provider-owned wire restrictions into the SDK's request builder."""
    provider = getattr(llm, "provider", None)
    if provider is None:
        return profile
    policy = request_parameter_policy_for(provider_connection(provider, None), llm.llm_name)
    profile = merge_profile(
        profile,
        OpenAIModelProfile(
            openai_chat_supports_max_completion_tokens=policy.chat_token_limit == "max_completion_tokens",
        ),
    )
    if policy.forced_tools_when_reasoning:
        return profile
    # Preserve the provider's other capabilities and explicit tool-choice errors.
    # Inferred output-tool forcing may use auto, while output validation still runs.
    return merge_profile(
        profile,
        OpenAIModelProfile(
            openai_supports_forced_tool_choice_with_thinking=False,
            openai_reasoning_enabled_by_default=policy.reasoning_default,
        ),
    )


class _InternalByteStream(httpx2.AsyncByteStream):
    """Expose a Starlette response body through the OpenAI SDK stream contract."""

    def __init__(self, response: StreamingResponse) -> None:
        self._response = response
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for raw in self._response.body_iterator:
            if self._closed:
                break
            if isinstance(raw, str):
                yield raw.encode("utf-8")
            else:
                yield bytes(raw)

    async def aclose(self) -> None:
        self._closed = True
        closer = getattr(self._response.body_iterator, "aclose", None)
        if closer is not None:
            await closer()


class _InternalLLMTransport(httpx2.AsyncBaseTransport):
    """Route SDK HTTP requests through Galaris authorization and accounting."""

    def __init__(
        self,
        llm: LLM,
        *,
        task_id: UUID | None,
        agent_run_id: UUID | None,
        conversation_round_id: UUID | None,
        agent_id: int | None,
        purpose: str | None,
        reasoning_effort: ReasoningEffort | None,
        durable: bool = False,
    ) -> None:
        self._llm = llm
        self._task_id = task_id
        self._agent_run_id = agent_run_id
        self._conversation_round_id = conversation_round_id
        self._agent_id = agent_id
        self._purpose = purpose
        self._reasoning_effort: ReasoningEffort | None = reasoning_effort
        self._durable = durable

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        raw_body = await request.aread()
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise UnexpectedModelBehavior(
                "The internal LLM request is not valid JSON."
            ) from exc
        if not isinstance(parsed, dict):
            raise UnexpectedModelBehavior(
                "The internal LLM request must be a JSON object."
            )
        body = cast(dict[str, Any], parsed)
        options: dict[str, Any] = {
            "purpose": self._purpose,
            "task_id": self._task_id,
            "agent_run_id": self._agent_run_id,
            "conversation_round_id": self._conversation_round_id,
            "agent_id": self._agent_id,
            "llm_override": self._llm,
            "route_executor_model": False,
            # This is the requested effort for accounting only. The SDK has already
            # resolved it in the payload; the proxy must not re-inject it.
            "reasoning_effort": self._reasoning_effort,
            "sdk_request": True,
            "request_timeout": request.extensions.get("timeout"),
        }
        try:
            from .call_capture import text_call_capture

            chat = proxy_chat_completion
            responses = proxy_responses
            if self._durable and text_call_capture.get() is None:
                from . import protocol_inference

                chat = protocol_inference.proxy_chat_completion
                responses = protocol_inference.proxy_responses
            if request.url.path == "/chat/completions":
                body["model"] = self._llm.code
                response = await chat(body, **options)
            elif request.url.path in {"/responses", "/responses/compact"}:
                operation: Literal["create", "compact"] = (
                    "compact" if request.url.path == "/responses/compact" else "create"
                )
                response = await responses(
                    body, operation=operation, model_code=self._llm.code, **options,
                )
            else:
                raise UnexpectedModelBehavior("Unsupported internal LLM endpoint.")
        except httpx.TimeoutException as exc:
            raise httpx2.TimeoutException(str(exc), request=request) from exc
        except httpx.TransportError as exc:
            raise httpx2.TransportError(str(exc), request=request) from exc
        headers = dict(response.headers)
        if isinstance(response, StreamingResponse):
            return httpx2.Response(
                response.status_code,
                headers=headers,
                stream=_InternalByteStream(response),
                request=request,
            )
        return httpx2.Response(
            response.status_code,
            headers=headers,
            content=bytes(response.body),
            request=request,
        )


class _InternalLLMProvider(Provider[AsyncOpenAI]):
    """OpenAI SDK provider whose transport never leaves the Galaris process."""

    def __init__(self, transport: _InternalLLMTransport) -> None:
        self._http_client = httpx2.AsyncClient(
            transport=transport,
            timeout=httpx2.Timeout(**PROXY_TIMEOUT.as_dict()),
        )
        self._client = AsyncOpenAI(
            api_key="unused-internal-client",
            base_url="http://llm-call.invalid",
            http_client=self._http_client,
            max_retries=0,
        )

    @property
    def name(self) -> str:
        return "galaris"

    @property
    def base_url(self) -> str:
        return "http://llm-call.invalid"

    @property
    def client(self) -> AsyncOpenAI:
        return self._client

    @staticmethod
    def model_profile(model_name: str) -> ModelProfile | None:
        return openai_model_profile(model_name)


def _responses_policy_settings(
    policy: ProviderResponsesPolicy,
    reasoning_effort: ReasoningEffort | None,
) -> OpenAIResponsesModelSettings:
    """Project provider-owned Responses requirements into every model call."""

    settings: OpenAIResponsesModelSettings = {}
    if policy.store is not None:
        settings["openai_store"] = policy.store
    if policy.reasoning_context is not None:
        settings["openai_reasoning_context"] = policy.reasoning_context
    if policy.reasoning_summary is not None:
        settings["openai_reasoning_summary"] = policy.reasoning_summary
    if policy.send_reasoning_ids is not None:
        settings["openai_send_reasoning_ids"] = policy.send_reasoning_ids
    if reasoning_effort is not None:
        settings["openai_reasoning_effort"] = reasoning_effort
    return settings


class InternalLLMResponsesModel(OpenAIResponsesModel):
    """Native Responses model routed through Galaris accounting and authorization."""

    def __init__(
        self,
        llm: LLM,
        *,
        task_id: UUID | None = None,
        agent_run_id: UUID | None = None,
        conversation_round_id: UUID | None = None,
        agent_id: int | None = None,
        purpose: LLMCallPurpose | str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        responses_policy: ProviderResponsesPolicy | None = None,
        durable: bool = False,
    ) -> None:
        policy = responses_policy or _responses_policy_for_llm(llm)
        if policy is None:
            raise ValueError(
                f"LLM {llm.code!r} does not have a native Responses policy."
            )
        transport = _InternalLLMTransport(
            llm,
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            agent_id=agent_id,
            purpose=str(purpose) if purpose is not None else None,
            reasoning_effort=reasoning_effort,
            durable=durable,
        )
        super().__init__(
            llm.llm_name,
            provider=_InternalLLMProvider(transport),
            profile=_compatible_model_profile(llm, policy.model_profile(llm.llm_name)),
            settings=_responses_policy_settings(policy, reasoning_effort),
        )
        self.llm = llm

        self.responses_policy = policy

    async def request(
        self, messages: list[ModelMessage], model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        async with self.request_stream(messages, model_settings, model_request_parameters) as stream:
            async for _ in stream:
                pass
            return stream.get()

    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        return _estimate_request_usage(messages, model_settings, model_request_parameters)


class InternalLLMChatModel(OpenAIChatModel):
    """Pydantic AI model routing requests through the internal ``llm_call`` proxy."""

    async def _map_user_prompt_content_item(
        self, item: UserContent, content: list[ChatCompletionContentPartParam],
    ) -> None:
        # Pydantic AI explicitly exposes this stable protected hook for provider formats.
        if isinstance(item, BinaryContent) and (item.is_audio or item.is_video):
            if not supports_native_input(self.llm, item.media_type):
                raise ValueError("The selected model/transport does not support this media input.")
            import base64

            wire: dict[str, Any] = (
                {"type": "video_url", "video_url": {"url": item.data_uri}}
                if item.is_video else
                {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(item.data).decode("ascii"),
                    "format": native_audio_format(item.media_type),
                }}
            )
            # OpenRouter extends OpenAI's typed content union with video and audio codecs.
            content.append(cast(ChatCompletionContentPartParam, wire))
            return
        await super()._map_user_prompt_content_item(item, content)

    def __init__(
        self,
        llm: LLM,
        *,
        task_id: Optional[UUID] = None,
        agent_run_id: Optional[UUID] = None,
        conversation_round_id: Optional[UUID] = None,
        agent_id: Optional[int] = None,
        purpose: LLMCallPurpose | str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        durable: bool = False,
    ) -> None:
        settings: OpenAIChatModelSettings = {}
        if reasoning_effort is not None:
            settings["openai_reasoning_effort"] = reasoning_effort
        transport = _InternalLLMTransport(
            llm,
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            agent_id=agent_id,
            purpose=str(purpose) if purpose is not None else None,
            reasoning_effort=reasoning_effort,
            durable=durable,
        )
        provider = getattr(llm, "provider", None)
        policy = (
            responses_policy_for(provider_connection(provider, None))
            if provider is not None else None
        )
        sdk_profile = (
            policy.model_profile(llm.llm_name)
            if policy is not None else openai_model_profile(llm.llm_name)
        )
        profile = _compatible_model_profile(
            llm,
            merge_profile(
                sdk_profile,
                # Preserve the strict-template guarantee using the SDK's public profile.
                OpenAIModelProfile(
                    openai_chat_supports_multiple_system_messages=False,
                    openai_chat_supports_max_completion_tokens=False,
                ),
            ),
        )
        super().__init__(
            llm.llm_name,
            provider=_InternalLLMProvider(transport),
            profile=profile,
            settings=settings,
        )
        self.llm = llm

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        # Preserve progressive call tracing even when the caller wants one final value.
        async with self.request_stream(
            messages,
            model_settings,
            model_request_parameters,
        ) as streamed_response:
            async for _event in streamed_response:
                pass
            return streamed_response.get()

    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        return _estimate_request_usage(messages, model_settings, model_request_parameters)


class InternalLLMFallbackModel(FallbackModel):
    """SDK fallback with the same local preflight budget guard as either protocol."""

    async def count_tokens(
        self, messages: list[ModelMessage], model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        return _estimate_request_usage(messages, model_settings, model_request_parameters)


def _estimate_request_usage(
    messages: list[ModelMessage],
    model_settings: ModelSettings | None,
    model_request_parameters: ModelRequestParameters,
) -> RequestUsage:
    """Bound local preflight usage without private SDK serializers or a paid count call.

    This is a deliberately approximate runaway guard, never billing data. Include tools,
    output schemas and instructions as well as history, including opaque reasoning.
    """
    # Base64 is a transport encoding, not text tokenized by a multimodal model. Counting it
    # as prose rejects ordinary images/audio before the provider can report actual usage.
    # Keep a coarse nonzero reserve per media part; provider usage remains the billing truth.
    estimate_messages: list[ModelMessage] = []
    media_reserve = 0
    for message in messages:
        if not isinstance(message, ModelRequest):
            estimate_messages.append(message)
            continue
        parts = list(message.parts)
        for index, part in enumerate(parts):
            if not isinstance(part, UserPromptPart) or isinstance(part.content, str):
                continue
            content: list[UserContent] = []
            for item in part.content:
                if isinstance(item, BinaryContent):
                    content.append(f"[native input: {item.media_type}]")
                    media_reserve += 4096
                else:
                    content.append(item)
            parts[index] = replace(part, content=content)
        estimate_messages.append(replace(message, parts=parts))
    history = ModelMessagesTypeAdapter.dump_json(estimate_messages).decode("utf-8")
    tools = [
        {"name": tool.name, "description": tool.description, "schema": tool.parameters_json_schema}
        for tool in [*model_request_parameters.function_tools, *model_request_parameters.output_tools]
    ]
    parameters = json.dumps(
        {
            "settings": model_settings,
            "tools": tools,
            "output": model_request_parameters.output_object,
            "instructions": model_request_parameters.instruction_parts,
            "native_tools": model_request_parameters.native_tools,
        },
        ensure_ascii=False,
        default=str,
    )
    return RequestUsage(input_tokens=max(1, math.ceil((len(history) + len(parameters)) / 4)) + media_reserve)


def _responses_policy_for_llm(llm: LLM) -> ProviderResponsesPolicy | None:
    provider = getattr(llm, "provider", None)
    if provider is None:
        return None
    profile = resolve_provider_profile(
        catalog_code=getattr(provider, "catalog_code", None),
        base_url=str(getattr(provider, "base_url", "") or ""),
    )
    if profile is None or not profile.supports_responses:
        return None
    connection = provider_connection(provider, None)
    if connection.catalog_code is None:
        connection = replace(connection, catalog_code=profile.code)
    policy = responses_policy_for(connection)
    return policy


def llm_supports_native_responses(llm: LLM) -> bool:
    """Return Responses availability declared by the provider bridge."""

    return _responses_policy_for_llm(llm) is not None


async def build_model_for_llm(
    llm: LLM,
    *,
    task_id: Optional[UUID] = None,
    agent_run_id: Optional[UUID] = None,
    conversation_round_id: Optional[UUID] = None,
    agent_id: Optional[int] = None,
    purpose: LLMCallPurpose | str | None = None,
    reasoning_effort: ReasoningEffort | None = None,
    enable_native_media: bool = False,
) -> InternalLLMChatModel | InternalLLMResponsesModel | FallbackModel:
    """Build a Pydantic AI model routed exclusively through ``llm_call``."""
    responses_policy = (
        None if enable_native_media and native_media_requires_chat(llm)
        else _responses_policy_for_llm(llm)
    )
    if responses_policy is not None:
        responses_model = InternalLLMResponsesModel(
            llm,
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            agent_id=agent_id,
            purpose=purpose,
            reasoning_effort=reasoning_effort,
            responses_policy=responses_policy,
            durable=True,
        )
        if not responses_policy.chat_fallback_statuses:
            return responses_model
        statuses = responses_policy.chat_fallback_statuses

        def rejected_protocol(exc: Exception) -> bool:
            # An HTTP refusal occurs before generation; streaming failures are
            # different SDK exceptions and must never repeat a delivered answer.
            return isinstance(exc, ModelHTTPError) and exc.status_code in statuses

        return InternalLLMFallbackModel(
            responses_model,
            InternalLLMChatModel(
                llm, task_id=task_id, agent_run_id=agent_run_id,
                conversation_round_id=conversation_round_id, agent_id=agent_id,
                purpose=purpose, reasoning_effort=reasoning_effort, durable=True,
            ),
            fallback_on=rejected_protocol,
        )
    return InternalLLMChatModel(
        llm,
        task_id=task_id,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        agent_id=agent_id,
        purpose=purpose,
        reasoning_effort=reasoning_effort,
        durable=True,
    )


def estimate_cost_from_usage(result: Any, llm: LLM) -> float:
    """Return billed cost, preferring provider-aware Pydantic usage accounting."""
    cost = 0.0
    try:
        usage = getattr(result, "usage", None)
        if callable(usage):
            usage = usage()
        if usage:
            reported = getattr(usage, "cost", None)
            reported_cost: float | None = None
            if not isinstance(reported, bool) and reported is not None:
                try:
                    amount = float(reported)
                except (TypeError, ValueError):
                    pass
                else:
                    if math.isfinite(amount) and amount >= 0:
                        reported_cost = amount
            if reported_cost is not None:
                cost = reported_cost
            else:
                input_tokens = getattr(usage, "input_tokens", 0) or 0
                input_cache_tokens = getattr(usage, "cache_read_tokens", 0) or 0
                output_tokens = getattr(usage, "output_tokens", 0) or 0
                output_cache_tokens = getattr(usage, "cache_write_tokens", 0) or 0
                if (
                    llm.cost_per_input_token is not None
                    and llm.cost_per_output_token is not None
                ):
                    cost = token_cost(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=input_cache_tokens,
                        cache_write_tokens=output_cache_tokens,
                        input_rate=llm.cost_per_input_token,
                        cached_input_rate=llm.cost_per_cached_input_token,
                        output_rate=llm.cost_per_output_token,
                        # Pydantic AI normalizes input tokens as an inclusive bucket.
                        input_includes_cache=True,
                    )
    except Exception:
        cost = 0.0
    return 0.0 if getattr(llm, "is_subscription", False) else cost
