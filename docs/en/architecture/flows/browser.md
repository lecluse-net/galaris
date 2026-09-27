<p align="right"><a href="../../../fr/architecture/flows/browser.md">Français</a> · <strong>English</strong></p>

# Agentic Browser Flow

The integrated browser is a Galaris Tool governed like the other MCP capabilities. A
`browser` connection is created automatically for each agent. Its
activation, followed by any function-by-function deactivations, determines exactly what the internal
harness and Hermes see in their catalog.

```text
Agent / Task
   → app.browser MCP functions
   → validation and owner {agent_id, task_id}
   → authenticated API on executor_net
   → browser-executor
      ├── one shared Chromium process
      ├── one isolated BrowserContext per session
      ├── outbound proxy with DNS resolution
      ├── internal executor_net network
      └── outbound browser_egress network
   → ARIA content with refs, or bounded full-page screenshot
   → MCP image blocks + `console://` files when the console is active
```

## Sessions and Authorization

`browser_open` creates an opaque session. It optionally accepts a viewport in CSS pixels, bounded
to 320–3840 px wide and 240–2160 px high, to select the responsive layout at load time (for
example, 1440 × 900 on desktop or 390 × 844 on mobile). Every subsequent operation must provide
the same
`agent_id` and the same `task_id`; another task, even one belonging to the same agent, therefore
cannot take over this session. Chromium contexts share neither cookies, cache, nor local storage.
They expire after a bounded period of inactivity, and `browser_close` immediately releases their
resources.

The generic connection interface allows the Tool to be enabled for an
agent and to separately authorize or remove `open`, `content`, `screenshot`, and the actions. When
the Galaris Tool is active for a Hermes agent, the manager disables Hermes's native browser toolset
to preserve a single authorization and audit boundary.

Chromium starts with the first session request, rather than during sidecar startup or health
checks. After the last context expires or closes, the next cleanup pass also closes Chromium.
Pending creations already reserve capacity and prevent sleep; requests arriving during browser
shutdown wait for a fresh browser. Expiry keeps `BROWSER_SESSION_TTL_SECONDS` (120 seconds by
default), with cleanup every 10 seconds. The first request after sleep pays the launch
cost. `/health` remains healthy while asleep; an unexpected Chromium disconnection still exits
the sidecar with failure so it can recover.

## Outputs

The connection parameter `default_output` accepts `content` or `screenshot`.

- `content`, the default value, returns the page's accessibility snapshot with stable references
  usable by `browser_click` and `browser_type`. Content that is too long indicates `next_offset`
  so it can be read in chunks.
- `screenshot` captures the full page height within the configured limit. A tall page is divided
  into vertical bands; the manifest indicates the dimensions, the `console://` URIs, and
  `truncated=true` if a height, band-count, or byte limit is reached.
  `browser_screenshot` can optionally modify the viewport before capture; the resolution selects
  the CSS layout, without disabling full-page capture or its splitting. The `console://` save is
  auxiliary: without Console, or if this save fails, the MCP image blocks and their manifest
  remain the successful result of the capture, with `path: null` for the unsaved band.

Actions also accept an explicit choice that overrides the connection default for that call. Images
return both MCP blocks visible to multimodal models and, when a console is active, durable files
under `console://browser/<session>/`. Without a console, no implicit local destination exists.

The contract provided to the model prescribes the robust sequence: open with
`output="content"`, retain the `session_id`, perform interactions in the same Task, reread
`browser_content` to check the URL and final state, then capture immediately. It recommends
`1440 × 900` for desktop, `390 × 844` for mobile, JPEG by default, and PNG for fine details. An
expired session is never retried: the model opens a new session and uses its new ID.

## Network Access

The sidecar exposes no host port. The backend reaches it on `executor_net` with a shared secret.
Each context has a local proxy bound to its owner. For every request the proxy resolves DNS,
sends the origin, method and addresses to `POST /api/browser/network/authorize`, then connects
to a checked address. The callback requires the shared secret and receives no paths, query
parameters or request bodies. An unavailable authorization service blocks the request.

The `browser` connection carries four settings:

- `allow_local_network=false` blocks private, loopback, reserved and link-local addresses,
  including IPv6. Setting it to `true` allows a local-access permission request.
- `network_filter_mode=block` denies destinations in `network_filter`; `allow` only admits
  listed destinations, and an empty allowlist blocks everything.
- `network_filter` accepts exact domains, `*.example.test`, IPs and CIDRs separated by commas
  or whitespace, with an optional port. Wildcards exclude the apex domain. Every DNS address
  must match an allowlist. Domain matching never bypasses the local-network check.
- `permission_methods` defaults to `POST PUT PATCH DELETE WEBSOCKET`. Known HTTP methods may
  be added or removed; an empty value restores the default, and an unknown value blocks access.
  Public GET requests pass without a question under the default configuration.

Configuration denials always precede remembered permissions. Local access and POST require
separate decisions. The deterministic key `browser:v1:post:https://example.test:443` covers
one method and normalized origin, across all paths, for one agent. Ports, protocols and
subdomains stay separate. `app.messenger.request_permission` stores the question, answer,
responsible user and date; a SQL constraint prevents duplicate active requests across workers.
It uses the common interaction mechanism, including textual replies and internal-chat buttons.
Unanswered questions expire after seven days and can be renewed; approvals and denials remain
until deleted. Changing an agent's responsible user invalidates a decision on its next use.

Redirects, subresources and WebSocket connections go through the proxy. HTTPS is decrypted
inside the sidecar process to inspect the method, then encrypted upstream with normal remote
certificate and hostname verification. The proxy certificate is ephemeral. Service workers,
QUIC and WebRTC output without a proxy are disabled. Open WebSockets are checked every second,
without overlapping checks; an unavailable service closes them after the 15-second check timeout.
Checks retain the socket's original destination even after DNS changes. HTTP requests already
forwarded are not cancelled retroactively.

Results expose `network_issues` for pending questions, denied permissions and configuration
blocks. Blocked actions are not replayed automatically after an answer: the agent must wait
for the decision and retry the appropriate action, without blindly resubmitting a form.
Human sessions without an agent connection keep the default restrictions and cannot create
permissions for an invented agent.

To preview a local application, enable `allow_local_network` on the agent's connection, allow
the destination through its filter, then answer the permission request. `localhost` refers to
the sidecar; use the destination container's DNS name or `host.docker.internal`, with a service
listening on an interface reachable from Docker. Credentialed URLs and schemes outside
HTTP(S)/WebSocket remain rejected.

Session idle time and capacity, operation timeout, content, HTML, default viewport and
screenshot limits live in `params`, under **Preferences → Browser**.
The page is available only when at least one `browser` connection is active. The
`GET /api/browser/status` endpoint requires preference access or edit privileges; direct
page access also hides the fields when the Tool is unused.

Every authenticated sidecar operation receives a validated `settings` snapshot. The
sidecar independently bounds it and applies it only to that operation, including operations
on existing sessions. Default dimensions affect new windows; explicitly requested viewports
remain bounded. The model cannot control administrator limits. The shared token lives
in the shared credentials volume.

Capacity is checked on every admission, including pending creations; lowering it does not
close existing sessions. Each session stores its idle timeout and updates it on its next
action. Expiry starts when the action ends and never closes a busy session. PDF exports
retain their separate concurrency limit.

## Entry Points to Read

- Tool and client: `back/app/browser/mcp.py`, `service.py`, `schemas.py`.
- Executor: `browser-executor/server.mjs`, `network-proxy.mjs` and `lib.mjs`.
- Policy and decisions: `back/app/browser/network.py`, `back/app/messenger/permissions.py`.
- Connection governance: `back/app/tools/mandatory_tools.py`,
  `back/app/tools/mcp_loader.py`.
- Hermes alignment: `back/bridge/hermes/manager.py`.
