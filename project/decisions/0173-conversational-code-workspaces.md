# 0173 — Conversational Git workspaces and an isolated code-server runtime

- Status: accepted architectural choice; implementation delivered locally and targeted acceptance
  acquired. Global qualification is recorded per snapshot under `artifacts/validation/`.
- Date: 2026-10-11.
- Plan: [Conversational code editor](../plans/editeur-code-conversationnel.md).

Humans need to inspect and edit the exact Git checkout used by their developers through
Console, including uncommitted changes. They requested standard VS Code behavior and
authorized reuse of the agent's existing Git identity and SSH forge credentials.

`app.code` owns persistent workspace identities, exact user/agent grants, conversation
references, browser sessions and the authenticated HTTP/WebSocket gateway. Console owns
bounded repository discovery and dedicated pinned SSH tunnels. `bridge.code_server`
registers the runtime adapter and native metadata projections through public ports.
The `CodeRuntime` port carries typed target and connection references: `app.code` has
no Console or Agent implementation dependency. The adapter resolves those domains'
public contracts. The UI is a Chat feature under `front/app/chat/code`; no second
frontend domain is introduced solely to embed this editor.
Conversation owns `repository_show`, including the scope of explicitly linked live Tasks;
Chat publishes requests to its resource-authorized sockets. Existing Document permissions
and `document_show` exposure do not change.

code-server 4.141.0 is a separately deployed service pinned by tag and image digest.
A trusted broker uses Bubblewrap namespaces to expose only the approved checkout, Git
metadata, and the editing session's selected Git/SSH configuration. Each editor runs as
the repository Unix account with no capabilities. Consultation mounts repositories and
Git metadata read only and has no network or forge keys; it does not chmod the agent's
files. The Docker namespace settings apply to this broker only. No Docker socket or host
devices are mounted. Linux user namespace support is a deployment prerequisite.

An external Console requires the same broker to be explicitly prepared on its target;
the independent SSH transport forwards only its configured loopback port. Embedded Console
uses the private service network, retaining the existing SSH forwarding prohibition.

As amended on 2026-10-13 at the user's request, external preparation is available through
**Deploy code editor** in each agent's Console connection, alongside helper installation.
Console owns the management authorization and encrypted parameters; the code-server bridge
registers its deployment implementation through Console's public installer port. The backend
image packages the existing runtime sources, avoiding a second implementation. The action
uploads an immutable bundle over pinned SFTP, builds a private Docker service per Unix account,
verifies its Linux namespaces and authenticated SSH tunnel, then atomically stores its access.
Only that account's home is mounted. Duplicate deployment reuses its service and credential;
an existing version is not replaced implicitly. Docker and forwarding remain administrator
prerequisites, and deployment is never an agent tool or an effect of `repository_show`.
Code revalidates existing checkout identities before and after runtime configuration, preserving
their URIs only when the target is unchanged. Concurrent connection changes prevent publication;
an existing live IDE prevents changing its runtime so that unsaved buffers remain recoverable. This technical operation stays
in Console and the bridge; no business Process is introduced.

As amended on 2026-10-17 at the user's request, maintenance of already configured managed
editors on active external SSH connections runs automatically at the end of every `make update`,
including prepared releases. The initial deployment action remains; the manual update button
is removed. Bundle fingerprints decide whether replacement is necessary. A current runtime
can be checked with live sessions, while replacement keeps the existing session interlocks,
port, credential, profiles and rollback. Maintenance never changes configured access or installs
an unconfigured target. Manually administered brokers are reported without modification.
Independent targets continue after a failure, but the update command fails until all managed
targets pass. No remote software is installed by `repository_show` or by an agent tool.

As amended on 2026-10-12 at the user's request, the gateway uses the application's single
public origin under `/api/code/gateway/`. Vite forwards HTTP and WebSockets in development;
Nginx does so in production, with a dedicated location that preserves IDE response headers
and bypasses SPA static-file handling. No separate gateway container, DNS record or
`CODE_EDITOR_ORIGIN` setting is required. The browser origin is shared: code-server and
its frontend extensions are trusted alongside the application shell; scoped cookies and
transport header filtering do not create browser origin isolation. Filesystem and process
isolation remains enforced by the broker. Browser launch uses an expiring, one-use
ticket in a fragment, exchanged for a scoped HttpOnly cookie. The cookie is bound to the
authenticated browser session family, user and current repository grants. Target fingerprints
include Console credentials and canonical checkout identity; changed targets are revalidated
instead of silently redirecting an old reference. Streams and durable session reconciliation
check revocation. IDE profiles never authorize access.
Deleted selected roles remain revoked even when their foreign key becomes null; a
session never falls back to the user's other roles in that case.

Documents and code use one typed selection in the discussion pane. A shell contribution
retains iframe nodes while the discussion changes content, layout or room. An origin/source
checked readiness message identifies a loaded IDE; the bundled extension only navigates
files and native Git diffs without reloading the iframe. Git requests surface native workspace trust
management; the integration never grants trust. Explicit Console updates preserve the
private port, credential and retained profiles. They hold the session-creation lock, reject
live or orphaned IDE processes, and restore the previous image if build or verification fails.
Unsaved buffers are conservatively treated as potentially dirty,
and session destruction is explicit. This integration provides no shared cursors, realtime
buffers, custom agent writing protocol or implicit approval of Git publication.

The minimal IDE terminal provides Git in the isolated runtime. Recreating the Console's
complete service environment is not part of this choice. Galaris retains CeCILL 2.1;
the independently distributed code-server and VS Code OSS retain their upstream notices.

As amended on 2026-10-14 at the user's request, the Chat pane keeps only its title,
layout controls and hiding action. File/Git toolbar commands, branch/mode badges,
sharing controls and explicit session deletion are removed along with their dedicated
client state and sharing/deletion APIs. Git repositories appear below Documents in
the right sidebar. Ordinary opening and reopening preserve native IDE navigation;
explicit `repository_show` file/diff requests remain supported. Initial runtime launches
drop old navigation requests instead of forcing Git changes. Existing repository grants,
read-only confinement, session leases and automatic reconciliation remain enforced.
Retained profiles require administrator maintenance when their quotas are reached;
removing a pane control does not authorize automatic deletion of unsaved buffers.

The first stable iteration also defers application-driven theme and user preference
synchronization. The deployed legacy runtime does not expose the theme operation;
the browser calls, backend/runtime APIs and extension theme handler are removed.
VS Code keeps its native theme and profile settings. Existing opening, hiding/reopening,
document transitions and draft retention remain unchanged. The browser regression
scenario exercises application theme changes against a runtime without a theme API;
native IDE coverage continues to protect editing and save conflicts.

As finalized on 2026-10-15, explicit session recovery rechecks the original browser
family, role, grants and checkout before resuming the same session/profile and issuing
a new scoped cookie. It never reloads a loaded iframe; native WebSocket reconnection
retains unsaved browser buffers. A fully stopped IDE cannot restore the old native IPC
connection: the pane opens a recovery frame on the same profile while retaining the
original frame and its draft. Users can switch between them and copy their changes.
Another restart requires confirmation before replacing the recovery frame, retaining
the original and bounding the pane to two frames per workspace. A retained old frame
or a recovery frame still loading does not contribute repository context to a message.
Network outages remain distinct from a stopped runtime.
The eight-session limit bounds running IDEs, separately from the 64 retained profiles
per runtime; stopped profiles no longer consume an eight-profile Unix-account quota.
An offline maintenance tool shares an exclusive state lock with the broker, refuses
orphaned IDE mounts, and archives a profile privately and durably before retiring it.
Restoration keeps its UUID and cannot overwrite an existing profile or bypass target
and access checks. There is no automatic deletion of drafts or new pane cleanup control.

Firefox source editing and recovery remain supported. Its native Markdown preview
limitation is accepted for this first stable scope and tracked by a separate expected
failure; Chromium and WebKit previews remain blocking qualifications. Theme synchronization,
the complete Console environment and a separate human Git identity remain optional
extensions, not prerequisites for this integration. Full validation results belong to
the frozen snapshot under `artifacts/validation/`, not to a claim of deployment.
