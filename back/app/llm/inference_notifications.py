"""Advisory wakeups; inference state and stream cursors remain in PostgreSQL."""

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from typing import Literal
from uuid import UUID

from core.database import after_commit

type Topic = Literal["work", "changes", "control"]
type Key = tuple[Topic, UUID | None]
_subscribers: dict[Key, set[asyncio.Event]] = {}

# Recovery for a lost local wakeup or writes made by an external process.
# This is deliberately independent of provider responsiveness and lease renewal.
RECONCILE_SECONDS = 30.0


@contextmanager
def subscribe(topic: Topic, inference_id: UUID | None = None) -> Generator[asyncio.Event]:
    """Subscribe before reading, clear before each read, then wait if caught up.

    Each reader owns its event: one reader cannot consume another's wakeup.
    Subscribing before reading also covers a commit between the read and wait.
    """
    key = (topic, inference_id)
    event = asyncio.Event()
    _subscribers.setdefault(key, set()).add(event)
    try:
        yield event
    finally:
        subscribers = _subscribers[key]
        subscribers.remove(event)
        if not subscribers:
            del _subscribers[key]


def notify(topic: Topic, inference_id: UUID | None = None) -> None:
    for event in tuple(_subscribers.get((topic, inference_id), ())):
        event.set()


def notify_after_commit(topic: Topic, inference_id: UUID | None = None) -> None:
    after_commit(
        lambda: notify(topic, inference_id),
        key=("llm-inference", topic, inference_id),
    )


async def wait(event: asyncio.Event, timeout: float | None = None) -> None:
    try:
        async with asyncio.timeout(RECONCILE_SECONDS if timeout is None else timeout):
            await event.wait()
    except TimeoutError:
        pass
