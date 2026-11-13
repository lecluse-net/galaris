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
concurrency, independent database sessions and retry backoff.

Actions are locally authorized instructions with a signed offset from event start/end,
optional occurrence scope and lateness policy. They work independently of browsing and
external polling. External calendars require explicit action activation. Local indexed
deadlines admit Tasks through `app.agent`, preserve their canonical URIs and derive outcomes
from Task. Lost Task admission receipts are reconciled before editing, retrying or relaunching;
terminal Tasks remain immutable. Each manual relaunch has a separate idempotency key and
launch number. Full execution context is frozen at admission, rather than copied into every
future occurrence/deadline.

Sync runs retain stages and failures locally, including read failures and interrupted leases.
Structured Loguru records use the existing Logfire bridge and omit private URLs, credentials
and event text. DbAdmin owns schema and system datasets, not recurring business synchronization.
The Agenda/Goal boundary established by decision 0278 remains unchanged.

## Verification

Database integration covers local commands, revisions, source isolation, recurrence exceptions,
rule splitting, Task admission/recovery/relaunches and HTTP authorization. The actual CalDAV
adapter runs against a stateful synthetic HTTP provider boundary for differential reads,
conditional writes, lost acknowledgements, conflicts, token expiry and malformed responses.
Independent PostgreSQL sessions exercise leases and configuration fencing. Volume tests use
10,000 and 100,000 synthetic appointments and verify complete dense-month responses without
source parsing. These tests do not claim interoperability qualification against a live Nextcloud.
