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


def default_concurrency(provider_type: str, catalog_code: str | None) -> int:
    return 1 if provider_type == "ollama" or catalog_code is None else 10


@dataclass(eq=False)
class Permit:
    scheduler: ProviderScheduler
    provider_id: int
    priority: int
    owner: str | None
    released: bool = False
    used: bool = False
    call_id: UUID | None = None
    requester: int | None = None
    mission: UUID | None = None

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
    requester: int | None = None
    mission: UUID | None = None


@dataclass
class _ProviderQueue:
    limit: int
    waiting: list[Ticket] = field(default_factory=list[Ticket])
    active: set[Permit] = field(default_factory=set[Permit])
    user_turn: dict[int | str | UUID | None, int] = field(default_factory=dict[int | str | UUID | None, int])
    mission_turn: dict[UUID | str | None, int] = field(default_factory=dict[UUID | str | None, int])
    turn: int = 0


def provider_has_capacity(limit: int, priority: int, total: int, background: int, same_priority: int) -> bool:
    if limit == 0:
        return True
    if total >= limit:
        return False
    if limit == 1:
        return True
    if priority == 2:
        return background < max(1, limit - 2)
    return limit == 2 or same_priority + background < limit - 1


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

    def enqueue(self, provider_id: int, limit: int, priority: int, *, owner: str | None = None,
                requester: int | None = None, mission: UUID | None = None) -> Ticket:
        if provider_id not in self._providers:
            self.configure(provider_id, limit)
        loop = asyncio.get_running_loop()
        ticket = Ticket(provider_id, priority, owner, loop.create_future(), loop.time(), requester, mission)
        self._providers[provider_id].waiting.append(ticket)
        self._schedule()
        return ticket

    async def acquire(self, provider_id: int, limit: int, priority: int, *, owner: str | None = None,
                      requester: int | None = None, mission: UUID | None = None) -> Permit:
        ticket = self.enqueue(provider_id, limit, priority, owner=owner, requester=requester, mission=mission)
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
        queue = self._providers[permit.provider_id]
        queue.active.discard(permit)
        if not queue.active and not queue.waiting:
            queue.user_turn.clear()
            queue.mission_turn.clear()
            queue.turn = 0
        self._schedule()

    def _schedule(self) -> None:
        if not self._scheduled and any(queue.waiting for queue in self._providers.values()):
            self._scheduled = True
            asyncio.get_running_loop().call_soon(self._drain)

    @staticmethod
    def _eligible(queue: _ProviderQueue, priority: int) -> bool:
        # One shared place remains usable by background work even at limit 2.
        # At >=3, voice and text each retain a protected place. Background
        # calls cannot borrow these; neither dialogue class borrows the other.
        background = sum(permit.priority == 2 for permit in queue.active)
        own = sum(permit.priority == priority for permit in queue.active)
        return provider_has_capacity(queue.limit, priority, len(queue.active), background, own)

    def _drain(self) -> None:
        self._scheduled = False
        now = asyncio.get_running_loop().time()
        for provider_id, queue in self._providers.items():
            if not queue.waiting:
                continue
            # A drain does not yield: only grants below can change these counts.
            owners = Counter(permit.owner for permit in queue.active if permit.owner)
            users = Counter(p.requester or p.mission or p.owner for p in queue.active)
            missions = Counter(p.mission or p.owner for p in queue.active)
            # Only contenders in this drain need a remembered turn.
            user_keys = {t.requester or t.mission or t.owner for t in queue.waiting}
            mission_keys = {t.mission or t.owner for t in queue.waiting}
            queue.user_turn = {k: v for k, v in queue.user_turn.items() if k in user_keys or k in users}
            queue.mission_turn = {k: v for k, v in queue.mission_turn.items() if k in mission_keys or k in missions}
            priorities = {ticket.priority for ticket in queue.waiting}
            while queue.waiting:
                allowed = {priority for priority in priorities if self._eligible(queue, priority)}
                eligible = [ticket for ticket in queue.waiting if ticket.priority in allowed]
                if not eligible:
                    break
                def rank(ticket: Ticket) -> tuple[int, int, int, int, int, int, float]:
                    age = int((now - ticket.queued_at) / 30)
                    concurrent = owners[ticket.owner] if ticket.owner else 0
                    mission = ticket.mission or ticket.owner
                    user = ticket.requester or mission
                    return (max(0, ticket.priority - age), users[user], queue.user_turn.get(user, 0),
                            missions[mission], queue.mission_turn.get(mission, 0),
                            concurrent, ticket.queued_at)
                ticket = min(eligible, key=rank)
                queue.waiting.remove(ticket)
                if ticket.future.cancelled():
                    continue
                permit = Permit(self, provider_id, ticket.priority, ticket.owner,
                                requester=ticket.requester, mission=ticket.mission)
                queue.active.add(permit)
                mission = ticket.mission or ticket.owner
                user = ticket.requester or mission
                queue.turn += 1
                queue.user_turn[user] = queue.mission_turn[mission] = queue.turn
                users[user] += 1
                missions[mission] += 1
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


async def acquire_call(provider_id: int, limit: int, priority: int, *, owner: str | None,
                       requester: int | None = None, mission: UUID | None = None) -> Permit:
    permit = _reserved.get()
    if permit is not None and permit.provider_id != provider_id and not permit.used:
        permit.release()
    if permit is None or permit.provider_id != provider_id or permit.used or permit.released:
        permit = await get_scheduler().acquire(provider_id, limit, priority, owner=owner,
                                               requester=requester, mission=mission)
        owned = _owned.get()
        if owned is not None:
            owned.append(permit)
    permit.used = True
    return permit


def bind_call(call_id: UUID, permit: Permit) -> None:
    permit.call_id = call_id
    _calls[call_id] = permit


def active_call_ids() -> tuple[UUID, ...]:
    """Physical calls currently owned by the backend's provider scheduler."""
    return tuple(_calls)


def release_call(call_id: UUID) -> None:
    permit = _calls.pop(call_id, None)
    if permit is not None:
        permit.release()
