# 0234 — Administrator-owned default privilege categories

Date: 2026-10-24
Status: accepted

## Decision

Default privilege organization is initialized by the authorization module's DbAdmin
dataset, with one durable receipt per category in `privilege_list_defaults`. Category
creation, initial assignment and receipt completion share the dataset transaction.
Receipts do not depend on category rows: administrator deletions, renames and privilege
moves survive later synchronizations. Initialization adopts the existing initial
category names and only assigns previously unassigned privileges. Only privileges
declared by active modules are assigned; other codes in the default organization are
ignored until their module is available at initialization.

Software labels store an i18n key in `display_name` and a read-only `translation_key`
provenance field. A rename clears that field; custom labels, even those matching an
i18n key, remain literal text. Neither categories nor their initialization receipts
grant permissions.

The former Chat-specific category datasets are retired: their unconditional creation
and null-only reassignment could restore a deleted category or undo an explicit
unassignment. Chat privileges now follow the same one-time Discussion initialization
as other domains. Existing custom categories are preserved.

The category integration tests cover initialization, adoption, rollback, renames,
unassignment and deletion across repeated synchronization. Browser tests cover label
translation and literal custom text, unchanged edits, and the assembled application
in French on mobile and English on desktop.
