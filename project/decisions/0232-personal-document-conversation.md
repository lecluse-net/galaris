# 0232 — Last conversation per Document and user

Date: 2026-10-24
Status: accepted

## Decision

Chat owns `chat_document_conversations`: one unique row per Document/user pair,
with a nullable canonical Messenger room UUID. All three foreign keys use
`ON DELETE CASCADE`; deleting a room removes the preference rather than leaving
a dangling reference. Absence of a row and a null room both mean no saved selection.
Soft-deleted or inaccessible resources remain subject to their domains' live ACLs.

The authenticated Chat API reads and updates only the caller's preference, requiring
Chat access, a Document privilege, current Document access (human or managed Agent),
and current membership of a text conversation. It never changes content, sharing,
or Document revisions. A saved room that is no longer readable is returned as null.

This adds the direct `app.chat -> app.document` dependency: the user interface preference
must validate the independently owned resource through its public facade. This is a
bounded consumer relationship, without importing Document internals, creating a new
module or adding a reverse dependency or a bootstrap port solely for UI state.
The architecture debt baseline is unchanged.

## Restoration

On desktop, loading a readable Document checks for a saved conversation and automatically
opens the panel when one exists. The contribution's optional discovery callback lets the
document page do this without importing Chat internals. A late discovery result must not
override an explicit open/close action or a newer Document. The panel remains closed when
there is no saved selection.

Opening a document's conversation panel restores that document's last selection for
the current user, including rooms outside the first picker page. Selecting or creating
a room saves it. Hiding and reopening the same panel preserves the draft; changing
Document clears the previous selection before loading the next preference. Writes are
serialized, and late reads cannot replace a newer Document or manual selection.
Failures retain a visible retry action; a room whose access has disappeared is not opened.

## Verification

Database tests cover isolation, nullable updates, unique upserts, live resource access
and actual cascaded deletes. Browser scenarios cover restoration after remount, switching
documents, pagination, delayed responses, save/read retries and preserved drafts, alongside
the existing desktop/mobile editing and conversation journeys.
The assembled document authoring journey reloads the page and verifies restoration without
clicking the Conversation button: manually reopening it in the former tests hid the startup defect.
