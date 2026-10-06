<p align="right"><a href="../../fr/admin/tool-administration.md">Français</a> · <strong>English</strong></p>

# Delegate Tool administration

**ToolAdmin** (`tool_admin`) administers the global Tool catalogue, shared parameters,
agent connections and function permissions. Its connection starts active when the bundled
Galaris assistant is first created for the administrator, and inactive for other agents.
Later deactivations remain preserved; previously initialized assistants do not automatically
receive this new grant. Conversation access is initially disabled. Human activation delegates global administration,
narrowed by individual function grants; it does not inherit the agent manager's human rights.
AgentAdmin retains its own scope and delegation.

## Enable and restrict delegation

In **Configure → Tools & connections → Connections** (`/tools?tab=connections`), enable
the agent's ToolAdmin connection. In **Authorizations**, limit functions to the intended work.
For Chat, also enable the Tool's conversation mode under **Tools**; long operations follow
the normal conversation deferral rules.

Reads and mutations check the active connection and exact function permission on every call.
Integrated definitions are read-only. Mandatory Galaris, Conversation, Memory and File Sharing
services can be inspected, but their settings and connections remain software-owned.
Only humans can delegate or modify ToolAdmin, AgentAdmin, Galaris Admin, Process Admin, Lab,
Goal management, Skill management and Console. A sequence of agent commands cannot grant
administrative capabilities to its caller.

## Test and create with a secret

### Prepare file indexing

The standard **File indexing** parameter (`tools.fileindexing`) offers **Disabled**,
**Only files already known**, and **Discover & index all available content** when the provider
supports it. The latter discovers content accessible through the connection; the known-files
mode does not traverse the provider.
Under **Tools → Global parameters**, set the value inherited by the Tool's connections;
under **Connections**, retain inheritance or override the value for an agent.
An imposed global value prevents local overrides, as with other parameters. **Only files already
known** is the default for compatible providers. Console also exposes this parameter for its
embedded target. Existing preferences
are carried over during synchronization and preserved through upgrades. Each agent's source
permissions remain enforced, and the integrated definition remains protected.

Console, AFFiNE and Grav currently support only files already known; Nextcloud also offers
discovery and indexing of all available content. Mail remains excluded. Messenger attachments,
including those belonging to mixed Tools, enter the catalogue on receipt or history import.
Listings create an entry for the requested directory and each returned file
or directory; searches create entries for their results. These observations are journaled
with canonical URIs, then immediately projected into private `file`/`directory`
Memory entries, searchable by name, URI and metadata without waiting for Dream. Disabling
or reconfiguring a connection removes its old entries from search; access to the source
file is also checked. Dream performs automatic traversal while idle: one work item lists
one direct directory page (at most 500 entries), then subdirectories wait for later turns.
The **File indexing and enrichment** mechanism shows pending work, processed directories
and retries; discovery makes no LLM calls.
In **Preferences > Dream**, **File rescanning** renews each eligible scheme every Monday
at midnight by default, in the application time zone. The other choices are every day at
midnight and disabled. A missed schedule catches up at the next available turn; an active
traversal or one already started for that schedule is not duplicated.
Known URIs are checked periodically without
traversing the provider. Only complete listings and proven deletions retire catalogue
entries; an unavailable source remains distinct from a deleted source.

Open an entry in **Memory**, edit its title or content, then save.
Manually edited fields are preserved during subsequent file observations.
Editing updates the Memory entry; the catalogue continues to update source references
and the file bytes remain with their provider.

Dream computes **SHA-256 over the complete file bytes**, without an LLM and independently
of the 32 MiB analysis limit. Identical files owned by the same agent then share one Memory
entry, one summary and multiple URIs, including across storage and messaging providers.
Other agents retain their own entry. Personal notes, titles, sources and relationships
survive grouping. A changed copy moves to another entry; a missing copy retires only its location.

In a Memory entry or the graph's file inspector, **File locations** shows available URIs
and thumbnails. Clicking a card opens its preview with fullscreen and original-download
actions. Images, PDF, text, HTML, audio, video and 3D models use the existing viewers;
Office files are converted to PDF for preview. Formats without a viewer remain downloadable.
Each access rechecks the connection and source resource; no file bytes are added to Memory.
Previews are bounded to 512 MiB, and converter-specific limits still apply.

In **Monitor → Dream → Indexing**, select the agent. Enter an eligible root, such as
`nextcloud://`, and choose **Index now**. The table shows encountered entries, complete
directories and errors; active runs can be cancelled. Partial coverage indicates a volume,
depth or pagination limit. Terminal diagnostics are retained for 30 days. Observation
failures are repaired with backoff without replaying external effects; **Retry repairs**
explicitly restarts terminal failures. Existing Dream
media options enable versioned enrichment while preserving personally curated content.
Dream then analyzes supported files to enrich their descriptions; directories remain
catalogue entries without automatic summaries.

Dream also prepares thumbnails of identified files and document attachments, without
AI calls and independently of media-analysis options. Supported images, videos, PDF,
Office, HTML, text and self-contained 3D models retain their PNG in durable storage.
Opening and reopening a graph resource reads that PNG; a changed version receives a
new derivative. The cache never bypasses permissions or a disabled connection.

### Create the Tool

1. Inspect `tool_admin_list` and read any existing definition with `tool_admin_get` to avoid duplicates.
2. A human opens **Tools → New Tool**, enters its code and label, declares a `token` parameter
   of type `password`, and configures HTTP or SSE MCP with Bearer authentication and `auth.param=token`.
3. Under **Test connection**, enter the temporary secret, select the recipient agent and choose
   **Prepare candidate for this agent**. Send only the resulting reference. It expires after
   15 minutes or a backend restart, is bound to the agent and prepared definition, and is held
   encrypted in bounded process memory.
4. The agent calls `tool_admin_mcp_test(candidate_reference=...)`. This negotiates MCP and
   discovers functions without saving or calling business functions. An empty catalogue can
   be successful. Results include the timestamp, duration, stages, failure category and truncation.
5. After success, `tool_admin_create(candidate_reference=...)` explicitly adopts the definition
   and credentials server-side. A successful test never implies persistence.
6. Use `tool_admin_connection_create` to create an initially inactive connection. Configure
   parameters and permissions, test with `tool_admin_connection_test`, activate with
   `tool_admin_connection_update`, then inspect effective functions.

An agent can create a credential-free definition directly with `definition`. New secrets use
a human reference; secret literals are refused in agent commands. Responses expose presence,
origin and forced state, never credentials. Closing the test clears temporary inputs and the
displayed reference. Connection diagnostics resolve values like the runtime and can test an
inactive connection without enabling it. Remote descriptions and schemas are untrusted data.

Direct diagnostics allow public destinations. A human-configured Tool or human-prepared candidate
explicitly authorizes its private destination. Metadata services, multicast, unspecified and
prohibited link-local addresses remain blocked. The transport uses the validated DNS address,
preserves Host and the TLS name, requests uncompressed responses and refuses compressed
responses to enforce its byte budget. Redirects and cross-origin SSE endpoints are refused.
Changing the destination requires a separately prepared definition; credentials from an old
destination are not transferred automatically. ToolAdmin does not configure or execute stdio;
existing definitions remain recognizable in redacted reads.
Their settings, permissions and connections are read-only, with parameter values redacted.
ToolAdmin refresh skips all stdio sources connected to the selected agents and reports
partial discovery without pruning their existing index.

## Parameters, permissions and commands

The `connection_schema.params` definition accepts an optional `label` for each parameter.
Forms display it alongside the technical code and description. For `string` and `integer`
parameters, `options` defines fixed choices; each entry has a `value` (the stored string) and
an optional `label` (the displayed text). For example:

```yaml
connection_schema:
  params:
    region:
      type: string
      label: Service region
      default: eu
      options:
        - value: eu
          label: Europe
        - value: us
          label: North America
```

Choice values must be non-empty, unique and compatible with the parameter type. A non-empty
default must be one of the choices. Without `options`, the usual control remains available.
Connections, global parameters and MCP tests display these choices; local and global writes
reject values outside the list. YAML import/export preserves this metadata.

For built-in Tools, the backend supplies a translation key in `label`, for example
`tools.connectionParamLabels.default_output`. The frontend translates parameter and choice
labels into French, English and Chinese. Custom Tool labels are displayed as entered,
without translation.

Local values override global values unless a global value is `forced`. Without either value,
the declared default applies. Omission preserves a value; `clear=true` explicitly clears it.
A secret can be preserved, removed, or replaced through a `secret_reference` bound to the same
code and endpoint. A mask never replaces a secret. Entire batches validate before writing
and persist in one transaction.

Functions resolve **connection override → global state → software default**. Modes are
**Enabled**, **Disabled**, and **Ask**; **Inherit** (`default`) removes an override. Sensitive
native functions default to Ask; third-party MCP capabilities default to Enabled.
A global denial can therefore be overridden by an explicit local enable;
`tool_admin_function_set` reports such overrides. `effective` describes resolved permission;
`available` also includes activation, runtime and conversation context. Discovery under one
connection does not establish another agent's access.

## Answer an action request

In **Permissions** (`/connection/permissions`), individual requests are separate from remembered
network permissions. Open **Review request** to inspect arguments, agent, approver and expiry.
**Allow this action** covers one operation; **Deny this action** prevents its continuation.
Where offered, **Always allow this function** explicitly changes this connection's function
mode to Enabled, including future arguments. It is unavailable for runtime-local commands.

Only the authorized approver can answer; viewing or management privileges cannot answer on
their behalf. If no private channel is available, the request stays accessible here and
delivery failure is shown. Requests expire within 24 hours, also bounded by their context
lifetime. Task releases its worker while waiting and retains the call for resumption.
Duplicate, expired or stale-configuration answers cannot dispatch a second operation.
**Unknown outcome** requires reconciliation, never automatic redispatch. Cancelling a request
does not undo an effect already sent.

Humans can configure mandatory service functions; their connections and definitions stay
protected. MCP resource and prompt policies are distinct from same-named tools. Update old
binary clients: Ask does not mean Enabled.

## Configure YOLO

On an agent's form, in the **General** tab, **YOLO mode — automatically approve authorizations**
appears below the Harness selection, after the identity fields, and defaults to off.
Enabling it opens a warning about commands, deletions, messages, costs and disclosures.
Cancel or dismiss the dialog to leave it off; the orange **Enable YOLO** button confirms activation.
The form appears as soon as it opens; manager and Harness lists load afterward. Profiles and
voices refresh when the **Models** tab opens. Active
mode is visible on the agent, and automatic decisions are identified in action requests.

YOLO approves new requests for this agent, including runtime actions. Existing human questions
remain human. Disabled capabilities and domain access rights still apply. Turning it off
withdraws unconsumed automatic agreements and restores human approval for subsequent actions.
Reassigning the manager resets it. An agent, Task or `@approve` cannot enable it. Mail retains
its domain approver when distinct from the agent manager.

For an upgrade, prepare compatible backend, frontend and runtime images, stop old active runs,
then use normal DbAdmin synchronization. Effective binary overrides are preserved; previously
ignored system restrictions are archived. Old Mail opt-ins become Ask without enabling blocked
functions. Previous Task/session approval never becomes YOLO. Preserve the audit when rolling
back; do not use an older runtime that treats Ask as authorization.

| Need | Functions |
|---|---|
| Catalogue and definitions | `tool_admin_list`, `tool_admin_get`, `tool_admin_create`, `tool_admin_update` |
| Dependencies and deletion | `tool_admin_impact`, `tool_admin_delete` |
| Shared settings | `tool_admin_global_params_set`, `tool_admin_conversation_set` |
| Diagnostics and functions | `tool_admin_mcp_test`, `tool_admin_function_list`, `tool_admin_function_get`, `tool_admin_function_set` |
| Connections | `tool_admin_connection_list`, `tool_admin_connection_get`, `tool_admin_connection_create`, `tool_admin_connection_update`, `tool_admin_connection_delete` |
| Local parameters and tests | `tool_admin_connection_params_set`, `tool_admin_connection_param_delete`, `tool_admin_connection_test` |
| Permissions and indexing | `tool_admin_connection_function_list`, `tool_admin_connection_function_set`, `tool_admin_catalog_refresh` |

Impact includes connections and direct Tool references, including workflows and messaging
identities. These dependencies block deletion and contribute to its version; removing a
Tool never implicitly removes their business data.

Lists use `offset` and `limit`: 50 by default, at most 500. Diagnostics also bound remote
pages, duration, concurrency, bytes and schemas. `tool_admin_function_get` returns function details.

## Conflicts, propagation and recovery

Mutations of existing objects provide `expected_version` from their latest read. This fingerprint
covers definition, parameters, permissions and dependencies. On `conflict`, read and reconcile
rather than blindly retrying. Reconcile a lost response by Tool code or agent/Tool pair.
Connection identity is immutable in the agent command. Deleting a linked Tool refuses cascades:
remove its connections explicitly, inspect technical references, read again, then delete using
the current fingerprint.

After a mutation, `persisted=true` confirms storage even when refresh is partial. Affected
catalogues reconcile without pruning after incomplete discovery. Refresh calls the Python functions
in `app.tools` directly, with a 20-second budget and permission checks before and after each agent.
Each agent's results are committed separately. Partial results identify `failed_agent_ids` and
`remaining_agent_ids`; look up their connections and retry `tool_admin_catalog_refresh` with those
`connection_ids`, not the already persisted mutation. No Process is created.
DbAdmin convergence removes obsolete technical `catalog_refresh` definitions and their runs,
after resolving any waiting Tasks.

Old native and external sessions recheck permissions. Following external calls use rotated
credentials. Revocation does not cancel a remote effect already sent. The search index never
grants permission.

The structural contract is recorded in [decision 0150](../../../project/decisions/0150-tool-administration.md).
