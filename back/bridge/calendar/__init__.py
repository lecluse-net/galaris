"""iCalendar bridge with per-agent feeds and durable automation receipts."""

from .models import CalendarFeed, CalendarTrigger
from .service import sync_calendars

__all__ = ["CalendarFeed", "CalendarTrigger", "sync_calendars"]
