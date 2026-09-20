from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.capabilities import ToolSearch
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.tools import ToolDefinition

from app.harness import runtime
from app.harness.runtime import Agent
from app.llm import LLM
from app.tools.tool_search_service import ToolSearchHit, ToolSearchResult


def _llm() -> LLM:
    return cast(LLM, SimpleNamespace())


@pytest.mark.asyncio
async def test_runtime_registers_tool_search_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakePydanticAgent:
        def __init__(self, _model: object, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        runtime,
        "build_model_for_llm",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(runtime, "PydanticAgent", FakePydanticAgent)
    agent = Agent(_llm(), agent_id=7)

    await agent.init()

    capabilities = cast(list[Any], captured["capabilities"])
    assert any(isinstance(capability, ToolSearch) for capability in capabilities)


@pytest.mark.asyncio
async def test_runtime_hybrid_search_returns_only_corpus_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(_llm(), agent_id=7)
    tools = [
        ToolDefinition(
            name="messenger_room_history",
            description="Read room messages",
            parameters_json_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="weather_forecast",
            description="Read weather",
            parameters_json_schema={"type": "object", "properties": {}},
        ),
    ]

    async def fake_search(catalog: Any, **_kwargs: Any) -> ToolSearchResult:
        assert catalog.names == {
            "messenger_room_history",
            "weather_forecast",
        }
        return ToolSearchResult(
            query="room",
            catalog_version=catalog.version,
            mode="hybrid",
            hits=(ToolSearchHit(entry=catalog.entries[0], score=1.0),),
        )

    monkeypatch.setattr(runtime, "search_catalog_in_isolated_session", fake_search)

    names = await agent._search_deferred_tools(  # pyright: ignore[reportPrivateUsage]
        None,
        ["room messages"],
        tools,
    )

    assert names == ["messenger_room_history"]


def test_parallel_tool_trace_is_correlated_by_call_id() -> None:
    state = runtime._StreamState()  # pyright: ignore[reportPrivateUsage]
    first = cast(
        FunctionToolCallEvent,
        SimpleNamespace(part=SimpleNamespace(tool_call_id="call-a")),
    )
    second = cast(
        FunctionToolCallEvent,
        SimpleNamespace(part=SimpleNamespace(tool_call_id="call-b")),
    )
    second_result = cast(
        FunctionToolResultEvent,
        SimpleNamespace(part=SimpleNamespace(tool_call_id="call-b")),
    )
    first_result = cast(
        FunctionToolResultEvent,
        SimpleNamespace(part=SimpleNamespace(tool_call_id="call-a")),
    )

    runtime._remember_tool_call(state, first)  # pyright: ignore[reportPrivateUsage]
    runtime._remember_tool_call(state, second)  # pyright: ignore[reportPrivateUsage]

    assert runtime._take_tool_call(  # pyright: ignore[reportPrivateUsage]
        state, second_result
    ) is second
    assert runtime._take_tool_call(  # pyright: ignore[reportPrivateUsage]
        state, first_result
    ) is first
    assert state.tool_call_events == {}
