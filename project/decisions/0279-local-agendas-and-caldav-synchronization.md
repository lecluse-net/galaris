# 0279 — Local agendas and background CalDAV synchronization

Status: accepted, implemented.

## Context

The calendar feature has no existing user data. Parsing and rewriting an entire iCalendar
file for every read/mutation does not support large agendas or independent, timely agent
actions. Calendar UI work follows backend qualification.

## Decision

`app.calendar` owns one local model for internal calendars, CalDAV calendars and read-only
iCalendar subscriptions. Agendas/events are historized; event revisions include their
exceptions. iCalendar remains the event interchange format. CalDAV is the preferred external
connection protocol (`caldav.calendar`), configured through standard connection parameters.
No data migration, compatibility route or former full-feed native storage is retained.

All event reads and commands use local persistence. Frontend queries select the current
month/week/day, the next thirty days or another explicit month-sized window. They return
all matching events without event pagination. The total historical event count does not
force source parsing. Occurrences are indexed, compact, disposable projections; recurrence
coverage is cached independently of action planning and expires after thirty days.

Remote locators, ETags and last synchronized revisions belong directly to the event aggregate;
a separate remote-object entity is unnecessary. An idempotency key identifies an operation,
not the remote resource or its concurrent version. A transactional outbox owns remote writes.
The bridge uses discovery, sync tokens, differential sync, batched multiget, conditional
creates/updates/deletes, and explicit conflict preservation/resolution. A local receipt with
`sync_state=pending` never constitutes remote confirmation. Invalid or partial reads cannot
advance cursors or justify deletion. Workers have leases, configuration fencing, bounded
independent database sessions and per-calendar synchronization deadlines.

The connection owns the synchronization interval through a typed standard parameter role,
`sync_interval_hours`: whole hours from 1 to 8760, defaulting to two. The usual connection
editor and global/local inheritance apply; adding a parameter remains an explicit action.
Feed columns cache the effective interval for the scheduler and discovered calendars inherit
it. The legacy primary-feed value remains a fallback until the role is configured. The
calendar update API no longer accepts an interval override. Connection details show no
calendars, tasks or synchronization controls; calendar lists and history belong to Agenda.
Automatic synchronization processes calendars one at a time. Local outbox edits, failed
attempts and interruptions preserve the configured delay; the next attempt is recorded
before network I/O, then checked again atomically when a worker claims the calendar.
Existing short polling deadlines cannot bypass the new interval. Changing an interval
recalculates the connection's calendars' deadlines without changing another connection. Initial discovery,
explicit synchronization requests and credential/source changes remain deliberate refreshes.
Reads and browser refreshes use local persistence and never poll the external server.

Configured calendar sources support public networks and private enterprise networks
(RFC 1918 IPv4 and IPv6 unique-local addresses), including names resolved through internal
DNS. HTTPS and certificate verification remain mandatory. DNS answers are validated and
pinned for each request, including redirects; loopback, link-local, unspecified, multicast
and other non-public special-purpose endpoints remain rejected. IPv4-mapped IPv6 addresses
follow the corresponding IPv4 policy. Redirects never forward credentials to a different
origin; CalDAV discovery and writes retain their existing redirect restrictions.

Actions are locally authorized instructions with a signed offset from event start/end,
optional occurrence scope and lateness policy. They work independently of browsing and
external polling. Task launches are enabled by default for internal and external calendars,
including calendars discovered during synchronization. An explicit per-calendar disable is
preserved by subsequent synchronization. Local indexed
deadlines admit Tasks through `app.agent`, preserve their canonical URIs and derive outcomes
from Task. Lost Task admission receipts are reconciled before editing, retrying or relaunching;
terminal Tasks remain immutable. Each manual relaunch has a separate idempotency key and
launch number. Full execution context is frozen at admission, rather than copied into every
future occurrence/deadline.
An unadmitted early notification that misses its lateness window is deferred to the event
start, retaining its trigger identity and original notification timestamp. Admission still
checks configuration, revisions and permissions and never repeats an already admitted Task.

Sync runs retain stages and failures locally, including read failures and interrupted leases.
Structured Loguru records use the existing Logfire bridge and omit private URLs, credentials
and event text. DbAdmin owns schema and system datasets, not recurring business synchronization.
The Agenda/Goal boundary established by decision 0278 remains unchanged.

Manual requests create or reuse a queued sync run and return its stable identity. The worker
adopts that run. Its bounded JSON progress snapshot exposes timestamped business stages
and network phases while running. Terminal success, conflict, interruption and failure paths
remove the step timeline and transient network/transfer fields, retaining HTTP status,
resource counters, byte counts and failure evidence. Existing historical API responses also
omit timelines. The UI renders live steps only while a run is queued or running.
The bridge reports through an execution-local callback without depending on calendar ORM
internals. Progress commits occur around network I/O, outside local aggregate mutations,
and renew only the current configuration-fenced lease; byte updates are throttled. Unknown
totals remain unknown. Processed uploads and verified writes have distinct counters.
The existing authorized, calendar-scoped journal endpoint can select one run. The shared
frontend monitor follows the requested identity once per second while active, slows when
idle and cancels obsolete reads. Agenda displays an expandable history of the 50 most recent
attempts, without pagination, and inserts each requested run at the top, expanded for live
progress. New synchronization is available in the dialog footer. The connection modal is restricted
to account parameters. Historical summaries never contain private URLs, credentials or event content.
The progress summary carries `calendar_changed`, set only after committed changes to events,
their synchronization/conflict state or discovered calendar metadata. Imported-resource counts
alone are insufficient because replayed identical resources are processed too. A terminal run
refreshes the calendar only when this flag is true, including partial commits before a failure;
the synchronization dialog remains open to display its result.

## Verification

Database integration covers local commands, revisions, source isolation, recurrence exceptions,
rule splitting, Task admission/recovery/relaunches and HTTP authorization. The actual CalDAV
adapter runs against a stateful synthetic HTTP provider boundary for differential reads,
conditional writes, lost acknowledgements, conflicts, token expiry and malformed responses.
Database/HTTP coverage checks connection-scoped hourly schedules, existing polling deadlines,
outbox edits, failures, interruption recovery, validation, persistence and authorization.
The connection component journey checks per-calendar settings, failed-save recovery,
reopening and read-only access on mobile and desktop.
The synthetic provider resolves to a private address through the real transport resolver;
replacing that resolver previously hid the incompatibility with enterprise networks.
Transport tests cover private/public IPv4/IPv6 endpoints, DNS pinning, redirects and rejected
special-purpose addresses without making external network requests.
Independent PostgreSQL sessions exercise leases and configuration fencing. Volume tests use
10,000 and 100,000 synthetic appointments and verify complete dense-month responses without
source parsing. These tests do not claim interoperability qualification against a live Nextcloud.
