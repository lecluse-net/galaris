"""Optional HTTPS iCalendar adapter for the canonical calendar domain."""

from app.calendar import CalendarFeed, CalendarTrigger, sync_calendars, register_ical_transport, register_caldav_transport
from . import transport, caldav
from app.calendar.contracts import register_calendar_provider
from .providers import provider

register_ical_transport(transport)
register_caldav_transport(caldav)
register_calendar_provider(provider)

__all__ = ["CalendarFeed", "CalendarTrigger", "sync_calendars"]
