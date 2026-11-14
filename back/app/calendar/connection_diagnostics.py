"""Read-only provider discovery, without scheduling or importing calendar events."""

from sqlalchemy import select

from app.connection.facade import get_connection, get_params_as_dict, calendar_access_token
from app.tools.facade import get_tool_by_id
from core.database import get_db

from .contracts import calendar_provider
from .crypto import decrypt
from .models import CalendarFeed
from .transport import read_calendar, validate_calendar_url


async def test_saved_connection(connection_id: int) -> bool:
    connection = await get_connection(connection_id)
    tool = await get_tool_by_id(connection.tool_id) if connection else None
    if tool is None or tool.calendar is None:
        raise ValueError("Calendar provider not found")
    _, params = await get_params_as_dict(connection_id, decrypt_passwords=True)
    mapping, settings = tool.calendar.param_map, tool.calendar.settings
    kind = settings.get("source_kind", "caldav")
    roots = {"google": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        "microsoft": "https://graph.microsoft.com/v1.0/me/calendars", "icloud": "https://caldav.icloud.com/"}
    sources: list[tuple[str, str, str | None, str | None]] = []
    if mapping.get("url") or kind in roots:
        url = roots[kind] if kind in roots else validate_calendar_url(str(params.get(mapping["url"]) or ""))
        sources.append((kind, url, str(params.get(mapping.get("username", "")) or "") or None,
                        str(params.get(mapping.get("password", "")) or "") or None))
    else:
        feeds = await get_db().scalars(select(CalendarFeed).where(CalendarFeed.connection_id == connection_id))
        sources = [(feed.source_kind, decrypt(feed.source_root_encrypted or feed.url_encrypted),
                    decrypt(feed.username_encrypted) or None, decrypt(feed.password_encrypted) or None) for feed in feeds]
    if not sources:
        return False
    for kind, url, username, password in sources:
        if kind == "internal":
            continue
        if kind == "ical":
            response = await read_calendar(url, username=username, password=password)
            if response.status_code != 200 or b"BEGIN:VCALENDAR" not in response.content:
                return False
        else:
            bearer = None
            if kind in {"google", "microsoft"} or settings.get("auth_type") == "oauth":
                _, bearer = await calendar_access_token(connection_id)
            await calendar_provider(kind, bearer).discover(url, username=username, password=password)
    return True
