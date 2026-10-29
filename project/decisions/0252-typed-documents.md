# 0252 — Typed Documents with common ownership and history

Status: accepted. Date: 2026-10-29.

Documents are the common identity for authored resources. `app.document` owns
metadata, sharing, classification, content revisions and storage. Its `text` and
`data` submodules supply HTML and JSON behavior. This supersedes the independent
Dataset ownership and library in decisions 0187 and 0211; Process definitions and
private Memory retain their own domains.

The public types are `text` and `data`. Historical `html` creation inputs remain
compatible. A registry supplies creation defaults, validation, extraction and the
frontend editor/preview contribution. All creation menus and type filters use it.
Each document has its own sharing policy through `app.share`.

The current-summary policy from decision 0246 applies to both types: manual edits
remain protected, generated summaries use cumulative change, and restoration never
rewinds descriptions or keywords. Memory accepts canonical type codes and reads
the live source summary and its media type. Text recall retains source-plus-summary
indexing; Data retains the native JSON retrieval from decision 0249, without a
second Memory embedding generation or inclusion in general personal-memory recall.

Native content has exactly one representation: text in `documents.content`, or a
`documents.file_id` reference to an immutable `core.storage` file. Revisions retain
their text or file reference. Metadata changes do not create content revisions;
restoration does not restore ownership, sharing, descriptions or keywords.

The transition retains old Dataset tables as recovery evidence. A required,
transactional DbAdmin action transfers exact content, revisions, current metadata,
ACLs, timestamps and personal classification, including deleted records. Verified
historical projections are merged; unrelated identity collisions stop the transfer.
Persistent transfer markers prevent replay from restoring revoked rights or
overwriting later edits. Existing `data://` references and Dataset HTTP contracts
delegate to the common records. Personal HTML-application consents and write budgets
remain enforced. Old tables are contracted only in a separately reviewed release.

Retiring the older summary-history table preserves every original row in the
durable `galaris_migration` schema with a verified digest before contraction.
Archived resource pointers retain their stored bytes. This is recovery evidence;
the application still exposes one current summary. Source changes or archive
damage stop retirement instead of replacing the original evidence.

Acceptance: create/open/edit/reopen both types in one library; filter before
pagination; preserve invalid JSON drafts; enforce live permissions and conflicts;
retain exact historical bytes and restore content through its editor profile;
preserve existing links, attachments and consents;
retain files referenced by historical revisions. Verify migration rollback,
idempotency and rejection of conflicting identities with synthetic PostgreSQL data.
