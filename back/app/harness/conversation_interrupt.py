"""Interrupt text generation between tool effects when a newer post is admitted."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import Hooks, ValidatedToolArgs
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition


class ConversationInterruption:
    """Poll durable admission only while generating; never cancel a running tool."""

    def __init__(
        self, pending: Callable[[], Awaitable[bool]], *, poll_seconds: float = 0.25,
    ) -> None:
        self.pending = pending
        self.poll_seconds = poll_seconds
        self.requested = False
        self.cancel: Callable[[], None] | None = None
        self._monitor: asyncio.Task[None] | None = None
        # These control hooks must be eager: deferring them would allow an obsolete run.
        self.hooks = Hooks(
            before_model_request=self._before_model,
            after_model_request=self._after_model,
            before_tool_execute=self._before_tool,
        )

    async def _check(self) -> bool:
        if self.requested or await self.pending():
            self.requested = True
            return True
        return False

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            if await self._check():
                if self.cancel is not None:
                    self.cancel()
                return

    async def _before_model(
        self, ctx: RunContext[Any], request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        await self.close()
        if await self._check():
            raise asyncio.CancelledError
        self._monitor = asyncio.create_task(self._watch())
        return request_context

    async def _after_model(
        self, ctx: RunContext[Any], *, request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        await self.close()
        return response

    async def _before_tool(
        self, ctx: RunContext[Any], *, call: ToolCallPart,
        tool_def: ToolDefinition, args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        # Conversation tools execute sequentially. At this boundary no effect has
        # started for this call; completed tool results remain in the runtime trace.
        await self.close()
        if await self._check():
            raise asyncio.CancelledError
        return args

    async def close(self) -> None:
        monitor, self._monitor = self._monitor, None
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
