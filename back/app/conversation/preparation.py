"""Interrupt read-only preparation while preserving the durable round's final guard."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .contracts import ConversationTurn


class ConversationSuperseded(asyncio.CancelledError):
    """A newer admitted input superseded preparation, not an operational tool error."""


async def run_preparation[T](turn: ConversationTurn, operation: Callable[[], Awaitable[T]]) -> T:
    """Cancel only a read-only phase; callers keep effects outside this scope."""

    pending = turn.should_interrupt
    if pending is None:
        return await operation()
    if await pending():
        raise ConversationSuperseded

    async def watch() -> None:
        while True:
            await asyncio.sleep(0.25)
            if await pending():
                return

    async def invoke() -> T:
        return await operation()

    work = asyncio.create_task(invoke())
    monitor = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait({work, monitor}, return_when=asyncio.FIRST_COMPLETED)
        if monitor in done:
            # Propagate a failed guard; never continue preparation without ownership.
            await monitor
            raise ConversationSuperseded
        result = await work
        if await pending():
            raise ConversationSuperseded
        return result
    finally:
        work.cancel()
        monitor.cancel()
        # Await cleanup, including the structured adapter's durable stop request.
        await asyncio.gather(work, monitor, return_exceptions=True)
