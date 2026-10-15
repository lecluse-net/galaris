# ADR 0186 — Managed files and verified internal storage moves

- Status: Accepted
- Date: 2026-10-15

## Decision

`core.storage` owns the technical `files` registry, volume identity and disk driver.
`app.file_share` exposes authorized `file://<uuid>` resources and private standalone
uploads. Chat and Memory retain attachment membership and authorization. Keeping the
technical registry in Core avoids a Memory → File Sharing → Memory dependency cycle.

The fixed disk root is `/data/files`. UUID v4 identities use two hexadecimal shards:
`/data/files/aa/bb/<uuid>`. Names are metadata, independent of physical keys. Rows retain
backend code, opaque storage key, byte count, SHA-256 and audit fields. Only the disk
driver is implemented. Other providers may be added later without changing logical URIs.
The existing thumbnail engine and `/data/thumbnails` layout remain unchanged.

Domain aliases retain existing `document://.../attachments/...` and `chat://...` access
checks. A file UUID alone grants no access. Standalone uploads have an agent owner;
attachment files inherit access through their authorized domain references. External
references retain their provider URI and never acquire fictitious native ownership.

## Migration and recovery

DbAdmin inventories internal document attachments, retained manifests and revisions,
the document-split archive when present, and native Chat files. Memory document bodies
and revisions remain in their original store; a moved shared resource remains readable
through the native reader's managed-file fallback. External transports are never opened.

A durable, immutable manifest records each source, UUID, aliases, size and checksum
before transfer. Each transfer stages on the destination filesystem, fsyncs and publishes
atomically without replacement. SQL registration commits before a separate cleanup
action can remove sources. Cleanup first validates the whole inventory, registry and
target checksums, then removes only individually verified source paths. Missing files,
conflicting UUIDs, changed inventories and corrupt destinations stop the operation.
Interrupted transfers and cleanups resume from the manifest and actual data.

DbAdmin now journals applicable actions before DDL. Otherwise a crash between committed
expansion and the first action could lose the schema delta and silently skip the move.
The volume UUID is bound to PostgreSQL and checked on every synchronization. An absent
or replaced volume blocks startup rather than creating an empty authoritative fallback.

## Reference retirement and physical deletion

Deleting a document removes its file aliases in the same transaction as its metadata
and ACLs. Files without another reference are soft-deleted. Only after commit may the
cleanup verify and unlink their bytes; `purged_at` records completion. Permanent
tombstones reject UUID resurrection, and DbAdmin resumes pending purges in bounded pages.
Chat aliases, independent-owner reservations and immutable archive reservations protect
shared bytes. Reservations are not access grants. No sweep of active or merely unlisted
files is authorized by this lifecycle.

The broad regression suite exposed a missing deletion consumer: managed reads had been
adapted while Memory's physical cleanup still targeted its legacy directory. Keep the
existing document-deletion test, and verify reference sharing, rollback and interruption
recovery in `core/storage/tests/test_lifecycle.py`; targeted upload tests alone are
insufficient to qualify this cross-domain change.
The populated upgrade scenario also includes previously deleted documents: their
description tombstones must not be mistaken for missing source files. Historical and
archive manifests remain authoritative. A detached Memory cleanup worker must keep
its own SQL session through managed-file cleanup; its test must not inherit a request
session that would hide an early context close.

## Operational consequences

Stop legacy writers and mount the final disk before upgrading. `make update` stops and
recreates the backend before its entrypoint runs DbAdmin. Do not use an online schema
sync to migrate a still-running legacy writer. Backup PostgreSQL, `/data/files` including
hidden identity/manifest files, `/data/memory`, and remaining `/data/chat` data together.
Large transfers extend startup; provision free space for verified transfer before source
cleanup. A backup restore includes the volume identity, not just UUID blobs.

Datasets, `data://`, declarative forms and additional storage drivers remain separate work.
