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

### Contact directory projection (2026-10-30)

The native `galaris://contact/` collection exposes the selected Agent's canonical Contacts
as JSON snapshots addressed by their contact UUID. Contact owns directory queries,
serialization and owner filtering; the composition root binds its public facade to a File
Sharing port for list, search, info, read and export, avoiding a dependency cycle through Contacts.
The browser requires `CONTACT_ACCESS` or `CONTACT_EDIT` and a
managed Agent, independently of generic file privileges. Entries display contact names and
open the existing Contact edit dialog, read-only without `CONTACT_EDIT`. The same exact
URI participates in the rich-resource system. Its dedicated `galaris-contact-card` persists
only a name and URI; a rendering contribution reads current coordinates through the
Contact API under the reader's own domain privileges and management scope. Saving a Contact
refreshes mounted cards; session and privilege changes discard old reads. Export rechecks
source access before capturing coordinates into a portable static rendering. The document
does not own, copy or grant access to the address book.
Agent File Sharing tools may edit only `display_name` and
`coordinates` through `file_write`/`file_edit`, with a mandatory `expected_etag` obtained
from `file_read`/`file_info`. The Contact writer validates the owner and compares the token
under a row lock before reusing Contact updates. Full snapshots preserve all identities and
metadata; partial JSON preserves omitted fields. Merge, split and forgetting remain dedicated
Contact-domain actions. Other native business snapshots remain read-only.

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

### Live IMAP browsing (2026-10-30)

The Mail transport exposes IMAP folders and header-only message listings through the existing
file facade. Opaque folder segments preserve arbitrary IMAP hierarchy delimiters and names;
display names and ancestors travel as provider metadata. Folder and message continuation
share the requested page budget, capped at 500. Messages have stable mailbox/UIDVALIDITY/UID
references and export their original MIME through the same bounded transport as attachments.

An optional transport context port binds server-owned `ResourceContext.browser_navigation`.
Human reads additionally require an authenticated user with Mail privileges and the selected
agent in their management scope. They never create inbound receipts, agent approvals or Tasks.
Autonomous body and attachment reads retain the INBOX consent checks from decision 0221.
The Mail reader uses paged text from the existing MIME parser; external HTML is inert and
remote images are not fetched. Read-only IMAP selection and BODY.PEEK preserve message flags.
No storage copy, mailbox model, agent capability or new provider registry is introduced.

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
