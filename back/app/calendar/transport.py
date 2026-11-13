"""Provider-neutral entry points; HTTPS implementation is registered by its bridge."""

from .contracts import CalendarHttpResponse, ical_transport


def validate_calendar_url(value: str) -> str:
    return ical_transport().validate_calendar_url(value)


async def read_calendar(url: str, *, username: str | None = None, password: str | None = None, etag: str | None = None) -> CalendarHttpResponse:
    return await ical_transport().read_calendar(url, username=username, password=password, etag=etag)


async def write_calendar(url: str, content: bytes, *, username: str | None = None,
                         password: str | None = None, etag: str | None = None) -> None:
    await ical_transport().write_calendar(url, content, username=username, password=password, etag=etag)
