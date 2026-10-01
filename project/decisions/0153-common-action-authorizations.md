# 0153 — Common one-action authorization for MCP and managed runtimes

Accepted on 2026-10-01.

`app.tools` owns durable authorization requests, one-use claims, private payloads,
receipts and notification/wake outboxes. `app.agent` owns the human manager and
versioned agent YOLO policy. Task, conversation and voice contribute lifecycle
guards and wake ports. A reusable MCP credential identifies an agent; it never
selects whichever Task happens to be running.

## Policy and authority

Every native MCP function declares an explicit `enabled` or `ask` default and a
reason. Sensitive mutations, delivery, paid processing and execution default to
`ask`. Third-party capabilities default to `enabled`; their annotations cannot
grant authority. Resolution is connection override, global Tool override, then
software default. `disabled` denies before effect. Absence of an override means
inheritance. Tool, resource and prompt identities are separate.

Mandatory service connections remain mandatory, while humans can configure their
individual functions. Agent ToolAdmin cannot alter mandatory or administrative
grants. Function policy never bypasses an inactive connection, access rights,
provider safeguards, network restrictions or runtime isolation.

YOLO defaults to false and requires an authenticated human web session, explicit
acknowledgement and expected policy version. Reassignment resets it. An agent
cannot enable it. YOLO consumes and audits new requests automatically; an existing
human question remains human. Task `auto_approve`, `@approve` and runtime session
allowlists no longer grant autonomy.

A permanent function choice is compared against the connection, parameters,
native classification and context that prepared its original question. A changed
target or configuration cannot acquire a permanent grant through a stale question.
Older requests without that fingerprint retain one-action review only.

## Binding and lifecycle

An agreement binds agent, human approver, context, runtime, capability, concrete
connection, operation, canonical arguments and relevant configuration. Keyed
fingerprints avoid exporting sensitive values. Arguments and receipts use the
existing encryption primitive. Presentation-only label changes do not revoke
agreements; configuration, scope, target and authority changes do.

The states are `pending`, `approved`, `denied`, `expired`, `invalidated`,
`executing`, `completed`, `failed`, and `outcome_unknown`. Decisions and claims
serialize against live policy. A terminal denial cannot be reasked under a new
callback in the same unchanged scope. Duplicate claims cannot dispatch twice.
An authoritative late receipt can reconcile `outcome_unknown`; it cannot restart
the operation or rewrite a reconciled terminal outcome.

Requests expire after 24 hours and are also bounded by their context lifetime.
Unsettled operations are limited to 50 per agent and 200 per approver. Outbox
leases retry notification independently of effects. Failed delivery remains
visible in the human interface. Closed private payloads and receipts are scrubbed
after 90 days in bounded batches; unknown outcomes retain reconciliation evidence.
Minimal deduplication records remain while a context can still address the action.
Aggregate Logfire metrics contain bounded labels and no action contents.

## Transports and effect boundaries

Native wrappers and external MCP tool/resource/prompt calls share the service.
`galaris.authorization/v1` carries an opaque continuation; execution metadata binds
the exact operation. Unsupported clients receive a pending/refused result rather
than implicit authorization. The continuation is an execution credential, not a
human approval endpoint.

Pydantic AI checkpoints retain deferred tool calls and their identities. Run
result v2 has `waiting_for_authorization` and exact request UUIDs. Task releases
its attempt/lease while waiting; conversation and voice expose the same waiting
disposition. Resumption uses the existing call, without a new model decision.

Managed Codex, Claude, DeepSeek/Cordis and Hermes intercept local SDK actions
before dispatch and carry a server-issued, run-bound credential. Common control
protocol v1 is mandatory for generic HTTP runtimes. The server checks frozen
assignment, revision, principal, objective and current configuration. Runtime
actors retain pending calls outside HTTP responses. Their MCP transport resumes
the original opaque continuation. Restarted unfinished actors report unknown
outcomes and never recreate effects. Cancellation revokes authority before
requesting physical stop; physical stop requires separate runtime evidence.
Hermes retains its native run/SSE transport, adapted to the same claims and
waiting disposition. Its governed SSH connection signature is frozen and checked
against both the server grant and injected runtime configuration.

Hidden system MCP tokens issued to managed runtimes require their run credential
on the ordinary MCP endpoint as well as the authorization control endpoint.
Omitting it cannot turn a stopped runtime into an independent principal session.
Human-created MCP client tokens retain their separate principal scope.

Mail preparation freezes final MIME, recipients and attachments before agreement;
the existing send journal and configured domain approver remain authoritative.
The legacy Mail approval handler still resolves historical pending messages.
Process admission persists a permit bound to its immutable payload; the worker
revalidates it immediately before starting. Integrated continuations retain this
permit after natural Task completion. Revocation blocks effects not yet started.
Lost start replies remain unknown until domain reconciliation proves an outcome.

Browser preserves fine network permissions and hard filters. Generic browser
agreements bind prepared session generation/revision and action arguments. A
blocked network request does not cause automatic replay of the whole click.
YOLO network authority is checked by generation and withdrawn from open channels.
File mutation preflights bind revisions/ETags or bounded content hashes; collection
membership is bounded to 200 entries and unversioned snapshots to 50 MiB. Provider
ACLs and conditional mutation rules still apply at transport.

## Upgrade and limits

DbAdmin expands function overrides with `state` and capability kind. Applied
binary overrides retain enabled/disabled meanings. Historically ignored mandatory
service overrides are archived outside `public` and removed from active policy.
Old Mail opt-ins become `ask`, preserving blocked functions. Completion evidence
makes conversion idempotent and preserves subsequent human choices.

Legacy Boolean columns remain for conservative compatibility: `ask` projects to
false. Do not roll back to an older runtime that ignores sensitive defaults or
current requests. Drain/stop pending runs, preserve the migration audit, deploy
compatible backend/frontend/runtime images together, then synchronize through
DbAdmin. Existing agents receive no automatic YOLO grant.

Agreement is permission for the bound scope, not a universal exactly-once promise.
Unversioned remote SSH file state cannot be inferred from a local path; Hermes
records that limitation rather than claiming a remote content snapshot. A shell
command can have effects beyond explicit file arguments. Runtime isolation and
hard provider guards remain necessary. Custom runtimes must implement and qualify
the protocol; a malicious runtime can execute outside its declared hooks.

Evidence belongs in the repository tests, the functional test catalog and local
qualification artifacts. Synthetic SDK qualification replaces only model and
human/external transport boundaries; it does not prove a production deployment.
