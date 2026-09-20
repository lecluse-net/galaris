"""Wrap-up behavior when a run exhausts its usage limits."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator, cast

import pytest
from pydantic_ai import AgentRunResultEvent, PartStartEvent
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from app.harness import runtime
from app.harness.runtime import Agent
from app.llm import LLM


def _billed_llm() -> LLM:
    return cast(
        LLM,
        SimpleNamespace(
            provider=None,
            cost_per_input_token=1e-6,
            cost_per_output_token=2e-6,
            cost_per_cached_input_token=None,
        ),
    )


def _captured_history() -> list[ModelMessage]:
    """History of an interrupted run whose last tool call never executed."""
    return [
        ModelRequest(parts=[UserPromptPart(content="Fabrique le PDF")]),
        ModelResponse(
            parts=[ToolCallPart("console_exec", {"command": "make pdf"}, "call-1")],
            usage=RequestUsage(input_tokens=1_000, output_tokens=100),
        ),
    ]


def test_aborted_run_keeps_subscription_usage_with_zero_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)
    agent = Agent(_billed_llm(), language="en")
    captured = [
        ModelResponse(
            parts=[ToolCallPart("file_write", {"path": "audio.mp3"}, "call-1")],
            usage=RequestUsage(input_tokens=120, output_tokens=8),
        ),
        ModelResponse(
            parts=[],
            usage=RequestUsage(input_tokens=80, output_tokens=0),
        ),
    ]

    usage = agent._run_usage_from_history(captured)  # pyright: ignore[reportPrivateUsage]

    assert usage.input_tokens == 200
    assert usage.output_tokens == 8
    assert usage.requests == 2
    assert usage.cost == 0.0


def test_empty_terminal_response_is_classified_separately() -> None:
    assert runtime._empty_model_output_failure(  # pyright: ignore[reportPrivateUsage]
        UnexpectedModelBehavior("Exceeded maximum output retries (2)"),
        [ModelResponse(parts=[])],
    )
    assert not runtime._empty_model_output_failure(  # pyright: ignore[reportPrivateUsage]
        UnexpectedModelBehavior("output validator failed"),
        [ModelResponse(parts=[TextPart("invalid but non-empty")])],
    )


class _StubPydanticAgent:
    """Fake Pydantic AI agent: the first run fails, the wrap-up run answers."""

    def __init__(self, first_error: Exception, wrapup_text: str) -> None:
        self.first_error = first_error
        self.wrapup_text = wrapup_text
        self.calls: list[SimpleNamespace] = []
        self.execution_modes: list[str] = []
        self.overrides: list[dict[str, Any]] = []

    @contextmanager
    def override(self, **kwargs: Any) -> Iterator[None]:
        self.overrides.append(kwargs)
        yield

    @contextmanager
    def parallel_tool_call_execution_mode(self, mode: str) -> Iterator[None]:
        self.execution_modes.append(mode)
        yield

    def run_stream_events(self, user_prompt: Any, **kwargs: Any) -> Any:
        self.calls.append(SimpleNamespace(prompt=user_prompt, **kwargs))
        first_call = len(self.calls) == 1

        @asynccontextmanager
        async def _ctx() -> Any:
            async def _events() -> AsyncIterator[Any]:
                if first_call:
                    raise self.first_error
                yield PartStartEvent(index=0, part=TextPart(content=self.wrapup_text))
                yield AgentRunResultEvent(
                    result=SimpleNamespace(
                        output=self.wrapup_text,
                        usage=RequestUsage(input_tokens=10, output_tokens=5),
                    )
                )

            yield _events()

        return _ctx()


def _agent_with_stub(
    stub: _StubPydanticAgent,
) -> Agent:
    agent = Agent(
        _billed_llm(),
        language="en",
    )
    agent._agent = cast(Any, stub)  # pyright: ignore[reportPrivateUsage]
    return agent


@pytest.fixture
def fake_capture(monkeypatch: pytest.MonkeyPatch) -> list[ModelMessage]:
    captured = _captured_history()

    @contextmanager
    def _capture() -> Iterator[list[ModelMessage]]:
        yield captured

    monkeypatch.setattr(runtime, "capture_run_messages", _capture)
    return captured


@pytest.mark.asyncio
async def test_usage_limit_triggers_wrapup_and_delivers_partial_result(
    fake_capture: list[ModelMessage],
) -> None:
    stub = _StubPydanticAgent(
        UsageLimitExceeded("Exceeded the request_limit"),
        "Bilan final : PDF produit dans outputs/.",
    )
    agent = _agent_with_stub(stub)

    messages = [message async for message in agent.run("Fabrique le PDF")]

    assert agent.budget_exhausted is True
    assert agent.error == ""

    notice = messages[0]
    assert notice.type == "tool"
    assert notice.tool_name == "budget_guard"
    assert "Run budget exhausted" in notice.content
    assert notice.cost > 0.0  # The aborted run's consumption stays accounted.

    final_texts = [m for m in messages if m.type == "text" and m.content]
    assert final_texts
    assert final_texts[0].success is True
    assert "Bilan final" in final_texts[0].content

    # The wrap-up run replays the history and closes the dangling call.
    assert len(stub.calls) == 2
    assert stub.execution_modes == ["sequential", "sequential"]
    assert stub.overrides == [{"tools": [], "toolsets": []}]
    wrapup_call = stub.calls[1]
    assert "budget" in str(wrapup_call.prompt).lower()
    history = cast(list[ModelMessage], wrapup_call.message_history)
    closing = history[-1]
    assert isinstance(closing, ModelRequest)
    closing_part = closing.parts[0]
    assert isinstance(closing_part, ToolReturnPart)
    assert closing_part.tool_call_id == "call-1"
    limits = wrapup_call.usage_limits
    assert limits.request_limit == 1


@pytest.mark.asyncio
async def test_non_limit_failure_keeps_error_and_accounts_cost(
    fake_capture: list[ModelMessage],
) -> None:
    stub = _StubPydanticAgent(RuntimeError("provider unreachable"), "unused")
    agent = _agent_with_stub(stub)

    messages = [message async for message in agent.run("Fabrique le PDF")]

    assert len(stub.calls) == 1  # No wrap-up on unrelated failures.
    assert stub.execution_modes == ["sequential"]
    assert agent.budget_exhausted is False
    assert "provider unreachable" in agent.error
    failure = messages[-1]
    assert failure.success is False
    assert failure.cost > 0.0


def test_close_dangling_tool_calls_appends_synthetic_returns_only_when_needed() -> None:
    complete = [
        ModelResponse(parts=[ToolCallPart("console_exec", {}, "call-1")]),
        ModelRequest(parts=[ToolReturnPart("console_exec", "ok", "call-1")]),
    ]
    untouched = runtime._close_dangling_tool_calls(  # pyright: ignore[reportPrivateUsage]
        list(complete), "en"
    )
    assert untouched == complete

    dangling = [
        ModelResponse(
            parts=[
                ToolCallPart("console_exec", {}, "call-1"),
                ToolCallPart("image_read", {}, "call-2"),
            ]
        ),
        ModelRequest(parts=[ToolReturnPart("console_exec", "ok", "call-1")]),
    ]
    closed = runtime._close_dangling_tool_calls(  # pyright: ignore[reportPrivateUsage]
        list(dangling), "en"
    )
    assert len(closed) == len(dangling) + 1
    closing = closed[-1]
    assert isinstance(closing, ModelRequest)
    parts = [part for part in closing.parts if isinstance(part, ToolReturnPart)]
    assert [part.tool_call_id for part in parts] == ["call-2"]
    assert parts[0].tool_name == "image_read"
    assert "interrupted" in str(parts[0].content)
