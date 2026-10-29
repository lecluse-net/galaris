# 0249 — Memory evidence budgets and native Dataset retrieval

Status: accepted, 2026-10-29.

## Decision

Continuity requests consult prior evidence before dependent answers or actions when
the injected brief lacks the required facts. A focused search may be followed by at most
two complementary searches. Self-contained requests and evidence already present do not
require redundant calls. Corrections retain old evidence unless erasure is explicitly
requested; unresolved contradictions are not resolved solely by recency. This aligns the
driver-neutral policy with the runtime Galaris skill. Instructions alone do not prove
real-model compliance.

Conversational French/English references can recover the nearest distinct human subject
within six recent messages for lexical recall, including when embeddings are unavailable.
The selected message is bounded to 600 characters before the unchanged 18-word/240-character
query budget. Machine replies cannot supply that lexical subject. Explicit topic resets drop
history from lexical and semantic seeds; named Tasks and structured Goal titles keep their
existing independent lexical subjects. No additional model call, storage or permission is added.
This is a bounded search hint, not an assertion that human history is authoritative evidence.

`memory_remember` can explicitly link a contradictory claim to an owned personal memory using
`contradicts_memory_id` and `expected_revision`. Acquisition rechecks the target under lock;
its idempotency identity includes that revision so reconsideration after a conflict can succeed
without replaying an obsolete pending proposal. Ordinary repeated calls remain idempotent.
The fact is acquired normally before linking, so a creation commit cannot release the target
lock during link publication. A late conflict reports the preserved fact and missing link;
reconsideration reuses that fact rather than creating another copy.

A saturated calendar retains the first positions but leaves up to half the bounded brief
slots for ordinary evidence. Unused reservations return to calendar entries. Character
budgets and access/contact admission remain strict; omitted appointments remain readable
through `memory_upcoming`. The former single ordinary slot lost complementary project facts
even when retrieval had found them. Large HTML table passages retain column labels
and complete ordinary rows. Locators still address the canonical block and revision.
The semantic index generation is incremented to rebuild existing passages.

Dataset owns its JSON, query engine and rebuildable embedding generations. It consumes the
public `app.llm` embedding handle; its MCP read operation uses `app.tools` registration and
the existing File Sharing connection. These consumers justify the two added declared
dependencies. No Document, personal memory or Process is created for Dataset retrieval.

Text discovery combines PostgreSQL full-text and literal matching, ranked before bounded
hydration. Semantic discovery fuses lexical and vector candidate ranks. Its candidate window
and incomplete/unavailable-index fallback are explicit. JSON pointers and revisions accompany
evidence. Name-only discovery retains its contract. Ranked cursors are scoped to query, mode
and resource. Live access and source versions are checked after provider calls; stale generations
cannot transfer evidence onto edited content.

Dream's `resource.index_dataset` schedules Dataset-owned preparation and atomic publication.
All source content is covered or indexing fails explicitly. Large collections pack into bounded
passages retaining row pointers. Publication checks model, source metadata and version under
lock; partial generations are ineligible. The two additive tables converge through DbAdmin's
normal schema target; no application content migration is needed.

`dataset_query` reads one authorized revision using RFC 6901 pointers, filters, projections,
stable sorting and aggregates. It accepts neither executable expressions nor SQL. Aggregates
cover every matching row before pagination. Decimal source literals are preserved for arithmetic;
decimal aggregates are strings and averages report precision. Missing/null counts are explicit;
incompatible numeric types fail. No units or date formats are inferred. Queries create no
revisions and grant no rights. Row output is bounded, with resumable offsets or an explicit
request to project a smaller row. Consumers should supply `expected_revision` on every page.

## Measurement

Reuse the existing synthetic memory campaign with frozen previous sources, paired order and
distinct retrieval/injection scores. Include passage/index sources in campaign fingerprints.
Each comparison arm must also use its own query constructors; otherwise a current query change
contaminates the frozen reference before retrieval begins. Cover concurrent routing and legacy
constructor signatures in the measurement tests.
Offline Recall@k excludes unanswerable cases; forbidden results are checked beyond k as well.
Prescribed embeddings qualify SQL, publication and authority, not model relevance. Real-provider
recordings, final answers and agent tool use remain distinct qualifications. Synthetic calendar
saturation does not measure its production frequency.
