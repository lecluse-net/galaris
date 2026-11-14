# 0289 — Stable native Calendar resources

Status: Accepted
Date: 2026-11-14

Each persisted CalendarFeed owns the stable identity `galaris://calendar/<positive integer>`.
It resolves to credential-free metadata, not an iCalendar subscription URL or an event export.
Renaming preserves identity. The resource does not create a sharing grant: agent reads and
list/search remain scoped to the owning agent and an active connection; human navigation
requires Calendar privileges and the existing agent management scope.

Calendar registers its reader and bounded lister through File Share's public callback API,
as Contacts and Code already do. This adds the reviewed Calendar → File Share composition
dependency without a reverse import or a cycle. Calendar operations retain their own tool
policies. API/MCP calendar reads expose `resource_uri`; File Share supplies info/read/list/search.

The frontend contributes canonicalization, search, cards and resource opening through the
existing rich-content registry. Discussions and resource attachments use their existing
preview/access pipeline, without generating thumbnails. The web route `/calendar?calendar_id=…`
resolves the owner under the management scope and focuses that calendar. Virtual Goal and
Memory layers remain projections and do not receive fabricated Calendar identities.

The sidebar reuses ActionContextMenu for the ellipsis, right click and keyboard menu key.
Visibility is a local display choice; it does not deactivate the source or its scheduled Tasks.
Synchronization reuses the existing monitor and command, and settings retain their existing editor.
