"""Interrupt read-only preparation while preserving the durable round's final guard."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .contracts import ConversationTurn


class ConversationSuperseded(asyncio.CancelledError):
    """A newer admitted input superseded preparation, not an operational tool error."""


class ConversationSuspended(asyncio.CancelledError):
    """The worker is stopping; keep this round available for recovery."""


async def run_preparation[T](turn: ConversationTurn, operation: Callable[[], Awaitable[T]]) -> T:
    """Cancel only a read-only phase; callers keep effects outside this scope."""

    pending = turn.should_interrupt
    suspend = turn.should_suspend
    if pending is None and suspend is None:
        return await operation()

    async def check() -> bool:
        if suspend is not None and suspend():
            raise ConversationSuspended
        return pending is not None and await pending()

    if await check():
        raise ConversationSuperseded

    async def watch() -> None:
        while True:
            await asyncio.sleep(0.25)
            if await check():
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
        if await check():
            raise ConversationSuperseded
        return result
    finally:
        work.cancel()
        monitor.cancel()
        # Await cleanup, including the structured adapter's durable stop request.
        await asyncio.gather(work, monitor, return_exceptions=True)
