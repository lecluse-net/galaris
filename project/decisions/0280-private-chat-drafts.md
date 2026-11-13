# Private current Chat drafts

Status: accepted

## Context

The Chat composer previously kept unsent text and device attachments only in component
memory. Reloading or recreating its host discarded that state. Uploading on Post could
not protect an attachment chosen before navigation.

## Decision

Chat owns one replaceable draft per authenticated human user and canonical Messenger
room. Text commits synchronously to scoped browser local storage; attachment bytes use
IndexedDB. A two-second dirty-only loop sends complete bounded snapshots over the
existing authenticated HTTP API, with immediate attachment uploads and lifecycle flushes.
This does not introduce a websocket transport or character-by-character updates.

`chat_drafts` retains only the current content and concurrency/idempotency cursors, with
no draft history. Optimistic revisions prevent stale writes and clears from overwriting
new edits. A pending mutation receipt is kept locally so a lost save response can be
retried even after further typing. Explicit conflict replacement requires confirmation.

Draft attachments use the existing bounded Chat upload path and immutable `core.storage`
identities. Chat owns their private references and author/room checks; they are not
Documents, shared resources or messages before publication. Publication reuses those
bytes as canonical Messenger attachments. After confirmed publication, only the matching
draft revision is cleared and its private file references are retired; canonical message
references retain the bytes. Removed draft attachments retire their unused references.

Both the main Chat page and the document conversation panel use the same composer and
save contract. The client preserves edits made during publication and never applies a
late response to another room or authenticated session. Browser storage failures are
reported; browser data deletion cannot preserve edits that never reached the server.

## Verification

The real HTTP/database tests in `app/chat/tests/test_attachment_http.py` exercise
persistence across requests, upload reuse, publication, lost-receipt retries, access
denials, failed sends, stale clears and file retention/retirement. Route authorization
coverage inventories the draft endpoints. `chat-drafts.spec.mjs` exercises the real
Vue composer through reload, navigation, offline recovery and delayed responses;
existing composer journeys retain keyboard, send and attachment coverage.
