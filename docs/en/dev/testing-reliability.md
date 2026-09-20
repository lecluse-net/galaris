<p align="right"><a href="../../fr/dev/testing-reliability.md">Français</a> · <strong>English</strong></p>

# Chat and agent execution reliability

Run `make quality` for the local quality gate, including `make tests-e2e`.
The `Quality` workflow also runs the browser journeys and retains diagnostics
for seven days. Automatic browser retries are disabled.

## Isolated browser stack

`compose.e2e.yaml` uses an ephemeral PostgreSQL database, the production frontend
build, real API, Socket.IO and schedulers. It shares no application network, host
ports, existing data volume or `.env` credentials. Its internal network blocks
external requests. The runner shares the frontend network namespace so it can
use `localhost`, a browser secure context, without crypto polyfills.

The test-only server `back/tests/e2e_app.py` scripts the conversation controller,
Task objective generation, model resolution and internal harness stream.
Admission, authorization, persistence, leases, attempts and delivery are real.
It refuses any environment other than `APP_ENV=test` with `db-e2e/test_db`.
These tests do not evaluate model intelligence or actual provider compatibility.

`tests/test_codex_provider.py` adds transport-level coverage: one case traverses
actual objective generation, Pydantic AI structured output, the SDK, the Responses
proxy and the Codex bridge against a simulated HTTP provider that requires SSE.
Related cases cover the final result, provider failure, missing terminal events
and authentication refresh.
They also reproduce a Codex terminal `output: []` after completed
`response.output_item.done` events: complete results are reconstructed in native
order without promoting unfinished fragments to valid output.

Journeys cover incremental output, durable handoff and reload, tools, offline
completion/reconnection, room isolation, multiple tabs, mobile viewport, partial
failure and conversation → Task → result delivery. Completion is controlled by
a barrier rather than arbitrary sleeps. Reports, traces and service logs are
saved in `artifacts/e2e/`.
The second tab and its reload must restore text already generated before the
completion barrier is released, exercising the active HTTP snapshot.
They also verify session restoration behind a proxy with a non-default port.
WebSocket unit tests protect pending connections against concurrent consumers
and cover disconnection, reconnection and session changes. Service workers are
disabled in these journeys; PWA update behavior needs separate coverage.
CI repeats every journey three times in the same isolated stack. Live/durable
handoff also covers overlapping HTTP reads: activity is read after messages,
and an older response must not erase an already known durable link.

```sh
make tests-e2e ARGS='--grep reconnect'
make tests-e2e ARGS='--repeat-each=5'
make tests ARGS='tests/test_conversation_concurrency.py tests/test_driver_conformance.py'
```

## Backend concurrency and contracts

Each backend test invocation owns a distinct Compose project. Tests requesting
`committed_database` get a private clone of a template frozen after DbAdmin
synchronization and before pytest, independent connections and real commits.
The clone is dropped even
on failure. Coverage includes concurrent round/Task claims, expired leases with
and without effects, and an abrupt worker process exit after committing a claim.
An old owner cannot build, complete or fail a round reclaimed by another worker.
Process tests also reject payload changes from late callbacks or snapshots,
including duplicate terminal statuses. Slow publication must let generation
continue and converge through a cumulative snapshot without queuing fragments.

The common conformance kit runs against Internal, Hermes and OpenAI Messages
adapters with scripted I/O. Adding a driver requires a new conformance case.
Frontend tests exhaust every contiguous partition of a short Unicode response,
including duplicate delivery, and verify reset followed by stale redelivery.

## Protecting against an observed regression

1. Capture the trigger, durable state and event sequence using anonymized data.
2. Verify the test fails before fixing the runtime.
3. Test the affected contract and add a browser journey for visible failures.
4. Synchronize with events/barriers, not arbitrary delays.
5. Check durable effects and reload behavior, not just event emission.

Extend this suite with crashes around delivery commits, ambiguous external
effects, plans and child tasks, long sessions, and separately budgeted real-model
evaluations. Controller-port tests alone do not prove these properties.
