# 0261 — Capacity-routed, source-owned document retrieval

Status: accepted. Date: 2026-10-31.

## Context

A compressed file's byte size does not measure its model input cost. Passing an
oversized PDF directly to a provider also supplies no guarantee that its tail was
read. Existing resumable document analysis traverses the source for exhaustive
questions; private Memory indexes do not own uploaded files or their permissions.

## Decision

Automatic document input admission uses a local UTF-8 token estimate against the
selected model's context capacity, after conversation, static tool schemas, output
reserve and a 20% safety margin. Unknown capacity uses a conservative 32,000-token
fallback. Multiple documents share the remaining budget. No generative classifier
decides whether retrieval is needed. Explicit direct/prepared gateway modes remain
overrides; prepared mode retains exhaustive traversal.

An oversized source is prepared completely, split into overlapping passages, and
searched with lexical scoring plus the configured embedding model when available.
Embeddings rank passages; they do not make the admission decision. Results include
physical page numbers and character offsets, explicitly state that selected text
is not exhaustive evidence, and direct visual/exhaustive questions to
`document_analyze`. Unextractable pages are reported. No source passage is treated
as an instruction. Failed embeddings fall back explicitly to lexical retrieval.
Preparation and index limits fail explicitly rather than publish a partial index.
Passages, vector values, embedding time and output size are bounded.

Semantic-only candidates must clear a conservative cosine floor of 0.5; their rank
alone never establishes relevance. Lexical candidates remain independently eligible.
The floor separates weak/opposite synthetic neighbors and was checked on relevant
FR/EN and unrelated queries using a configured embedding model. It is a retrieval
admission policy, not proof that a passage answers the question. Absence of sufficient
retrieved evidence never proves absence from the source. No LLM classifies admission
or relevance. Raw binary/base64 delivery does not establish decoded or exhaustive
reading; read-tool descriptions and the runtime skill make that distinction explicit.

`app.llm` owns retrieval without depending on File Sharing. `app.file_share` checks
the exact canonical resource's access before loading or publishing an optional
cache. Managed immutable files attach this disposable projection to `core.storage`
through a generic `file_derivatives` table. The projection contains extracted text
and vectors, keyed by source digest, reader/chunker version and embedding identity.
There is one generation per file/namespace; a changed model replaces it. Inline
gateway uploads and remote files without a managed identity use request-local
indexes, with no persistent RAG cache. This does not change remote catalog indexing.

Agents may query an exact documentary file URI using the existing `file_search`
tool in semantic or lexical mode. The response contains one file hit with bounded,
structured source passages and explicit non-exhaustive coverage, without a cursor.
Different questions reuse the same managed-file index, including across authorized
agents. Current source permissions and version are rechecked after retrieval.
Lexical queries make no embedding calls and never replace a semantic generation.
Managed file metadata and automatic RAG inputs advertise this follow-up path; the
runtime skill documents it. Existing collection and typed resource searches retain
their semantics. Neither admission nor explicit retrieval writes personal memories.
File Sharing declares a structural reader port; the application composition binds
the LLM implementation, preserving the existing dependency budgets.

Projection publication belongs to an awaited storage infrastructure worker with
a fresh context and a short transaction. It neither inherits the caller's database
session nor commits the caller's pending business changes.

Retiring a file reference deletes its derived text and vectors in the same SQL
transaction, even when another reference retains the original bytes. Publication
and retirement lock the immutable source row in the same order. A tombstoned
source rejects late publication. Rollback preserves the source and its index;
physical-byte cleanup remains separately recoverable. A still-authorized alias of
a shared, live source may rebuild the index. A foreign-key cascade also protects
physical SQL deletion. Ordinary conversation history retains its own lifecycle.
Preparation workspaces follow source retirement too: composition binds a storage
cleanup port that invalidates all local reader entries, cancels and reaps active
converter tasks, then removes their files before retirement can finish. A short
source-locked registration prevents new workspaces racing past retirement. These
callbacks never run SQL; cache eviction on rollback is safe and rebuildable. Confirmed
external deletions retain their successful mutation result if cleanup fails, with
`indexing_status=failed`; a cleanup error must not invite replay of the source effect.
Removing an attachment from the current Document retains its source for revisions;
forgetting the owning Document retires these references and purges the derived index.

After full initial materialization/hash verification, managed immutable sources reuse
their preparation manifest when file identity, size, device/inode and modification/change
timestamps remain unchanged. Exact URI access and metadata are checked on every read
and after preparation. A changed fingerprint forces a fresh materialization. Sources
without this immutable identity retain complete reads before cache lookup. Prepared
text is not retained in a process-wide RAM cache: manifests are validated off-thread
and bounded by seven days, 2 GiB and 256 entries per agent; active readers hold workspace
locks against quota eviction. No filesystem path is exposed to an agent.

## Verification and limits

Synthetic tests cover tail evidence, bounded citations, context/history/tool/output
admission, Chat and Responses preservation, embedding reuse and corrupt-cache
rebuilds, real uploaded-file access, same-file direct delivery to a larger model,
transaction rollback, deletion and late index publication with separate committed
database sessions. File retirement retains bounded batch queries.

MCP tests exercise repeated questions in internal and Hermes contexts, source
positions, lexical requests without embeddings, denied access, no new Memory items
or revisions, shared attachment index reuse and grant revocation.

Regression tests reproduce and reject negative, orthogonal and weak semantic neighbors.
Preparation tests cover measured immutable reuse, denied access, source deletion during
conversion, cleanup of all shared readers and explicit cleanup failure after a confirmed
external deletion. The real-model qualification uses disposable synthetic 20-page files,
including an OCR-only final page, multiple sources and an absent fact. Its independent
checker requires actual MCP retrieval receipts and exact page/character citations, rejects
fabricated values/locators and unsupported full-reading claims, and records bounded
requests, tokens and duration. It does not create Tasks, Agents or personal memories,
and does not qualify the scheduler or a managed external runtime.

Input cost remains an estimate rather than a provider tokenizer or billing figure.
Dynamic tool discovery and provider envelopes use the safety margin. Retrieval
cannot prove an absence or exhaustive visual coverage. Per-file vector scoring is
bounded and local; this change does not introduce cross-file vector search or put
uploaded content into an agent's private Memory.
