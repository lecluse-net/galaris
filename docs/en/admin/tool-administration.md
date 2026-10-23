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

Under **Tools**, **Custom tools** opens by default, before **Galaris built-in tools**.
These subtabs separate tools you add from those provided by the platform. Creating or importing a tool automatically
shows the saved tool’s subtab. Under **Connections** and **Authorizations**, the **Filter by
tool** selector groups choices under **Galaris** and **Custom**. The connection form's **Tool**
field uses the same sections for the tools allowed in that form. List badges identify the
same origin; optional integrated Tools stay in the Galaris group when disableable, while
their definitions remain protected. A dedicated bridge does not create a standard Tool:
Tools using Nextcloud, AFFiNE or a messaging bridge remain custom. n8n is no longer created
automatically; an existing entry remains custom, with its process references and history.

In the **New tool** form, enable at least one capability (MCP, API, file sharing,
messaging or listener) before creating the Tool. Without an enabled capability, **Create**
is disabled and a message explains what is missing.

### Delete a custom tool

Under **Tools → Custom tools**, click the tool’s **Delete** action. The confirmation calculates
and displays related data to remove: agent connections, shared and local parameters, permissions,
approval requests, OAuth accounts and any other dependent data, including messaging and processes.
**Cancel**, the close button and the backdrop dismiss the impact without deleting anything.
An unavailable impact must be reloaded before confirmation becomes available.

Confirmed deletion is permanent and transactional. If the affected scope has changed since the
impact was opened, the server rejects that confirmation; the interface refreshes the impact and
requires another confirmation. Tasks, goals and other independent resources linked by optional
references are retained without those references. Other tools’ data is retained. This operation
does not delete external service data or cancel actions already started there.

Protected built-in definitions remain non-deletable. ToolAdmin MCP keeps its dependency-free
deletion rule; the cascade described here requires human confirmation through the interface and
the Tool editing privilege.

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

## Connect an MCP server with OAuth

Under **Connections**, open the agent’s active **HTTP** or **SSE** MCP connection
and click **Connect account**. Sign in with the provider and approve access. Galaris
retrieves and stores the token automatically. OAuth belongs only to the connection:
the usual flow requires no Client ID, scope or secret, and there is no OAuth setting in the Tool.
If a connection already exists for that agent and tool, the button reuses its saved
parameters and activates it if needed, even when it is absent from the displayed list.

Galaris discovers the provider’s capabilities and stops as soon as setup succeeds:

1. It uses a direct return to Galaris with an existing client, public Client ID Metadata
   Documents (CIMD), or Dynamic Client Registration (DCR), according to availability.
   Access through `http://localhost:<port>` or `http://127.0.0.1:<port>` returns directly
   to that address without a script, even when `APP_HOST` contains a domain name. The browser
   must run on the computer making Galaris available on that port.
2. If preparation of that flow is refused, it tries device authorization when advertised
   by the provider. Open the proposed page and confirm the displayed code; no installation
   is required. Galaris respects polling intervals and slowdown responses, then shows the
   connected account.
3. The local relay below is offered only as a last resort when the direct callback is
   refused and no flow without a relay can be prepared.

Dynamic registration starts with a public client, then tries advertised Basic or POST
client authentication if the provider requires a generated secret. Requested grants and scopes
follow provider metadata. A provider omitting its PKCE methods is tried with S256; Galaris
never removes PKCE to obtain authorization.

When no automatic registration is available, the connection asks for a pre-registered
OAuth application’s credentials and displays the required callback URL. An optional secret
is encrypted with the grant and is not returned to the browser. Network errors, unavailable
responses, consent denial, or an expired code do not automatically switch methods.
Other connections remain unchanged.

On failure, the connection keeps the error visible and includes the service’s HTTP status
and OAuth error code when available. **Retry** repeats the failed action. Raw provider
responses and tokens are never displayed.

When flows without a relay are unavailable, Galaris tries a local callback registered
under its own name. If accepted, the connection offers
a **connection relay** download. On the browser’s computer, run `python3 galaris-connect.py`
from the download folder (Python 3 required, no dependencies to install). The relay listens
only on `127.0.0.1:3334`, opens the provider, then returns the browser to Galaris. It closes
after the callback or ten minutes; if the port is busy, close the other relay and restart.
If the browser does not open, use the authorization link shown in Galaris after starting the relay.

The relay receives only the temporary PKCE-protected code: no token or Galaris session
is sent to it. The new tab finds the request using a local state/connection association
that expires after ten minutes. The API still verifies permissions and the initiating user.
Galaris can stay private: the browser must reach its `APP_HOST` address, through a VPN if
needed, and the server must reach the provider.

If the service also rejects the local callback, it returns `invalid_redirect_uri`.
The message includes the exact URL, built from `APP_HOST` followed by
`/connection/oauth-callback` for the web flow, or the local address attempted as a fallback.
Check HTTPS, the domain name, and the provider’s redirect
rules. An address declared only in a hosts file or internal DNS can work in the browser
while being rejected by the remote service. This code alone does not establish an allowlist
requirement: confirm the reason with the provider before requesting an additional allowed URL.
Retrying without changing the address or the service’s rules does not resolve this refusal.

Authorization belongs to that agent connection. Tokens and registered client secrets are
encrypted and never appear in API parameter responses or YAML exports. Tokens refresh
automatically when the provider issues a refresh token. Expiry without renewal or revocation
requires authorization again. **Disconnect account** removes local tokens and pending requests;
to revoke the provider's consent too, use its own authorized-applications screen.

A callback expires after ten minutes and can be used only once. After denial or failure,
start again from the connection. Changing the agent or MCP URL invalidates
the previous grant. Galaris function permissions still apply. These methods require MCP OAuth
metadata; the authorization-code flow uses PKCE S256. They do not apply to stdio or REST APIs.
HTTPS is required except on localhost. A private server can use OAuth endpoints on its own origin;
other discovered origins must be public.

## Enable a REST API

In **Tools → New tool**, or when editing a configurable Tool, select **Enable API**.
One Tool can provide both MCP and REST. The **REST API** tab configures the base URL,
authentication (none, Bearer, header, Basic or query parameter), timeout and maximum response
size. No operation catalogue or OpenAPI document is required.

Enter the HTTP(S) address directly in the **REST API** tab, as with MCP:
it belongs to the Tool and is shared by all its connections.
Enabling the capability proposes the `api_token` (password) parameter. Select connection
parameter names for authentication and additional headers; never put a token in the URL
or calling code. For Basic authentication, also declare a username connection parameter
and select the secret password parameter.

Enter credential and header values in **Global parameters** or **Connections → Edit**. Existing inheritance,
overrides, imposed values, encryption and masking apply. Definitions and YAML exports
contain only parameter names for these values. Disabled connections and connections belonging to another
agent cannot be used.

REST endpoint permissions belong exclusively to the token in the third-party service.
MCP **Enabled / Disabled / Ask** permissions do not filter REST calls. The application
facade is available to future Code and Process consumers; it introduces neither a generic
MCP tool nor a public HTTP proxy. Redirects are not followed, HTTP errors retain their
status, and requests are never retried automatically. Remote job tracking and callbacks
will be addressed separately.

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

Console and AFFiNE currently support only files already known; Nextcloud also offers
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
Office files and spreadsheets can display a first-printed-page thumbnail, with original download
and no full-screen viewer. Other formats without a viewer remain downloadable.
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
Office, HTML, text and self-contained 3D models retain a lossless WebP within 320 × 320 pixels,
preserving proportions and transparency in durable sharded storage.
Opening and reopening a graph resource reads that WebP; a changed version receives a
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

In a custom Tool form, each driver parameter list ends with **New parameter…**.
This action adds a parameter to the right-hand panel with a unique name and the appropriate
type, then assigns it to the current field. The parameter and its assignment are saved with
the Tool; closing without saving discards these additions.

Deleting a parameter used by an active configuration or holding a global value requires
confirmation and lists the affected configurations. **Cancel**, closing and clicking the
backdrop preserve the parameter and its assignments. After confirming, reassign affected
fields before saving the Tool.

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
**Enabled**, **Disabled**, and **Ask**; **Inherit** (`default`) removes an override.
In the **Authorizations** matrix, **Global (all)** and **This connection** offer Enabled, Disabled and Ask.
Only the applicable rule is selected: an agent override leaves global buttons unselected
but clickable. Selecting a global mode saves that rule and atomically clears the selected
connection's override; other connections retain their exceptions. With no saved global rule,
the software default is displayed when inherited. `default` remains the API inheritance
value; the UI returns to inheritance by selecting a global rule.
Successive local choices are saved in order; a failure is reported and triggers a rule reload.
Saving policies does not wait for remote MCP discovery.
Sensitive native functions default to Ask;
third-party MCP capabilities default to Enabled.
A global denial can therefore be overridden by an explicit local enable;
`tool_admin_function_set` reports such overrides. `effective` describes resolved permission;
`available` also includes activation, runtime and conversation context. Discovery under one
connection does not establish another agent's access.

## Choose Browser access to public sites

Under **Tools & connections → Tools**, open the Browser's **Global parameters**.
**Public site access** (`public_access_mode`) offers **Public sites allowed** (`allow`, initial choice for new installations) to avoid
per-site requests, or **Per-site approval** (`ask`).
Existing instances keep their choices; if this parameter was absent, the upgrade adds `ask`
to preserve their behaviour. Clearing the global value also restores the `ask` fallback.
Agents can override the choice on their connection unless the global setting is forced.
Destination filters and remembered denials per method still take precedence.
Localhost, loopback and private networks remain blocked by default; **Local network access**
only enables separate approval requests for them. Returning to per-site mode keeps no implicit
approval from public mode. Browser function policies remain separately configurable under
**Authorizations**.

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

Expiry releases the task's authorization wait, including when a late answer detects it.
A decision received before a voice turn enters its waiting state remains queued until
the turn suspends. Interruption after dispatch leaves the action's outcome unknown;
it does not permit automatic redispatch.
If a Hermes run that may have produced effects disappears, it ends in error with its
history preserved, without remaining in an authorization wait or restarting automatically.

Humans can configure mandatory service functions; their connections and definitions stay
protected. MCP resource and prompt policies are distinct from same-named tools. Update old
binary clients: Ask does not mean Enabled.

## Explicit permissions

Ask actions require a human decision or a matching remembered permission per function or
runtime action type. There is no global automatic approval mode. Reassigning the manager
invalidates remembered runtime permissions. Blocks, domain rights and context restrictions
remain enforced after any agreement.

Normal DbAdmin synchronization removes `agents.yolo` and `agent_authorization_changes`.
Unconsumed legacy automatic approvals are invalidated before execution; completed action
history is retained.

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
