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

### Progressive video playback (2026-10-18)

Video playback uses an optional byte-range transport port in the canonical file
facade. Samba, Nextcloud/WebDAV, AFFiNE, console SFTP, internal files and public HTTPS
read requested portions without full-file staging or a frontend Blob. Unsupported
providers keep the existing bounded preview. Downloads and other previews retain
their original contracts. HTTP sources that ignore Range are scanned sequentially
with bounded memory; seeking on those sources may transfer preceding bytes again.

An authenticated POST issues a six-hour HttpOnly cookie scoped to one opaque media
URL, one URI, Agent, role and browser session family. Its signing key is derived for
this use and cannot authenticate normal API requests. GET and HEAD recheck the live
account, auth version, family, privilege, managed Agent and resource ACLs. Byte ranges
return 206 or 416 with the original size. Closing the viewer deletes its scoped
cookie; context changes and late replies release unused grants. Streaming cleanup
closes provider handles on completion, failure and interruption. SMB sessions renew
before their operation deadline and reject a changed version across renewals.

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
