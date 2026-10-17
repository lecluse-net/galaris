"""Shared physical-call admission for the supported single-worker backend.

Durable inference requests stay in PostgreSQL until admitted. Native callers
wait on lightweight tickets, without retaining a database transaction. A permit
belongs to one physical call, never to a tool or an entire agent run.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from .purposes import LLMCallPurpose


def default_concurrency(provider_type: str, catalog_code: str | None) -> int:
    return 1 if provider_type == "ollama" or catalog_code is None else 10


def call_priority(purpose: str | None, *, round_origin: str | None = None) -> int:
    if round_origin == "voice" or purpose == LLMCallPurpose.CONVERSATION_AUDIO:
        return 0
    if round_origin == "text" or purpose in {
        LLMCallPurpose.CONVERSATION_TEXT, LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE,
        LLMCallPurpose.CONVERSATION_PROCESS_ADMISSION,
    }:
        return 1
    return 2


@dataclass(eq=False)
class Permit:
    scheduler: ProviderScheduler
    provider_id: int
    priority: int
    owner: str | None
    released: bool = False
    used: bool = False
    call_id: UUID | None = None

    def release(self) -> None:
        if not self.released:
            self.released = True
            if self.call_id is not None:
                _calls.pop(self.call_id, None)
            self.scheduler.release(self)


@dataclass(eq=False)
class Ticket:
    provider_id: int
    priority: int
    owner: str | None
    future: asyncio.Future[Permit]
    queued_at: float


@dataclass
class _ProviderQueue:
    limit: int
    waiting: list[Ticket] = field(default_factory=list[Ticket])
    active: set[Permit] = field(default_factory=set[Permit])


class ProviderScheduler:
    """Priority admission with protected dialogue capacity and bounded aging."""

    def __init__(self) -> None:
        self._providers: dict[int, _ProviderQueue] = {}
        self._scheduled = False

    def configure(self, provider_id: int, limit: int) -> None:
        if limit < 0:
            raise ValueError("Provider concurrency cannot be negative.")
        queue = self._providers.get(provider_id)
        if queue is None:
            self._providers[provider_id] = _ProviderQueue(limit=limit)
        else:
            queue.limit = limit
        self._schedule()

    def enqueue(self, provider_id: int, limit: int, priority: int, *, owner: str | None = None) -> Ticket:
        if provider_id not in self._providers:
            self.configure(provider_id, limit)
        loop = asyncio.get_running_loop()
        ticket = Ticket(provider_id, priority, owner, loop.create_future(), loop.time())
        self._providers[provider_id].waiting.append(ticket)
        self._schedule()
        return ticket

    async def acquire(self, provider_id: int, limit: int, priority: int, *, owner: str | None = None) -> Permit:
        ticket = self.enqueue(provider_id, limit, priority, owner=owner)
        try:
            return await asyncio.shield(ticket.future)
        except BaseException:
            self.cancel(ticket)
            raise

    def cancel(self, ticket: Ticket) -> None:
        queue = self._providers[ticket.provider_id]
        if ticket in queue.waiting:
            queue.waiting.remove(ticket)
        if ticket.future.done() and not ticket.future.cancelled():
            ticket.future.result().release()
        else:
            ticket.future.cancel()
        self._schedule()

    def release(self, permit: Permit) -> None:
        self._providers[permit.provider_id].active.discard(permit)
        self._schedule()

    def _schedule(self) -> None:
        if not self._scheduled and any(queue.waiting for queue in self._providers.values()):
            self._scheduled = True
            asyncio.get_running_loop().call_soon(self._drain)

    @staticmethod
    def _eligible(queue: _ProviderQueue, priority: int) -> bool:
        if queue.limit == 0:
            return True
        if len(queue.active) >= queue.limit:
            return False
        # One shared place remains usable by background work even at limit 2.
        # At >=3, voice and text each retain a protected place. Background
        # calls cannot borrow these; neither dialogue class borrows the other.
        if queue.limit == 1:
            return True
        background = sum(permit.priority == 2 for permit in queue.active)
        if priority == 2:
            return background < max(1, queue.limit - 2)
        if queue.limit == 2:
            return True
        own = sum(permit.priority == priority for permit in queue.active)
        return own + background < queue.limit - 1

    def _drain(self) -> None:
        self._scheduled = False
        now = asyncio.get_running_loop().time()
        for provider_id, queue in self._providers.items():
            if not queue.waiting:
                continue
            # A drain does not yield: only grants below can change these counts.
            owners = Counter(permit.owner for permit in queue.active if permit.owner)
            priorities = {ticket.priority for ticket in queue.waiting}
            while queue.waiting:
                allowed = {priority for priority in priorities if self._eligible(queue, priority)}
                eligible = [ticket for ticket in queue.waiting if ticket.priority in allowed]
                if not eligible:
                    break
                def rank(ticket: Ticket, owners: Counter[str] = owners) -> tuple[int, int, float]:
                    age = int((now - ticket.queued_at) / 30)
                    concurrent = owners[ticket.owner] if ticket.owner else 0
                    return max(0, ticket.priority - age), concurrent, ticket.queued_at
                ticket = min(eligible, key=rank)
                queue.waiting.remove(ticket)
                if ticket.future.cancelled():
                    continue
                permit = Permit(self, provider_id, ticket.priority, ticket.owner)
                queue.active.add(permit)
                if ticket.owner:
                    owners[ticket.owner] += 1
                ticket.future.set_result(permit)


_scheduler: ProviderScheduler | None = None
_event_loop: asyncio.AbstractEventLoop | None = None
_reserved: ContextVar[Permit | None] = ContextVar("llm_provider_permit", default=None)
_owned: ContextVar[list[Permit] | None] = ContextVar("llm_provider_owned_permits", default=None)
_calls: dict[UUID, Permit] = {}


def get_scheduler() -> ProviderScheduler:
    global _scheduler, _event_loop
    loop = asyncio.get_running_loop()
    if loop is not _event_loop or _scheduler is None:
        _event_loop = loop
        _scheduler = ProviderScheduler()
        _calls.clear()
    return _scheduler


@contextmanager
def reserved(permit: Permit | None) -> Generator[None]:
    token = _reserved.set(permit)
    owned = [permit] if permit is not None else []
    ownership_token = _owned.set(owned)
    try:
        yield
    finally:
        for held in owned:
            held.release()
        _owned.reset(ownership_token)
        _reserved.reset(token)


async def acquire_call(provider_id: int, limit: int, priority: int, *, owner: str | None) -> Permit:
    permit = _reserved.get()
    if permit is not None and permit.provider_id != provider_id and not permit.used:
        permit.release()
    if permit is None or permit.provider_id != provider_id or permit.used or permit.released:
        permit = await get_scheduler().acquire(provider_id, limit, priority, owner=owner)
        owned = _owned.get()
        if owned is not None:
            owned.append(permit)
    permit.used = True
    return permit


def bind_call(call_id: UUID, permit: Permit) -> None:
    permit.call_id = call_id
    _calls[call_id] = permit


def release_call(call_id: UUID) -> None:
    permit = _calls.pop(call_id, None)
    if permit is not None:
        permit.release()
