# 0282 — Calendar workspace and per-occurrence Task launches

Date: 2026-11-13
Status: Accepted

## Decision

`front/app/calendar` owns the Agenda workspace at `/calendar`, its public client contracts,
components, navigation and translations. `/connection/calendars` opens the same workspace;
connection diagnostics reuse its public calendar service. External credentials and source
configuration remain in the standard connection parameter editors.

Month, Week, Day and Schedule views select calendars per managed agent. Event editing uses
explicit recurrence scopes and revision checks. Each agent has one automatically created
internal default agenda, protected against deletion and deactivation. New internal calendars
cannot be created through the UI or API; external Tools supply additional agendas. Legacy
secondary internal agendas remain accessible without deleting or moving their events.
The API's default flag identifies only the internal agenda; the external ORM marker remains
private synchronization-root metadata. Source captions show Galaris for internal layers and
the current Tool label for external calendars, resolved through the public Tools facade.
CalDAV writes
use local receipts; iCalendar subscriptions remain read-only. Local actions do not require
remote event write permission. Events never become Documents, Goals or Process definitions.

Task launches replace notifications in the event editor. Instructions, signed offsets from
event start/end, occurrence scopes and lateness policies use existing action contracts.
Event details retain full paginated execution history and authorized Task links. Relaunches
retain previous outcomes and use stable request keys.

The bounded `POST /calendars/execution-states` read accepts at most 500 occurrence identities
for one authorized connection. It reports each action's latest launch state and the total
historical launch count, without event text or Task content. This avoids one history query
per displayed event. Task states use the existing `app.agent` facade. Calendar privileges
and connection management scope remain enforced by the API.

Action creation accepts an optional request key. Its event-scoped deterministic UUID makes
retries after lost responses idempotent. Reusing a key with a different payload conflicts
instead of silently updating or creating another action. Existing callers may omit the key.
No database schema or scheduling engine is introduced.

## Automatic event execution

Every enabled event occurrence has a Task deadline. When no existing VALARM or active local
action applies, its start produces the stable `event:start` deadline through the same durable
trigger journal. Existing configured launches retain their timing, avoiding an additional
default Task beside them. Event creation and default scheduling share one transaction; the
editor no longer offers an opt-in checkbox or performs a second action-save request.
The scheduler reconciles older events without actions and maintains recurrence coverage.
Dispatch materializes complete, current event details into both the Task objective and data.
Calendar/connection activation, lateness, admission idempotency and terminal outcomes remain
authoritative. The editor uses the shared scrolling dialog-form layout with a fixed action bar.

Connection details reuse the existing ConnectionList modal in a detail-only mode. Composition
through ResourceDetailDialog keeps the calendar on its current route without introducing the
reverse calendar-to-connection module dependency. Loading, errors and parameter persistence
continue to use the existing connection editor and store.

## Frontend dependency review

The reviewed additions to the frontend dependency inventory are `app/calendar` to
`app/agent` (public agent selector), `core/api` (HTTP), `core/authorize` (privileges),
`core/navigation` (navigation types), and `core/util` (shared header and Solaire tokens).
`app/connection` consumes `app/calendar`'s public service and asynchronous workspace export
for existing diagnostic and route consumers. These six edges introduce no private import
or dependency cycle. The generated frontend inventory records these specific additions;
existing private-import and cycle ceilings are not increased.

Calendar colors are browser-local presentation preferences, isolated by authenticated user
and by calendar identity (or agent identity for Goals and Memory). They use the eleven Solaire
tones and their matching light/dark backgrounds; Memory defaults to yellow. The settings
dialog saves the selection explicitly. The reviewed `app/calendar` → `core/user` addition
uses only the public `useAuthStore` export to obtain the reactive user identity, preventing
preferences from leaking between accounts. It introduces no private import or cycle.

Month grids are split into contiguous query windows within the backend's 32-day limit.
Requests are fenced when agent, period or session changes. Timed events retain their
timezone and unchanged ambiguous instants; all-day ends remain exclusive in the API and
inclusive in the editor. Revision conflicts preserve the user's draft.

## Verification

Backend integration covers state aggregation, retained history, idempotent action saves and
payload conflicts. Existing HTTP authorization scenarios cover privileges, connection scope
and batch limits. Actual Vue/Quasar components use synthetic HTTP fixtures for editing,
failed saves, retries, recurrence scopes, moves, Task access, settings and late responses.
The assembled E2E journey exercises creation, persistence, editing and reopening through
the real API. It also protects Create from being obscured by the shell user menu, a failure
that isolated component tests cannot detect.
