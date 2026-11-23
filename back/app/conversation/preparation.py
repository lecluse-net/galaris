"""Interrupt read-only preparation while preserving the durable round's final guard."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from uuid import UUID

from core.database import after_commit

from .contracts import ConversationTurn


_room_waiters: dict[UUID, set[asyncio.Event]] = {}
_CONTROL_RECONCILE_SECONDS = 2.0


@contextmanager
def watch_room_control(room_id: UUID) -> Generator[Callable[[], Awaitable[None]]]:
    event = asyncio.Event()
    waiters = _room_waiters.setdefault(room_id, set())
    waiters.add(event)

    async def wait() -> None:
        try:
            async with asyncio.timeout(_CONTROL_RECONCILE_SECONDS):
                await event.wait()
        except TimeoutError:
            pass
        event.clear()

    try:
        yield wait
    finally:
        waiters.remove(event)
        if not waiters:
            del _room_waiters[room_id]


def wake_room_after_commit(room_id: UUID) -> None:
    def notify() -> None:
        for event in _room_waiters.get(room_id, ()):
            event.set()

    after_commit(notify, key=("conversation-control", room_id))


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
        wait_for_change = turn.wait_for_interrupt
        while True:
            if wait_for_change is None:
                await asyncio.sleep(0.25)
            else:
                await wait_for_change()
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
