from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from pydantic_ai import UsageLimits
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.llm import structured_service
from app.llm.purposes import LLMCallPurpose


class _PromptedResult(BaseModel):
    memories: list[str]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["structured", "prompted", "text", "text_with_tools"])
@pytest.mark.parametrize("subscription", [False, True])
async def test_successful_inference_uses_persisted_gateway_cost(db, monkeypatch, mode, subscription):
    from app.llm import LLMCall, llm_call_service

    call = LLMCall(provider_name="test", requested_model="test", is_subscription=subscription)
    db.add(call)
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    async def respond(_messages, info):
        await llm_call_service.finalize_call(call.id, trace={"usage": {
            "prompt_tokens": 120, "completion_tokens": 30, "cost": .042}})
        if info.output_tools:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"memories": []})])
        return ModelResponse(parts=[TextPart('{"memories":[]}' if mode == "prompted" else "Done")])

    from pydantic_ai.usage import RequestUsage
    model = FunctionModel(respond)
    monkeypatch.setattr(model, "count_tokens", AsyncMock(return_value=RequestUsage(input_tokens=1)))
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(return_value=model))
    # Provider billing takes precedence over local pricing, including billed zero.
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 9.0)
    arguments = dict(llm=SimpleNamespace(), prompt="Work", system_prompt="Instructions",
                     temperature=0.0, request_limit=1)
    if mode == "text_with_tools":
        arguments["tools"] = []
    else:
        arguments.update(task_id=None, agent_id=None, count_tokens_before_request=False)
    if mode in {"structured", "prompted"}:
        arguments["output_type"] = _PromptedResult
    result = await getattr(structured_service, f"run_{mode}")(**arguments)
    await db.refresh(call)
    assert result.cost == call.cost == (0 if subscription else .042)


@pytest.mark.asyncio
async def test_prompted_output_exposes_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def respond(
        _messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        observed["function_tools"] = list(info.function_tools)
        observed["output_tools"] = list(info.output_tools)
        observed["model_settings"] = info.model_settings
        return ModelResponse(
            parts=[TextPart(content='{"memories":["durable preference"]}')]
        )

    async def fake_build_model(*_args: object, **kwargs: object) -> FunctionModel:
        observed["purpose"] = kwargs.get("purpose")
        return FunctionModel(respond)

    monkeypatch.setattr(structured_service, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(
        structured_service,
        "estimate_cost_from_usage",
        lambda *_args: 0.0,
    )

    result = await structured_service.run_prompted(
        llm=SimpleNamespace(),
        output_type=_PromptedResult,
        prompt="Extract memories.",
        system_prompt="Return prompted JSON.",
        task_id=None,
        agent_id=None,
        temperature=0.0,
        request_limit=1,
        max_tokens=256,
        output_retries=0,
        count_tokens_before_request=False,
        purpose=LLMCallPurpose.DREAM_TOPIC_CONTINUITY,
    )

    assert result.output == _PromptedResult(memories=["durable preference"])
    assert observed == {
        "function_tools": [],
        "output_tools": [],
        "model_settings": {"temperature": 0.0, "max_tokens": 256},
        "purpose": LLMCallPurpose.DREAM_TOPIC_CONTINUITY,
    }


@pytest.mark.asyncio
async def test_prompted_output_applies_the_reasoning_paired_with_its_model_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content='{"memories":[]}')])

    async def fake_build_model(*_args: object, **kwargs: object) -> FunctionModel:
        observed["reasoning_effort"] = kwargs.get("reasoning_effort")
        return FunctionModel(respond)

    resolve_reasoning = AsyncMock(return_value="xhigh")
    monkeypatch.setattr(structured_service, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(
        structured_service.llm_service,
        "get_profile_reasoning_effort_for_agent_id",
        resolve_reasoning,
    )
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_args: 0.0)

    result = await structured_service.run_prompted(
        llm=SimpleNamespace(),
        output_type=_PromptedResult,
        prompt="Extract memories.",
        system_prompt="Return prompted JSON.",
        task_id=None,
        agent_id=12,
        temperature=0.0,
        request_limit=1,
        count_tokens_before_request=False,
        model_field="text_low_llm_id",
    )

    assert result.output == _PromptedResult(memories=[])
    assert observed["reasoning_effort"] == "xhigh"
    resolve_reasoning.assert_awaited_once_with("text_low_llm_id", 12)


@pytest.mark.asyncio
async def test_structured_output_prefers_explicit_reasoning_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="done")])

    async def fake_build_model(*_args: object, **kwargs: object) -> FunctionModel:
        observed["reasoning_effort"] = kwargs.get("reasoning_effort")
        return FunctionModel(respond)

    profile_reasoning = AsyncMock(return_value="low")
    monkeypatch.setattr(structured_service, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(
        structured_service.llm_service,
        "get_profile_reasoning_effort_for_agent_id",
        profile_reasoning,
    )
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_args: 0.0)

    result = await structured_service.run_structured(
        llm=SimpleNamespace(),
        output_type=str,
        prompt="Complete the task.",
        system_prompt="Return text.",
        task_id=None,
        agent_id=12,
        temperature=0.0,
        request_limit=1,
        count_tokens_before_request=False,
        model_field="text_standard_llm_id",
        reasoning_effort_override="xhigh",
    )

    assert result.output == "done"
    assert observed["reasoning_effort"] == "xhigh"
    profile_reasoning.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompted_output_retry_is_not_blocked_without_request_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0

    def respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        nonlocal request_count
        request_count += 1
        content = (
            '{"memories":{"unexpected":"shape"}}'
            if request_count == 1
            else '{"memories":["durable preference"]}'
        )
        return ModelResponse(parts=[TextPart(content=content)])

    async def fake_build_model(*_args: object, **_kwargs: object) -> FunctionModel:
        return FunctionModel(respond)

    monkeypatch.setattr(structured_service, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(
        structured_service,
        "estimate_cost_from_usage",
        lambda *_args: 0.0,
    )

    result = await structured_service.run_prompted(
        llm=SimpleNamespace(),
        output_type=_PromptedResult,
        prompt="Extract memories.",
        system_prompt="Return prompted JSON.",
        task_id=None,
        agent_id=None,
        temperature=0.0,
        request_limit=None,
        output_retries=1,
        count_tokens_before_request=False,
    )

    assert request_count == 2
    assert result.output == _PromptedResult(memories=["durable preference"])


@pytest.mark.asyncio
async def test_text_output_exposes_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def respond(
        _messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        observed["function_tools"] = list(info.function_tools)
        observed["output_tools"] = list(info.output_tools)
        return ModelResponse(parts=[TextPart(content='[{"title":"durable"}]')])

    async def fake_build_model(*_args: object, **_kwargs: object) -> FunctionModel:
        return FunctionModel(respond)

    monkeypatch.setattr(structured_service, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(
        structured_service,
        "estimate_cost_from_usage",
        lambda *_args: 0.0,
    )

    result = await structured_service.run_text(
        llm=SimpleNamespace(),
        prompt="Extract memories.",
        system_prompt="Return a JSON list.",
        task_id=None,
        agent_id=None,
        temperature=0.0,
        request_limit=1,
        count_tokens_before_request=False,
    )

    assert result.output == '[{"title":"durable"}]'
    assert observed == {"function_tools": [], "output_tools": []}


@pytest.mark.asyncio
async def test_text_with_tools_records_the_exact_effect_free_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = 0

    def respond(
        _messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal step
        assert [tool.name for tool in info.function_tools] == ["record_action"]
        step += 1
        if step == 1:
            return ModelResponse(
                parts=[ToolCallPart("record_action", {"objective": "Prepare report"})]
            )
        return ModelResponse(parts=[TextPart(content="Work started.")])

    async def fake_build_model(*_args: object, **_kwargs: object) -> FunctionModel:
        return FunctionModel(respond)

    async def record_action(objective: str) -> dict[str, object]:
        return {"recorded": True, "objective": objective}

    def local_usage_limits(**kwargs: object) -> UsageLimits:
        kwargs["count_tokens_before_request"] = False
        return UsageLimits(**kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(structured_service, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(structured_service, "UsageLimits", local_usage_limits)
    monkeypatch.setattr(
        structured_service,
        "estimate_cost_from_usage",
        lambda *_args: 0.0,
    )

    result = await structured_service.run_text_with_tools(
        llm=SimpleNamespace(),
        prompt="Prepare a report.",
        system_prompt="Use the recording tool.",
        tools=[record_action],
    )

    assert result.output == "Work started."
    assert result.tool_calls == [
        {"name": "record_action", "arguments": {"objective": "Prepare report"}}
    ]
