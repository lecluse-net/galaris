"""One PostgreSQL listener per contended database and event loop."""

import asyncio
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import Context
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
from loguru import logger
from sqlalchemy.engine import Engine

CHANNEL = "llm_provider_capacity"


class _Connection(Protocol):
    def add_termination_listener(self, callback: Callable[[object], None]) -> None: ...
    async def add_listener(self, channel: str, callback: Callable[[object, int, str, str], None]) -> None: ...
    def terminate(self) -> None: ...


@dataclass
class _Listener:
    waiters: dict[int, set[asyncio.Event]] = field(default_factory=dict[int, set[asyncio.Event]])

    async def listen(self, engine: Engine) -> None:
        url = engine.url.set(drivername="postgresql")
        while True:
            connection: _Connection | None = None
            try:
                closed = asyncio.Event()
                connection = cast(_Connection, await cast(Any, asyncpg).connect(
                    url.render_as_string(hide_password=False), timeout=3))
                connection.add_termination_listener(lambda _: closed.set())
                await connection.add_listener(CHANNEL, self.notify)
                # A release may have committed while LISTEN was being installed.
                for events in self.waiters.values():
                    for event in events:
                        event.set()
                await closed.wait()
            except Exception as exc:
                logger.debug("Provider capacity listener disconnected ({})", type(exc).__name__)
            finally:
                if connection is not None:
                    connection.terminate()
            await asyncio.sleep(2)

    def notify(self, _connection: object, _pid: int, _channel: str, payload: str) -> None:
        if payload.isascii() and payload.isdecimal() and len(payload) <= 10:
            for event in self.waiters.get(int(payload), ()):
                event.set()


_listeners: dict[tuple[asyncio.AbstractEventLoop, Engine], tuple[_Listener, asyncio.Task[None]]] = {}


@contextmanager
def subscribe(engine: Engine, provider_id: int) -> Generator[asyncio.Event]:
    key = (asyncio.get_running_loop(), engine)
    if key not in _listeners:
        listener = _Listener()
        _listeners[key] = listener, asyncio.create_task(listener.listen(engine), context=Context())
    listener, task = _listeners[key]
    event = asyncio.Event()
    events = listener.waiters.setdefault(provider_id, set())
    events.add(event)
    try:
        yield event
    finally:
        events.remove(event)
        if not events:
            del listener.waiters[provider_id]
        if not listener.waiters:
            del _listeners[key]
            task.cancel()
