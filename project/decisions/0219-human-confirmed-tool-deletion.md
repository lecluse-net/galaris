# 0219 — Human-confirmed cascading Tool deletion

Status: accepted, 2026-10-23.

## Context

The human Tools page offered deletion but the owning service refused any connected
Tool. Its generic error did not explain the dependency refusal. Administrators need
to remove a custom integration and its configuration together after reviewing impact.

## Decision

`GET /tools/{tool_id}/deletion-impact` requires `TOOL_EDIT` and an editable definition.
It exposes aggregate categories and an opaque confirmation version, never credentials
or dependency content. The human client submits that version with `cascade=true` to
`DELETE /tools/{tool_id}`. Protected integrated definitions remain immutable.

The server locks the Tool and affected dependent rows, recomputes the identity graph
and rejects a stale confirmation with 409. The graph follows inbound FK constraints
as complete tuples, including composite keys. Non-null and cascading dependencies
are removed together; nullable internal cycles are broken before deletion. Independent
`SET NULL` references retain their records. Configuration projections and action
authorizations are removed rather than retaining unusable orphan grants. Exclusive
Process sharing policies and owned run file aliases are also retired.

All persistence changes share one transaction. Failure rolls everything back. Approval
prompts and suspended contexts are notified after commit; notification failures are
logged separately and cannot turn a committed deletion into a reported deletion failure.
External service data and already dispatched remote actions are outside this operation.

The dialog supports loading, errors, retry, dismissal and review after 409. A closed
dialog cannot accept a late preview. Successful deletion invalidates connection state
and parameter caches, including views already mounted in another Tools tab.

The existing dependency-free service/MCP deletion remains the default for callers
without this explicit human confirmation. No schema or foreign-key policy is changed.

## Verification

Real PostgreSQL scenarios cover connected configuration, OAuth, global/local permissions,
approval requests, dependent Process/Messenger data, composite sharing isolation, nullable
ancestry, independent Tasks, stale confirmations and an injected failure before commit.
HTTP checks cover authentication, privilege denial and protected definitions. Component
and assembled journeys cover cancellation, late previews, retry, 409 and successful removal.
