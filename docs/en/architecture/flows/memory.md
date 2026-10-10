<p align="right"><a href="../../../fr/architecture/flows/memory.md">Français</a> · <strong>English</strong></p>

# Memory Flow

Durable memory is a governed Galaris domain. A driver or bridge never reads its storage
directly and never decides the scope of a session on its own.

The document retains its authoritative content; its Memory item has independent
content that can serve as a synthesis, without an additional `summary` field. Search
and embeddings cover both contents and keywords, plus the document title or the
memory's derived label. Previews remain computed excerpts. The v5 semantic index
is rebuilt in the background after DbAdmin synchronization.

Updates and acquisitions carry no free-text `reason` comment.
History retains content, versions, authors, tasks and dates. Document append retries
are recognized through an internal `document_append` marker; DbAdmin converts legacy
revisions before removing their reasons. Dream's `retention_reason` eligibility
criterion remains enforced.

Memories are described by their content and provenance, without the retired
`memory_type` field. When removing it, DbAdmin normalizes only machine-owned fields in
memory metadata, memory Dream checkpoints and memory extraction Lab experiments.
Keywords, authored JSON content, tested values, schema examples and defaults,
source captures and call journals are preserved.

## Read Before an Execution

Items may carry an optional `temporal` object (year, month, day, ISO weekday, hour and minute).
All components use Galaris's global timezone (`TZ`); memories store no timezone override.
Missing components are unrestricted; supplied constraints are combined.
Context preparation restricts ordinary recall to unanchored memories and separately selects current matches and those within
`MEMORY_TEMPORAL_LOOKAHEAD_HOURS`, without a query-similarity requirement. This path preserves
ACLs, contact scope and final admission, deduplicates UUIDs and respects the shared budget,
with calendar matches taking priority over ordinary memories and experiences. Dated memories
outside the window cannot return through similarity. Topic and type filters do not limit the
calendar branch; conversational contact isolation remains mandatory.
The occurrence stays in the excerpt used by conversational context capsules. `memory_upcoming`
exposes further pages. Temporality is independent of validity and triggers neither notifications
nor expiration. See decision [0144](../../../../project/decisions/0144-partial-memory-temporality.md).

The administration list reuses `next_match` through the `temporal` filter on `/memory/browse`.
The UI always applies the filter from the first search, with no option to disable it.
It prefills a single date/time field in Galaris's global timezone. The server resolves edited
local targets in that same timezone; the initial target preserves its UTC instant, including
within repeated hours. Lookahead remains zero and matches display in the global timezone,
independently of the browser timezone. Text/topic/interlocutor filters select unanchored memories.
The calendar branch independently selects matching anchors without requiring lexical or semantic
relevance. Their union is counted, sorted and paginated in SQL before hydration; calendar matches
come first by default. The text recall cap does not truncate calendar results. Responses
include `temporal_window` and a per-result `temporal_match_at` (null for undated memories). Simulations retain current ACLs,
validity and revisions.

```text
app.messenger journal ──► bounded session snapshot ──┐
                                                     ├─► AgentRunContext
PostgreSQL Memory ── ACL/validity ── hybrid ──► brief ─────────┘         │
                                                              ├─► Pydantic AI history + context
                                                              └─► Hermes MemoryProvider + history
```

The session snapshot is indexed by connection and room. The journal is authoritative as soon as it
contains rows; `Task.messages` and a runtime's history serve only as fallbacks.

The durable brief does not trigger any model. The query first filters by owner, direct access,
public visibility, validity dates, and contact scope. The Agent profile
projection remains excluded from the brief, since identity and personality already come from the
canonical profile in the system prompt, but it remains available to explicit search. Lexical
evidence and semantic similarity order admissible candidates; a low score alone does not empty
recall. Results may be empty when no admissible candidate is available. The final item and
character budgets remain strict, and each excerpt carries the logical
identifier and its sources.

Final admission checks each result independently within one SQL `READ COMMITTED`
snapshot: its revision, content fingerprint, permissions, validity and graph path links
must still match. A valid result does not readmit another obsolete occurrence of the
same UUID, including when pages overlap. Paginated search also attaches each excerpt
to its own revision. Changes committed after this check apply to subsequent admissions.
Revision and path proofs are passed as bound data to a fixed-shape query:
increasing the result count does not multiply the SQL branches to compile and plan.

The Topic is a ranking prior, never an implicit access boundary. With a current canonical Topic,
its memories receive the maximum thematic signal. Without a current Topic, the query vector
preselects the closest public Topic among those containing a memory accessible to the agent, only
if its similarity reaches `0,55`; its similarity bounds the prior's strength. In both cases, the
authorized global path remains merged so that a thematic ranking error cannot hide a genuinely
relevant memory.

The lexical query is never the Task's complete objective. It is derived deterministically and with
bounds: the structured Goal title when one exists, otherwise the Task label, and finally a short
excerpt of the objective as a last resort. For a conversation round, technical sender prefixes and
the Agent code are removed; the semantic seed adds at most the two immediately preceding
canonical messages to resolve “try again,” “it,” and other references to the previous turn. For a
human Messenger Task, the contact's canonical UUID bounds the search; its display name, native
identifier, and bridge code are therefore not repeated in the semantic seed. Cycle suffixes are
removed so that a new cycle can retrieve previous ones. This reduction prevents a long prompt from
becoming an FTS conjunction that is impossible to satisfy.
Lexical candidate generation joins significant terms with `OR`, then ranks them by FTS coverage.
When the vector provider is unavailable, the fallback can therefore offer the best partially
matching memories instead of requiring every query word.

The stored `search_vector_folded` FTS projection normalizes accents and compatible
Unicode forms at write time. The query is normalized before tokenization. Recall
strengthens explicitly capitalized name groups and their complete sequence matches,
then rewards missing query terms and identities.
These signals require no additional search or model call and preserve temporal
anchor priority. They remain heuristics: homonyms, unknown aliases, pronouns and
historical dates need further evidence. See decision
[0158](../../../../project/decisions/0158-indexed-memory-query-evidence.md).

For an indirectly named person, positive statements between two full names can
identify the target in already readable excerpts. The relationship category must
match the request; negated, quoted or uncertain statements provide no such evidence.
A supported complete affirmative clause between the names is required, including
when checking contracted negations.
Only a uniquely identified target name receives this priority. Ranking then
prioritizes the target and relationship rather than only the named
reference person's profile. A neighbour already obtained through a strong confirmed
link may supply the role without a query word when its title starts with the resolved
full name. Scope restrictions still apply. Once the identity is covered, missing
requested terms take priority. Repeated excerpt word sequences are downranked without
merging or deletion, preserving numbers and negations. Translations and paraphrases
are not automatically treated as equivalent. No search channel or model call is added.

There is no memory space. Each standalone memory belongs directly to an agent and remains
private to that agent. Sharing applies to documents; their Memory synthesis inherits current
document permissions. Structural projections retain their domain's visibility rules.
Automatic acquisitions remain private and create no sharing grants.

### Scope of Conversational Memories

A Topic has a public and global `MemoryItem` projection. Each observed interlocutor separately has
a private `MemoryItem` node, deterministic for
`(agent, bridge, remote identifier)`. Every automatic extraction first waits for a Topic. Upon
extraction, a conversational memory is sealed to the contact by `MemoryContactItem`, and
`MemoryTopicContactScope + MemoryTopicContactItem` records the exact membership.
Governed acquisitions and writing tools reuse this server-side scope upon creation:
two interlocutors stating the same fact obtain two distinct memories, each sealed to its contact
record, with no exposure window while waiting for Dream.

```text
Public Topic ───── topic_contains ────► private memory
      └──── topic_involves_contact ───► private contact
private contact ─── contact_contains ──► private memory
```

The novelty recall filters on the Topic/contact pair. A memory already linked to one contact cannot
be attached to another.
The `topic_contains`, `contact_contains`, and `topic_involves_contact` links are graph projections
useful for navigation. The last one makes the structural pair directly visible, but a join on
these links never replaces the exact scope.
A conversational source without a proven contact remains ineligible. The absence of a Topic blocks
the three automatic Task, text-round, and Voice-turn extractors, without changing explicit tool
writes or the separate learning contract.

A `Document` owns its title, authoritative content and collaboration rights. It has
exactly one `MemoryItem` of nature `document`, whose HTML synthesis is optional.
Standalone memories are private to their agent, have a content-derived display label,
and have no editable title or independent sharing. Documents are private when created,
mutable and not deduplicated. The document and its graph node retain the same UUID and
existing URIs. Document and synthesis revisions are independent. Lexical and vector
search use both the full document and its synthesis, including an empty synthesis,
and return one result per pair. Synthesis access inherits the document's live rights,
including revocation. Documents are excluded from Dream acquisitions and automatic
inactivity forgetting. A document memory cannot be forgotten or merged independently.
Deletion uses `DELETE /memory/documents/{id}` and also erases the synthesis, its history
and associated resources under the document's deletion protections and permissions.
Revoking sharing removes the node from affected agents' lists, searches and graphs while
preserving the shared synthesis for its owner and remaining authorized readers.

The document and its synthesis share one current keyword list in `memory_items.keywords`.
Both editing routes normalize and write that list with document permissions and the common
optimistic lock. Keyword-only changes refresh search without creating a document or synthesis
content revision. Historical snapshots remain immutable. Migration from documents previously
stored in `memory_items` retains keywords in place and never resets them on replay.

## Collaborative Working Documents

```text
file_create(path="document://") ──► Document(private) + MemoryItem(empty synthesis)
       │
       ├─► file_read(document://uuid, offset) ──► bounded passage
       ├─► file_edit(start_line, end_line, content) ──► atomic revision
       ├─► file_append(document://uuid, content) ──► atomic revision
       └─► document_share(agent_id, read|edit|none) ──► direct grant
                                                        │
                                                        └─► another agent
                                                             ├─ file_search(document://)
                                                             ├─ file_read(document://uuid)
                                                             └─ edit/append if authorized
```

The MCP surface remains deliberately small. `file_search` provides discovery of `memory://` and
`document://` URIs; `memory_forget` provides explicit owner-based deletion.
`file_read` never returns an entire document by default: it accepts an offset for continuation.
`file_edit` replaces an inclusive range of lines, numbered starting at 1.
A missing range or concurrent revision fails without modification and requests a reread.
Revisions retain the authoring agent and Task.

The arrival of the `documents` table first triggers a DbAdmin `BEFORE_EXPAND` archive
of legacy items, revisions and grants in `galaris_migration`. Counts and digests verify
its integrity; the archive remains immutable and retained after migration.
`app.memory.document_split` runs at `AFTER_EXPAND`, creates documents from this archive
and rejects source changes between phases. Its transaction preserves resource pointers and associates immutable
revisions before initializing the empty synthesis. Previously shared standalone
memories become documents without losing access rights. Private memories retain
their authored titles in their content before switching to derived display labels;
earlier revisions remain readable. Failure rolls back the transfer, and replay
preserves an already authored synthesis. After transfer verification, contraction in
the same update removes `document_type`, `filename`, `visibility`, `global_access`
and `group_access` from `memory_items`. Structural export names remain in metadata
and historical contracts delegate to the document. Failure retains the columns and
supports automatic retry. Already expanded databases also use this archive before
removing the columns. Archived pointers protect resources against explicit forget
and orphan cleanup; this SQL archive does not replace file backups. Archive removal
requires a separate, explicitly validated administrative operation.

Before delegation, the owner explicitly shares the document and then places its UUID in the child
Task's objective. Agents keep provisional notes in the document and separately promote genuinely
durable conclusions with `memory_remember`.

The `app.agent` context registry is fail-open. It prepares a single shared value. Hermes receives
this exact value through the projected provider and does not recalculate it; the internal harness
receives it in the `AgentRunRequest`.

When the Galaris provider is active, generated configuration disables `MEMORY.md`, `USER.md`, and
the native `memory` tool by default. This policy is a default, not a lock: `hermes.default.config`,
then the agent-specific Hermes configuration, can explicitly reactivate either store or keep the
toolset disabled. The per-agent override always takes precedence.

The same provider adds a common system policy to drivers. The model must examine the brief, then
call `file_search(memory://)` only when durable context could materially change the work and the
brief is insufficient. A `high` or recurring Task requires this evaluation, never the call itself.
Transactional state remains read with the tools of its domain. An explicit search uses a short query
and the single hybrid strategy.

The injected brief presents itself as already retrieved and asks the model to consult it before any
new Memory search. Without changing this selective policy, the descriptions of `file_search` and
`memory_remember` make two voluntary uses more salient: explicitly searching for missing or
insufficient durable context, and spontaneously memorizing durable information likely to help a
future conversation.

## Single Two-Way Hybrid Recall

```text
API /memory/browse without text ───────► ACL/validity ──► SQL filters ─► page
                     with text ───────► bounded hybrid recall + temporal anchors

API /memory/search + MCP/voice/brief + any file_search(memory://)
       ├─► thematic path ──► FTS + exact cosine ─┐
       └─► global path ─────► FTS + exact cosine ─┼─► weighted ranking ─► diversity ─► results
                 strong confirmed links ──► reranking┤
                 sources + link centrality ─────────┤
                                                     │
              model/index/provider unavailable ─────┘
                                      signaled two-way lexical fallback
```

The hybrid mode is the sole strategy for bounded search surfaces (`/memory/search`, automatic
brief, MCP tools, and Voice). `/memory/recall` is a deprecated HTTP alias for the same contract.
It merges lexical and semantic candidates, returns the most relevant semantic chunk as the excerpt,
and indicates `mode`, `degraded`, and `degradation_reason`. No caller can deliberately degrade it
to lexical: this path is exclusively an automatic fallback when the model, provider, or semantic
index is unavailable. For `memory://`, the generic `mode` parameter of `file_search` therefore
does not change this strategy. The `/memory/browse` list uses hybrid recall with a text filter, at most 500 undated
results and a truncation indication. Without text it browses undated memories matching the
filters; temporal matches are added separately. Bounded recall announces neither an exact
total nor exhaustive pagination.

Version `memory-query-evidence/v12` merges FTS and pgvector in the current Topic when present,
then in the authorized global scope. Informative query terms, their rarity, named identities
and exact titles dominate ranking, complemented by semantic similarity. Topic, confirmed links,
sources, freshness and centrality supply secondary context bonuses. Diversity favors terms,
identities and facts not yet covered. A low lexical or vector score alone does not remove
authorized candidates. Centrality accounts for accessible links around the candidate, including
outside the top-k. Automatic injections create no
co-use association: being presented together does not prove a business relationship. The pool is
48 candidates and the result contains at most eight items by default; the pool, weights, and
diversity are configured exclusively by the global Params in the Memory section. A diversity
selection penalizes results that are too similar and keeps only one representative of near
duplicates. Its threshold is the single `MEMORY_DUPLICATE_SIMILARITY_THRESHOLD`, shared with
acquisition, findings, and automatic merges; it cannot be overridden per call. The internal
detailed result exposes each hit's sources and the numbers of thematic/global candidates and
results. An exact contact also bounds the global path: it accepts memories from that contact in
other Topics and autonomous non-conversational memories, but excludes any memory sealed by
another interlocutor. Without a contact, the global path retains ordinary ACL recall.

After these textual and vector ranks, recall inspects at most one hop from their candidates through
confirmed `MemoryLink`s (`suggested=false`) whose confidence reaches `0,75`. This `graph_link`
path, weighted at `1,1` and modulated by link confidence, enriches candidate context. A neighbor
without its own lexical/vector result can become evidence when accessible excerpts identify
one unique relational target; ambiguity, negation and uncertainty never arbitrarily select a
person. Confirmed structural paths can also supply passages matching query terms.
Lexical fallback ranks partial matches by FTS coverage without requiring every word of a
long query. These paths retain the same ACLs, validity and contact filters, then pass final
revision and path admission. A link,
even with confidence `1,0`, can therefore never bring a memory sealed to Paul into Jacques's
current recall.

A positive `topic_membership_candidate` proposal creates no candidate and does not define canonical
membership in a Topic. When a memory is already a candidate through an authorized path, however,
it adds the `suggested_topic_link` source and contributes to the graph signal by its confidence
multiplied by `MEMORY_RECALL_SUGGESTED_LINK_WEIGHT` (`0,25` by default). Anomaly, merge, and
separation signals remain excluded from ranking: their meaning is not unambiguously positive for
memory relevance.

The common brief and `file_search(memory://)` resolve the Task's Topic and contact record, or
those of the conversational turn, on the server side. For the automatic brief, the contact record
alone constitutes the identity boundary, and its label does not pollute the thematic query. An
explicit search may still use a name as a lexical term, without making it a boundary: the boundary
remains the contact's exact UUID and persisted membership.

The public `memory_role=topic` projections and structural contact records are never rendered as
factual memories by this surface. Their embeddings remain available for ranking and navigation.

The vector branch applies owner, grants, visibility, dates, and types in the SQL query before
distance calculation. It considers only chunks whose `model_key`, dimension, and
`source_fingerprint` match the current model and memory. pgvector search remains exact. The brief
keeps a short lexical query but passes the full objective, bounded by Param, to the embedding.
The executable benchmark accepts different semantic queries and pools to compare quality and p95
latency between a concise scope and an expanded scope. It also covers preference, contact,
procedure, correction, expiration, forgetting, inter-agent ACL, and lexical fallback; its baseline
reaches `recall@5 >= 90 %` without leakage. An ANN index under ACL filters will therefore be
introduced only after measured degradation on representative volume.

`access_count` and `last_accessed_at` measure only memory actually presented to an LLM, through the
common context or through `file_search` and `file_read`. Administration API and UI searches,
consultations, and sorting are always neutral, with no option allowing the client to change this
rule. These usage writes are atomic and never change `updated_at`. For a `MemoryItem`, `updated_at`
means exclusively the last effective modification of the payload or keywords; owner, title,
visibility, grants, provenance, and other metadata do not participate. Internal recalls used by
Dream to avoid duplicates never count as useful accesses.

`created_at` represents the memory's original date when a reliable producer provides one. Dream
passes it the creation date of the source Task, even when that historical Task is analyzed later.
Acquisition records, sources, and revisions retain their own write date to preserve the audit trail.
During a merge, the item retains the oldest known original date.

Usage distinguishes `context`, `search`, and `read`. The execution result additionally retains only
the short query, the numbers retrieved and actually injected, truncation, and the UUIDs of
injected items; the injected text is never copied into this metadata. The interface thus presents
the automatic brief separately from explicit `memory_*` calls.

## Acquisition, Dream, and Automatic Extraction

`memory_sources` is the provenance association between a memory and its canonical activity. Each
row retains the extensible `source_kind + source_ref` identity and, as applicable, carries a typed
foreign key to `tasks` or `conversation_rounds`. These two relationships are many-to-many: an
activity can produce multiple memories, and a reused or merged memory can be confirmed by multiple
activities. A creation, update, or merge always adds the new source without rewriting the content
during a simple merge. Memory tools called from a text or Voice round use the persistent round
injected on the server side; they fall back to `agent:manual` only when no canonical Task or round
exists.

The FKs use `ON DELETE CASCADE` only on the provenance row: physically deleting an activity removes
its association, never the `MemoryItem`. Ordinary writes directly populate the typed FK when the
canonical source exists.

```text
explicit producer
(Memory page, memory tool, Hermes write)
  → idempotent acquisition journal
  → security filter + deterministic decision
       ├─ create      → new item + source
       ├─ update      → new revision + source
       ├─ link        → explicit relationship
       ├─ contradict  → new item + contradiction link
       └─ skip/unsafe → audited automatic rejection
```

Direct writes reject recognized credentials in content and metadata, with a diagnostic that
contains no sensitive value. Detecting a `secret:` assignment requires a field boundary:
the word in ordinary prose remains accepted. Private keys, tokens, Bearer credentials and
other credential assignments remain filtered. Automatic extraction redacts recognized material
or discards an unrecoverable result before storage.

An admissible acquisition is applied immediately. There is neither a validation queue nor a human
question in Galaris: messaging-channel interlocutors are generally not interface users and could
not answer such a request. The internal journal provides idempotency, provenance, and recovery
after interruption; a transient technical state is resumed by the worker and is never exposed as a
decision to be made.

Exact content deduplication preserves an identity only when both `valid_from` and `valid_until`
match, including missing bounds. A fact confirmed again with a different validity interval
therefore does not reuse an expired memory. The old memory retains its dates and provenance
and remains excluded from recall.

### Separate Procedural Learning

Task-result analysis reuses certain observable Memory evidence, but it does not belong to this
domain. The Dream mechanism `skill.learn_task_outcome` creates and strengthens procedures in the
dedicated `app.skill` tables. It creates no `MemoryItem`, and historical experiences are no longer
recalled. Its score, injection thresholds, and audit are described in the
[Dream flow](dream.md) and ADR 0047.

Memory search in Tasks is entirely detached from their termination. The
`app.dream` mechanism `memory.extract_task` takes one successful root Task per cycle that has not
yet been scanned, is attached to an agent and a topic, is outside a Goal, Voice, and explicit
capture refusal, presents the small model with a bounded hybrid recall of already-known memories,
the exact human sender identity when available, and, when one exists, the next-turn objective of
the same conversation as a clue to the actual result. It retains as duplicate candidates only
matches that reach the single `MEMORY_DUPLICATE_SIMILARITY_THRESHOLD`. It checkpoints one
structured decision and then applies each operation with a stable identity.
This decision creates an absent fact (`CREATE`), adds the source to a candidate memory without
rewriting it (`LINK`), or abstains with an empty list (`IGNORE`). The server rejects any target that
was not part of the recall, excludes Topic/Contact projections, and offers as a `LINK` target only
a memory owned by the current agent. The model must still verify the identity of the fact: a theme,
a related decision, or partial overlap is never sufficient. A conversational attachment may
complete the contact and Topic of a global memory belonging to the same agent, but can never cross
another contact's boundary. During application, `app.memory` recalculates correlation from the
exact content of each proposed fact: below the threshold it creates a new item; at or above the
threshold it keeps the existing item and adds only the new `MemorySource`. A `CREATE` decision
merged in this way is audited as the actually applied `LINK` effect.

Each creation must declare high future utility and a closed retention rationale: explicit
preference, stable personal fact, decision or commitment, recurring constraint, reusable
procedure, explicit correction, or durable relationship. The server removes any proposal without
both signals. The prompt excludes public dossier or research facts, deliverable summaries, and
one-off details. Each response must be one complete JSON object. A first invalid response triggers a
bounded corrective retry; a second invalid response fails preparation and can never produce a
successful receipt. Each applied creation or attachment remains an effect of the receipt, but server
results also checkpoint, for each operation, the memory UUID and the `stored` or `merged` status.
A rejected operation, an unavailable source, or incomplete evidence fails application and preserves
the receipt for replay: a proposal alone can no longer count as a write. Older successful receipts
that contain operations without this evidence automatically become eligible again and are reapplied
with their stable idempotency keys. Interface totals separate new memories from attached sources
and read only application evidence. Other Dream effects, notably Topic association, are never
counted as memories. An empty list leaves a successful-scan record. The mechanism exposes no tool
to the local model, stops as soon as a Voice conversation starts, and is available only when
`MEMORY_CAPTURE_ENABLED` is active.

`memory.extract_task` becomes eligible only after the `topic.classify_task` receipt finishes. The
same subject therefore does not appear simultaneously as an in-progress classification and a
remaining extraction; the counter of unscanned Tasks directly uses the extraction mechanism's
states instead of subtracting all receipts from all terminal Tasks.

The language of generated content follows the durable source: `Task.data.language`, detected by the
dispatcher from the conversation, or `VoiceConversationSession.language` for Voice.
Structured prompts enforce this language for the titles, descriptions, content, and keywords of
folders and ordinary memories. Deterministic sections use the same code, and the final item
retains `metadata.language`. `DEFAULT_LANGUAGE`, already stored in the PostgreSQL settings, is used
only as a fallback when no usable source language exists. This behavior does not implicitly
retranslate historical memories, so as not to rewrite durable memory without new provenance.

The Dream scheduler requests only one operation at a time and rotates the starting point among
available mechanisms. After each operation finishes completely, it waits
`DREAM_POLL_SECONDS` before starting another. A long LLM call therefore does not reduce this
breathing interval; the same duration is used as the polling interval when no subject is available.

`app.memory.link_reconciliation` makes no inferences. It rereads every provenance from a classified
Task, round, or Voice turn, then attaches the memory to the canonical Topic. A conversational
source additionally uses the exact contact and the authoritative Topic/contact scope. The same
service projects the direct `topic_involves_contact` edge and reconstructs `cycle_of` and
`result_of`. It compares a desired state only with links carrying its `projection_key`, so reruns
create, update, or remove obsolete projections without touching explicit links or memory ACLs.

Targeted mode accepts a `MemoryItem` UUID and processes its incoming and outgoing edges. Each
successful Dream operation can register these nodes in the durable Memory worker. The
`MEMORY_LINK_RECONCILIATION_TRIGGER_MODE` parameter chooses between manual only, after Dream,
scheduled, or both. Scheduled global mode respects
`MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS` and is registered only when neither a Task nor a Voice
conversation is active; if load returns before execution, the job is deferred. The
`GET|POST /api/memory/link-reconciliation` routes expose its schedule and latest state; `POST`
immediately executes a global sweep in the current request, with no durable job or inactivity
guard. The reconciler's transactional lock serializes this launch with any concurrent scheduled
sweep. The command
`make rebuild-memory-links ARGS='--item-id <uuid>'` exposes the same contract to operators.

Messenger conversations and Goal Tasks can thus be examined without automatically promoting their
complete summary: only an element satisfying the durability contract becomes a memory.
Deterministic Goal projections remain the structured authority for their cycles.
Explicit calls to `memory_remember` or `memory_summarize` remain immediate.

`memory.extract_conversation_round` applies the same contract to classified text and Voice rounds.
It separates the current round from at most five preceding canonical messages. All acquisitions
retain the provenance `conversation_round:<uuid>`. Realtime audio rounds without a transcript are
ignored, since their durable promotion remains explicit through Memory tools.

## Thematic Folders and Manual Administration

`app.topic` classifies Tasks and Voice sessions into global folders, then projects each folder as a
public, ownerless, source-managed `MemoryItem`. Private memories remain private: the
`topic_contains` edge grants no access to the neighbor. Folder reading uses `TOPIC_ACCESS`;
creation, modification, deletion, merging, and splitting use the separate administrative privilege
`TOPIC_EDIT`.

Classification mechanisms first try reuse through a structured output that permits no creation.
The candidate list is ordered by RRF fusion of lexical relevance, proximity to only the public
pgvector projections, and popular folders serving as anchors. A missing model or index preserves
lexical and popularity ranking. Distance never chooses the folder. A second inference proposes a
new folder only after this pass fails; a deterministic similarity filter and transactional lock then
prevent near-duplicates and concurrent duplicates.

The reconciler's `memory.topic_maintenance` family processes the current index snapshot.
Without an LLM and without published content, it produces at most 100 signals per category:
attachment of an orphaned memory, member distant from the anchor, nearby public Topics, and stable
private groups sufficiently separated to suggest a split. Private groups are calculated by owner
and never form a public or inter-agent centroid. The reserved
`topic_*_candidate` and `topic_membership_anomaly` relationships carry `suggested=true`, the
model, the version, and bounded evidence. Reconciliation replaces only these generated
suggestions; it never creates, moves, or deletes a canonical `topic_contains`.

`DREAM_TOPIC_CREATION_MODE` controls the effect of a remaining proposal. `forbid` leaves the
activity unclassified, `auto` creates immediately, and `propose`—the default value—opens a
persistent Messenger interaction. The original user chooses whether to create, reuse one of the
checkpointed UUIDs, or leave the activity unclassified. A proposal without a human route remains
unclassified; its key linked to the Dream receipt prevents duplicate sending during recovery.

A merge moves all `topic_contains` edges to the target, reassigns Tasks and Voice sessions, then
forgets the source projection. A split is a manual partition: the administrator creates the new
folder and explicitly chooses the memories whose edge should be moved; the others remain in the
source folder. Memory content, UUID, owner, visibility, and grants never change. The public
projection is the only `MemoryItem` carrying the canonical `topic_id`, with `ON DELETE CASCADE`;
both ends of `memory_links` in turn cascade only to the edges. The memory node at the other end
never depends on the link and survives. All other `topic_id` values—Tasks, sessions and Voice
turns, Messenger journal, and rounds—use `ON DELETE SET NULL`. Because the API archives the Topic
instead of physically deleting it, its service explicitly applies the same policy: it purges the
derived projection and its edges, preserves linked memories, and resets all references to `NULL`.

## Canonical Data Projections

```text
Agent ───────────────► profile record ──────────────┐
Goal ────────────────► description and progress ────┼─► private, source-managed MemoryItem
GoalCycle + Task ────► report ──────────────────────┤          │
Messenger sender ────► contact record ──────────────┤          ├─ UUID retained on Agent/Goal/Cycle
assigned/successful Process ► procedure/result ─────┘          │
                                                              └─ hashed source identity for contact
```

`Agent`, `Goal`, and `GoalCycle` remain the sources of truth for their structured data. Memory
builds Markdown pages from them to make their information useful to drivers' common recall, without
moving or duplicating business data entry. Keywords are entirely deterministic: source type,
identifiers, owner agent, status, cycle number, and verdict. The Agent record contains identity,
personality, and job description, but never keys, tokens, passwords, Hermes configuration, or other
technical secrets. The Goal contains its description and canonical tracking data. Each cycle
contains its report, evidence, verdict, and Task result, including when that Task is subsequently
archived. To ensure that a Goal with thousands of cycles never causes an unbounded load, only the
100 most recent cycle projections are retained. The window is calculated by `sequence`; when it
advances, the outgoing projection is forgotten and its `goal_cycles.memory_item_id` becomes null.

A second, deliberately smaller projection represents each human sender observed by Messenger as a
contact record. Its address is exactly `(messaging_id, user_id)`: the canonical bridge code and
case-sensitive native identifier. `owner_agent_id` isolates the private record without becoming a
property of the human. The source key is the SHA-256 of a versioned canonical JSON containing these
three values; it therefore does not expose the native identifier in the constraint or technical
errors. The content retains only the display name, messaging service, and identifier, never the
connection, room, or message text. A new non-empty name revises the same record; an empty name never
replaces a known name. An identical observation creates no revision.

`memory.project_process` projects each assigned `ProcessDefinition` and the output of each
successful `ProcessRun` into private memory without an LLM. Input, raw
snapshot, tokens, and callbacks are never copied. The output passes through the recursive Process
sanitizer, then is bounded to 12,000 characters. A result is linked to its definition by
`result_of`; only the last 20 successes per agent and process are retained. Deleting or removing
an item from the window forgets the projection, not the canonical source.

A projection carries `source_managed=true`, remains private, read-only, and without a grant. Neither
an agent, an administrator, nor the UI can modify it, share it, link it manually, or forget it. A
source modification registers a durable job that recalculates the page and creates a revision only
if its content or metadata changed. Deleting the source calls the internal forgetting path.
Rebuilding also reconciles orphaned projections if the event could not be processed. Cycles are
linked to their Goal by `cycle_of`.

Logical UUIDs are stored in `agents.memory_item_id`, `goals.memory_item_id`, and
`goal_cycles.memory_item_id`. The deterministic identity `(managed_source_kind, managed_source_ref)`
allows an existing item to be reattached if this pointer is missing, without creating a duplicate.
Dataset synchronization fills missing links, and the worker reconciles them at startup. Contacts
add no source column: their deterministic source identity attaches them directly, and the
Messenger journal is used for replay. The explicit procedure is:

```bash
make rebuild-source-memory                         # missing UUIDs only
make rebuild-source-memory ARGS='--all'            # refresh all projections
make rebuild-source-memory ARGS='--recreate --provider native'
                                                    # recreate with a selected provider
make rebuild-messenger-contacts                     # replay human senders
make rebuild-memory-index                           # missing semantic index
make rebuild-memory-index ARGS='--all'              # full background recalculation
make rebuild-memory-links                           # deterministic links from their sources
```

`rebuild-memory-links` refuses to create an edge while a Task or Voice session that already has
memory provenance lacks a thematic folder. It requeues exhausted classifications, then must be run
again after Dream completes this phase. After this global barrier, it reconstructs the `cycle_of`,
`result_of`, `topic_contains`, `contact_contains`, and `topic_involves_contact` edges from canonical
Goals, Processes, Tasks, Voice sessions, Topics, and Topic/contact scopes. Manually entered links
and relationships resulting from a consolidation decision cannot be deduced from these sources and
cannot be recreated after a full SQL deletion.

Goal MCP tools remain necessary for exact reads, commands, current states, and membership checks.
Memory is a recall and search projection, not a replacement transactional API.

Messenger messages, connections, rooms, authentication identifiers, LLM/tool configurations, and
Lab diagnostics are never projected automatically. The minimal contact record for human senders
contains no conversation text. Terminal Tasks and transcribed Voice turns are examined gradually by
Dream. Process is the other bounded and deterministic exception described above.

## Storage and Forgetting

Node URLs are associated exclusively through `memory_urls(id, memory_node_id, url)`.
`memory_items.primary_url` is a nullable text column identifying the preferred preview
source. Transport catalogue observations reference a URL row through `memory_url_id`,
without a direct node FK; metadata and `MemorySource` no longer duplicate locations.
The node's `file_sha256` stores the SHA-256 of complete bytes for every file format,
including attachments. A new copy preserves the primary URL; moves update it and
deletion selects a remaining location, or `NULL`. A DbAdmin action transfers existing
associations before contraction. See [decision 0159](../../../../project/decisions/0159-memory-url-associations.md).

Nullable `file_media_type` and `file_size_bytes` describe the original file,
separately from the editorial record's format and size. A unique index protects
each node/URL pair, and a deferred FK enforces primary URL membership. Usage
records reference Tasks through a nullable FK that preserves the audit on deletion.

`MemoryItem.id` is the stable logical identity. Each revision points to an opaque
`(provider_code, resource_id)` pair. The `native` provider writes atomically to the fixed
`/data/memory` directory; the database never derives a path from `resource_id`.

There is no longer a product archive. Forgetting deletes all related resources, vector projections,
and traces, then leaves only a contentless tombstone. Explicit forgetting retains an irreversible
fingerprint of the content and its source in the acquisition journal: the same information cannot
be relearned automatically from that source, while a different correction remains admissible.

Lightweight maintenance no longer deletes a memory based on inactivity. `app.memory` owns the
policies and `MemoryFinding`s of type `duplicate`, `contradiction`, or `aging`; the
`memory.maintain_findings` mechanism detects and processes them sequentially in Dream during
inactivity. Memory drives; Dream executes. Each policy has `off`, `manual`, and `automatic` modes;
automatic mode calls exactly the same service as the UI's manual action. This mechanism uses no
generative LLM and remains excluded from Dream gauges. Duplicates read the current embedding index
or file SHA values. Identical SHA values score 100% without embeddings; fingerprint
acquisition performs no merge. Dream applies its duplicate policy while retaining
URLs, notes, provenance and usage. Ownership and access must remain compatible;
attachments only merge within the same document. Other duplicates apply the same
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD` as acquisition and recall.
Contradictions additionally require an explainable textual marker.

Applied aging sets `old_at`/`old_reason`. It does not delete the item or remove it from RAG. The
reference date is the last significant modification, never `last_accessed_at`, so that a search
cannot rejuvenate the memories it retrieves. A significant modification or new provenance clears
this marking.

`GET /memory/retention/preview?days=<n>` counts expirations and inactivity in read-only mode, by
type and oldest date. This preview activates no deletion and never modifies `activity_at`; the
delivered policy value therefore remains `0` until an operator chooses a duration based on the
observed data.

A memory originating from a source does not follow these public commands. For Agent, Goal, and
GoalCycle, its deletion is triggered exclusively by deletion of the canonical data. A contact
record persists even if its connection is deleted, since that route does not participate in human
identity. When changing providers, the `--recreate` procedure forgets the old resources, releases
their source identity, creates new items, and then puts their UUIDs back into the canonical tables.

## Surfaces

- Python facade and services: `search_memory(text, agent_id=..., **options)` from `app.memory`
  returns a simple ranked list of `MemorySearchItem` without scores; `back/app/memory/` contains
  the detailed engine.
- Administration API: `/api/memory` with RBAC `MEMORY_ACCESS`,
  `MEMORY_EDIT`, and `MEMORY_ADMIN`; `/memory/search` returns the ranked list without scores and
  `/memory/browse` provides paginated lexical browsing. Options absent from
  `/memory/search` come from the current Params; `/memory/recall` remains a deprecated alias.
  `/memory/metrics` exposes the contentless local mirror of counters/histograms,
  `/memory/retention/preview` estimates a policy before activation, and
  `/memory/duplicates/preview` lists, without mutation, files with identical SHA and ordinary pairs above the global cosine
  merge threshold, optionally for an agent, and returns this value in its response.
  `/memory/findings` exposes persistent detections and its `apply`/`dismiss` actions with the same
  revision controls as automatic mode.
- Agent MCP: `file_search`, `file_info`, `file_read`, `file_create`, `file_write`,
  `file_append`, `file_edit` facade over `memory://` and `document://`; business commands
  `memory_remember`, `memory_forget`, `memory_summarize`, and `document_share`.
- Interface: under `/memory`, the **List** tab retains search, owner, content, revisions,
  provenance, direct access, and links. The **Graph** tab loads a lightweight subgraph by cursors
  without payloads. The API provides neighbor expansion and directory-child expansion.
  3D displays each page as it arrives and loads children when approaching a directory,
  in pages of 100; 2D loads all pages. Opening uses pages of at most 500 nodes, with
  10,000 edges per page in 3D and 2,500 in 2D, with no global node cap. Queries read
  only graph columns. Leaf folding uses the global count of distinct admissible neighbors,
  including suggestions, and requires a confirmed link. From eight leaves, the anchor carries
  a count; zoom and an explicit control reveal them. The frontend retains the animated ECharts
  engine in 2D up to 600 loaded items, fixing the selected item, with initial placement converging
  naturally and gentle rebalancing for 0.7 seconds after the graph changes. Closing node details
  preserves positions and the camera. Hidden leaves retain
  their placement; zooming and unfolding do not restart physics.
  Larger windows use bounded placement with stable coordinates and reserved bounds for hidden
  members. Zooming out simplifies symbols, titles and detailed links without removing their
  relationships from the simulation. The frontend budgets titles with collision
  hiding. This projection does not yet provide a server hierarchy or spatial loading; see
  [decision 0157](../../../../project/decisions/0157-stable-memory-leaf-branches.md) (in French).
  Sources are checked on every load: connections are resolved in batches,
  and Nextcloud shares metadata reads for files in the same directory, falling back to individual
  files when the listing is denied or incomplete. No access result survives between requests. The selected
  agent already determines the ACL scope and therefore remains implicit: its projection is not
  displayed. A public Topic enters this graph only if it contains a memory owned by the agent or
  an item directly shared with it; other agents' folders are not displayed merely because of their
  public visibility. Topics, contacts, and documents are exposed with distinct visual roles;
  Topic–memory/document, Contact–memory, and Contact–Topic relationships are reinforced, while
  suggestions remain fine and discontinuous. Recency combines last access and last modification in
  an indexed calculated column. Settings remain under **Preferences → Memory**. The interface is
  for auditing, correcting, or forgetting, not for accepting or rejecting acquisitions.

The page opens the Three.js 3D renderer by default; ECharts remains selectable.
Both views reuse the same page contract, canonical identities and details. A worker prepares
placement while retaining the personal 2D positions separately. File Share roots, topics and
contacts precede folders/directories, documents and details. Known `parent_of` children are
kept in their previous lateral distribution, with depth based on local link length rather
than distant fixed levels or a new spiral. Child pages also restore their saved private
2D positions.
They load when approaching a visible directory, with at most two concurrent requests and
another page per camera movement, without recursively crawling the provider.
Links to deferred children also wait for expansion.
Visible markers share instanced geometry and links share segment buffers. Cell bounds are
tested against the frustum and a screen index handles selection. Node and relation styles
are shared with 2D. A bounded atlas reuses public folder SVGs and Material paths;
links use instanced ribbons to preserve CSS pixel widths. Shaders reuse 2D curvatures.
Segment counts depend on projected length and curvature, using instanced chunks of four
segments, up to 64 per link. The CPU culls offscreen envelopes and hides a whole link when
either endpoint is behind the camera. It updates buffers only
when subdivision changes; shaders calculate points and normals in one draw call for
links. 3D widths are multiplied by 2.25 at a distance and 1.25 nearby. Distant 3D markers use 56 % of
the capped base size, nearby markers 110 %. Labels have no background.
Left dragging rotates
camera and viewing target around the pressed node without centering it on screen,
while dragging from the background uses OrbitControls panning until release, including
from the fitted overview. A drag never becomes a click after movement. Wheel navigation
translates camera and target along the ray under the pointer, preserving orientation
and the aimed screen point. The pointed node's depth sets the step; background uses
visible depth or a steady speed in empty space. Pinch and buttons retain the central
axis. Navigation can pass nodes and continue through empty space; maximum retreat
returns to a stable, centered overview.
Framing uses rendered markers, viewport dimensions and depth in the viewing direction;
it fills the limiting dimension with a glyph margin and centers projected bounds.
The result is cached between data, viewport and direction changes, and reused at maximum
zoom-out and on resize.
Labels and thumbnails have
bounded budgets, and rendering stops at rest. Version 2 of `camera_3d` and the pages of visited
branches are saved independently of `camera`, without a schema migration. A camera from the
previous flat placement is fitted again. WebGL loss falls back to 2D and reloads its complete
catalogue. Responses from an old context are discarded; errors retain the partial map with
retry. This renderer does not implement the planned prepared regional server map:
[ADR 0166](../../../../project/decisions/0166-batched-memory-3d-renderer.md) (in French).

Logfire metrics and the local mirror measure count, mode, degradation, latency, result count, and
characters actually injected. Labels are bounded and never contain a query, text, memory UUID,
room, or interlocutor.
