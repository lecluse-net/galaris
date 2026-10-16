<p align="right"><a href="../../fr/dev/datasets.md">Français</a> · <strong>English</strong></p>

# Datasets and data contracts

`app.dataset` owns the common codec, Datasets and their JSON operations.
Its public facade is `app.dataset.facade`. Historical imports from
`app.process.values` retain the frozen BPMN v2 profile restrictions.

```json
{
  "approved": {"type": "bool", "value": false},
  "report": {"type": "File", "value": "file://00000000-0000-4000-8000-000000000001"},
  "note": {"type": "string", "value": null}
}
```

The variable codec uses `{type, value}`. Supported types are `int`, `float`, `string`,
`bool`, `Agent`, `User`, `File`, `Document`, `Dataset`, `array` and `object`.
Containers recursively contain typed values. Integers must be exact and safe for
JavaScript transport. Non-finite numbers, duplicate JSON keys and oversized values
are rejected. Type checks do not grant reference access; resolution checks live ACLs.

Datasets accept every JSON root type without an associated schema. Content and revision
source text remain exact. The typed codec remains available for process variables; Process
owns their declarations and validation. Document applications use the Dataset bridge under
the viewer's permissions and personal consent. Free writes and restores check JSON,
permissions and revisions without imposing a business structure.
Writes require `expected_revision`; sharing requires `expected_lock_version`. File Sharing's
registered `data://` provider uses these same services.

The resumable DbAdmin action `app.dataset.legacy_documents` retains original rows
and files and creates verified aliases. Legacy Memory entry points delegate to the
Dataset authority. The HTML bridge preserves personal consent for the exact document
revision and binding, with one persistent user/Dataset budget of 30 writes and 4 MB
per minute across applications.

Sharing reuses `DocumentSharingLevelUpdate` and Memory's recipient directory.
`PUT /datasets/{id}/sharing-level` atomically replaces the level and grants under a lock
and `expected_lock_version`, without rewriting JSON or revisions. The common frontend
`SharingPanel` handles read/write grants and group inheritance. Editors do not become
owners; read-only resources cannot be reshared.

`GET /datasets/{id}/usages` pages `documents`, `processes` and `agents` categories.
The composition root registers public Memory, Process and LLM providers; Dataset imports
none of their models. Queries cover current native Document content, run references and
snapshots, and retained tool traces. Source-module permissions and ACLs apply before counts
and pagination. These are observed references, not an exhaustive dependency graph.
Deletion remains logical, with a lock and expected version; the engine retains ownership
of its Datasets' lifecycle.

## Historical projection and retirement criteria

Dataset is the sole authority for content, history and permissions. Native `data://`
creation does not create a Memory Document. Only a verified migration alias receives a
`DatasetDocumentProjection`, defined in `app.memory.contracts`: metadata, version, hash
and grants, without content or history. Deletion removes the projection from current
readers while preserving sources and the alias as migration evidence. This state is
read through an explicit asynchronous query.

Historical Memory calls remain adapters to Dataset for editors, HTML applications,
attachments and Process consumers that still use them. New consumers use
`app.dataset.facade` or File Sharing with `data://`.

Retiring the projection requires migrating these consumers, removing Process foreign keys
to the historical Document, and qualifying content, revisions, sharing/revocation,
attachments, consent and budgets through canonical URIs. Verified aliases remain a contract
for reading old references independently of the projection. Preserving them and migration
evidence does not require another content write path. This consolidation does not remove
source rows.
