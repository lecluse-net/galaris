from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import CancellationToken
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from app.agent.contracts import (
    AgentRunCheckpoint,
    AgentRunControl,
    AgentRunRequest,
    AgentSnapshot,
    ResolvedModel,
)
from app.harness.checkpoint import HarnessRunCheckpoint
from app.harness.runtime import Agent
from app.llm import LLM


def _request(
    save_checkpoint: AsyncMock,
    *,
    resume_checkpoint: AgentRunCheckpoint | None = None,
) -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Create the report",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        resume_checkpoint=resume_checkpoint,
        control=AgentRunControl(save_checkpoint=save_checkpoint),
    )


class _CancelledPydanticAgent:
    def __init__(self, history: list[ModelMessage], *, external: bool) -> None:
        self.history = history
        self.external = external
        self.cancellation_token: CancellationToken | None = None

    @contextmanager
    def parallel_tool_call_execution_mode(self, _mode: str) -> Iterator[None]:
        yield

    def run_stream_events(self, _prompt: Any, **kwargs: Any) -> Any:
        self.cancellation_token = cast(CancellationToken, kwargs["cancellation_token"])

        @asynccontextmanager
        async def stream() -> AsyncIterator[AsyncIterator[Any]]:
            async def events() -> AsyncIterator[Any]:
                if False:
                    yield None
                cancelled = RunCancelled("paused", messages=self.history)
                if self.external:
                    raise asyncio.CancelledError from cancelled
                raise cancelled

            yield events()

        return stream()


class _CountingFunctionModel(FunctionModel):
    async def count_tokens(
        self,
        _messages: list[ModelMessage],
        _model_settings: ModelSettings | None,
        _model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        return RequestUsage(input_tokens=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_cancellation_is_checkpointed_for_resume(external: bool) -> None:
    save = AsyncMock()
    checkpoint = HarnessRunCheckpoint(_request(save))
    history: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="Create the report")]),
        ModelResponse(
            parts=[TextPart(content="Partial answer")],
            state="interrupted",
        ),
    ]
    stub = _CancelledPydanticAgent(history, external=external)
    agent = Agent(cast(LLM, SimpleNamespace()), checkpoint=checkpoint)
    agent._agent = cast(Any, stub)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(asyncio.CancelledError):
        _ = [message async for message in agent.run("Create the report")]

    assert isinstance(stub.cancellation_token, CancellationToken)
    saved = save.await_args.args[0]
    assert saved.status == "interrupted"
    restored = HarnessRunCheckpoint(
        _request(AsyncMock(), resume_checkpoint=saved)
    ).restored_messages()
    assert cast(ModelResponse, restored[-1]).state == "interrupted"


@pytest.mark.asyncio
async def test_request_cancel_uses_pydantic_cancellation_token() -> None:
    save = AsyncMock()
    checkpoint = HarnessRunCheckpoint(_request(save))
    model_started = asyncio.Event()

    async def model_stream(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str]:
        model_started.set()
        await asyncio.Event().wait()
        if False:
            yield "The cancelled model call must not complete."

    agent = Agent(cast(LLM, SimpleNamespace()), checkpoint=checkpoint)
    agent._agent = cast(  # pyright: ignore[reportPrivateUsage]
        Any,
        PydanticAgent(_CountingFunctionModel(stream_function=model_stream)),
    )

    async def consume() -> list[object]:
        return [message async for message in agent.run("Create the report")]

    execution = asyncio.create_task(consume())
    await asyncio.wait_for(model_started.wait(), timeout=1)
    agent.request_cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, timeout=1)

    saved = save.await_args.args[0]
    assert saved.status == "interrupted"
    restored = HarnessRunCheckpoint(
        _request(AsyncMock(), resume_checkpoint=saved)
    ).restored_messages()
    response = cast(ModelResponse, restored[-1])
    assert response.state == "interrupted"
