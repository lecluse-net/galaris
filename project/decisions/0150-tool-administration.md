# 0150 — Delegated Service administration

Accepted on 2026-09-30.

ServiceAdmin (`service_admin`) is an optional native Service, connected inactive by default
except when the bundled Galaris assistant is first created for its administrator,
with conversation access initially disabled. Human activation delegates global Service
and connection administration, narrowed by its individual function permissions.
Server-owned identity and live grants are checked for reads and writes; human HTTP
privileges and agent management scopes remain independent.
This initial grant remains revocable. Subsequent synchronization preserves deactivation,
and does not automatically add it to previously initialized assistants.

## Delegation matrix

| Caller / target | Read / diagnostic | Definition | Settings / connections / functions |
|---|---|---|---|
| Agent without the exact live ServiceAdmin function | Denied | Denied | Denied |
| Delegated agent / custom ordinary Service | Allowed | Allowed | Allowed |
| Delegated agent / optional integrated Service | Allowed | Denied | Allowed |
| Delegated agent / mandatory service | Allowed | Denied | Denied |
| Delegated agent / administrative or executable native package | Allowed | Denied | Denied |
| Delegated agent / existing stdio Service | Redacted read only; diagnostic denied | Denied | Denied |
| Human HTTP administrator | Existing RBAC and management scope | Existing restrictions | Existing restrictions |

Human-only packages are ServiceAdmin, AgentAdmin, Galaris Admin, Process Admin,
Lab, Goal management, Skill management and Console. This conservative policy also
applies to AgentAdmin through the shared administration context. Agents cannot
create a custom Service with a reserved native code or launch/configure stdio through
this surface.
Existing stdio parameter defaults and local/global values are also redacted. ServiceAdmin
catalog refresh skips every active stdio source, including other Services connected to the
same agent, reports partial discovery and preserves the existing index. Human HTTP
administration and explicitly authorized runtime execution retain their existing behavior.

## Shared contract and concurrency

The owning Services and Connections services expose administration operations through
their facades. HTTP keeps its authorization boundary and uses the same validation,
projections and persistence primitives. Service mutations serialize on a transaction
advisory lock; connection mutations lock their parent Service. Ordered parent locks
also protect the caller's ServiceAdmin delegation until commit. MCP mutations require
an opaque state fingerprint, including configuration, parameters, function overrides
and dependencies. Connection fingerprints include the parent configuration and global
permissions. Reads by code or agent/Service pair reconcile lost responses.

Parameter batches validate before writing and commit once. Connected custom Services
cannot be deleted through delegated MCP; dependencies are inspected again under the lock.
Human-confirmed cascading deletion is defined separately in
[decision 0219](0219-human-confirmed-tool-deletion.md). Existing domain
foreign-key cleanup and listener reconciliation remain authoritative. Refresh failures
after commit return `persisted=true` with a separate partial refresh outcome.

## Candidate secrets and network boundary

An authorized human can prepare an encrypted, temporary MCP candidate for a selected
managed agent, without sending its credentials through the model. Its opaque reference
expires after 15 minutes, is bound to that agent and exact endpoint, and becomes invalid
on restart. The single-process runtime retains at most 32 candidates; there is no new
durable secret vault. Diagnostic success never saves a Service or runs a remote function.
An agent can adopt the prepared definition explicitly, preserving its credentials
server-side. Ordinary parameter writes refuse secret literals and accept only a
matching candidate reference or explicit removal.

HTTP/SSE diagnostics allow public destinations; an existing human-configured Service or
human-prepared candidate explicitly authorizes its private destination. Metadata,
unspecified, multicast and prohibited link-local destinations remain denied. DNS is
validated and the HTTP connection uses the validated address with the original Host
and TLS name. Redirects and cross-origin SSE endpoints are refused. Secret-bearing
configuration cannot silently transfer credentials to a changed destination.

Diagnostics request identity encoding and reject compressed responses so expansion
cannot bypass the transport byte budget. Diagnostics have bounded concurrency, total duration, remote pages, function count,
response bytes and per-function detail. Truncated discovery is never exhaustive.
Remote schemas and descriptions are untrusted data. Old mounted external tool proxies
resolve current configuration and authorization before each call; credential rotation
applies to the next request, without claiming to cancel an already sent remote effect.

Catalog refresh uses ordinary Python functions owned by `app.services`, with a total
20-second budget. Each agent's results are committed separately and the original exact
function delegation is checked before discovery and before commit. Partial discovery
preserves the index and returns failed/remaining agent identifiers for explicit
reconciliation without replaying an already persisted configuration change. Timeout or
interruption rolls back the current agent and preserves previously committed results.

Processes are reserved for business workflows, such as n8n workflows. Technical catalogue
maintenance creates no Process definition or run. This replaces the earlier integrated
ServiceAdmin engine: DbAdmin removes its exact `service_admin:<agent>:catalog_refresh` definitions,
runs and jobs, settling approval receipts and waiting Tasks before purging. Other workflows
are preserved. Unfinished reconciliation is retried through `service_admin_catalog_refresh`.
