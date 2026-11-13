<p align="right"><a href="../../../fr/architecture/flows/calendar.md">Français</a> · <strong>English</strong></p>

# Local agenda, CalDAV and action execution

`app.calendar` owns the canonical model for internal and external calendars. Each agent has a
system **Personal agenda** (`agenda`) without an external account. Additional internal and
external calendars use the same model. `bridge.calendar` implements **CalDAV**; exchanged
events remain **iCalendar** (`VEVENT`, recurrence rules, exceptions and `VALARM`). An iCalendar
file subscription is read-only.

## Configuration and authorization

The provider capability is `caldav.calendar`. `calendar_config.settings` holds source kind
(`caldav` by default, or `ical`), timezone and working-hour preferences. Its `param_map`
references standard connection parameters for `url`, `username`, `password` and optional
labels. Private URLs and passwords use encrypted `password` parameters, with ordinary
connection inheritance and enforced values. Agenda has no parallel credential editor.
External calendars come from these parameters and CalDAV discovery; the calendar creation
API creates internal calendars only.

`CALENDAR_ACCESS` or `CALENDAR_EDIT` permits reading within agent management scope.
`CALENDAR_EDIT` permits commands; remote capabilities still constrain writes. MCP functions
retain their global/local policies and active connection. Explicit calendar identities are
checked against their agent and connection. Disabled connections/calendars are excluded from
workers. Task details retain their own authorization. Reading a resource never grants writing.

URLs, credentials, content and snapshots are encrypted at rest. Scheduling boundaries and
identities remain queryable for indexes. The bridge retains HTTPS, public-address validation
and pinning on every request/redirect, bounded responses, and no cross-origin credential forwarding.

## Model and history

- `calendar_feeds`: calendar, connection, timezone, capabilities, sync cursor and lease.
- `calendar_events`: single event or series master, encrypted iCalendar component, revision,
  remote locator and ETag. No separate `remote_object` table is required.
- `calendar_event_exceptions`: exception components with original occurrence identities.
- `calendar_event_revisions`: immutable revision snapshots, including deletion.
- `calendar_occurrences` and `calendar_projection_windows`: disposable local projections,
  indexed by calendar/date range. Long text is not copied into every occurrence.
- `calendar_actions`: local instructions, start/end anchor, signed offset, scope and lateness.
- `calendar_triggers`: action execution for an occurrence, deadline and linked Task.
- `calendar_sync_operations`: transactional write/delete outbox, versions and attempts.
- `calendar_sync_runs`: durable sync stages and failures, including failed reads.

Calendars and events use `HistoryMixin` and soft deletion. Event snapshots include exceptions.
Projection pruning never deletes events, revisions, executions or Tasks. DbAdmin converges
schema/system datasets; event synchronization remains a domain operation. No calendar data
migration is required: this redesign precedes the feature's first use.

## Local date-window queries

Neither HTTP nor MCP event reads/commands contact the provider. `GET /calendars/events` takes
an agent and selected calendars with `period=month`, `week`, `day` or `next30`. `month=YYYY-MM`
selects another month; explicit `start`/`end` supports navigation. Boundaries use the display
timezone and daylight-saving rules. Requests span at most one month and return every matching
event with `total`, `complete` and stale calendar identifiers, without event pagination or
silent truncation. A protective 10,000-occurrence limit requires a narrower date range.
Each occurrence uses a primary-key event lookup; the complete response supplies its own total
without a separate count. This avoids full-history joins when PostgreSQL statistics are still
incomplete after a bulk import.

Single events have permanent projections; recurrence projections cover useful windows and
are cached. Daily maintenance expires caches after thirty days under event locks, preserving
concurrent rebuilds. Browsing an old month never schedules actions or removes future deadlines.
Window responses contain compact metadata; details load full text and exceptions. Stale or
unavailable sources cannot prove that a time slot is free.

Mutations require `expected_revision`. Scope is `series`, `occurrence` or `following`;
`recurrence_key` retains the original identity after rescheduling. Changing the recurrence rule
from an instance splits the series while retaining future exceptions. All-day events retain
dates and exclusive end dates; timed recurrences use explicit timezones. Excessive expansion
fails explicitly in an isolated worker, never presenting partial data as complete.

## CalDAV synchronization

A local mutation and its outbox operation are committed together. `sync_state=pending`
means local intent, not remote confirmation.

The external worker checks every minute. Healthy calendars are polled every five minutes;
pending writes or an explicit request wake synchronization. Concurrency is bounded, with
independent database sessions per branch. A lease and configuration revision fence stale responses.

CalDAV provides discovery, `sync-token` and `sync-collection`. Modified resources are fetched
in `calendar-multiget` batches. Truncated responses are continued before completing the sync.
An expired token triggers full reconciliation. iCalendar subscriptions use conditional ETag
reads where supported. Invalid/incomplete responses never advance the cursor or justify deletion.

Each CalDAV resource has a stable locator and ETag. Creates use `If-None-Match: *`;
updates/deletes use `If-Match` with a strong ETag. Lost acknowledgements are reconciled by
reading the outcome, without duplicate creation. Concurrent remote versions preserve both
contents and block writes until explicit revision-checked resolution. Errors preserve outbox
operations, progressive retry delays, and structured local evidence: calendar, run, operation,
stage, category, HTTP status and code location, without private URLs or contents.

## Actions and Tasks

An action is a scheduled Task admission through the public `app.agent` facade. It may run
before/start/after an event. Several actions may share a deadline with distinct identities.
External calendars require explicit action activation. Read-only events may have local actions;
imported event data never becomes an authorized instruction.

The local worker checks deadlines every ten seconds independently of providers or open views.
It checks activation, revision, occurrence and lateness; overdue actions become `skipped`.
Admission uses a stable key. Tasks whose admission receipts were lost are reconciled before
edits/retries/relaunches. Full context is frozen at admission in Task and the receipt.
`submitted` means that a Task exists; only `Task.SUCCESS` marks an action treated. Missing or
inaccessible Tasks remain unavailable.

The journal filters by event/occurrence and exposes `galaris://task/<uuid>`. Manual relaunches
use a separate key and launch number, preserving the previous terminal Task. Cancelled events
do not produce new actions.

Agenda owns dated commitments and reminders. Goal owns durable outcomes and reviews: never
copy a Goal review into Agenda. Reminder Tasks receive no implicit `goal_id`. A Task may use
its ordinary permissions to start a Process; synchronization/reminders are not Process wrappers.
