<p align="right"><a href="../../../fr/architecture/flows/browser.md">Français</a> · <strong>English</strong></p>

# Agentic Browser Flow

The integrated browser is a Galaris Tool governed like the other MCP capabilities. A
`browser` connection is created automatically for each agent, but remains inactive by default. Its
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

The Tool is disabled by default. The generic connection interface allows it to be enabled for an
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

The sidecar exposes no host port. The backend reaches it on `executor_net` with a shared secret;
only the sidecar also has Internet access. The local proxy resolves each destination itself and
connects Chromium to any HTTP(S) URL reachable from its networks, including Docker service names,
private or reserved addresses, the sidecar's loopback, and `host.docker.internal`. Redirects and
subresources receive the same access. URLs containing credentials and schemes other than HTTP(S)
remain refused so as not to introduce credentials into tool calls or expose the sidecar's
filesystem.

This openness notably allows previewing an application under development served by another
container on `executor_net`, or by the host through `host.docker.internal`. Because `localhost`
refers to the sidecar itself, an application running elsewhere must use its container's DNS name
or `host.docker.internal`, and listen on an interface accessible from Docker. A server launched
in the embedded Console is therefore reachable at `http://ssh-executor:<port>` if it listens on
`0.0.0.0`.

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
- Executor: `browser-executor/server.mjs` and `lib.mjs`.
- Connection governance: `back/app/tools/mandatory_tools.py`,
  `back/app/tools/mcp_loader.py`.
- Hermes alignment: `back/bridge/hermes/manager.py`.
