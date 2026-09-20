"""Structured LLM-output facade used by agent orchestration.

Pydantic AI remains an ``app.llm`` implementation detail; calling domains do not construct
framework agents themselves.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Generator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import JsonValue
from pydantic_ai import (
    Agent as PydanticAgent,
    ModelRetry,
    PromptedOutput,
    UsageLimits,
)
from pydantic_ai import messages as pydantic_messages
from pydantic_ai.models import Model

from app.llm.provider_models import LLM
from app.llm.provider_facade import ReasoningEffort
from . import llm_service
from .accounting_scope import llm_call_accounting
from app.llm.purposes import LLMCallPurpose
from app.llm.pydantic_ai_utils import (
    build_model_for_llm,
    estimate_cost_from_usage,
)


_reasoning_scope: ContextVar[tuple[ReasoningEffort | None] | None] = ContextVar(
    "llm_reasoning_scope", default=None
)


@contextmanager
def reasoning_effort_scope(effort: ReasoningEffort | None) -> Generator[None]:
    """Freeze resolved reasoning across a composed inference, including an explicit None."""
    token = _reasoning_scope.set((effort,))
    try:
        yield
    finally:
        _reasoning_scope.reset(token)


async def resolve_reasoning_effort(
    model_field: str | None, agent_id: int | None, override: ReasoningEffort | None = None
) -> ReasoningEffort | None:
    scope = _reasoning_scope.get()
    if scope is not None:
        return scope[0]
    if override is not None:
        return override
    return (
        await llm_service.get_profile_reasoning_effort_for_agent_id(model_field, agent_id)
        if model_field is not None
        else None
    )


OutputT = TypeVar("OutputT")
StructuredOutputRetry = ModelRetry


@dataclass(frozen=True)
class StructuredInferenceResult(Generic[OutputT]):
    output: OutputT
    cost: float
    messages: list[Any]


@dataclass(frozen=True)
class ToolInferenceResult:
    output: str
    cost: float
    messages: list[Any]
    tool_calls: list[dict[str, Any]]


async def run_structured(
    *,
    llm: LLM,
    output_type: type[OutputT],
    prompt: str,
    system_prompt: str,
    task_id: UUID | None,
    agent_id: int | None,
    temperature: float,
    request_limit: int | None,
    max_tokens: int | None = None,
    output_retries: int | None = None,
    output_validator: Callable[[OutputT], OutputT] | None = None,
    count_tokens_before_request: bool = True,
    agent_run_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
    purpose: LLMCallPurpose | str | None = None,
    model_field: str | None = None,
    reasoning_effort_override: ReasoningEffort | None = None,
    output_mode: Literal["tool", "prompted"] = "tool",
    output_context: dict[str, JsonValue] | None = None,
) -> StructuredInferenceResult[OutputT]:
    from .call_capture import inference_owner, text_call_capture
    from .contracts import StructuredInferenceRequest
    from .output_registry import for_type

    profile_reasoning_effort = await resolve_reasoning_effort(
        model_field, agent_id, reasoning_effort_override
    )
    capture = text_call_capture.get()
    if output_context is not None and (capture is None or not capture.structured or not capture.durable):
        raise ValueError("Validation context requires a durable structured inference.")
    request: StructuredInferenceRequest | None = None
    if capture is not None and capture.structured:
        parameters: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            parameters["max_tokens"] = max_tokens
        request = StructuredInferenceRequest(
            llm_id=llm.id, task_id=task_id, agent_id=agent_id,
            agent_run_id=agent_run_id, conversation_round_id=conversation_round_id,
            prompt=prompt, system_prompt=system_prompt,
            parameters={**parameters, **capture.parameters},
            request_limit=request_limit, count_tokens_before_request=count_tokens_before_request,
            purpose=str(purpose or ""), model_field=model_field,
            reasoning_effort=profile_reasoning_effort,
            output=(for_type(output_type, output_validator, mode=output_mode, context=output_context)
                    if capture.durable else StructuredInferenceRequest.model_validate(capture.request).output),
            output_retries=output_retries,
        )
        if capture.durable:
            from .inference_execution import run_structured as run_durable_structured

            return await run_durable_structured(request, output_type)

    model: Model = await build_model_for_llm(
        llm,
        task_id=task_id,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        agent_id=agent_id,
        purpose=purpose,
        reasoning_effort=profile_reasoning_effort,
    )
    if capture is not None and request is not None:
        from .text_inference import RecordedTextModel

        capture.request = {**capture.request, **request.model_dump(mode="json")}
        model = RecordedTextModel(model, capture)
    model_settings: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        model_settings["max_tokens"] = max_tokens
    kwargs: dict[str, Any] = {
        "output_type": PromptedOutput(output_type) if output_mode == "prompted" else output_type,
        "system_prompt": system_prompt,
        "model_settings": model_settings,
    }
    if output_retries is not None:
        kwargs["retries"] = {"output": output_retries}
    agent: Any = PydanticAgent(model, **kwargs)
    if output_validator is not None:
        agent.output_validator(output_validator)
    if inference_owner.get() is not None:
        from core.database import release_db_transaction

        await release_db_transaction()
    with llm_call_accounting() as accounting:
        result = await agent.run(
            prompt,
            usage_limits=UsageLimits(
                request_limit=request_limit,
                count_tokens_before_request=count_tokens_before_request,
            ),
        )
    return StructuredInferenceResult(
        output=result.output,
        cost=accounting.cost if accounting.costs else estimate_cost_from_usage(result, llm),
        messages=list(result.all_messages()),
    )


async def run_prompted(
    *,
    llm: LLM,
    output_type: type[OutputT],
    prompt: str,
    system_prompt: str,
    task_id: UUID | None,
    agent_id: int | None,
    temperature: float,
    request_limit: int | None,
    max_tokens: int | None = None,
    output_retries: int = 0,
    count_tokens_before_request: bool = True,
    agent_run_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
    purpose: LLMCallPurpose | str | None = None,
    model_field: str | None = None,
    reasoning_effort_override: ReasoningEffort | None = None,
) -> StructuredInferenceResult[OutputT]:
    """Run prompt-described structured output without exposing any tool.

    ``PromptedOutput`` embeds the JSON schema in the model instructions and parses the text
    response locally. It is suitable for small OpenAI-compatible local models that implement
    neither tool calls nor provider-native JSON schema.
    """

    return await run_structured(
        llm=llm,
        output_type=output_type,
        prompt=prompt,
        system_prompt=system_prompt,
        task_id=task_id,
        agent_id=agent_id,
        temperature=temperature,
        request_limit=request_limit,
        max_tokens=max_tokens,
        output_retries=output_retries,
        count_tokens_before_request=count_tokens_before_request,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        purpose=purpose,
        model_field=model_field,
        reasoning_effort_override=reasoning_effort_override,
        output_mode="prompted",
    )


async def run_text(
    *,
    llm: LLM,
    prompt: str,
    system_prompt: str,
    task_id: UUID | None,
    agent_id: int | None,
    temperature: float,
    request_limit: int | None,
    count_tokens_before_request: bool = True,
    purpose: LLMCallPurpose | str | None = None,
    model_field: str | None = None,
) -> StructuredInferenceResult[str]:
    """Generate plain text through Pydantic AI without tools or an output schema."""
    from .call_capture import text_call_capture
    from .contracts import TextInferenceRequest

    profile_reasoning_effort = await resolve_reasoning_effort(model_field, agent_id)
    capture = text_call_capture.get()
    if capture is not None and capture.durable:
        from .inference_execution import run_text as run_durable_text

        return await run_durable_text(TextInferenceRequest(
            llm_id=llm.id, task_id=task_id, agent_id=agent_id,
            prompt=prompt, system_prompt=system_prompt,
            parameters={"temperature": temperature, **capture.parameters},
            request_limit=request_limit, count_tokens_before_request=count_tokens_before_request,
            purpose=str(purpose or ""), model_field=model_field,
            reasoning_effort=profile_reasoning_effort,
        ))

    model: Model = await build_model_for_llm(
        llm,
        task_id=task_id,
        agent_id=agent_id,
        purpose=purpose,
        reasoning_effort=profile_reasoning_effort,
    )
    if capture is not None:
        from .text_inference import RecordedTextModel

        capture.request = TextInferenceRequest(
            llm_id=llm.id, task_id=task_id, agent_id=agent_id,
            prompt=prompt, system_prompt=system_prompt,
            parameters={"temperature": temperature, **capture.parameters},
            request_limit=request_limit, count_tokens_before_request=count_tokens_before_request,
            purpose=str(purpose or ""), model_field=model_field,
            reasoning_effort=profile_reasoning_effort,
        ).model_dump(mode="json")
        model = RecordedTextModel(model, capture)
    kwargs: dict[str, Any] = {
        "output_type": str,
        "system_prompt": system_prompt,
        "model_settings": {"temperature": temperature},
    }
    agent: Any = PydanticAgent(model, **kwargs)
    from .call_capture import inference_owner

    if inference_owner.get() is not None:
        from core.database import release_db_transaction

        # This session belongs to the detached inference root. Return its setup
        # connection before waiting on the provider; ordinary callers keep theirs.
        await release_db_transaction()
    with llm_call_accounting() as accounting:
        result = await agent.run(
            prompt,
            usage_limits=UsageLimits(
                request_limit=request_limit,
                count_tokens_before_request=count_tokens_before_request,
            ),
        )
    return StructuredInferenceResult(
        output=str(result.output),
        cost=accounting.cost if accounting.costs else estimate_cost_from_usage(result, llm),
        messages=list(result.all_messages()),
    )


async def run_text_with_tools(
    *,
    llm: LLM,
    prompt: str,
    system_prompt: str,
    tools: list[Callable[..., Any]],
    temperature: float = 0.0,
    request_limit: int = 4,
    tool_calls_limit: int = 3,
    purpose: LLMCallPurpose | str | None = None,
    model_field: str | None = None,
) -> ToolInferenceResult:
    """Run effect-free recording tools and return their exact model call transcript."""

    model = await build_model_for_llm(
        llm,
        task_id=None,
        agent_id=None,
        purpose=purpose,
        reasoning_effort=await resolve_reasoning_effort(model_field, None),
    )
    agent: Any = PydanticAgent(
        model,
        output_type=str,
        instructions=system_prompt,
        tools=tools,
        model_settings={"temperature": temperature, "parallel_tool_calls": False},
        retries={"tools": 1, "output": 1},
    )
    with llm_call_accounting() as accounting:
        result = await agent.run(
            prompt,
            usage_limits=UsageLimits(
                request_limit=request_limit,
                tool_calls_limit=tool_calls_limit,
                count_tokens_before_request=True,
            ),
        )
    messages = list(result.all_messages())
    calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, pydantic_messages.ModelResponse):
            continue
        for part in message.parts:
            if not isinstance(part, pydantic_messages.ToolCallPart):
                continue
            raw_args = part.args
            if isinstance(raw_args, str):
                try:
                    arguments: Any = json.loads(raw_args)
                except ValueError:
                    arguments = {"raw": raw_args}
            else:
                arguments = raw_args
            calls.append({"name": part.tool_name, "arguments": arguments})
    return ToolInferenceResult(
        output=str(result.output),
        cost=accounting.cost if accounting.costs else estimate_cost_from_usage(result, llm),
        messages=messages,
        tool_calls=calls,
    )


__all__ = [
    "StructuredInferenceResult",
    "ToolInferenceResult",
    "StructuredOutputRetry",
    "run_prompted",
    "run_structured",
    "run_text",
    "run_text_with_tools",
]
