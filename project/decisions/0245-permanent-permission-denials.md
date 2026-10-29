# 0245 — Symmetric permanent permission decisions

Status: accepted. Date: 2026-10-29.

Permanent denial uses the same scope and human authority as permanent approval.
One-time decisions remain bound to the individual operation. Domain approvals that do not
support remembering remain individual decisions.

- MCP functions reuse the existing connection policy: approval sets `enabled`, denial sets
  `disabled`. Withdrawing either sets `ask`. Other connections and functions are unaffected.
- Harness action types reuse `runtime_action_permissions` with an `allowed` boolean.
  Existing rows default to true. Both decisions retain configuration, manager and policy-version
  binding, and can be revoked. Denial blocks dispatch before another question is created,
  including for pending or approved operations. Already executing effects remain unchanged.
- Browser method/origin denials already persist. The all-sites choice now supports either
  decision for configured permission methods and WebSocket. A broad denial takes priority over
  public-access mode; methods outside permission policy keep their current behavior.

Permissions shows both kinds of remembered decisions. `pending=true` lists unanswered network
requests, `pending=false` lists answered decisions; omitting it preserves the unfiltered API.
Removing a decision does not grant access or replay an operation. Chat projects the committed
choice, including when the original pending question predates the permanent-denial option.

Use DbAdmin to add the Harness decision column; no handwritten migration is required.
Verification covers persistence, isolated scope, denial across tasks, withdrawal, human-only
authorization, Chat choices, API projections and responsive component interactions.
