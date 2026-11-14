"""Ports for optional external calendar providers."""

from dataclasses import dataclass
from typing import Protocol
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar


@dataclass(frozen=True, slots=True)
class CalendarSyncProgress:
    phase: str
    completed: int = 0
    total: int | None = None
    http_status: int | None = None


_sync_monitor: ContextVar[Callable[[CalendarSyncProgress], Awaitable[None]] | None] = ContextVar("calendar_sync_monitor", default=None)


@contextmanager
def monitor_calendar_sync(callback: Callable[[CalendarSyncProgress], Awaitable[None]]) -> Generator[None]:
    token = _sync_monitor.set(callback)
    try:
        yield
    finally:
        _sync_monitor.reset(token)


async def report_calendar_sync(phase: str, completed: int = 0, total: int | None = None, *, http_status: int | None = None) -> None:
    callback = _sync_monitor.get()
    if callback is not None:
        await callback(CalendarSyncProgress(phase, completed, total, http_status))


@dataclass(frozen=True, slots=True)
class CalendarHttpResponse:
    content: bytes
    final_url: str
    headers: dict[str, str]
    status_code: int = 200


class CalendarTransport(Protocol):
    def validate_calendar_url(self, value: str) -> str: ...
    async def read_calendar(self, url: str, *, username: str | None = None, password: str | None = None, etag: str | None = None) -> CalendarHttpResponse: ...
    async def write_calendar(self, url: str, content: bytes, *, username: str | None = None,
                             password: str | None = None, etag: str | None = None) -> None: ...


_ical_transport: CalendarTransport | None = None


def register_ical_transport(transport: CalendarTransport) -> None:
    global _ical_transport
    _ical_transport = transport


def ical_transport() -> CalendarTransport:
    if _ical_transport is None:
        raise ValueError("The iCalendar bridge is unavailable")
    return _ical_transport


@dataclass(frozen=True, slots=True)
class RemoteCalendar:
    href: str
    label: str
    writable: bool


@dataclass(frozen=True, slots=True)
class RemoteChange:
    href: str
    etag: str | None
    content: bytes | None
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class RemoteChanges:
    changes: tuple[RemoteChange, ...]
    token: str | None
    full: bool


class RemoteConflictError(ValueError):
    pass


class InvalidSyncTokenError(ValueError):
    pass


class StaleSyncError(ValueError):
    pass


class CalDavTransport(Protocol):
    async def discover(self, url: str, *, username: str | None, password: str | None) -> list[RemoteCalendar]: ...
    async def changes(self, url: str, *, token: str | None, username: str | None, password: str | None) -> RemoteChanges: ...
    async def fetch(self, url: str, *, username: str | None, password: str | None) -> CalendarHttpResponse | None: ...
    async def put(self, url: str, content: bytes, *, etag: str | None, username: str | None, password: str | None) -> CalendarHttpResponse: ...
    async def remove(self, url: str, *, etag: str, username: str | None, password: str | None) -> None: ...


_caldav_transport: CalDavTransport | None = None


def register_caldav_transport(transport: CalDavTransport) -> None:
    global _caldav_transport
    _caldav_transport = transport


def caldav_transport() -> CalDavTransport:
    if _caldav_transport is None:
        raise ValueError("The CalDAV bridge is unavailable")
    return _caldav_transport


_provider_factory: Callable[[str, str | None], CalDavTransport] | None = None


def register_calendar_provider(factory: Callable[[str, str | None], CalDavTransport]) -> None:
    global _provider_factory
    _provider_factory = factory


def calendar_provider(kind: str, bearer: str | None = None) -> CalDavTransport:
    if kind == "caldav" and bearer is None:
        return caldav_transport()
    if _provider_factory is None:
        raise ValueError("The calendar provider bridge is unavailable")
    return _provider_factory(kind, bearer)
