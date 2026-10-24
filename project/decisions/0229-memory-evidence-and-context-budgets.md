# 0229 — Memory evidence, attribution and bounded context

Status: accepted, 2026-10-24.

## Decision

Vector similarity proposes duplicate candidates. It never establishes complete
equivalence by itself. Without an affirmative configured decision, acquisition
keeps the new fact. Exact-content idempotency and duplicate handling remain in
place. A decision about an outdated candidate cannot discard new content.

Dream factual extraction includes successful child Tasks and Goal-cycle Tasks.
Prepared, delegated and Goal instructions are attributed to AI; a root human
request uses its preserved original demand when available. Tool observations
remain separate from final narrative claims. AI-only sources cannot create or
edit human preferences, personal facts, relationships or explicit human corrections,
even if the model selects that retention category. Capture opt-out propagates through
parent and causal Task lineage. Each producing Task retains its own provenance;
replay does not multiply the same acquisition. No parent acquires another
agent's private memories. Conversation acquisition may reuse already completed
document analyses in the admitted Task tree, retaining agent, URI, version and
resource checks. This starts no additional document analysis.

Calendar matches retain their order and priority. When ordinary candidates also
exist and the item budget allows at least two entries, one ordinary slot and up
to one third of the character budget are protected from calendar saturation.
The overall item and character limits remain unchanged; omitted calendar
matches remain available through `memory_upcoming`. This replaces unconditional
calendar domination of the common brief, not the independent calendar branch.

Search retains weak candidates. The compatibility `relevance_status` describes
retrieval availability; the additive `evidence_status` explicitly remains
`unassessed` for nonempty results and `no_evidence` for an empty result. It is
never a sufficiency judgement. Drivers must inspect attribution, dates and
conflicts before using candidates as evidence for an answer.

Authority ranking counts distinct canonical origins rather than receipts:
revisions and late extraction of one Task, round or Document count once.
Passages and interpretations entirely derived from one resource URI also count
once. Unknown vocabularies retain exact identities. This is a bounded provenance
signal, not a truth score or a proof of statistical independence.

Confirmed `contradicts` links expose up to three accessible alternative claims,
their revisions, recording dates and sources. The common brief carries an
unresolved-conflict warning and source validity intervals. Suggested links,
expired or forgotten sources, other agents and other contacts confer no access.
No claim is automatically replaced, expired, forgotten or declared true because
it is newer. ENRICH/CONTRADICT persistence belongs to the separate conversational
continuity work.

## Qualification

Regression scenarios first reproduce lost complementary facts, human attribution
of generated instructions and context starvation. PostgreSQL integration tests
cover acquisition replay, Task lineage, already acquired document evidence and
conflict access. The existing conversation benchmark compares frozen pre-change
sources with the current engine on identical synthetic worlds and clocks;
retrieval and actual injection are measured separately. Earlier tests protected
threshold-only merging and inspected a legacy Task preview rather than the
canonical extraction input; the revised tests exercise the actual decision and
input boundaries. The reference loader
freezes context assembly as well as ranking, and uses `core.storage` after the
Memory/Document separation.

Configured-provider qualification is explicit and separate. Provider credentials
remain in the development runtime. Only synthetic input texts, recorded vectors
and prepared prompts/answers cross into benchmark artifacts. A provider failure
does not count as a measured answer or get replaced by another model. Diagnostic
artifacts remain outside versioned documentation; aggregate results and limits
are recorded in the memory plan.
