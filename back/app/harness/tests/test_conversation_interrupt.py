from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from pydantic_ai import Agent, CancellationToken
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app.harness.conversation_interrupt import ConversationInterruption


@pytest.mark.asyncio
async def test_superseded_preparation_is_control_flow_through_a_real_tool_run():
    from app.conversation import ConversationSuperseded

    async def stream(_messages, _info):
        yield {0: DeltaToolCall(name="submit", json_args="{}", tool_call_id="submit-1")}
    agent = Agent(FunctionModel(stream_function=stream))
    @agent.tool_plain
    async def submit() -> str:
        raise ConversationSuperseded("new input")
    with pytest.raises(ConversationSuperseded):
        async with agent.run_stream_events("Prepare report") as events:
            async for _ in events:
                pass


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_text", "during_text", "during_tool"])
async def test_new_post_interrupts_generation_but_finishes_started_tool(phase: str) -> None:
    during_tool = phase == "during_tool"
    pending = asyncio.Event()
    model_started = asyncio.Event()
    tool_started = asyncio.Event()
    release_tool = asyncio.Event()
    effects: list[str] = []
    model_calls = 0

    async def newer_input() -> bool:
        return pending.is_set()

    token = CancellationToken()
    interruption = ConversationInterruption(newer_input, poll_seconds=0.01)
    interruption.cancel = token.cancel

    async def model_stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal model_calls
        model_calls += 1
        model_started.set()
        if during_tool:
            yield {0: DeltaToolCall(name="save", json_args="{}", tool_call_id="save-1")}
        else:
            if phase == "during_text":
                yield "Ancien brouillon"
            await asyncio.Event().wait()

    agent = Agent(FunctionModel(stream_function=model_stream), capabilities=[interruption.hooks])

    @agent.tool_plain
    async def save() -> str:
        tool_started.set()
        await release_tool.wait()
        effects.append("saved")
        return "saved"

    async def consume() -> None:
        try:
            async with agent.run_stream_events("Rédige", cancellation_token=token) as stream:
                async for _event in stream:
                    pass
        finally:
            await interruption.close()

    run = asyncio.create_task(consume())
    try:
        await asyncio.wait_for((tool_started if during_tool else model_started).wait(), 2)
        pending.set()
        if during_tool:
            # The tool must be allowed to finish; no second model request may start.
            await asyncio.sleep(0.04)
            assert not run.done()
            release_tool.set()
        with pytest.raises((RunCancelled, asyncio.CancelledError)):
            await asyncio.wait_for(run, 2)
        assert interruption.requested
        assert effects == (["saved"] if during_tool else [])
        assert model_calls == 1
    finally:
        release_tool.set()
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await interruption.close()


@pytest.mark.asyncio
async def test_uninterrupted_response_finishes_and_stops_observing_new_posts() -> None:
    pending = asyncio.Event()

    async def newer_input() -> bool:
        return pending.is_set()

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        yield "Réponse complète"

    token = CancellationToken()
    interruption = ConversationInterruption(newer_input, poll_seconds=0.01)
    interruption.cancel = token.cancel
    agent = Agent(FunctionModel(stream_function=stream), capabilities=[interruption.hooks])
    try:
        async with agent.run_stream("Bonjour", cancellation_token=token) as result:
            assert await result.get_output() == "Réponse complète"
        pending.set()
        await asyncio.sleep(0.04)
        assert not interruption.requested
        assert not token.cancelled
    finally:
        await interruption.close()
