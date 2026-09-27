"""Absolute per-provider-call deadline, independent of Task activity and retries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from core.params import runtime_settings


class LLMCallTimeoutError(TimeoutError):
    """The provider did not finish one call within its allotted wall-clock time."""


class LLMCallDeadline:
    def __init__(self, started_at: datetime | None = None) -> None:
        self.seconds = runtime_settings.LLM_CALL_TIMEOUT_MINUTES * 60.0
        elapsed = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds()) if started_at else 0.0
        self.expires_at = asyncio.get_running_loop().time() + max(0.0, self.seconds - elapsed)

    @asynccontextmanager
    async def enforce(self) -> AsyncGenerator[None]:
        error = f"LLM call exceeded its absolute limit of {self.seconds:g} seconds without a terminal result."
        if asyncio.get_running_loop().time() >= self.expires_at:
            raise LLMCallTimeoutError(error)
        timer = asyncio.timeout_at(self.expires_at)
        try:
            async with timer:
                yield
        except TimeoutError as exc:
            if not timer.expired():
                raise
            raise LLMCallTimeoutError(error) from exc

    async def iterate[T](
        self, stream: AsyncIterator[T], *, completed: Callable[[], bool] | None = None,
    ) -> AsyncIterator[T]:
        while True:
            try:
                async with self.enforce():
                    item = await anext(stream)
            except StopAsyncIteration:
                return
            except LLMCallTimeoutError:
                # A terminal provider event wins over a stalled transport trailer.
                if completed is not None and completed():
                    return
                raise
            yield item
