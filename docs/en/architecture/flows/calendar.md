<p align="right"><a href="../../../fr/architecture/flows/calendar.md">Français</a> · <strong>English</strong></p>

# Calendar Tool and iCalendar

`bridge.calendar` adapts HTTPS iCalendar resources to the `app.tools` catalog, agent connections, Tasks, and Galaris Processes. The built-in `calendar` Tool is always present in the catalog, but it is never connected automatically: an administrator explicitly creates a Calendar connection for the agent from the **Tools > Connections** screen.

## Connection and calendars

A Calendar connection has general time-slot search preferences: IANA time zone, start and end of the workday, and search interval. The same modal then allows one or more `CalendarFeed` resources to be added. Each resource specifies its human owner, its `read` or `write` mode, its active triggers, and the selected Task or Process action.

Each `CalendarFeed` actually references its `Connection`. Deleting the connection therefore deletes its calendar configuration; disabling the connection immediately removes the MCP functions and excludes its calendars from CRON. The full URL, HTTP credentials, and iCalendar snapshot are encrypted at rest. The APIs return only the host name and indicators showing whether secrets are present.

Network access accepts HTTPS only. The bridge resolves and pins a public address for each request and redirect in order to reject private networks. Responses are capped at 5 MiB. A write replaces an `.ics` resource with `PUT` and `If-Match` when the server provides an ETag.

The **Test synchronization** button downloads and expands the feed without triggering an action. It displays the next three occurrences and, for a write-enabled calendar, the capability announced by the server.

## Synchronization and triggering

The durable scheduler of `app.task` hosts `calendar-sync` with a 900-second interval:

1. it selects only calendars belonging to active connections that are themselves active;
2. `recurring-ical-events` expands RFC 5545 recurrences and `VALARM` alarms;
3. event starts and notifications within the window since the previous check produce a stable fingerprint;
4. the unique constraint `(calendar_id, fingerprint)` creates a single `CalendarTrigger`;
5. the bridge submits a Task through the public façade of `app.agent`, or launches the Process assigned to the agent through `app.process` with an idempotency key derived from the fingerprint.

Recovery after an outage rereads up to seven days. Calendar text is always marked as untrusted external content in Tasks and MCP tools.

## MCP functions

An active connection exposes the following native functions to its agent:

- `calendar_list` and `calendar_events` to discover calendars and their occurrences;
- `calendar_is_available` to check an exact time range and obtain conflicts;
- `calendar_find_free_slots` to search for time slots according to the connection preferences;
- `calendar_create_event`, `calendar_update_event`, and `calendar_delete_event` for resources declared as writable.

Optional calendar identifiers are always cross-checked against the agent's active connection. Canceled or transparent events do not block an availability slot.
