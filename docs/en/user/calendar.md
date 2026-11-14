<p align="right"><a href="../../fr/user/calendar.md">Français</a> · <strong>English</strong></p>

# Agenda and Task launches

An event can optionally reference a Galaris Contact belonging to its agent. Use the
**Linked contact** field to search and select one in the editor; event details can open
the contact record. Agents can also supply `contact_id` through Calendar tools, or remove
the link with `clear_contact=True`. For recurring events, the contact applies to the whole
series. The reference stays local to Galaris: it sends no invitation and is not transmitted
to the external calendar.

Open **Knowledge → Agenda** (`/calendar`). Every agent has a personal agenda without an
external account. Its CalDAV calendars and iCalendar subscriptions can be displayed in the
same workspace. External connections use the standard protocol parameter editors in
**Tools & connections**.
Each agent has one internal default agenda, created automatically. Settings can rename it and
change its color, but cannot delete or disable it or create additional internal agendas.
External calendars supplement it. Any existing secondary internal agendas remain accessible
to preserve their events.

When calendar reading is enabled for the agent, its context includes ongoing appointments and
those in the next ten days, in chronological order and limited to ten occurrences in total by default.
In **Preferences → Memory → Agent temporal context**, configure the horizon in days and the
maximum event count separately. Both limits apply together.
This summary refreshes whenever context is built; stale sources and additional appointments
are flagged. Blocked or on-request functions are not read automatically. The agent can use its
authorized tools to inspect other dates, check availability or set itself a reminder within
the assigned work.

The agenda is the agent’s dated memory aid, usable from conversations and Tasks alike:
appointments, deadlines and things to remember at a particular time. A request such as
“remind me around 15:00 that I need to leave” should create a personal agenda event when
the function is authorized.

The **Memory** source, selectable in the calendar list, displays the agent’s dated memories over
the visible period. Click an occurrence to open the original content. Partial dates retain
their precision and recurrence in Galaris’s global timezone: a date without a time spans the
day, and a month alone spans that month. Memories remain owned by Memory.
This source also contributes to the agent’s temporal context, with its source memory link,
without a second injection into the ordinary Memory brief. Access and conversation contact
scope remain enforced; managers need Memory access to view this layer.
These occurrences are informational: no Task, autonomous wake-up, availability reservation
or external calendar export. Hiding the layer in the UI does not change agent context.
Goal behavior remains unchanged.

## Navigate the calendar

Each calendar appears on its own row, with its source shown underneath. Local calendars,
**Goals** and **Memory** carry the **Galaris** label. External calendars show their source
Tool's label rather than its protocol name.
A star identifies the default calendar. Its checkbox shows or hides events; clicking
the name or the rest of the row opens its settings dialog without changing the selection.
Pressing Enter on a focused row also opens its settings.
In **My calendars**, the **…** button and a right click on a row open the same menu:
copy the reference, show or hide the calendar, open its settings and, for external calendars
with edit permission, start synchronization and view its progress.
Each calendar owns a stable `galaris://calendar/<identifier>` URL. Paste it into a discussion
or add it as a resource attachment to open its details without a thumbnail, then the calendar.
Renaming preserves the link; a reference grants no additional access. **Goals** and **Memory**
layers retain their original resource identities.
The default **Personal agenda** name follows the interface language; custom names are preserved.
In the calendar settings dialog, choose one of the eleven Solaire colors and save to apply it
to its checkbox and events in both light and dark themes. **Memory** defaults to yellow. Choices are
saved per user in the current browser, including those for **Goals** and **Memory**.
The dialog title is the calendar name, followed by a **Galaris** badge or its source Tool's
label. Tabs follow the Goal dialog presentation: **Settings** and, for external calendars
only, **Synchronization**. The internal calendar, **Goals** and **Memory** have no
synchronization information or actions.

Choose an agent, then check the calendars to display. Switch between **Month**, **Week**,
**Day** and **Schedule**. Use **Today**, the arrows or the small calendar to change the period.
Click a date to open its day view; the “more” button opens additional appointments on busy days.
Month view shows each ISO week number to the left of its row. Week view includes the number
in the period title. Weeks start on Monday.

The display timezone is independent of the timezone saved with each event. Multi-day all-day events retain their
calendar dates. Mobile opens Schedule by default; the filter button expands calendar filters.

## Create and edit events

Use **Create event** or click a day's empty space to open a new all-day appointment. In Week
or Day view, press on the starting hour and release on the ending hour: the highlighted range
fills both times in the form. For example, selecting 9–11 prepares a two-hour appointment.
A simple slot click prepares one hour; Escape cancels an ongoing selection. The date number
still opens Day view, and existing events open their details. Enter the title, dates,
location and optional instructions. An all-day event's end date includes the last selected day.

Repeat daily, weekly, monthly, yearly or with a custom recurrence rule. Choose an interval,
weekdays and an end date or occurrence count. More complex existing rules remain preserved as
custom rules.

Open an event to edit or delete it. For a series, explicitly choose **this event**, **this and
following events** or **all events in the series**. Dragging an event preserves its duration
and asks for confirmation and recurrence scope. Concurrent changes block an outdated write
and preserve the draft; reload the current version before continuing. iCalendar subscriptions
remain read-only.

## Replace a notification with a Task

Every event automatically schedules a Task at its start, with no checkbox or second save.
Launches are enabled by default on new internal and synchronized calendars, including
automatically discovered calendars. Explicitly disabling a calendar's launches in settings
is preserved by later synchronization.
The title and description specify the expected work. The Task also receives the dates,
timezone, location and complete event context, including updates available at launch time.
Each recurring occurrence has its own execution without duplication on reads or recovery.

Existing VALARM reminders and configured launches retain their timing and instructions;
they replace the default launch for the applicable occurrence. Calendar, connection and
execution activation settings and maximum lateness policies still apply. If an early launch
misses its recovery window, it is rescheduled to the event start under the same identity to
avoid duplicate admission. An already admitted launch does not restart at event start.
Tasks use the
connection's agent and its ordinary permissions.

Calendar-launched Tasks are background work, like Goal cycles. Discussion-originated work
takes precedence in the queue, even when a calendar Task has been waiting longer. This
priority does not forcibly stop work already in progress.

Calendar cards show each action's latest state for that occurrence. Event details list every
launch, deadline, error and link to an accessible Task. For recurring events, **Whole series**
expands the execution history. States refresh automatically; use Refresh for an immediate read.

**Launch again** creates a separate execution after a terminal Task or a failed, cancelled or
skipped launch. The previous Task retains its outcome. Active Tasks cannot be relaunched.
Retries of the same action save and manual relaunch use stable request keys to avoid duplicates.

## Synchronization and access

Select **CalDAV**, **Google Calendar**, **Microsoft 365 / Outlook**, **Apple iCloud** or
**private iCalendar** in the Tool's calendar protocol. Nextcloud uses CalDAV. Configure
a shared CalDAV root as a global Tool parameter with forced inheritance when needed.
A private ICS URL belongs to its account connection. Google, Microsoft and iCloud use
predefined service endpoints.

For Google and Microsoft, reference standard `client_id` and `client_secret` parameters
for the registered provider application, then set their global Tool values. Register the
callback URL displayed by Galaris with that application. Microsoft accepts `common` for
personal and work accounts, or an enterprise directory tenant. In each connection,
**Calendar account authorization → Connect account** opens provider consent. Tokens are
encrypted and refreshed automatically; revoked access requires reauthorization. Any MCP
authorization remains independent. Enterprise consent policies still apply.

CalDAV supports an application password or OAuth using authorization/token endpoints
and scopes configured in the Tool. iCloud uses the Apple account and an app-specific
password. ICS subscriptions, including private Google/Outlook links, remain read only.

Google/Microsoft single events can be created, updated and deleted in Galaris. Their
recurring series, exceptions and cancellations are imported; create or edit recurrence
in the provider calendar. These writes are rejected before local mutation. Entire-series
deletion remains available. CalDAV retains recurrence editing. Google/Microsoft currently
read complete paginated snapshots without a date window; an incomplete response aborts
without deleting local events.

The synchronization interval belongs to the **connection** and applies to every calendar
from the same account, including Nextcloud. In the Tool definition, map the **Synchronization
interval (hours)** role to a standard integer parameter, for example `sync_interval_hours`.
Manage its value in the connection parameters: 1 to 8760 hours, default 2, with the usual
global/local inheritance. Parameters are created only through an explicit action. Existing
primary-calendar intervals remain the fallback until the role is configured. Connection
details contain no calendar list or monitoring screen; these belong to the Agenda page.

Deadlines are checked every minute and calendars run sequentially. Failures, interruptions
and local edits respect the connection interval. **Refresh** reloads the local replica;
internal calendars never contact an external server.

The external calendar's **Synchronization** tab contains only its 50 most recent attempts,
without pagination. **New synchronization**, in the dialog footer, inserts the attempt at
the top and opens it automatically. Its state,
timestamped stages, processed items, transferred kilobytes and HTTP status update live inside
that entry. Recent attempts remain available; reopening restores the
journal. Detailed steps and network phases are temporary and are omitted from the final
stored summary. Results, duration, counters and any failure remain available.
The dialog stays open after manual synchronization, including failures. The calendar refreshes
at completion only when real changes were committed: events, synchronization state, conflicts
or discovered calendars. Reading identical events again does not trigger a refresh. A failure
after committed changes still allows those changes to be reflected. Failures
retain their stage, category and counters. Pending conflicts can be
compared and resolved inside the newest attempt's details. **Connection parameters**
remains in the dialog footer and opens the connection without leaving Agenda.
**Save** also stays in the **Settings** tab's footer. Use the title-bar cross to close.

CalDAV and iCalendar connections support public HTTPS servers and servers on the company's
private network (private IPv4 and IPv6 unique-local addresses). The server must be reachable
from the Galaris backend and present a valid certificate. Loopback and link-local addresses
remain excluded.

**Open Task**, **Open review** and **Open Goal** display their detail dialogs over the
agenda. Closing them returns to the event and preserves the agenda's period, view and filters.
For a synchronized calendar, **Connection parameters** opens that connection's standard
dialog directly without leaving the agenda.

Reads and edits use the local replica. **Sync pending** means saved locally, awaiting provider
confirmation. Calendar settings provide attempt history and its retained errors. When a
conflict occurs, compare both versions and explicitly choose the local or remote version.

`CALENDAR_ACCESS` permits reading; `CALENDAR_EDIT` permits mutations. Event edits also require
a writable calendar. Local Task actions remain configurable on a read-only subscription with
calendar editing permission. Opening a Task requires its corresponding Task privileges.
Connection parameters retain their separate privileges.

## Goals in the agenda

With Goal privileges, enable **Goals** in the calendar list. In a Goal form, **Fixed dates
in the agenda** configures the first passage, its timezone, daily, weekly, monthly or yearly
recurrence and maximum lateness. Allowed schedules and agent availability still apply:
the scheduled date is eligibility, not a reservation or a guaranteed exact start.

Future passages are projections. At their due time they become retained individual events,
first waiting, then linked to their cycle and exact Task. Monday's passage opens Monday's
Task even if it started later. Details distinguish planned time, actual admission and work
completion; a review Task remains separately accessible with Task privileges.

Changing recurrence or title affects only the future. Past and elapsed passages and active
cycles retain their date, title and links. Pausing or completing removes future projections;
resuming starts a segment from activation time. Expired passages remain **Skipped** without
a Task. Nonexistent monthly dates and daylight saving clock gaps are omitted.

Existing Goals retain their cycles and delay or parent-driven mode. Delay mode shows only
its next known eligibility. Older cycles appear at actual creation time without inventing
historical planning. The title available when older cycles are imported is preserved across
later renames. Manual launches create distinct passages. The Goal layer never adds an
ordinary agenda reminder that would create another Task for the same cycle.
