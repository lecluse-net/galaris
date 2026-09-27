"""Safety guards for deterministic tool loops and incomplete provider outputs."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator, cast

import pytest
from pydantic_ai import AgentRunResultEvent, PartDeltaEvent, PartStartEvent
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    TextPartDelta,
    UserPromptPart,
)

from app.agent.contracts import AIMessage
from app.harness import runtime
from app.harness.runtime import Agent


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("decision", ["adapt", "report"])
@pytest.mark.parametrize("transport", ["native", "mcp"])
@pytest.mark.parametrize("durable", [False, True])
async def test_repeated_tools_allow_skill_reread_or_an_honest_report(
    db, monkeypatch, failed, decision, transport, durable,
):
    """Finish tool batches before advice and roll back their real failure-journal writes."""
    from unittest.mock import AsyncMock

    from fastmcp import FastMCP
    from pydantic_ai.messages import ToolReturnPart
    from pydantic_ai.models.function import DeltaToolCall
    from pydantic_ai.toolsets import FunctionToolset

    from app.harness.checkpoint import TOOL_ERROR_SCHEMA, HarnessRunCheckpoint
    from app.harness.mcp_toolset import ExecutionEvidenceClient
    from pydantic_ai.mcp import MCPToolset
    from app.harness.tests.test_runtime_cancellation import _CountingFunctionModel, _request

    calls = []

    def probe() -> dict[str, str]:
        calls.append("probe")
        if failed:
            return {
                "schema": TOOL_ERROR_SCHEMA, "status": "error", "outcome": "unknown",
                "error": f"Source unavailable.\nError reference: {len(calls):012x}",
                "instruction": "Verify the current state before retrying.",
            }
        return {"content": "Unchanged document"}

    def pending() -> str:
        calls.append("pending")
        return "Pending operation completed once"

    def read_skill() -> str:
        calls.append("read_skill")
        return "Use the alternative method."

    def alternative() -> str:
        calls.append("alternative")
        return "Work completed"

    async def model(messages, info):
        returns = [part for message in messages for part in message.parts
                   if isinstance(part, ToolReturnPart)]
        if not returns:
            yield {index: DeltaToolCall(name, "{}", tool_call_id=f"call_{index}")
                   for index, name in enumerate(["probe", "probe", "probe", "pending"])}
            return
        prompts = [part.content for message in messages for part in message.parts
                   if isinstance(part, UserPromptPart) and isinstance(part.content, str)]
        advice = "\n".join(prompts[1:])
        assert "three" in advice and "skill" in advice
        assert ("same error" if failed else "without new progress") in advice
        assert {tool.name for tool in info.function_tools} >= {"read_skill", "alternative"}
        assert len([part for part in returns if part.tool_name == "probe"]) == 3
        assert len([part for part in returns if part.tool_name == "pending"]) == 1
        if decision == "report":
            yield "The same error occurred three times; work remains blocked." if failed else "Repeated reads did not advance the work."
        elif returns[-1].tool_name == "pending":
            yield {0: DeltaToolCall("read_skill", "{}", tool_call_id="skill")}
        elif returns[-1].tool_name == "read_skill":
            yield {0: DeltaToolCall("alternative", "{}", tool_call_id="alternative")}
        else:
            yield "Work completed after rereading the skill."

    if transport == "mcp":
        server = FastMCP("repetition-guidance")
        for tool in [probe, pending, read_skill, alternative]:
            server.tool()(tool)
        toolset = MCPToolset(ExecutionEvidenceClient(server))
    else:
        toolset = FunctionToolset([probe, pending, read_skill, alternative])
    save = AsyncMock()
    checkpoint = HarnessRunCheckpoint(_request(save))
    monkeypatch.setattr(runtime, "build_model_for_llm", AsyncMock(return_value=_CountingFunctionModel(stream_function=model)))
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)
    agent = Agent(
        cast(Any, SimpleNamespace()), mcp_servers=[toolset],
        checkpoint=checkpoint if durable else None, real_time=not durable,
        reasoning_effort="low",
    )
    await agent.init()

    messages = [message async for message in agent.run("Complete the work")]

    assert agent.error == ""
    assert calls == ["probe", "probe", "probe", "pending"] + (
        ["read_skill", "alternative"] if decision == "adapt" else []
    )
    assert messages[-1].success is True
    assert len([message for message in messages if message.tool_name == "no_progress_guard"]) == 1
    assert agent.budget_exhausted is False
    # No completed operation is left pending or lost from the durable journal.
    if durable:
        assert len(checkpoint.effects) == len(calls)
        assert all(effect["status"] in {"completed", "error_reported"} for effect in checkpoint.effects)


def test_trace_tool_result_keeps_only_bounded_outcome_fields() -> None:
    result = runtime._trace_tool_result(  # pyright: ignore[reportPrivateUsage]
        {
            "status": "completed",
            "exit_code": 0,
            "uri": "console://work/site/index.html",
            "stdout": "must not be persisted in the compact trace",
        }
    )

    assert result == {
        "status": "completed",
        "exit_code": 0,
        "uri": "console://work/site/index.html",
    }


def test_trace_tool_result_accepts_json_and_rejects_unstructured_text() -> None:
    assert runtime._trace_tool_result(  # pyright: ignore[reportPrivateUsage]
        '{"status":"failed","exit_code":1}'
    ) == {"status": "failed", "exit_code": 1}
    assert (
        runtime._trace_tool_result("command completed")  # pyright: ignore[reportPrivateUsage]
        is None
    )


def test_reported_error_stays_visible_as_failure_without_an_automatic_retry_limit():
    from pydantic_ai import FunctionToolResultEvent
    from pydantic_ai.messages import ToolReturnPart
    from app.harness.checkpoint import TOOL_ERROR_SCHEMA

    event = FunctionToolResultEvent(ToolReturnPart(
        tool_name="file_copy", tool_call_id="copy",
        content={"schema": TOOL_ERROR_SCHEMA, "status": "error", "outcome": "unknown",
                 "error": "Source unavailable", "instruction": "Verify the current state"},
    ))
    message = runtime._function_to_message(event, None)
    assert message.success is False
    assert message.tool_retry_limit is None
    assert message.tool_result == {"status": "error", "outcome": "unknown"}
    assert "Source unavailable" in message.content


def test_repeated_tool_errors_remain_available_for_the_agent_to_decide() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    failure = AIMessage(
        type="tool",
        tool_name="skill_galaris_read_file",
        tool_arguments={"path": "messenger.md"},
        content="Unable to read resource 'messenger.md'",
        success=False,
    )

    assert [runtime._observe_tool_result(state, failure) for _ in range(6)] == [
        False, False, True, False, False, True,
    ]


def test_tool_error_resets_the_successful_no_progress_streak() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    failure = AIMessage(type="tool", tool_name="tool", content="failed", success=False)
    success = AIMessage(type="tool", tool_name="tool", content="ok", success=True)

    runtime._observe_tool_result(state, failure)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_tool_result(state, failure)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_tool_result(state, success)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_tool_result(state, failure)  # pyright: ignore[reportPrivateUsage]

    assert state.repeated_tool_count == 1


def test_new_results_beyond_the_trace_preview_count_as_progress() -> None:
    state = runtime._StreamState()
    message = AIMessage(type="tool", tool_name="file_read", content="Same trace preview")
    for index in range(4):
        assert runtime._observe_tool_result(state, message, "x" * 600 + str(index)) is False


def test_repeated_identical_successful_tool_call_advises_on_third_result() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    success = AIMessage(
        type="tool",
        tool_name="file_write",
        tool_arguments={"path": "final.html", "content": "placeholder"},
        content="No modification: final.html already contains this text.",
        success=True,
    )

    runtime._observe_tool_result(state, success)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_tool_result(state, success)  # pyright: ignore[reportPrivateUsage]
    assert runtime._observe_tool_result(state, success) is True  # pyright: ignore[reportPrivateUsage]


def test_file_create_ignores_generated_content_for_no_progress_signature() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    for index in range(2):
        runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
            state,
            AIMessage(
                type="tool",
                tool_name="file_create",
                tool_arguments={
                    "title": "Draft",
                    "role": "primary_working_document",
                    "content": f"variant {index}",
                },
                content=f'{{"document_id":"{index}","state":"reused"}}',
                success=True,
            ),
        )
    assert runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
        state,
        AIMessage(
            type="tool",
            tool_name="file_create",
            tool_arguments={
                "title": "Draft",
                "role": "primary_working_document",
                "content": "variant 3",
            },
            content='{"document_id":"same","state":"reused"}',
            success=True,
        ),
    ) is True


def test_repeated_append_advises_even_when_reported_size_changes() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    for size in (100, 200):
        runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
            state,
            AIMessage(
                type="tool",
                tool_name="file_append",
                tool_arguments={"uri": "document://doc-1", "content": "same section"},
                content=f'{{"state":"appended","size_bytes":{size}}}',
                success=True,
            ),
        )
    assert runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
        state,
        AIMessage(
            type="tool",
            tool_name="file_append",
            tool_arguments={"uri": "document://doc-1", "content": "same section"},
            content='{"state":"appended","size_bytes":300}',
            success=True,
        ),
    ) is True


def test_repeated_realtime_text_is_reset_by_tool_result() -> None:
    state = runtime._StreamState(  # pyright: ignore[reportPrivateUsage]
        observe_text_no_progress=True
    )
    line = "Je vais lire le document de travail pour voir où cela en est.\n"

    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
        state,
        AIMessage(type="tool", tool_name="file_list", content="[]", success=True),
    )
    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]

    # Would raise if the two pre-tool repetitions still counted against the window.


def test_repeated_realtime_text_is_reset_by_failed_tool_result() -> None:
    state = runtime._StreamState(  # pyright: ignore[reportPrivateUsage]
        observe_text_no_progress=True
    )
    line = "Je vais lire le document de travail pour voir où cela en est.\n"

    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
        state,
        AIMessage(type="tool", tool_name="file_list", content="permission denied", success=False),
    )
    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, line)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("tool_name", ["file_write", "file_edit"])
def test_file_rewrite_ignores_generated_content_for_no_progress_signature(
    tool_name: str,
) -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    for index in range(2):
        runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
            state,
            AIMessage(
                type="tool",
                tool_name=tool_name,
                tool_arguments={
                    "uri": "console://work/www-lecluse-net/src/pages/index.astro",
                    "content": f"variant {index}",
                },
                content="written",
                success=True,
            ),
        )
    assert runtime._observe_tool_result(  # pyright: ignore[reportPrivateUsage]
        state,
        AIMessage(
            type="tool",
            tool_name=tool_name,
            tool_arguments={
                "uri": "console://work/www-lecluse-net/src/pages/index.astro",
                "content": "variant 3",
            },
            content="written",
            success=True,
        ),
    ) is True


def test_repeated_realtime_text_stops_on_third_meaningful_line() -> None:
    state = runtime._StreamState(  # pyright: ignore[reportPrivateUsage]
        observe_text_no_progress=True
    )
    first = "Je vais lire le document de travail pour voir où cela en est.\n"
    second = "Je vérifie ensuite les éléments déjà produits avant de continuer.\n"

    runtime._observe_text_progress(state, first)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, second)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, first)  # pyright: ignore[reportPrivateUsage]
    runtime._observe_text_progress(state, second)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(runtime.RepeatedTextNoProgressError, match="repeated three times"):
        runtime._observe_text_progress(  # pyright: ignore[reportPrivateUsage]
            state,
            first,
        )


def test_text_loop_guard_is_disabled_for_background_execution() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    repeated = "Je vais lire le document de travail pour voir où cela en est.\n"

    for _index in range(10):
        runtime._observe_text_progress(  # pyright: ignore[reportPrivateUsage]
            state,
            repeated,
        )


@pytest.mark.asyncio
async def test_length_limited_response_is_not_emitted_as_success() -> None:
    response = ModelResponse(
        parts=[TextPart(content="Let me try again forever")],
        finish_reason="length",
    )
    result = SimpleNamespace(new_messages=lambda: [response])

    async def events() -> AsyncIterator[Any]:
        yield AgentRunResultEvent(result=cast(Any, result))

    agent = Agent(cast(Any, SimpleNamespace()), language="en")
    stream = agent._emit_stream_messages(  # pyright: ignore[reportPrivateUsage]
        events(),
        runtime._StreamState(),  # pyright: ignore[reportPrivateUsage]
        None,
    )

    with pytest.raises(runtime.IncompleteModelResponseError, match="finish_reason=length"):
        _ = [message async for message in stream]


@pytest.mark.asyncio
async def test_stream_records_the_authoritative_terminal_output_after_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(output="Final answer", new_messages=lambda: [])

    async def events() -> AsyncIterator[Any]:
        yield PartStartEvent(index=0, part=TextPart(content="Inspecting first."))
        yield AgentRunResultEvent(result=cast(Any, result))

    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)
    agent = Agent(cast(Any, SimpleNamespace()), language="en")
    messages = [
        message
        async for message in agent._emit_stream_messages(  # pyright: ignore[reportPrivateUsage]
            events(),
            runtime._StreamState(),  # pyright: ignore[reportPrivateUsage]
            None,
        )
    ]

    assert [message.content for message in messages] == ["Inspecting first.", ""]
    assert agent.terminal_output == "Final answer"


@pytest.mark.asyncio
async def test_stream_removes_split_history_metadata_before_creating_ai_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_answer = (
        "[2026-08-24T22:23+02:00 | Lyra d'Exemple] "
        "Ohhh mon Nicolas..."
    )
    result = SimpleNamespace(output=raw_answer, new_messages=lambda: [])

    async def events() -> AsyncIterator[Any]:
        yield PartStartEvent(
            index=0,
            part=TextPart(content="[2026-08-24T22:23+"),
        )
        yield PartDeltaEvent(
            index=0,
            delta=TextPartDelta(content_delta="02:00 | Lyra d'Exemple] "),
        )
        yield PartDeltaEvent(
            index=0,
            delta=TextPartDelta(content_delta="Ohhh mon Nicolas..."),
        )
        yield AgentRunResultEvent(result=cast(Any, result))

    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)
    agent = Agent(cast(Any, SimpleNamespace()), language="fr")
    messages = [
        message
        async for message in agent._emit_stream_messages(  # pyright: ignore[reportPrivateUsage]
            events(),
            runtime._StreamState(),  # pyright: ignore[reportPrivateUsage]
            None,
        )
    ]

    assert [message.content for message in messages] == ["Ohhh mon Nicolas...", ""]
    assert [message.content for message in agent.messages] == [
        "Ohhh mon Nicolas...",
        "",
    ]
    assert agent.terminal_output == "Ohhh mon Nicolas..."
    assert all("Lyra d'Exemple" not in message.content for message in agent.messages)


@pytest.mark.asyncio
async def test_agent_run_turns_length_limited_stream_into_terminal_failure() -> None:
    response = ModelResponse(
        parts=[TextPart(content="unfinished answer")],
        finish_reason="length",
    )
    result = SimpleNamespace(new_messages=lambda: [response])

    class StubPydanticAgent:
        @contextmanager
        def override(self, **_kwargs: Any) -> Iterator[None]:
            yield

        @contextmanager
        def parallel_tool_call_execution_mode(self, _mode: str) -> Iterator[None]:
            yield

        @asynccontextmanager
        async def run_stream_events(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
            async def events() -> AsyncIterator[Any]:
                yield PartStartEvent(index=0, part=TextPart(content="unfinished answer"))
                yield AgentRunResultEvent(result=cast(Any, result))

            yield events()

    agent = Agent(cast(Any, SimpleNamespace()), language="en")
    agent._agent = cast(Any, StubPydanticAgent())  # pyright: ignore[reportPrivateUsage]

    messages = [message async for message in agent.run("do the work")]

    assert messages[0].content == "unfinished answer"
    assert messages[-1].success is False
    assert "finish_reason=length" in messages[-1].content
    assert "finish_reason=length" in agent.error
