from __future__ import annotations

from types import SimpleNamespace
from decimal import Decimal
from typing import TypedDict, cast

import pytest
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition
from fastapi.responses import StreamingResponse
import json

from app.llm import LLM, LLMCallPurpose
from app.llm.pydantic_ai_utils import InternalLLMChatModel, estimate_cost_from_usage


def test_cost_prefers_pydantic_provider_accounting() -> None:
    result = SimpleNamespace(usage=lambda: SimpleNamespace(
        cost=Decimal("0.1234"),
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=0,
        cache_write_tokens=0,
    ))
    llm = cast(LLM, SimpleNamespace(
        cost_per_input_token=99.0,
        cost_per_cached_input_token=None,
        cost_per_output_token=99.0,
        is_subscription=False,
    ))

    assert estimate_cost_from_usage(result, llm) == pytest.approx(0.1234)


def test_subscription_zeroes_billed_cost_without_changing_usage() -> None:
    usage = SimpleNamespace(
        cost=Decimal("0.1234"),
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    result = SimpleNamespace(usage=lambda: usage)
    llm = cast(LLM, SimpleNamespace(
        cost_per_input_token=1.0,
        cost_per_cached_input_token=None,
        cost_per_output_token=2.0,
        is_subscription=True,
    ))

    assert estimate_cost_from_usage(result, llm) == 0.0
    assert usage.cost == Decimal("0.1234")


def test_cost_falls_back_to_configured_rates_with_inclusive_cache_tokens() -> None:
    result = SimpleNamespace(usage=lambda: SimpleNamespace(
        cost=None,
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=40,
        cache_write_tokens=0,
    ))
    llm = cast(LLM, SimpleNamespace(
        cost_per_input_token=2.0,
        cost_per_cached_input_token=0.5,
        cost_per_output_token=4.0,
        is_subscription=False,
    ))

    assert estimate_cost_from_usage(result, llm) == pytest.approx(
        (60 * 2.0 + 40 * 0.5 + 20 * 4.0) / 1_000_000
    )


def test_internal_model_base_url_does_not_access_provider_client() -> None:
    llm = cast(
        LLM,
        SimpleNamespace(
            code="internal-model",
            llm_name="provider/model",
        ),
    )

    model = InternalLLMChatModel(llm)

    assert model.base_url == "http://llm-call.invalid"


@pytest.fixture
def captured_requests(monkeypatch):
    """Exercise the SDK's real request mapping and SSE reader."""
    requests = []

    async def proxy(body, **kwargs):
        requests.append((body, kwargs))

        async def chunks():
            payload = {"id": "chat_test", "object": "chat.completion.chunk", "created": 1,
                "model": "opaque", "choices": [{"index": 0, "delta": {
                    "content": json.dumps({"decision": "continue"})}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr("app.llm.pydantic_ai_utils.proxy_chat_completion", proxy)
    return requests


@pytest.mark.asyncio
async def test_prompted_json_output_includes_sdk_schema_instructions(captured_requests) -> None:
    class Decision(TypedDict):
        decision: str

    model = InternalLLMChatModel(
        cast(LLM, SimpleNamespace(code="internal-model", llm_name="opaque")),
        purpose=LLMCallPurpose.DREAM_TOPIC_CONTINUITY,
        reasoning_effort="xhigh",
    )
    agent = Agent(model, output_type=PromptedOutput(Decision),
                  instructions="Réponds avec une décision structurée.")
    result = await agent.run("Continue ?")
    assert result.output == {"decision": "continue"}
    body, options = captured_requests[0]
    assert body["response_format"] == {"type": "json_object"}
    assert "json" in str(body["messages"]).lower()
    assert options["purpose"] == LLMCallPurpose.DREAM_TOPIC_CONTINUITY
    assert options["reasoning_effort"] == "xhigh"
    assert options["sdk_request"] is True
    assert options["route_executor_model"] is False


@pytest.mark.asyncio
async def test_internal_model_merges_leading_system_messages(captured_requests) -> None:
    model = InternalLLMChatModel(
        cast(LLM, SimpleNamespace(code="internal-model", llm_name="opaque")),
    )
    await model.request(
        [ModelRequest(parts=[
            SystemPromptPart(content="<runtime_metadata>history</runtime_metadata>"),
            SystemPromptPart(content="Governed instructions."),
            UserPromptPart(content="Bonjour"),
        ])], {}, ModelRequestParameters(),
    )
    messages = captured_requests[0][0]["messages"]
    assert messages == [
        {"role": "system", "content": "<runtime_metadata>history</runtime_metadata>\n\nGoverned instructions."},
        {"role": "user", "content": "Bonjour"},
    ]


@pytest.mark.asyncio
async def test_local_token_guard_includes_tool_schemas_and_instruction_budget(captured_requests) -> None:
    model = InternalLLMChatModel(
        cast(LLM, SimpleNamespace(code="internal-model", llm_name="opaque")),
    )
    messages = [ModelRequest(parts=[UserPromptPart(content="Work")])]
    baseline = await model.count_tokens(messages, {}, ModelRequestParameters())
    large = await model.count_tokens(messages, {}, ModelRequestParameters(function_tools=[
        ToolDefinition(name="large_tool", description="x" * 8000),
    ]))
    assert large.input_tokens >= baseline.input_tokens + 2000
    assert captured_requests == []
