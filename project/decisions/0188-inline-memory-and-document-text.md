# 0188 — Row-owned text for Memory and Documents

Status: accepted.

Native text lives in `memory_items.content` (ordinary memories and documentary
syntheses), `documents.content` (working documents), `memory_revisions.content`
(memory/document history), and `memory_summary_revisions.content` (synthesis history).
These are PostgreSQL `TEXT` columns.

Text, metadata and revisions share one database transaction. Existing opaque
resource references remain compatible; the native reader resolves inline text
before retained disk sources. Metadata and history lists exclude full payloads.
Partial indexes support native pointer lookups without indexing the text itself.

`app.memory.inline_text_contents` is an additive DbAdmin action triggered by the
content columns. It copies native current/history text in bounded pages, checks
source SHA-256, preserves exact UTF-8 bytes and verifies SQL against an immutable
backup in `galaris_migration.memory_text_contents`. Missing sources, hash mismatches,
invalid UTF-8 and NUL characters stop the transfer. Errors roll back; replay never
overwrites the backup or content legitimately changed after migration. No source
column or file is removed.

Old writers must stop before the initial transfer. Production uses the existing
update/startup DbAdmin path. Development is qualified separately; this work does
not modify production. Backups include the migration schema and retained sources.
Binary attachments and external providers retain their current storage.

Canonical contacts are a live resource exception. Their Memory items and revisions
keep `content = NULL`; reads rebuild the current contact JSON from canonical
metadata and strong identities after authorization, even for old Memory revisions.
Search projections remain indexed but never supply a stored contact body.
`app.memory.live_contacts` removes historical generated bodies, and the inline
transfer excludes these contacts so a replay cannot restore obsolete copies.
