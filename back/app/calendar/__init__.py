"""Personal agent agendas and optional connected calendar resources."""

from .contracts import CalendarHttpResponse, register_ical_transport, register_caldav_transport
from .models import (CalendarFeed, CalendarTrigger, CalendarEvent, CalendarEventException, CalendarOccurrence,
                     CalendarAction, CalendarSyncOperation, CalendarSyncRun, CalendarEventRevision, CalendarProjectionWindow)
from .service import sync_calendars, sync_native_calendars, sync_external_calendars
from .service import connection_for_calendar, calendar_authorization_changed
from app.connection.facade import register_oauth_observer
from app.tools import register_protocol_resource_resolver, register_connection_probe
from .connection_diagnostics import test_saved_connection as _test_saved_connection
from .maintenance import prune_calendar_cache

register_protocol_resource_resolver("calendar", connection_for_calendar)
register_connection_probe("calendar", _test_saved_connection)
register_oauth_observer("calendar", calendar_authorization_changed)

from app.agent import register_context_provider
from .context import calendar_context_provider

register_context_provider("calendar", calendar_context_provider, priority=30)

from app.contact.facade import register_contact_reference_handler
from .contact_links import update_contact_references

register_contact_reference_handler("calendar", update_contact_references)

from app.file_share import register_calendar_resource_provider
from .resources import read_calendar_resource, list_calendar_resources

register_calendar_resource_provider(read_calendar_resource, list_calendar_resources)

__all__ = ["CalendarFeed", "CalendarTrigger", "CalendarHttpResponse", "register_ical_transport", "sync_calendars",
           "sync_native_calendars", "sync_external_calendars", "connection_for_calendar", "register_caldav_transport",
           "CalendarEvent", "CalendarEventException", "CalendarOccurrence", "CalendarAction", "CalendarSyncOperation",
           "CalendarSyncRun", "CalendarEventRevision", "CalendarProjectionWindow", "prune_calendar_cache"]
