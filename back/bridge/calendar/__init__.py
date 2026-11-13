"""Optional HTTPS iCalendar adapter for the canonical calendar domain."""

from app.calendar import CalendarFeed, CalendarTrigger, sync_calendars, register_ical_transport, register_caldav_transport
from . import transport, caldav

register_ical_transport(transport)
register_caldav_transport(caldav)

__all__ = ["CalendarFeed", "CalendarTrigger", "sync_calendars"]
