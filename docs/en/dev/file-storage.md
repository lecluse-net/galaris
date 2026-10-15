<p align="right"><a href="../../fr/dev/file-storage.md">Français</a> · <strong>English</strong></p>

# Internal files and storage migration

Internal files have a `file://<uuid>` identity and a `files` registry in `core.storage`.
File Sharing exposes reads, copies, independent uploads and thumbnails. Chat and Documents
retain attachment membership and authorization. Datasets remain documents in this release;
`app.dataset` and `data://` belong to a later step.

## Storage

Current and historical Memory/Document text now lives in PostgreSQL `content`
columns. Transfer preserves `/data/memory` sources and a verified SQL backup.
See [text storage in the database](memory-text-storage.md).

Only the `disk` driver is implemented. Bytes live under
`/data/files/<first 2 hexadecimal characters>/<next 2>/<canonical uuid>`, without an
extension. `files` stores the official name, original name, MIME, actual size, SHA-256,
backend, opaque storage key and audit fields. A display name is never a filesystem path.
The driver protocol supports later evolution; no S3/SMB driver or SDK is included.

`file_aliases` links files to their historical domain references. Reading `file://`
requires an independent owner (`file_owners`) or a Document/Chat reference authorized
at access time. Knowing the UUID grants no access. The parser rejects `file:///etc/...`,
Windows paths, hosts and traversal.

`file_create(path="file://", name=..., content=...)` creates an independent file private
to the agent and returns its URI. `file_copy` accepts this collection as an explicit
destination. Bytes are immutable; create another file for different content. HTTP uploads
stream with the `MEMORY_RESOURCE_MAX_BYTES` bound. MCP retains its existing content limits.

The `/file-share/files` API accepts multipart uploads for a managed agent. Its
`/{uuid}/content`, `/{uuid}/thumbnail` and `PATCH /{uuid}` rename routes enforce RBAC,
management scope and file access. Only an independent file's owner can rename it;
attachment names remain in their domain manifests. Browsers use authorized HTTP
downloads, never direct local filesystem access.

The `core.preview.thumbnails` engine, `/data/thumbnails` root and rendering remain
unchanged. The new facade uses `file://<uuid>` as its cache reference. Historical
attachment routes and caches continue to work.

## DbAdmin migration

`file_storage_composition` declares an `AFTER_EXPAND` transfer and an `AFTER_CONTRACT`
source removal, triggered by adding `files`/`file_aliases`. DbAdmin journals obligations
**before** Atlas: an interruption after table creation cannot lose the migration.
Each phase has its own database transaction.

The inventory includes:

- Document attachments, imported images and link cards, including retained attachments;
- revision manifests and the Document/Memory split archive when present;
- files owned by the native Chat Tool, including uploads and voice notes.

A description pointer left by an already forgotten document is not a source: the old
store may legitimately have erased its bytes. References still held by a manifest,
revision or archive must still be migrated and verified.

External references such as Nextcloud are never opened, downloaded or moved. Document
bodies, summaries and Memory revisions are not indiscriminately treated as attachments.
Existing HTML, JSON, messages and receipts are not rewritten and no domain event is replayed.

The durable `/data/files/.migration/internal-files.json` manifest precedes the first
transfer. It records sources, UUIDs, names, aliases, sizes and checksums. A changed
inventory or source stops recovery. Destinations are published atomically after
verification and fsync. A UUID collision with different bytes blocks without overwriting.
Sources remain until the registry commits and all destinations pass verification.
Cleanup then removes only explicitly inventoried and individually verified source paths.
An interruption leaves durable destinations; recovery accepts only already removed
sources whose destinations can still be verified against the manifest.

## Operations

The container root remains `/data/files`. An additional override mount can put it on
a dedicated HDD or volume, independent of PostgreSQL and thumbnails:

```yaml
services:
  backend:
    volumes:
      - type: bind
        source: /mnt/galaris-files
        target: /data/files
        bind:
          create_host_path: false
```

Prepare the host directory and mount the final disk **before the first migration**.
Volume initialization sets directory ownership for the application user. Any future
worker using these bytes needs the same mount and appropriate access. The hidden
`.store-uuid` file is bound to `file_stores` and checked on every synchronization.
Never delete or replace it to bypass a failed check.

Stop legacy writers before migration. `make update` recreates the backend and runs
DbAdmin before the API; do not migrate a running legacy backend through an online sync.
Allow space and startup time for verified transfer: moving between disks copies and
verifies bytes before removing sources. An anomaly blocks startup and preserves
available sources. Repair the mount or source and rerun the same DbAdmin path without
deleting its journal.

Back up PostgreSQL, `/data/files` **including hidden files**, `/data/memory` and remaining
`/data/chat` data together. Restore them at the same logical point. Chat cleanup never
walks the shared registry to delete another domain's files. A detached attachment remains
readable when retained by a document or its history. Deleting a document removes its
references in the same transaction. Only files without another reference are retired;
after commit, their bytes are verified and removed. A Chat reference, independent owner
or Document/Memory archive always protects the file. Internal `agent-file://` and
`archive-file://` reservations grant no read access.
The retained `files` tombstone prevents UUID reuse. `purged_at` records completion;
the DbAdmin reconciler resumes interrupted purges, including an unlink followed by
an interrupted commit. Active file bytes are never swept.

Synthetic storage, migration, authorization and regression coverage lives in
`core/storage/tests`, `core/dbadmin/tests`, `app/memory/tests/test_managed_files.py`,
`app/chat/tests` and `app/file_share/tests`.
The document-deletion scenario in `app/memory/tests/test_service.py` must also pass:
it protects physical removal of attachments that are no longer needed.
