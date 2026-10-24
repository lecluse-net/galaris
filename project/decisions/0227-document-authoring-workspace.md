# 0227 — Document authoring with checklists, outline and conversation

Status: accepted, 2026-10-24.

Documents remains the editorial workspace; Chat remains the conversation and activity
workspace. Documents can open an existing canonical conversation or create a new one in
a right-hand panel. Chat contributes a lazily loaded panel through a core-owned port,
following the existing document-editor contribution mechanism and avoiding a reverse
Document-to-Chat dependency. Both
surfaces reuse the same chat state implementation, with independent selections and
subscriptions. This preserves streaming, admission identities, history and authorization
without duplicating the messaging workflow. Document access uses Document privileges,
independently of personal Memory privileges.

Sending waits for document autosave and attaches the identifier of the loaded current
document through the existing message contract. Failed saves retain the composer draft.
No document or Dataset permission is granted by opening a conversation or sending its
context. The desktop panel can be hidden while retaining its conversation and draft;
mobile uses a dialog.

The Document editor owns a shared attention capture through `core.util`. Both Documents
and the document pane in Chat expose that capture through their core-owned component ports.
Mouse and keyboard selection survives moving focus to the composer. After autosave, each
message uses the existing `document_focus` contract alongside the displayed Document UUID:
saved revision, bounded selected text with UTF-16 start/end offsets, last cursor and visible
passage when available. This is per-editor, transient state; it is never written into the
Document HTML. Document/context changes and replaced content invalidate old positions.
The canonical message metadata and prompt projection retain their existing authorization,
size bounds and treatment of client-reported excerpts as data.

Both conversation surfaces share visible-room presence and focused message read receipts.
The inbox, service worker and server Web Push pipeline consume that presence independently
of the current route. Already viewed messages cancel delayed local fallbacks, and opening
a conversation dismisses its existing toasts and system notifications. The server skips
push admission for visible rooms and checks presence again immediately before delivery.

The optional left-hand outline projects the heading hierarchy as an indented list of
links, without tree lines or folding controls, using the document's background and border.
The editor toolbar's Conversation icon toggles the chat panel. Desktop document/chat
widths are adjusted with the same splitter handle as the library/document boundary,
including keyboard resizing; hiding the panel retains its width setting and draft.
It updates during editing and navigates within the document without adding content,
identifiers or revisions.

Checklist items store their checked state in the Document's HTML as `data-checked` on
list items within `ul.galaris-checklist`. Editor controls are transient node views;
saved HTML remains readable, versioned and portable. Read-only views and exports show
the saved states. Checklists do not create Datasets or task resources.
