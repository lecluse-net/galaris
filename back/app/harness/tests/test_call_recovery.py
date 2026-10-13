"""Manual recovery interrupts model generation while retaining completed effects."""
import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ThinkingPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import DeltaThinkingPart, DeltaToolCall
from pydantic_ai.toolsets import FunctionToolset

from app.harness import runtime
from app.harness.checkpoint import HarnessRunCheckpoint
from app.harness.runtime import Agent
from app.harness.tests.test_runtime_cancellation import _CountingFunctionModel, _request


@pytest.mark.asyncio
@pytest.mark.parametrize("generation", ["silent", "thinking", "arguments"])
async def test_manual_call_recovery_closes_provider_preserves_effects_and_discards_unexecuted_arguments(monkeypatch, generation):
    stalled = asyncio.Event()
    closed = []
    writes = []
    calls = 0

    def save_report() -> str:
        writes.append("saved")
        return "Synthetic report saved"

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {0: DeltaToolCall("save_report", "{}", tool_call_id="save")}
        elif calls == 2:
            try:
                if generation == "thinking":
                    yield {0: DeltaThinkingPart(content="A legitimate long reflection begins.")}
                elif generation == "arguments":
                    yield {0: DeltaToolCall("save_report", '{"unfinished":', tool_call_id="unexecuted")}
                stalled.set()
                await asyncio.Future()
            finally:
                closed.append(2)
        else:
            assert closed == [2]  # The old stream must close before another opens.
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            assert [p.content for p in returns] == ["Synthetic report saved"]
            assert not any(isinstance(p, ThinkingPart) for m in messages for p in m.parts)
            assert not any(isinstance(p, ToolCallPart) and p.tool_call_id == "unexecuted" for m in messages for p in m.parts)
            assert any(isinstance(p, UserPromptPart) and "USER REQUEST" in str(p.content) for m in messages for p in m.parts)
            assert {tool.name for tool in info.function_tools} == {"save_report"}
            yield "Verified the saved report after changing approach."

    monkeypatch.setattr(runtime, "build_model_for_llm", AsyncMock(return_value=_CountingFunctionModel(stream_function=model)))
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_: 0.0)
    checkpoint = HarnessRunCheckpoint(_request(AsyncMock()))
    agent = Agent(cast(Any, SimpleNamespace()), mcp_servers=[FunctionToolset([save_report])], checkpoint=checkpoint)
    await agent.init()

    async def collect():
        return [message async for message in agent.run("Save and verify the report")]

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(stalled.wait(), 3)
        assert agent.request_call_recovery() is True
        assert agent.request_call_recovery() is True  # Duplicate request, single interruption.
        messages = await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert writes == ["saved"]
    assert calls == 3
    assert agent.manual_call_recoveries == 1
    assert agent.reasoning_recoveries == 0
    assert agent.error == ""
    assert messages[-1].success is True
    assert len([m for m in messages if m.tool_name == "call_recovery"]) == 1
    assert len(checkpoint.effects) == 1
    assert checkpoint.effects[0]["status"] == "completed"
    assert agent.request_call_recovery() is False


@pytest.mark.asyncio
async def test_manual_recovery_refuses_running_tool_and_external_cancellation_still_wins(monkeypatch):
    tool_started = asyncio.Event()
    finish_tool = asyncio.Event()
    model_stalled = asyncio.Event()
    calls = 0

    async def save_report() -> str:
        tool_started.set()
        await finish_tool.wait()
        return "Synthetic effect completed"

    async def model(_messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {0: DeltaToolCall("save_report", "{}", tool_call_id="save")}
        else:
            model_stalled.set()
            await asyncio.Future()

    monkeypatch.setattr(runtime, "build_model_for_llm", AsyncMock(return_value=_CountingFunctionModel(stream_function=model)))
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_: 0.0)
    checkpoint = HarnessRunCheckpoint(_request(AsyncMock()))
    agent = Agent(cast(Any, SimpleNamespace()), mcp_servers=[FunctionToolset([save_report])], checkpoint=checkpoint)
    await agent.init()

    async def collect():
        return [message async for message in agent.run("Save the report")]

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(tool_started.wait(), 3)
        assert agent.request_call_recovery() is False
        assert not task.done()
        finish_tool.set()
        await asyncio.wait_for(model_stalled.wait(), 3)
        assert agent.request_call_recovery() is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert calls == 2
    assert checkpoint.effects[0]["status"] == "completed"
    assert agent.manual_call_recoveries == 0


@pytest.mark.asyncio
async def test_manual_recovery_does_not_reset_the_original_request_budget(monkeypatch):
    stalled = asyncio.Event()
    calls = 0

    async def model(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            stalled.set()
            await asyncio.Future()
        else:
            assert not info.function_tools
            yield "BLOCKED: original request budget exhausted."

    monkeypatch.setattr(runtime.runtime_settings, "TASK_AGENT_MAX_REQUESTS", 1)
    monkeypatch.setattr(runtime, "build_model_for_llm", AsyncMock(return_value=_CountingFunctionModel(stream_function=model)))
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_: 0.0)
    agent = Agent(cast(Any, SimpleNamespace()))
    await agent.init()

    async def collect():
        return [message async for message in agent.run("Verify the report")]

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(stalled.wait(), 3)
        assert agent.request_call_recovery()
        messages = await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert calls == 2  # One request, then the existing tool-free exhaustion report.
    assert agent.budget_exhausted
    assert messages[-1].success
