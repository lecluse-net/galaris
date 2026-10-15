<p align="right"><a href="../../fr/dev/memory-text-storage.md">Français</a> · <strong>English</strong></p>

# Text content in the database

Native text lives directly in the tables owning its state and revisions. Content,
metadata and history share one PostgreSQL transaction; new text writes create no file.

| Table and column | Content |
|---|---|
| `memory_items.content` | Current memory or independent document synthesis |
| `documents.content` | Current document content |
| `memory_revisions.content` | Memory and document history |
| `memory_summary_revisions.content` | Document synthesis history |

Columns use `TEXT` without normalizing line endings. `NULL` remains possible for
binary resources or external providers. Metadata lists and history pages exclude full payloads.
Resource URIs, access rules and update conflicts retain their current guarantees.

## Migration without deleting sources

`app.memory.content_migration` registers the DbAdmin action
`app.memory.inline_text_contents`, triggered by the new columns. Stop old writers
before the initial switch; `make update` applies the changes before starting the API.
Do not transfer while an old backend is still writing.

The migration processes batches of 100 rows and verifies SHA-256 and exact UTF-8 bytes.
It compares SQL values with an immutable backup in
`galaris_migration.memory_text_contents`. A missing source, changed hash, invalid text
or NUL character stops the transfer without deleting its source. Errors roll back;
replay preserves the backup and never replaces content legitimately changed later.

This migration deletes no files from `/data/memory`. Archived resources and legacy
Dataset sources remain available. Back up PostgreSQL **with `galaris_migration`** and
retained source files until their removal is explicitly decided. Attachments remain
in their existing file storage; external providers are neither downloaded nor rewritten.

See [rich content](../user/rich-content.md) and
[decision 0188](../../../project/decisions/0188-inline-memory-and-document-text.md).
