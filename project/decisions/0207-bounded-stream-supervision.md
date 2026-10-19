# 0207 — Bounded inference streaming and incremental supervision

Date: 2026-10-19
Status: accepted

## Context

Physical inference streaming repeatedly serialized unchanged request histories and
cumulative output into full WebSocket call updates. Provider reads waited for each
supervision write and delivery. The SDK adapter materialized its cumulative response
and parsed partial tool JSON for every token. Transport and semantic journal readers
woke each other even when their representation had no new events.

## Decision

Keep the durable inference journal and commit-before-delivery guarantee. Insert event
batches in bulk, preserve lifecycle-before-call locking and read the latest event only
after acquiring the call lock. Read cursor pages and their attempt status in one short
transaction. Distinct wire/message wakeups avoid unnecessary reads; lifecycle changes
wake both, and periodic reconciliation still handles lost advisory notifications.

The SDK adapter materializes only changed parts at batch boundaries, with time and
size limits, and applies committed changes without copying the full accumulated result.
The raw transport retains its 50 ms/64 KiB bound: increasing read-ahead can delay runtime
guards and provider interruption.

Each provider stream owns at most one asynchronous supervision worker, limited to four
updates per second. Changes received during an update or its throttle interval schedule
one trailing flush even if the provider pauses. There is no pending snapshot queue.
Cancel and join that worker before
terminal persistence. Partial writes check and lock the running call before updating;
they never modify a terminal call. Terminal trace persistence remains authoritative.

WebSocket `llm_call.progress` carries changing metadata and versioned text/reasoning
appends or replacements, without prompts, request histories or raw responses. Tool
snapshots are sent only when changed. Create and terminal `update` events retain their
full contracts. Every emission retains resource authorization, using an existence query
instead of loading the full trace. Clients apply deltas only to the exact base revision,
recover gaps through one in-flight authorized call read, and reject obsolete responses
after a terminal state, session change or unmount. UTC revisions retain microseconds.

Chat runtime reducers retain immutable root replacement with shallow reactivity. Historic
message text is projected independently of live fragments. Ordered live fragments accumulate
outside Vue in one bounded state and render at most every 50 ms; state transitions remain
immediate and navigation/disconnection discard obsolete buffered work. No schema, provider credentials,
retry policy, tool execution semantics or production setting changes are needed.

## Verification

Synthetic PostgreSQL measurements cover large unchanged histories and cumulative output.
Regression scenarios cover bounded slow supervision, terminal immutability, separate
wakeups, durable readback, cancellation, concurrent subscribers and recovery guards.
Browser scenarios cover Unicode deltas, lost-batch recovery, terminal safety and existing
Chat/Task/LLM consumers. The earlier rollback-only inference fixture could not represent
concurrent supervision; inference tests now use independent connections and real commits
in an ephemeral database. Measurements remain local artifacts, never production data.
