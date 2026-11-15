# 0292 — Desktop client reusing the server interface

Status: accepted; implementation in the development repository, platform qualification pending.

## Contract

An independent Electron client in `desktop/` connects to an administrator-supplied HTTPS
Galaris origin. It loads the existing server interface, preserving same-origin API,
WebSocket, authentication, document isolation and PWA update behavior. It does not bundle
the backend, introduce offline business data, or duplicate frontend domain modules.

Only the local Vue/Quasar launcher and tab bar receive a bounded preload, with separate
sender authorization. Every IPC invocation validates its sender and main-frame URL.
Server tabs use `WebContentsView` instances sharing the server partition; switching views
retains each page's state. Same-origin new-window links become tabs, while blob/data
previews remain separate windows. New internal tabs have no opener relationship, matching
the server interface's `noopener` links. The owner closes each view with its unload protection
before closing itself, switching servers or installing an update. A veto retains that view;
clean tabs already closed are not restored. Tabs are not persisted across restarts.
French and English spellchecking runs locally, with Electron's default dictionary downloads
and a native context menu for suggestions and dictionary additions.
Server tabs and resource previews have no
preload, Node integration or webview. Context isolation, web security and the renderer
sandbox remain enabled. Permission requests are limited to the selected server's main
frame and require native consent. HTTPS navigation inside the tab preserves OAuth state.
External new-window links use an allowlisted URL scheme; resource previews remain sandboxed.

The selected origin is committed only after a successful load. Failed, cancelled and
superseded attempts preserve the previous server. Persistent partitions are keyed by
origin so changing servers does not reuse cookies or local storage. Returning to an origin
restores its session. Uninstalling or switching servers does not revoke server sessions.

## Distribution

electron-builder supplies x64 Windows NSIS, Linux AppImage and optional Debian packages.
electron-updater supplies automatic downloads for NSIS and AppImage, followed by an
explicit restart decision. Closing the application never installs an update. Debian
remains a manual package upgrade. There is no tray/background delivery guarantee.

The native wrapper and server interface have separate update cycles. Wrapper updates
come only from the official public repository, never the selected server. Stable tags
without a `v` prefix are shared with source releases; builds use the release tag version.
Publication extends the existing exact-commit security gate, requires successful builds
on both operating systems, uploads artifacts and update metadata to a draft, then exposes
them together. Windows publication requires a signing certificate. Published releases
are never overwritten.

## Verification

Docker Make targets exercise policies, preferences, update state and real Electron
journeys against entirely synthetic servers. CI also exercises Windows. Local rendering
uses the existing Quasar graphic reference and shared Solaire values. Physical media,
Web Push delivery and signed cross-version installation still require platform qualification.
