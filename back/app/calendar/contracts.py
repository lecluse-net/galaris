"""Ports for optional external calendar providers."""

from dataclasses import dataclass
from typing import Protocol


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
