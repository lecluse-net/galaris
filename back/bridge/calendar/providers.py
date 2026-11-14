"""Provider selection and scoped CalDAV authorization (never module globals)."""
from __future__ import annotations

from dataclasses import dataclass

from app.calendar.contracts import CalendarHttpResponse, CalDavTransport, RemoteCalendar, RemoteChanges
from . import caldav
from .transport import calendar_authorization


@dataclass(frozen=True)
class DavProvider:
    kind: str
    bearer: str | None

    async def discover(self, url: str, *, username: str | None, password: str | None) -> list[RemoteCalendar]:
        with calendar_authorization(self.bearer, self.kind == "icloud"):
            return await caldav.discover(url, username=username, password=password)

    async def changes(self, url: str, *, token: str | None, username: str | None, password: str | None) -> RemoteChanges:
        with calendar_authorization(self.bearer, self.kind == "icloud"):
            return await caldav.changes(url, token=token, username=username, password=password)

    async def fetch(self, url: str, *, username: str | None, password: str | None) -> CalendarHttpResponse | None:
        with calendar_authorization(self.bearer, self.kind == "icloud"):
            return await caldav.fetch(url, username=username, password=password)

    async def put(self, url: str, content: bytes, *, etag: str | None, username: str | None, password: str | None) -> CalendarHttpResponse:
        with calendar_authorization(self.bearer, self.kind == "icloud"):
            return await caldav.put(url, content, etag=etag, username=username, password=password)

    async def remove(self, url: str, *, etag: str, username: str | None, password: str | None) -> None:
        with calendar_authorization(self.bearer, self.kind == "icloud"):
            await caldav.remove(url, etag=etag, username=username, password=password)


def provider(kind: str, bearer: str | None) -> CalDavTransport:
    if kind in {"caldav", "icloud"}:
        return DavProvider(kind, bearer)
    from .rest import RestCalendarProvider
    if kind not in {"google", "microsoft"} or bearer is None:
        raise ValueError("Unknown calendar provider or missing authorization")
    return RestCalendarProvider(kind, bearer)
