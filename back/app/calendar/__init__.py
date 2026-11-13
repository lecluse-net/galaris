"""Personal agent agendas and optional connected calendar resources."""

from .contracts import CalendarHttpResponse, register_ical_transport, register_caldav_transport
from .models import (CalendarFeed, CalendarTrigger, CalendarEvent, CalendarEventException, CalendarOccurrence,
                     CalendarAction, CalendarSyncOperation, CalendarSyncRun, CalendarEventRevision, CalendarProjectionWindow)
from .service import sync_calendars, sync_native_calendars, sync_external_calendars
from .service import connection_for_calendar
from app.tools import register_protocol_resource_resolver
from .maintenance import prune_calendar_cache

register_protocol_resource_resolver("calendar", connection_for_calendar)

__all__ = ["CalendarFeed", "CalendarTrigger", "CalendarHttpResponse", "register_ical_transport", "sync_calendars",
           "sync_native_calendars", "sync_external_calendars", "connection_for_calendar", "register_caldav_transport",
           "CalendarEvent", "CalendarEventException", "CalendarOccurrence", "CalendarAction", "CalendarSyncOperation",
           "CalendarSyncRun", "CalendarEventRevision", "CalendarProjectionWindow", "prune_calendar_cache"]
