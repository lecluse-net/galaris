from __future__ import annotations

import random
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import facade
from app.agent.contracts import (
    AIMessage,
    AgentEvent,
    AgentRunControl,
    AgentRunRequest,
    AgentSnapshot,
    ExecutionResult,
    ResolvedModel,
)
from app.agent.reasoning_guard import (
    MAX_REASONING_PATTERN_REPETITIONS,
    ReasoningDegenerationError,
    ReasoningPatternGuard,
)
from app.agent.registry import INTERNAL_HARNESS


@pytest.fixture(autouse=True)
def default_configuration(monkeypatch):
    from app.agent import HarnessExecutionPolicy
    from app.agent.harness_port import harness_selection_port
    monkeypatch.setattr(harness_selection_port, "configuration", AsyncMock(return_value=(HarnessExecutionPolicy(), 0)))


def _message(content: str) -> AIMessage:
    return AIMessage(type="tool", tool_name="thinking", content=content)


def _request(*, publish_event: AsyncMock | None = None) -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=None,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Test the reasoning guard",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        control=AgentRunControl(publish_event=publish_event),
    )


def test_reasoning_guard_allows_thirty_repetitions() -> None:
    guard = ReasoningPatternGuard()

    for _index in range(MAX_REASONING_PATTERN_REPETITIONS):
        guard.observe(_message("I am checking the same hypothesis."))


def test_reasoning_guard_stops_the_thirty_first_repetition() -> None:
    guard = ReasoningPatternGuard()

    with pytest.raises(ReasoningDegenerationError, match="more than 30"):
        for _index in range(MAX_REASONING_PATTERN_REPETITIONS + 1):
            guard.observe(_message("I am checking the same hypothesis."))


def test_reasoning_guard_detects_a_pattern_inside_one_block() -> None:
    guard = ReasoningPatternGuard()

    with pytest.raises(ReasoningDegenerationError, match="more than 30"):
        guard.observe(
            _message(
                " ".join(
                    "check again"
                    for _index in range(MAX_REASONING_PATTERN_REPETITIONS + 1)
                )
            )
        )


@pytest.mark.parametrize("snapshots", [False, True])
def test_reasoning_guard_detects_repetition_independently_of_stream_fragments(snapshots: bool) -> None:
    text = "I am checking the same hypothesis. " * 80
    rng = random.Random(19)
    guard = ReasoningPatternGuard()
    offset = 0
    with pytest.raises(ReasoningDegenerationError):
        while offset < len(text):
            end = min(len(text), offset + rng.randint(1, 11))
            guard.observe(AIMessage(
                type="tool", tool_name="thinking", stream_id="thought",
                stream_mode="snapshot" if snapshots else "delta",
                content=text[:end] if snapshots else text[offset:end],
            ))
            offset = end


@pytest.mark.parametrize("replay", [False, True])
def test_repeated_fragments_inside_one_word_are_not_repeated_reasoning(replay: bool) -> None:
    guard = ReasoningPatternGuard()
    old = AIMessage(type="text", content="Earlier reply.", stream_id="earlier", stream_mode="snapshot", stream_complete=True)
    guard.observe(old)
    for _ in range(80):
        guard.observe(AIMessage(type="text", content="a", stream_id="word"))
        if replay:
            guard.observe(old)
    guard.observe(AIMessage(type="text", content=" ", stream_id="word", stream_complete=True))


def test_reasoning_guard_does_not_count_replayed_snapshots_as_generated_prose() -> None:
    guard = ReasoningPatternGuard()
    message = AIMessage(
        type="tool", tool_name="thinking", content="Inspecting the workspace.",
        stream_id="hermes:thought", stream_mode="snapshot",
    )
    for _index in range(MAX_REASONING_PATTERN_REPETITIONS + 1):
        guard.observe(message)


def test_reasoning_guard_still_detects_repetition_in_growing_snapshots() -> None:
    guard = ReasoningPatternGuard()
    with pytest.raises(ReasoningDegenerationError):
        for index in range(1, MAX_REASONING_PATTERN_REPETITIONS + 2):
            guard.observe(AIMessage(
                type="text", content="check again " * index,
                stream_id="hermes:text", stream_mode="snapshot",
            ))


def test_real_tool_activity_resets_the_reasoning_streak() -> None:
    guard = ReasoningPatternGuard()

    for _index in range(MAX_REASONING_PATTERN_REPETITIONS):
        guard.observe(_message("I am checking the same hypothesis."))
    guard.observe(AIMessage(type="tool", tool_name="file_read", content="Loaded"))
    guard.observe(_message("I am checking the same hypothesis."))


@pytest.mark.asyncio
async def test_facade_closes_the_driver_stream_and_publishes_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False
    publish_event = AsyncMock()

    class DegenerateDriver:
        async def stream(self, _request: AgentRunRequest):
            nonlocal closed
            try:
                for _index in range(MAX_REASONING_PATTERN_REPETITIONS + 1):
                    yield AgentEvent.from_message(
                        _message("I am checking the same hypothesis.")
                    )
            finally:
                closed = True

    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: DegenerateDriver())

    emitted: list[AgentEvent] = []
    with pytest.raises(ReasoningDegenerationError, match="more than 30"):
        async for event in facade.stream(_request(publish_event=publish_event)):
            emitted.append(event)

    assert closed is True
    assert len(emitted) == MAX_REASONING_PATTERN_REPETITIONS
    published = [call.args[0] for call in publish_event.await_args_list]
    assert [event.kind for event in published] == [
        "run.started",
        *(["tool.completed"] * MAX_REASONING_PATTERN_REPETITIONS),
        "run.failed",
    ]
    failed = published[-1]
    assert failed.kind == "run.failed"
    assert failed.result is not None
    assert failed.result.success is False
    assert "ReasoningDegenerationError" in failed.result.result


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_snapshot", [False, True])
async def test_facade_keeps_stream_fragments_ephemeral(
    monkeypatch: pytest.MonkeyPatch,
    tool_snapshot: bool,
) -> None:
    publish_event = AsyncMock()

    class FragmentedDriver:
        async def stream(self, _request: AgentRunRequest):
            yield AgentEvent.from_message(
                AIMessage(
                    type="tool",
                    tool_name="thinking",
                    content="Inspection ",
                    stream_id="codex:reasoning:r1:0",
                )
            )
            yield AgentEvent.from_message(
                AIMessage(
                    type="tool",
                    tool_name="thinking",
                    content="des contrats.",
                    stream_id="codex:reasoning:r1:0",
                )
            )
            if tool_snapshot:
                yield AgentEvent.from_message(AIMessage(
                    type="tool", tool_name="file_read", content="Loaded",
                    stream_id="hermes:tool", stream_mode="snapshot",
                ))
            yield AgentEvent.from_result(
                ExecutionResult(prompt="p", result="Terminé.")
            )

    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: FragmentedDriver())

    events = [
        event
        async for event in facade.stream(_request(publish_event=publish_event))
    ]

    assert [event.kind for event in events] == ["message"] * (3 if tool_snapshot else 2) + ["result"]
    published = [call.args[0] for call in publish_event.await_args_list]
    assert [event.kind for event in published] == (
        ["run.started", "tool.completed", "run.completed"]
        if tool_snapshot else ["run.started", "run.completed"]
    )
