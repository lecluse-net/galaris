import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from app.harness import runtime
from app.harness.runtime import (
    Agent,
    compact_agent_history,
    compact_capability_load_returns,
    compact_completed_tool_arguments,
    compact_stale_tool_returns,
)
from app.llm import LLM


def test_normalized_usage_keeps_measured_tokens_and_estimated_cost_distinct() -> None:
    result = SimpleNamespace(
        usage=lambda: SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            cache_read_tokens=40,
            cache_write_tokens=5,
            requests=2,
            tool_calls=3,
            details={"reasoning_tokens": 9},
            cost=None,
        )
    )
    llm = cast(
        LLM,
        SimpleNamespace(
            cost_per_input_token=0.01,
            cost_per_output_token=0.02,
        ),
    )

    usage = runtime._normalized_usage(  # pyright: ignore[reportPrivateUsage]
        result,
        llm,
        1.8,
    )

    assert usage.input_tokens == 120
    assert usage.output_tokens == 30
    assert usage.reasoning_tokens == 9
    assert usage.requests == 2
    assert usage.tool_calls == 3
    assert usage.cost == 1.8
    assert usage.token_quality == "exact"
    assert usage.cost_quality == "estimated"


def test_tool_failure_journal_recovers_the_native_technical_type() -> None:
    result_part = SimpleNamespace()

    assert runtime._tool_failure_error_type(  # pyright: ignore[reportPrivateUsage]
        result_part,
        "Tool failed.\nTechnical type: MemoryConflictError.\nError reference: abc123",
    ) == "MemoryConflictError"
    assert runtime._tool_failure_error_type(  # pyright: ignore[reportPrivateUsage]
        result_part,
        "Échec de l’outil.\nType technique : GoalRevisionConflict.",
    ) == "GoalRevisionConflict"


def test_large_completed_tool_arguments_are_compacted_without_mutating_trace() -> None:
    content = "Sample " * 2_000
    response = ModelResponse(
        parts=[
            ToolCallPart(
                "file_write",
                {"path": "plaquette.html", "content": content, "overwrite": True},
                "call-1",
            )
        ]
    )
    tool_return = ModelRequest(
        parts=[
            ToolReturnPart(
                "file_write",
                "Text file written: brochure.html",
                "call-1",
            )
        ]
    )

    compacted = compact_completed_tool_arguments([response, tool_return])

    original_part = response.parts[0]
    assert isinstance(original_part, ToolCallPart)
    assert original_part.args["content"] == content

    compacted_response = compacted[0]
    assert isinstance(compacted_response, ModelResponse)
    compacted_part = compacted_response.parts[0]
    assert isinstance(compacted_part, ToolCallPart)
    assert compacted_part.tool_call_id == "call-1"
    assert compacted_part.args["path"] == "plaquette.html"
    assert "content omitted after execution" in compacted_part.args["content"]
    assert compacted[1] is tool_return


def test_large_raw_json_arguments_remain_valid_json_after_compaction() -> None:
    raw_args = json.dumps({"path": "report.md", "content": "x" * 10_000})
    response = ModelResponse(
        parts=[ToolCallPart("file_write", raw_args, "call-2")]
    )

    compacted = compact_completed_tool_arguments([response, ModelRequest(parts=[ToolReturnPart("file_write", "done", "call-2")])])

    compacted_response = compacted[0]
    assert isinstance(compacted_response, ModelResponse)
    part = compacted_response.parts[0]
    assert isinstance(part, ToolCallPart)
    parsed = json.loads(part.args)
    assert parsed["path"] == "report.md"
    assert "content omitted after execution" in parsed["content"]


def test_large_invalid_raw_arguments_are_not_replaced_with_an_invalid_schema() -> None:
    raw_args = "{" + "x" * 10_000
    response = ModelResponse(
        parts=[ToolCallPart("file_write", raw_args, "call-invalid")]
    )

    compacted = compact_completed_tool_arguments([response])

    compacted_response = compacted[0]
    assert isinstance(compacted_response, ModelResponse)
    part = compacted_response.parts[0]
    assert isinstance(part, ToolCallPart)
    assert part.args == raw_args


@pytest.mark.parametrize("raw", [False, True])
def test_pending_tool_arguments_are_never_compacted(raw: bool) -> None:
    args = {"command": "x" * 10_000}
    original = json.dumps(args) if raw else args
    response = ModelResponse(parts=[ToolCallPart("console_exec", original, "pending")])
    compacted = compact_completed_tool_arguments([response])
    assert compacted[0].parts[0].args == original


def _tool_exchange(index: int, content: str) -> tuple[ModelResponse, ModelRequest]:
    call_id = f"call-{index}"
    return (
        ModelResponse(parts=[ToolCallPart("console_exec", {"command": "ls"}, call_id)]),
        ModelRequest(parts=[ToolReturnPart("console_exec", content, call_id)]),
    )


def test_stale_large_tool_returns_keep_preview_and_recent_ones_stay_intact() -> None:
    large = "stdout line\n" * 1_000
    messages: list[ModelResponse | ModelRequest] = []
    for index in range(6):
        response, tool_return = _tool_exchange(index, large)
        messages.extend((response, tool_return))

    compacted = compact_stale_tool_returns(list(messages))

    returns = [
        part
        for message in compacted
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert len(returns) == 6
    for stale in returns[:2]:
        assert isinstance(stale.content, str)
        assert "tool result truncated after use" in stale.content
        assert stale.content.startswith("stdout line")
        assert len(stale.content) < len(large)
    for recent in returns[2:]:
        assert recent.content == large

    # The original trace must never be mutated.
    original_returns = [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert all(part.content == large for part in original_returns)


def test_small_and_recent_tool_returns_are_left_untouched() -> None:
    small = "ok"
    messages: list[ModelResponse | ModelRequest] = []
    for index in range(6):
        response, tool_return = _tool_exchange(index, small)
        messages.extend((response, tool_return))

    compacted = compact_stale_tool_returns(list(messages))

    assert compacted == messages


def test_capability_load_instructions_are_removed_from_model_history() -> None:
    instructions = "Galaris guide\n" * 2_000
    response = ModelResponse(
        parts=[
            ToolCallPart(
                "load_capability",
                {"id": "galaris"},
                "call-capability",
                tool_kind="capability-load",
            )
        ]
    )
    tool_return = ModelRequest(
        parts=[
            ToolReturnPart(
                "load_capability",
                {"instructions": instructions},
                "call-capability",
                tool_kind="capability-load",
            )
        ]
    )

    compacted = compact_capability_load_returns([response, tool_return])

    compacted_return = compacted[1]
    assert isinstance(compacted_return, ModelRequest)
    part = compacted_return.parts[0]
    assert isinstance(part, ToolReturnPart)
    assert part.content == {}
    assert part.tool_call_id == "call-capability"
    assert part.tool_kind == "capability-load"
    assert tool_return.parts[0].content == {"instructions": instructions}


def test_compact_agent_history_applies_both_compactions() -> None:
    big_args_response = ModelResponse(
        parts=[ToolCallPart("file_write", {"content": "x" * 10_000}, "call-args")]
    )
    big_args_return = ModelRequest(
        parts=[ToolReturnPart("file_write", "written", "call-args")]
    )
    messages: list[ModelResponse | ModelRequest] = [big_args_response, big_args_return]
    for index in range(5):
        response, tool_return = _tool_exchange(index, "y" * 8_000)
        messages.extend((response, tool_return))

    compacted = compact_agent_history(list(messages))

    first_response = compacted[0]
    assert isinstance(first_response, ModelResponse)
    call_part = first_response.parts[0]
    assert isinstance(call_part, ToolCallPart)
    assert "content omitted after execution" in call_part.args["content"]
    second_return = compacted[3]
    assert isinstance(second_return, ModelRequest)
    return_part = second_return.parts[0]
    assert isinstance(return_part, ToolReturnPart)
    assert isinstance(return_part.content, str)
    assert "tool result truncated after use" in return_part.content


def test_compact_agent_history_bounds_context_without_orphaning_tools() -> None:
    messages: list[ModelMessage] = []
    for index in range(12):
        call_id = f"call-{index}"
        messages.extend(
            [
                ModelResponse(
                    parts=[ToolCallPart("search_web", {"query": str(index)}, call_id)]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="search_web",
                            content="x" * 2_000,
                            tool_call_id=call_id,
                        )
                    ]
                ),
            ]
        )

    compacted = compact_agent_history(messages, max_chars=8_000)

    assert isinstance(compacted[0], ModelRequest)
    assert "Earlier completed history was compacted" in str(
        compacted[0].parts[0].content
    )
    calls = {
        part.tool_call_id
        for message in compacted
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }
    returns = {
        part.tool_call_id
        for message in compacted
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    assert calls == returns


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("real_time", "expected_effort"),
    [(True, "low"), (False, None)],
)
async def test_real_time_codex_agent_uses_low_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    real_time: bool,
    expected_effort: str | None,
) -> None:
    captured: dict[str, Any] = {}

    class FakePydanticAgent:
        def __init__(self, _model: object, **kwargs: Any) -> None:
            captured.update(kwargs)

    llm = cast(
        LLM,
        SimpleNamespace(
            provider=SimpleNamespace(
                id=1,
                name="OpenAI — ChatGPT",
                catalog_code="openai-codex",
                provider_type="openai_codex",
                base_url="https://chatgpt.com/backend-api/codex",
                configuration={},
            ),
        ),
    )
    monkeypatch.setattr(runtime, "build_model_for_llm", AsyncMock(return_value=object()))
    monkeypatch.setattr(runtime, "PydanticAgent", FakePydanticAgent)

    agent = Agent(llm, real_time=real_time)
    await agent.init()

    model_settings = captured["model_settings"]
    assert model_settings.get("openai_reasoning_effort") == expected_effort
    assert model_settings.get("parallel_tool_calls") is False
