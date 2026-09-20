<p align="right"><a href="../../fr/dev/reliability-operations.md">Français</a> · <strong>English</strong></p>

# Reliability operations

## Schema and topology

See [DbAdmin](dbadmin.md) and [decision 0073](../../../project/decisions/0073-operational-schema-and-runtime-limits.md).
Run one Uvicorn worker per installation. Parameter caches and realtime connections are not
distributed. `STAGED` and `DEGRADED` report discrepancies without preventing a usable app from starting.

## Budgets and retention

Advanced Task settings expose `TASK_ROOT_MAX_TOKENS`, `TASK_ROOT_MAX_COST` and
`TASK_ROOT_MAX_SECONDS` (0 disables each limit). They cover a root and its causal descendants,
including retries. Reservations estimate each active phase: a phase may exceed its reservation,
external harness accounting may be incomplete. Enabling `TASK_BUDGET_SHARE_GOAL` shares these
limits across all tasks in the same Goal, starting with its first task. Archived tasks remain
included; distinct Goals keep separate budgets.
These are admission controls, not provider billing caps. Raising or disabling a limit permits
resumption on the next scheduler pass, within the 60-second admission delay.

The **Usage and budgets** panel loads a snapshot when opened and supports manual refresh.
`GET /api/tasks/<uuid>/budget` uses the task's management scope. It exposes recorded lineage
usage, active phases, estimated reservations and remaining capacity after reservations.
A `null` limit or remainder means unlimited, never zero available. Viewing it enables no
budget and changes no lease or admission state. Expired leases release their reservations.

Default HTTP quotas (1,000/minute/IP and HTTP path, configurable under **Preferences → System**
through `HTTP_RATE_LIMIT_PER_MINUTE`) run after modular route resolution, before
authorization and field validation. Each login endpoint retains its explicit 10/minute/IP
quota. Storage remains local to the worker; quota tests explicitly enable it. Proxy-header
trust is a deployment concern: keep the backend behind its trusted proxy without untrusted
direct access.

`TASK_SCHEDULER_FAIRNESS_SECONDS` promotes old tasks ahead of new requests. Zero preserves
existing priorities. `TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER` limits simultaneous phases across
all agents of an owner (0 disables it). Transaction locks protect lease reservations; expiry
releases capacity. Excess tasks wait at least five seconds, preserving their phase and results.

`INCIDENT_TRACE_RETENTION_DAYS` and `LLM_TRACE_RETENTION_DAYS` default to zero. Positive values
permit hourly batches of at most 100 eligible diagnostic payloads, preserving incident rows,
accounting and references. Public `prune_traces(preview=True)` functions preview the next batch
without mutation. Conversation/process traces and potentially needed task traces are retained.
Back up required traces before enabling retention.

## Signals and diagnosis

`runtime_event_loop_lag_seconds` records event-loop lag.
`scheduler_periodic_*` metrics record maintenance duration and failures.
Readiness includes `loop_lag_seconds` and `monitor_age_seconds`: an alive monitor with no tick for
more than 30 seconds (or three intervals) is not ready. When work waits despite available workers,
inspect leases, budgets and harness limits. Investigate repeated maintenance exceptions and
provider availability. Do not automatically replay external effects to clear a health signal.

Initial startup uses `task_objective_preparation_seconds`, `task_admission_seconds` and
`task_initial_queue_wait_upper_bound_seconds`. Histograms are emitted at the first claim when
the corresponding boundaries were recorded. Every Task source now records enqueue, while
conversation admission additionally measures preparation. The last interval includes
persistence before commit and any pause before the first claim: it is an upper bound, not
evidence of scheduler saturation. Retries and historical Tasks without measurements are excluded.
The previous `task_queue_wait_seconds`, based on `updated_at`/`created_at`, is no longer emitted;
update dashboards without mixing the two series. Task and round details retain these measurements
across restarts, independently of Logfire availability.

`Task.lifecycle_timing` separates queue time, leased processing, user pauses, external waits
and backoff, including a breakdown by phase. Historical Tasks recover processing timestamps
from `llm_calls`; a historical commit time cannot be reconstructed exactly without a recorded
trace. Dispatcher costs are projected from persisted calls even when a truncated response
forces a fallback decision. Repeated updates count one call once; subscriptions retain zero
billed cost. File writes to Messenger record a receipt after upload. Final notifications match
the exact URI and destination and do not resend an already delivered image.
Successful results from the common inference facades use the same accounting, preventing
objective preparation or briefing from replacing a known cost with a local estimate.

Conversation deliveries and Task/Process notifications in `UNKNOWN` can be resolved in the round
detail with evidence and edit privileges within the agent scope. Decisions are recorded per
attempt; active leases and stale attempts cannot be resolved. Resolution sends no message and
replays no work. Check the destination before marking delivered or skipped;
uncertainty does not justify automatic redelivery.

### Verification by transport

This inventory describes the implemented adapters, not every theoretical provider API feature.
Matching message text alone is never a receipt: legitimate sends may have identical content.
Preserve the remote identifier and destination when available.

| Transport | Send key reusable after restart | Available lookup | Handling `UNKNOWN` |
|---|---|---|---|
| Internal Chat | Local canonical journal; no send key in the Messenger contract | Persisted messages and round links | Verify the durable message and destination before resolving |
| Matrix | No: each call generates a fresh `txnId` | Paginated history and event identifiers | Verify remotely; do not call `send_to_room` to search for a receipt |
| Nextcloud Talk | No durable send key in the adapter | Paginated history; file lookup by unique DAV name | Verify remotely and record evidence |
| OneBot | No durable send key in the adapter | Recent history depending on implementation, without a durable cursor | Absence from a limited window does not justify resending |
| Telegram | No durable send key in the adapter | Local journal; no remote history through this adapter | Verify in the destination client |
| WhatsApp | No durable send key in the adapter | Local journal; no remote history through this adapter | Verify in the destination client |

Matrix deduplicates a given remote transaction, but generating a new key on each call does not
provide idempotent crash recovery. Current adapters offer no reliable lookup by a persisted send
key that would permit general automatic reconciliation. Human resolution preserves uncertainty
until evidence is available.

## Browser validation

`make tests-e2e ARGS='--repeat-each=3'` runs the same scenarios on Chromium, Firefox and
WebKit without automatic retries. The PWA test enables the real service worker and replaces
the shell in a volume dedicated to that run; other scenarios block workers to isolate their
contract. Traces and logs remain under `artifacts/e2e/<run>/`.
`GALARIS_E2E_DEBUG=pw:browser make tests-e2e` enables browser process diagnostics.

On Linux, WebKit uses its official GTK port through Xvfb. Headless WPE build 2336
(Playwright 1.62.1) intermittently crashed during MFA input, including with tracing and
the card backdrop filter disabled. Its protocol reports `crashed: true`; this WPE defect
is not considered fixed. GTK retains the same actions, assertions and tracing; this coverage
does not replace testing on real Safari/iOS devices.

Chat catches up on missing HTTP projections while its visible response remains provisional,
then stops at convergence or store shutdown. Without notification permission, it neither
waits for a worker nor queries the native push service. Authorized subscriptions are still
restored.

## Release and rollback

`make build-release RELEASE_REF=<commit>` archives a commit and exports four production images
to `artifacts/releases/<commit>`. Uncommitted changes are excluded. Base images use digests;
system packages are resolved at build time. Promote the same images without rebuilding; a bitwise
reproducible rebuild is not promised.

Run `make tests-release RELEASE_DIR=<directory>` to exercise the exact application images
without application source mounts, test the executors, and scan every image. The resulting
`TESTED_IMAGE_IDS` binds qualification to the manifest. Promote with
`APP_ENV=prod make update RELEASE_DIR=<directory>`: identities are verified, Compose uses
`--no-build --pull never --wait`, and running container images are checked. Without `RELEASE_DIR`,
the historical rebuild path remains available. `MANAGED_HARNESSES` records images included
through `RELEASE_HARNESS_IMAGES_FILE`, or explicitly states that harnesses are external.
Keep the previous bundle and a consistent database/files/keys backup.

An image rollback cannot undo destructive schema contraction. Verify schema compatibility first;
otherwise restore the database, files and keys together.

`UPGRADE_PREVIOUS_IMAGE=<image@sha256:...> UPGRADE_CANDIDATE_IMAGE=<candidate image>
make tests-upgrade` checks populated-schema convergence, login, documents and attachments,
ACL denials, repeated synchronization, then restoration using the previous image. Release CI
requires an explicit previous-image reference. `UPGRADE_FROM=<commit> make tests-upgrade`
remains a source-regression mode using candidate dependencies, not previous-image qualification.
The rehearsal uses no installation volume.

## Progress and pressure

Independent measurement jobs run every ten seconds. Labels contain only engine or notification
kind, never payloads, account identifiers or secrets. Initial staging thresholds:

| Metric | Initial threshold | Response |
|---|---|---|
| `process_oldest_pending_seconds` | > 60 s for 2 min | Inspect admission and engine availability; never resubmit an uncertain effect |
| `process_oldest_observation_seconds` | > 120 s for 2 min | Repair the connection and refresh the same run |
| `process_unknown_runs` | > 0 for 2 min | Distinguish observation failure from uncertain delivery |
| `runtime_event_loop_lag_seconds` | > 1 s for 1 min | Correlate CPU and I/O, reduce competing work and restore failed components |
| `task_oldest_ready_seconds` | > 60 s for 5 min | Inspect capacity and occupied agents |
| `task_expired_leases` | Nonzero for two samples | Inspect event loop, pool and scheduler recovery |
| `conversation_oldest_notification_seconds` | > 60 s for 5 min | Verify the destination and resolve with evidence |
| `buffered_io_reserved_bytes` | > 90% of 1 GiB for 5 min | Reduce buffered workload and inspect active operations |
| `db_pool_checked_out / db_pool_capacity` | > 90% for 1 min | Find long transactions before enlarging the pool |
| `db_pool_acquisition_seconds` | p95 > 0.5 s for 1 min | Inspect queueing, connection establishment, pre-ping and timeouts |
| `temporary_filesystem_free_bytes` | < 1 GiB | Free temporary storage before retrying transfers |

Observation age includes runs never observed. Task notification age uses its last update, not
a delivery percentile. The pool histogram measures acquisition including queueing, connection
establishment and pre-ping, labelled `acquired`, `timeout` or `error`. Hourly
`db_relation_storage_bytes` includes data, TOAST and indexes; `db_relation_estimated_rows`
uses catalogue estimates, without scanning payloads. Initial service objectives are HTTP/login p95
below one second excluding providers, admission p95 below 60 seconds excluding quota waits,
and no expired leases under nominal load. These require measurement on the target installation.

`tests/test_durable_concurrency.py` exercises saturated admission alongside real login,
32 concurrent identity reads, a 4 MiB file copy, real lease renewal, two local WebRTC peers
and off-loop base64 encoding. It measures p95 latency, RSS growth, loop lag and received frames;
it does not measure remote-provider capacity or billing.

## Retention and media repair

`GET /api/processes/retention/preview` requires Process administration and global Agent scope.
It describes the next batch without mutation. Purges handle at most 500 runs and 500 events per
run per pass. Refresh tokens expired for seven days are purged in batches of 500; unexpired
tokens retain replay evidence. LLM accounting survives content-trace expiration. Active Task
causal components, unresolved result consumers and undelivered media bytes protect their runs.

`GET /api/processes/runs/<uuid>/export` provides an administrative diagnostic export scoped
to managed Agents. Events use `after_event`/`next_event` cursors and page sizes
10/20/50/100/500 (default 50). Named secrets and download capabilities are redacted, and
payloads remain sanitizer-bounded. This diagnostic export does not replace a complete
database/files backup. Disable retention during a multi-page export to prevent concurrent purging.

For uncertain media delivery, read `GET /api/multimedia/runs/<run>/deliveries`, verify the remote
destination and wait for `delivery_lease_until`. POST to
`/api/multimedia/runs/<run>/deliveries/<receipt>/resolve` with `attempt_number`, `evidence` and
`decision`: `attach` requires an accessible canonical URI whose SHA-256 matches the receipt;
`retry_absent` requires verified absence and no URI. A timeout is not absence evidence. Refresh
the same Process afterwards; repair never generates another media output. Resolution is audited
and idempotent for the same attempt and evidence. Terminal results remain immutable.

## Transfer budgets

Materialization takes a byte limit and a global deadline (120 seconds by default). HTTP counts
decoded bytes; SFTP and Messenger receive the same bound. Mail descriptors no longer download
attachments and may report unknown size. Entire MIME reads are limited by Mail policy and
`2 × requested bytes + 1,000,000` envelope bytes. A small attachment in a larger message can
therefore be rejected. Admission remains reserved until its IMAP thread finishes; a hard socket
read deadline of 120 seconds complements configured connection/operation timeouts.

SDK/base64 buffers use conservative envelopes within a shared 1 GiB budget, at most four
operations and one per operation identity. Multimedia engines reserve 800 MB, so effective
concurrency can be below four. Voice decoding uses the same admission and batches of 50 frames.
The Talk output track admits 100 frames of 20 ms before applying backpressure; barge-in
invalidates the old generation, including blocked producers. This does not cap total backend RSS.

## Consistent backups and recovery objectives

Stop admission and quiesce application and harness writers before capturing the database,
`/data`, keys and external runtime state. `pg_dump` alone cannot atomically snapshot files.
Archive image identities and keys with the protected backup. Initial objectives are zero RPO
for a frozen maintenance window and 15-minute RTO for a small installation, subject to rehearsal
with its real data volume. Scripts report drill duration, excluding incident detection and remote
backup transfer. Rollback restores the schema and files before using old code/images; never
assume an old image tolerates a schema contraction.

`make tests-restore` starts two independent document/file-receipt writers, waits for at least
ten writes each, then requests and awaits their shutdown before dumping and archiving.
Every restored object, SHA-256 and acknowledged write count is verified. Measured RPO applies
to that maintenance boundary; this does not promise atomic hot backup of external providers.

## Code checks

### Frontend loading and agent evaluation

Frontend builds print `frontend_build_bytes` using `scripts/report-build.mjs`: raw and gzip
bytes for eager static JS/CSS imports, separately from all chunks. The HTML editor is
asynchronous: reading a document should not initialize its editing engine. The measurement
excludes fonts and API calls. The service worker retains its full precache, so offline
installation downloads differ from the initial dependency graph.

With `APP_ENV=dev` (passed to the frontend as `VITE_APP_ENV`), PWA caching is disabled,
including static builds. It is also disabled when using the Vite server. The worker
caches no resources and intercepts no requests; activation deletes old Workbox caches
for its scope without touching other caches. It remains registered for push notifications.

In development, Vite also serves `/sw.js` for browsers retaining an older production
worker. This URL returns the canonical worker compiled as a classic script with an empty
precache, then reopens controlled tabs at their current URLs. It preserves the worker
registration and push subscriptions; new pages then use `/dev-sw.js` and hot reload.
Without this compatibility, `/sw.js` returns Vite HTML, the worker update fails, and a
normal refresh can keep displaying the old screen. The browser test
`pwa-recovery.spec.mjs` reproduces this transition with an actual Chromium worker.

The monthly dashboard uses five SQL queries: totals for both months are grouped, agent
statistics are scoped before aggregation, and available months are combined in SQL.
The browser retains at most six visited months for 30 seconds and shares concurrent requests
for the same month. Refresh reads the server and invalidates cached comparisons. Session,
role or privilege changes clear data and discard late responses. The cache stays in memory;
LLM calls and live activity retain their contracts. Backend Dashboard tests,
`dashboardStore.test.mjs` and `dashboard.spec.mjs` cover these guarantees.

The [public Lab validation corpus](lab-reference-corpus.md) supports repeatable comparisons
of editorial constraints and result evidence.

### Composed guarantees and qualification

The versioned [initial operational objectives](operational-objectives.json)
define metrics, thresholds, duration, diagnosis and repair. Operators must configure these
alerts in their monitoring service; committing the file does not deploy remote alerts.
Local admission delay is separate from provider latency and is not a billing ceiling.

`make tests-load` runs one minute of local WebRTC, authenticated HTTP, encoding, saturated
admission, file copying and lease renewal. `make tests-dbadmin-load` uses 100,000 rows and
concurrent writes to test interruption under a lock, nullable expansion, backfill, tightening
and indexing. `DBADMIN_LOAD_ROWS` accepts 1,000–1,000,000 rows. Both use ephemeral databases.
CHECK/exclusion expressions are recorded directly from PostgreSQL; semantic SQL equivalence
and destructive transformations are not inferred from these observations.

Generic webhooks accept `Idempotency-Key` (1–255 characters). Replaying the same payload
for the same connection returns the original Task. Reusing that key with another payload
returns 409. Requests without a key remain distinct.

Memory revision endpoints accept `limit`/`offset`, default 50, maximum 500; subsequent pages
remain available in the UI. Document browsing does not load revision relationships and
deduplicates keyword facets in SQL. Conversation and Process owners release completed traces
to configured LLM retention while accounting, identity and errors survive. The scoped,
purge-authorized `GET /api/llm-calls/retention/preview` reports protection reasons without
exposing prompts. Existing `/api/llm-calls/history` and `/api/llm-calls/<uuid>` endpoints export
authorized traces before retention; pause retention during a multipage export.

Run `python scripts/memory_orphans.py` inside the backend container to review unreferenced
native files; pass `--after <next_cursor>` for another page. Files younger than one day and
historical revision resources are protected. Save the JSON inventory. Only after stopping
writers may the standalone tool apply `--apply <inventory.json> --quiescent`; references,
size and mtime are rechecked. It never runs automatically and does not replace backups.

Set `UPGRADE_EVIDENCE_DIR=<bundle>` when running `make tests-upgrade` with immutable previous
and candidate images. Successful convergence and coordinated restoration produce
`UPGRADE_QUALIFICATION.json`. `make tests-release` requires it and writes `QUALIFICATION.json`,
bound to all image identities and the upgrade proof's digest. Promotion compares the installed
backend with the qualified previous image (or candidate for idempotent redeployment).
A new upgrade rehearsal invalidates old qualification markers. Fresh installations still
require the bundle's initialization tests.

`make lint` runs Ruff (all Pyflakes checks and loop-variable captures) and ESLint across
JavaScript, TypeScript and Vue in all three layers. Frontend builds also require lint;
invalid templates and prop mutations fail the gate. File-based routes keep `index.vue`
and `[id].vue` names. Strict typing remains enforced through `make typecheck`, including
Vite configuration and bridges.

`make tests-coverage` measures branches in DbAdmin, browser sessions, Task transitions/budgets,
Process, multimedia receipts and bounded IO. Its 95% gate is not whole-product
coverage. Missing branches remain visible in `artifacts/coverage.xml`.
`make tests-mutations` separately proves that weakened transition guards are detected.

## Reproducible growth and volume measurements

`make tests ARGS='app/llm/tests/test_retention_growth.py'` simulates 84 days of creation,
consumption and pruning. Weekly measurements include raw rows, logical bytes, retention
reasons and PostgreSQL physical size. A logical plateau does not imply that MVCC pages
are immediately returned to the system. After consumption, pruning preserves identities,
tokens, costs and business results. Report: `artifacts/llm-retention-growth.json`.

`make tests ARGS='app/memory/tests/test_library_performance.py'` compares a 50-document
page over 100 and 1,000 documents, with 10,000 and 100,000 revisions respectively. It bounds
SQL queries, Python allocations and time, checks ACLs and prevents revision loading during
projection. Report: `artifacts/memory-library-benchmark.json`. Python allocations are not
whole-process RSS.

`make tests-dbadmin-load` measures inspection, nullable expansion, backfill, contraction,
index creation and replay separately over 100,000 rows. A concurrent writer records its
latency; an actual lock wait is observed in `pg_stat_activity` before interrupting and
resuming Atlas. Convergence timings include inspection and planning, not just DDL SQL.
Report: `artifacts/dbadmin-volume-benchmark.json`. These tests use the ephemeral database
exclusively and do not modify development volumes.
