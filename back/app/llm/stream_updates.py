"""One bounded, replaceable supervision update per physical provider stream."""

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import anyio
from loguru import logger

from . import llm_call_service


class StreamUpdates:
    """Never make provider reads wait for a database or WebSocket consumer.

    The provider iterator owns the cumulative trace. The worker materializes only
    the newest state, at most four times a second, with no queue of intermediate copies.
    A pending change is flushed even if no further provider event arrives.
    Finalization cancels and joins this worker before storing the terminal trace.
    """

    def __init__(self, call_id: UUID, snapshot: Callable[[], dict[str, Any]]) -> None:
        self.call_id = call_id
        self.snapshot = snapshot
        self._task: asyncio.Task[None] | None = None
        self._last_update = 0.0
        self._dirty = False
        self._closed = False

    def changed(self) -> None:
        if self._closed:
            return
        self._dirty = True
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._update(), name=f"llm-progress:{self.call_id}")

    async def _update(self) -> None:
        while self._dirty:
            delay = 0.25 - (time.monotonic() - self._last_update)
            if delay > 0:
                await asyncio.sleep(delay)
            self._dirty = False
            self._last_update = time.monotonic()
            try:
                await llm_call_service.update_running_call(self.call_id, **self.snapshot())
            except Exception:
                logger.exception("LLM trace partial update failed for call {}", self.call_id)

    async def close(self) -> None:
        self._closed = True
        self._dirty = False
        if self._task is not None:
            self._task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
