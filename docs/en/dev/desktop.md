<p align="right"><a href="../../fr/dev/desktop.md">Français</a> · <strong>English</strong></p>

# Electron desktop client

The independent `desktop/` package reuses the server interface and bundles only the
Vue/Quasar server selector, tab bar and Electron runtime. It adds no business module, local server,
Node access for the remote interface, or CORS configuration.
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
the sidebar inset, theme and page surface. It reports only these presentation values
through bounded console messages from the selected origin's main frame, without exposing
a remote API. The main process clamps the inset and recalculates views when switching
tabs, zooming or resizing. The sidebar retains its full height. Below 1024 CSS pixels,
or without this shell (external sign-in, older interface), the bar spans the window above
the remote view. The adapter and its observers disappear with the document; this layout
does not require a server rebuild.
Rich-text editors retain their custom menu; Shift+right-click allows the native menu
without changing the selection. Internal links opened in tabs are isolated from their
opener, matching existing `noopener` consumers.
Permissions reject third-party
frames and origins and request native consent for supported capabilities. Local program
schemes are never passed to `shell.openExternal`. Invalid certificates remain rejected.

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
