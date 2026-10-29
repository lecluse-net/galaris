<p align="right"><a href="../../fr/dev/datasets.md">Français</a> · <strong>English</strong></p>

# Data documents and JSON contracts

`app.document` owns every document's identity, current content, metadata, sharing,
classification and revisions. `app.document.text` supplies HTML behavior;
`app.document.data` supplies JSON behavior. `app.document.type_registry` describes
the available types and their validation. The public JSON facade is
`app.document.data.facade`. Historical `app.dataset` and `app.dataset.facade`
imports delegate to this implementation and own no second content copy.

## Persistence and history

Public types are `text` and `data`. Existing HTML becomes Text. Data accepts every
JSON root without an associated schema and preserves exact UTF-8 source, including
indentation and line endings. Each write checks current permissions and
`expected_revision`. Invalid JSON never replaces the last saved version.

`documents` and `document_revisions` are shared. The `text` storage mode keeps content
in the database; `file` references an immutable `core.storage` file under `/data/files`.
A revision protects its file even after current content changes. Thumbnails are
rebuildable derivatives. Title, owner, Topic, sharing, summary and keywords are current
metadata; editing them creates no content version. Restoring content creates a new
version without restoring those metadata fields. Summary format is explicit: existing
plain-text Data descriptions remain plain text and are never interpreted as HTML.

## Library and interfaces

The Documents library lists Text and Data, filters types before pagination and applies
permissions to counts. The creation button opens the type menu; context menus offer
the same types. The editor shell is shared. Text supplies the HTML editor; Data supplies
JSON `CodeEditor`, including historical previews. Autosave preserves invalid drafts
and blocks leaving until a draft is saved or abandoned.

`POST /documents` accepts `document_type="text"` or `"data"`. `/datasets` routes and
`data://` URIs remain compatible and access the same records. Historical `/dataset/:id`
links open the document in `/documents`. Document references grant no access. HTML
applications retain personal consent bound to the page revision and their write budget.

## Codec and queries

The variable codec retains `{type, value}` with `int`, `float`, `string`, `bool`,
`Agent`, `User`, `File`, `Document`, `Dataset`, `array` and `object`. Historical
`app.process.values` imports retain the frozen BPMN v2 profile. Process owns variable
declarations and executable definitions; those definitions do not become Documents.
Typing a reference never authorizes its target.

Codec integers must be safe for JavaScript transport. Non-finite numbers, duplicate
object keys and oversized inputs are rejected. A document's JSON source nevertheless
retains its exact numbers; the Process codec does not normalize that source.

`dataset_query` queries an authorized `data://` using RFC 6901 JSON pointers, AND filters,
projection, sorting, pagination and aggregates. `expected_revision` protects reads
between pages. Results distinguish missing and null values; numeric aggregates use
decimal strings. Units, expressions and implicit date conversions are not inferred.
Pages default to 50 and accept 500, with bounded content. Semantic discovery depends
on the configured vector model and Dream indexing; incomplete coverage remains visible.

## Migration and compatibility

Decision [0252](../../../project/decisions/0252-typed-documents.md) describes the transition.
DbAdmin archives sources, transfers exact content, versions, authors, permissions and
metadata, and verifies copies before finalizing types. Historical documentary projections
with the same identity are merged; collision with an independent document stops transfer.

Current Dataset classification is authoritative for its documents. Historical projection
placements are archived and replaced to prevent obsolete sharing inheritance from
returning. Personal folders and appearances are retained. Dataset roles receive the
corresponding Document capabilities for the shared library. Durable markers prevent
replay from restoring revoked access or overwriting later edits.

`datasets` and `dataset_revisions` remain recovery sources. Their removal belongs to a
later release; this migration deletes neither source table. Verified aliases,
attachments, consents and budgets keep their identities and checks. Real PostgreSQL
upgrade tests live in `app/document/tests/test_typed_document_upgrade.py`.
