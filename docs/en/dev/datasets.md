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
The Documents library excludes Datasets, including historical projections, before
counting, pagination and filter catalogues. `POST /memory/documents` rejects the
`dataset` type; creation uses `POST /datasets` or `file_create(path="data://", ...)`.
Reading an old Dataset through `GET /memory/documents/{id}` returns only
`{resource_type: "dataset", resource_uri: "data://…"}` after authorization, without
a Document payload. Old links open the Dataset editor. Memory search and graph exclude
these historical projections from current Documents. HTML `data://` links remain Dataset
references and are searched through their owning domain.

A Document can attach live Dataset references through its `dataset-attachments`. Its
manifest stores only URIs, without copying JSON or granting Dataset access. Mutations
check Document write access and lock version, plus independent Dataset read access on
attachment. Unavailable references no longer reveal their title. Detaching preserves the
Dataset. `file_list` on attachments returns readable `data://` references without offering
deletion of the attached resource. Dataset usages include these references under Document ACLs.
Writes require `expected_revision`; sharing requires `expected_lock_version`. File Sharing's
registered `data://` provider uses these same services.

MCP reads retain exact JSON and character offsets. They also expose one-based `start_line`,
`end_line` and `total_lines`, plus `start_line_complete` and `end_line_complete`. These flags
identify lines cut by pagination: read their missing text before replacing them with
`file_edit`. Empty pages have no line coordinates. Edits still require `expected_revision`;
these coordinates avoid rereading the entire inventory just to count its lines.

Planner collection inventories are created directly with
`file_create(path="data://", name=..., content=...)`. The receipt retains the exact returned
URI and must match a successful operation by the discovery step. The planner rereads complete
JSON under the agent's permissions before freezing the list; old `document://` receipts
remain usable only through verified Dataset aliases. An HTML Document cannot serve as a
JSON inventory. The internal inventory is not a deliverable to send. Missing JSON in `content`
is rejected before effect, with guidance naming the argument to correct, and creates no resource.

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

`GET /datasets/{id}/owner` returns the owner and authorized targets.
`PATCH /datasets/{id}/owner` requires write and management access and
`expected_lock_version`. Targets are managed agents and the current user;
`DATASET_ADMIN` also permits other active users. Transfers keep the former owner as an
editor, remove the new owner's redundant grant and update the historical projection
without changing content or its revision. Read-only Datasets are excluded.
The frontend indents loaded JSON without re-encoding numbers or strings;
display formatting does not make the draft dirty.

`GET /datasets/{id}/usages` pages `documents`, `processes` and `agents` categories.
The composition root registers public Memory, Process and LLM providers; Dataset imports
none of their models. Queries cover current native Document content, run references and
snapshots, and retained tool traces. Source-module permissions and ACLs apply before counts
and pagination. These are observed references, not an exhaustive dependency graph.
Deletion remains logical, with a lock and expected version.

Process runs store variables in `process_runs.data` and file links in
`process_run_files`, without a Dataset. Variables, links and execution receipts commit
atomically. Access follows the parent Process's existing policy. Dataset provides the
shared typed codec without owning run storage.
Former metadata markers `engine_dataset`, `engine_managed` and `engine_agent` confer no
special status. Ordinary permissions govern reads, writes, attachments, ownership and
deletion, including Memory aliases. Logical deletion still requires management access
and the expected version; history and Process runs remain intact.

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
