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
    RetryPromptPart,
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


@pytest.mark.parametrize("returned_error", ["retry", "canonical", "canonical_json", "explicit", "explicit_json"])
def test_rejected_tool_arguments_remain_available_for_retry(returned_error) -> None:
    content = "<p>Synthetic lesson</p>" * 500
    call = ModelResponse(parts=[ToolCallPart("file_edit", {"content": content}, "retry-1")])
    if returned_error == "retry":
        retry = ModelRequest(parts=[RetryPromptPart("Permission required", tool_name="file_edit", tool_call_id="retry-1")])
    else:
        error = (
            {"schema": "galaris.tool-error/v1", "status": "error", "outcome": "rejected", "error": "Content requires correction"}
            if returned_error.startswith("canonical") else
            {"ok": False, "error": "Content requires correction"}
        )
        payload = json.dumps(error) if returned_error.endswith("json") else error
        retry = ModelRequest(parts=[ToolReturnPart("file_edit", payload, "retry-1")])
    compacted = compact_completed_tool_arguments([call, retry])
    assert compacted[0].parts[0].args["content"] == content


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

    # The same provider ID in a later, unanswered turn is still executable input.
    pending = ModelResponse(parts=[ToolCallPart("file_write", {"content": content}, "call-1")])
    resumed = compact_completed_tool_arguments([response, tool_return, pending])
    assert resumed[-1] is pending
    assert pending.parts[0].args["content"] == content


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


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("collection", [False, True])
def test_external_result_history_keeps_outcomes_and_nested_pagination(raw, collection):
    payload = {
        "rows": list(range(10_000)) if collection else "record " * 5_000,
        "ok": True,
        "pageInfo": {"endCursor": "synthetic-next", "hasNextPage": True},
        "revision": 7,
    }
    original = json.dumps(payload) if raw else payload
    messages = [ModelResponse(parts=[ToolCallPart("external_search", {}, "search")]),
                ModelRequest(parts=[ToolReturnPart("external_search", original, "search")])]
    for index in range(5):
        messages.extend(_tool_exchange(index, "ok"))
    compacted = compact_stale_tool_returns(messages)
    part = compacted[1].parts[0]
    summary = json.loads(part.content) if raw else part.content
    assert summary["ok"] is True
    assert summary["pageInfo"] == payload["pageInfo"]
    assert summary["revision"] == 7
    assert "history_note" in summary
    assert len(json.dumps(summary, ensure_ascii=False)) <= 4_000
    assert messages[1].parts[0].content == original
    assert compact_stale_tool_returns(compacted) == compacted


@pytest.mark.parametrize("payload", [
    list(range(10_000)),
    {f"field_{index}": index for index in range(2_000)},
    {"rows": [{"value": "\\\"\n" * 3_000}] * 40, "next_cursor": None},
])
def test_structured_history_budget_also_bounds_many_small_values(payload):
    messages = [ModelRequest(parts=[ToolReturnPart("external", payload, "external")])]
    for index in range(5):
        messages.extend(_tool_exchange(index, "ok"))
    compacted = compact_stale_tool_returns(messages)
    summary = compacted[0].parts[0].content
    assert len(json.dumps(summary, ensure_ascii=False)) <= 4_000
    assert compact_stale_tool_returns(compacted) == compacted
    assert messages[0].parts[0].content == payload


def test_oversized_recent_mcp_result_is_bounded_before_it_exhausts_the_model_context():
    original = json.dumps({"rows": list(range(100_000)), "next_cursor": "continue-here"})
    call = ModelResponse(parts=[ToolCallPart("external_list", {"page": 1}, "list-1")])
    returned = ModelRequest(parts=[ToolReturnPart("external_list", original, "list-1")])
    compacted = compact_agent_history([call, returned], max_chars=20_000)
    assert compacted[0] is call
    summary = json.loads(compacted[1].parts[0].content)
    assert summary["next_cursor"] == "continue-here"
    assert "history_note" in summary
    assert runtime._history_message_size(compacted[1]) < 20_000
    assert compacted[1].parts[0].tool_call_id == "list-1"
    assert returned.parts[0].content == original


@pytest.mark.parametrize("source", ["{invalid " * 1_000, "[" * 2_500 + "0" + "]" * 2_500])
def test_malformed_or_deep_provider_text_can_be_compacted_without_crashing(source):
    messages = [ModelRequest(parts=[ToolReturnPart("external", source, "external")])]
    for index in range(5):
        messages.extend(_tool_exchange(index, "ok"))
    compacted = compact_stale_tool_returns(messages)
    assert len(compacted[0].parts[0].content) < len(source)
    assert messages[0].parts[0].content == source


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("offset_unit,next_offset", [("block", 8), (None, None)])
def test_stale_resource_reads_keep_pagination_without_presenting_a_read_failure(
    raw: bool, offset_unit: str | None, next_offset: int | None,
) -> None:
    body = (
        "<p>Synthetic inventory entry</p>" * 500
        if offset_unit == "block"
        else json.dumps([{"entry": index} for index in range(1_000)])
    )
    payload = {
        "uri": "document://00000000-0000-4000-8000-000000000001",
        "content": body,
        "start": 3,
        "end": 8,
        "total": 8 if next_offset is None else 12,
        "next_offset": next_offset,
        "revision": 2,
        "media_type": "text/html" if offset_unit == "block" else "application/json",
    }
    if offset_unit is not None:
        payload.update(offset_unit=offset_unit, blocks=[{"number": 4, "html": body}])
    original = json.dumps(payload) if raw else payload
    read_return = ModelRequest(parts=[ToolReturnPart("file_read", original, "read-1")])
    messages: list[ModelMessage] = [
        ModelResponse(parts=[ToolCallPart("file_read", {"uri": payload["uri"]}, "read-1")]),
        read_return,
    ]
    for index in range(5):
        messages.extend(_tool_exchange(index, "ok"))
    recent_return = ModelRequest(parts=[ToolReturnPart("file_read", original, "read-2")])
    messages.extend([
        ModelResponse(parts=[ToolCallPart("file_read", {"uri": payload["uri"]}, "read-2")]),
        recent_return,
    ])

    compacted = compact_stale_tool_returns(messages)
    part = compacted[1].parts[0]
    assert isinstance(part, ToolReturnPart)
    summary = json.loads(part.content) if raw else part.content
    for key in ("uri", "start", "end", "total", "next_offset", "revision", "media_type"):
        assert summary[key] == payload[key]
    assert summary.get("offset_unit") == offset_unit
    assert "history_note" in summary
    assert summary["content_preview"] == body[:600]
    assert "content omitted after execution" in summary["content"]
    assert "blocks" not in summary
    assert len(json.dumps(summary)) < 4_000
    assert part.tool_call_id == "read-1"
    assert read_return.parts[0].content == original
    assert compacted[-1] is recent_return
    assert compact_stale_tool_returns(compacted) == compacted


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
