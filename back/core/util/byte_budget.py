"""Admission for operations whose SDK requires buffered binary payloads."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from .thread_io import complete_await


class BufferedAdmissionDeferred(TimeoutError):
    """Local capacity was unavailable; no remote operation has been attempted."""


@dataclass
class _Envelope:
    available: int
    closed: bool = False


_envelopes: ContextVar[dict[int, _Envelope] | None] = ContextVar(
    "byte_budget_envelopes", default=None
)


class ByteBudget:
    def __init__(self, capacity: int, *, max_operations: int = 4) -> None:
        self.capacity = capacity
        self.max_operations = max_operations
        self.used = 0
        self.active = 0
        self.owners: set[str] = set()
        self._condition = asyncio.Condition()

    @asynccontextmanager
    async def reserve(
        self, size: int, *, owner: str, timeout: float = 30, child_bytes: int = 0
    ) -> AsyncGenerator[None]:
        """Reserve own buffers plus an explicit allowance for nested adapters.

        Child allocations consume that allowance instead of competing with their
        parent for global slots. Ordinary reservations do not imply an allowance.
        """
        if child_bytes < 0:
            raise ValueError("Child allowance must be nonnegative")
        total = size + child_bytes
        if size <= 0 or size > self.capacity:
            raise ValueError("Buffered operation exceeds the process memory budget")
        if total > self.capacity:
            raise ValueError("Buffered envelope exceeds the process memory budget")
        parents = _envelopes.get() or {}
        parent = parents.get(id(self))
        if parent is not None and parent.closed:
            parent = None
        try:
            async with asyncio.timeout(timeout), self._condition:
                await self._condition.wait_for(
                    lambda: (
                        (parent is not None and parent.closed)
                        or (
                            (
                                parent.available >= total
                                if parent is not None
                                else self.used + total <= self.capacity
                                and self.active < self.max_operations
                            )
                            and owner not in self.owners
                        )
                    )
                )
                if parent is not None and parent.closed:
                    raise BufferedAdmissionDeferred("The parent allocation has finished")
                if parent is not None:
                    parent.available -= total
                else:
                    self.used += total
                    self.active += 1
                self.owners.add(owner)
        except TimeoutError as exc:
            raise BufferedAdmissionDeferred("Buffered I/O is waiting for local capacity") from exc
        inherited = dict(parents)
        envelope = _Envelope(child_bytes) if child_bytes else None
        if envelope is not None:
            inherited[id(self)] = envelope
        else:
            inherited.pop(id(self), None)
        token = _envelopes.set(inherited)
        try:
            yield
        finally:
            _envelopes.reset(token)

            async def release() -> None:
                async with self._condition:
                    if envelope is not None:
                        envelope.closed = True
                        self._condition.notify_all()
                        allocation = envelope
                        await self._condition.wait_for(lambda: allocation.available == child_bytes)
                    if parent is not None:
                        parent.available += total
                    else:
                        self.used -= total
                        self.active -= 1
                    self.owners.remove(owner)
                    self._condition.notify_all()

            await complete_await(release())


# Conservative allocation envelopes include content, base64/JSON and driver
# copies. This bounds admitted binary work, not the backend's total RSS.
buffered_io_budget = ByteBudget(1024 * 1024 * 1024)
