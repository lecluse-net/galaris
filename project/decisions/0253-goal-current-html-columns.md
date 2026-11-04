# 0253 — Inline Goal descriptions and freely classified tracking Documents

Status: accepted. Date: 2026-10-29.

Goal descriptions are business state stored directly in `goals.description` as
editorial HTML (`rich-text`, version 1), without a Document identity or text
history. The existing rich-text field remains their editor.

Tracking remains the Goal's sole associated Document, referenced by
`tracking_document_id`, retaining its URI, editor, history and sharing contract.
It is created unclassified: visible in the document list, absent from the tree
including its root. Each user can classify or unclassify it independently.

Tracking concision is generation guidance, never a length-based validation rule.
Goal tracking is exempt from rich-text byte and visible-character caps while retaining
the same safe HTML profile. Judgement reasons, progress summaries and evidence have
no character or item-count caps and are never truncated. Prompt and schema descriptions
encourage synthesis without discarding useful information. HTML security checks and
the shared document storage quota remain applicable.

Automatic Goal folder creation, renaming and task-deliverable filing are retired.
Historical queued jobs complete without effects. Existing folders and personal
placements are preserved as ordinary editable organization, with automatic Goal
markers and forced logical paths removed. No folder is recreated after removal.

Agents read both current texts through `file_read("galaris://goal/<uuid>")` with
Goal owner/administration checks. The tracking `document://` URI remains usable
with its existing Document permissions. `goal_update_suivi` and judgement retain
Goal and tracking revision checks. `description_document_id` is removed from API
responses; description consumers use the Goal URI instead.

DbAdmin copies only the latest description HTML, including storage-backed sources
and soft-deleted Goals. Missing or invalid sources block the transfer. The source
Document is soft-deleted only after the text is copied, before Atlas removes its
obsolete reference. Tracking content, identity, revisions and grants are untouched.
Existing preservation archives remain intact; no description history is imported.

When contraction is deferred, preparation makes the retained source reference nullable
so the current runtime can create Goals using inline descriptions. Existing references
remain available for transfer. Copying and retiring a source description are atomic;
once retired, that source must not prevent later legitimate edits or overwrite them
during synchronization replay.

This supersedes automatic filing in decision 0107 and the description-as-Document
contract. Decision 0252 still governs the tracking Document; Goal descriptions
remain owned by their business domain.
