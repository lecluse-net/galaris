<p align="right"><a href="../../fr/dev/desktop.md">Français</a> · <strong>English</strong></p>

# Electron desktop client

The independent `desktop/` package reuses the server interface and bundles the
Vue/Quasar server selector, local MCP settings, tab bar, and Electron runtime.
Remote views stay isolated from local operations.
See decision [0292](../../../project/decisions/0292-desktop-client.md) and the
[user journey](../user/desktop.md).

## Build and verify

```bash
make desktop-deps     # create/update package-lock.json in Docker
make desktop-build    # strict types and launcher/main/preload builds
make tests-desktop    # build, unit rules, Electron journeys under Xvfb
make desktop-package  # x64 AppImage and .deb in desktop/release/
make desktop-package-windows # unsigned x64 Windows installer, Docker/Wine
```

These commands do not use the application stack or its secrets. Dependencies are retained
in a Docker volume identified by the lock. Synthetic diagnostics and screenshots live
under `artifacts/desktop/`. Tests disable the Chromium sandbox only inside their isolated
container; the shipped client retains `sandbox: true`.

The launcher reuses native Quasar components from the graphic reference and the shared
Solaire palette. It follows the system theme and selects en/fr/zh catalogs from the system
language. The remote interface retains its own language and user preferences.
Its HTML title follows `PageHeader` through Quasar Meta, falling back to authorized,
translated navigation labels and the most specific parent route for nested pages.
Electron follows title changes for each tab, including
background tabs.

`server.json` contains only the server origin in the Electron user directory. The atomic
write of this tiny file does not yield to concurrent cancellation. Cookies, caches and
web storage live in a separate persistent partition for each origin. HTTP is accepted
only in development for loopback addresses. A failed connection preserves the last saved
server and keeps the launcher usable.

The local `galaris-desktop:` protocol serves only bundled assets. The preload exposes bounded
launcher and tab operations; each invocation verifies the window, main frame and exact URL,
with separate authorization for the two interfaces. Remote tabs are `WebContentsView`
instances without a preload; only the local tab bar has one. Each view retains its state
while another is selected, sharing a server partition. Same-origin new windows become tabs;
blob/data previews remain isolated windows. Views are explicitly closed with `beforeunload`
before destroying their window, including server switches and installation. A veto retains
the affected view; tabs already closed are not restored. No tab list is persisted.
The session enables the `fr` and `en-US` Hunspell dictionaries on Windows/Linux; words are
processed locally. Electron downloads dictionaries from its default CDN. The context menu
offers suggestions, dictionary additions and editing actions. Previews have no preload.
The local tab bar is a native view above the remote views. Inside the Galaris shell
(`.page-container`), an isolated adapter reserves its height in the content and observes
the sidebar inset, theme, page surface, and visible dialogs or fullscreen previews. It reports
only these presentation values
through bounded console messages from the selected origin's main frame, without exposing
a remote API. The main process clamps the inset and recalculates views when switching
tabs, zooming or resizing. While the active tab has an open modal or fullscreen preview,
Electron hides the bar and gives the view the entire content area. The bar returns when
the last modal or preview closes. The sidebar retains its full height. Below 1024 CSS pixels,
or without this shell (external sign-in, older interface), the bar spans the window above
the remote view. The adapter and its observers disappear with the document; this layout
does not require a server rebuild.
Rich-text editors retain their custom menu; Shift+right-click allows the native menu
without changing the selection. Internal links opened in tabs are isolated from their
opener, matching existing `noopener` consumers.
Permissions reject third-party
frames and origins and request native consent for supported capabilities. Local program
schemes are never passed to `shell.openExternal`. Invalid certificates remain rejected.

## MCP relay

The main process discovers well-known user configurations and files selected through
the native file picker. It stores the fingerprint of each shared configuration for
the selected Galaris server. The local renderer receives MCP summaries and status. Commands, arguments,
local URLs, and variables stay in the main process. Stdio instances start on demand
for each MCP session.

Sharing creates an HTTP Service using the web session's `SERVICE_EDIT` privilege.
The session is used for explicit registration. The desktop then uses a credential
scoped to that relay. The server keeps a separate secret in the protected Service
configuration. Desktop credentials use the system key store when available. On Linux
without a usable key store, settings use a user-owned file with mode `0600`.

The desktop retrieves jobs and returns replies by HTTPS POST to the existing Galaris
origin using the Chromium network stack. The backend calls the hosted MCP endpoint
on its existing internal HTTP listener with a separate credential. Connection and
function permissions follow the normal MCP path. In-flight requests are encrypted, expire, are
claimed once, and are removed after delivery or expiration. HTML views use the same
relay as tools. The main process rejects resource reads with a `file:` URI.
Unsolicited notifications, sampling, and elicitation stay local.

## One-shot capture in Chat

The main process associates an ephemeral key with the desktop tab that sends a
Chat message. It establishes presence over the existing HTTPS origin and adds
the key to the outgoing message request. The backend binds presence to an
account and an active web session family. The turn catalog hides
`chat_screenshot` when a turn merges messages from different origins. The tool
checks the live session and conversation access before and during the request.

Only the local consent window can obtain Electron display capture permission,
after a selection and user gesture. It extracts one bounded JPEG and immediately
stops the track. The preview stays local until confirmation. The temporary
encrypted reply in PostgreSQL is removed after consumption or expiry. After
validating the current turn, the Chat Service saves the image in the server's
managed file storage. The tool returns the canonical `file://<uuid>` URI, file
name, and MIME type. The agent can attach the file using this URI. Closing the
tab, disconnecting, and expiry invalidate pending requests.

## Distribution and updates

`electron-builder` produces Windows NSIS, Linux AppImage and Debian packages.
`electron-updater` checks only public `lecluse-net/galaris` releases with SemVer tags
without `v`. The selected server URL cannot change the update channel. Windows and
AppImage download automatically and offer an explicit restart; closing alone installs
nothing. Debian packages require a manual upgrade. User sessions survive updates.

Update and startup failures are retained locally in `desktop-update.log`, next to
`server.json`, with stage, version, cause, error code, exit status when supplied and stack.
Two bounded files are retained; credentials and sensitive URL parameters are removed
before writing. Diagnostic storage failures are reported in the launcher without hiding
the original failure. The client adds no external telemetry.

The `Desktop client` workflow tests and builds previews on native Linux and Windows
runners. The guarded `Publish release` workflow qualifies the exact commit with
`release-check`, then builds both platforms at that commit. It uses the tag as
the client version, attaches installers, blockmaps and `latest*.yml` to a draft, then
publishes only when all files are present. Failures leave an unpublished draft; existing
published releases remain unchanged. No electron-builder build publishes directly.

Functional tests stay in `Desktop client`, separate from source publication; they add
no functional gate to its security checks.

For signed Windows releases, configure the GitHub secrets `DESKTOP_WINDOWS_CERTIFICATE`
(base64 PFX or an electron-builder-supported URL) and
`DESKTOP_WINDOWS_CERTIFICATE_PASSWORD`. Publication requires signing and fails when it is
missing; preview builds may remain unsigned. Keep the certificate and publisher identity
consistent for updates. Never put certificates or GitHub tokens in the repository or
distributed assets.

Before shipping, check on real Windows and Linux systems: installation, relaunch,
connection, microphone/camera, calls, downloads, notifications and upgrading from one
published version to the next while preserving the session. Synthetic update tests cover
concurrent checks, failure/retry, progress and chosen restart. The real engine downloads
a synthetic file, rejects a corrupted digest and succeeds on retry; these do not prove signed
installation on a real workstation or physical devices.
