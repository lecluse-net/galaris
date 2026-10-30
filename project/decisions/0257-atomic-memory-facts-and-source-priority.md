# 0257 — Atomic Memory facts and canonical source priority

Status: accepted. Date: 2026-10-30.

## Context

Private structured Contacts remain canonical `memory_items`. Excluding their projections
from factual recall hid existing coordinates from agents. Conversely, explicit memory
writes could copy those coordinates into ordinary prose. Duplicate consolidation must
preserve the real resource without making every fact linked to it indelible.

## Decision

Contact cards participate in authorized hybrid recall and explicit searches. Display names
supply lexical identity evidence. Ordinary personal facts retain their exact contact scope;
another agent's private directory remains inaccessible. Generic text writes and acquisitions
reject detected coordinates, including mixed coordinate/fact submissions. The rejection audit
does not copy raw coordinates. Contact discovery remains their owner.

Agents submit one `AtomicMemoryFact`: an authorized `subject_ref`, normalized snake_case
`predicate`, typed scalar `value` or `{ref: URI}`, optional `negated` and `unit`. Missing
subjects resolve to the current contact or owning agent. The server stores versioned
`metadata.atomic_fact`, generates the escaped HTML view for existing readers and persists
subject/value graph links. Provenance and time remain separate. Complementary properties
create separate atoms; corrections preserve both claims and their contradiction.

MCP and Hermes reject narrated prose. Explicit summaries, terminal capture and new Dream
extraction produce typed atoms. Terminal capture checkpoints extraction before applying
idempotent acquisitions. Historical checkpoints and human editorial notes remain compatible.
An intentional human replacement clears stale atomic metadata and generated links; agents
cannot rewrite an atom as a paragraph. Historical prose is not bulk migrated or deleted.

Exact atoms deduplicate under an advisory lock by owner, subject, property, typed value,
negation, unit, contact scope and temporal anchor. Names and evidence timestamps do not
define identity. Different subjects or assertions never merge from similarity alone.

The single duplicate similarity threshold retrieves candidates. Acquisition requires a bounded
native equivalence decision, then prefers an equivalent source-backed item over an ordinary
copy regardless of age or ranking. Maintenance requires complete literal containment before
absorbing an ordinary copy into a resource. Independent authoritative resources never collapse
through that route. Existing byte-identical file consolidation preserves URLs and associations.
Private evidence stays in the owner-bound journal/finding, not a shared resource's provenance.

Only direct resource representations are protected: managed projections and Document references
cannot be forgotten through generic Memory deletion or ordinary duplicate merging. Source owners
retain their lifecycle operations. A graph link, citation or fact subject does not confer
protection: an ordinary fact linked to a Contact remains forgettable.

## Verification and limits

Synthetic database scenarios cover searchable cards, coordinate rejection, isolation, typed
persistence and links, exact retries, homonyms, source priority, source deletion refusal and
deletion of linked ordinary facts. Capture tests verify checkpoint recovery. The schema
enforces one typed triple; interpreting a short textual value as one meaningful assertion still
depends on extraction quality.
