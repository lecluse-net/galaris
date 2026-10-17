# 0201 — Agent-scoped virtual file browser

Date: 2026-10-17
Status: accepted

## Decision

Knowledge exposes a Files page in `front/app/file_share`. Its roots come from the
canonical `app.file_share` scheme descriptions for a selected managed Agent. The
browser delegates URI resolution, live provider access and domain ACLs to the existing
facade through authenticated read-only HTTP routes. It creates no resource model,
storage copy or second provider registry. `root_listable` distinguishes a scheme that
lists its root from one that lists only an explicitly addressed subcollection.

Directory loading uses provider continuation cursors. SSH listings keep one page in
memory and use directory-bound lexical continuation keys; independent `file://` files
use owner-filtered UUID continuation. Providers without continuation expose their
truncation explicitly. The interface loads more entries on scroll, preserves loaded
entries on retry and discards requests and previews when the Agent or session changes.
Thumbnails share the bounded preview queue and release offscreen object URLs. Known
resources open the existing domain dialogs; other files reuse the shared attachment
viewer, including its isolated HTML rendering.

## Explicit dependency review

The new frontend module requires exactly these public dependencies:

| Dependency | Purpose |
|---|---|
| `app/agent` | Authorized Agent selection |
| `core/api` | Authenticated HTTP and session invalidation |
| `core/authorize` | Navigation privilege |
| `core/navigation` | Navigation contribution type |
| `core/util` | Page header, shared previews, domain-detail composition and artwork |

These five edges were reviewed against their public entry points. They introduce no
private imports or dependency cycles. Record only these new-module edges in the
frontend dependency baseline; existing debt is unchanged. Backend dependencies already
belong to the file-share facade's allowed domain set.

The shared attachment viewer also uses the public `core/api` error formatter.
Record this `core/util` → `core/api` edge alongside the five module edges; the
Documents adapter keeps its existing API and delegates rendering to that viewer.

## Verification

Real HTTP tests check permissions, Agent isolation, content reads and file continuation.
SFTP boundary tests check unordered multi-page listings and home containment. Chromium
component journeys check desktop/mobile navigation, scrolling, recovery, keyboard file
previews, existing Document dialogs and late replies after an Agent change.
