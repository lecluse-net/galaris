# 0256 — Contact acquisition and Dream reconciliation

Status: accepted. Date: 2026-10-30.

This completes the deterministic detection introduced by 0255. The Dispatcher retains
its inference schema and routing policies. Router-side notifications call a registered
port, bound to `app.contact` at startup. Human and AI rounds, `END`, forced replies and
Tasks supply durable observations. Coalesced rounds scan every current input, excluding
old routing history. Lab evaluations do not invoke the persistence port.

`app.contact` owns per-coordinate `ContactDiscoveryJob` rows, unique by agent and stable
source observation. The existing Task scheduler hosts its independent periodic callback.
Contact work is neither an agent execution nor a business Process and does not depend
on Dream being idle. Dispatch waits only for a durable enqueue, not owner inference.

Known coordinates finish without LLM calls or contact mutations. Unknown details use
two bounded model operations: structured owner evidence from the profile's ultra-low
text resource, followed by closed choices from its decision resource. The latter selects
creation, enrichment, ignore or unresolved identity. No tools or planning loop run.
Names and literal citations must be supported by the bounded conversation context;
coordinate values are exclusively the detector's observations. Candidate UUIDs are
agent-scoped, and application revalidates ownership and fingerprints. Unsupported
identity or messaging platform remains unresolved, rather than inventing a person.
For acquisition the explicit closed choice expresses uncertainty; provider confidence
and class probability are retained as distinct, uncalibrated annotations. They do not
introduce an undocumented numerical veto on a supported creation/enrichment decision.
Contact fusion likewise exposes a closed unresolved-identity option instead of applying
a universal cutoff to provider-specific confidence scores.

The directory uses the existing canonical private Memory contacts. Email and messaging
identities retain their namespaces; phones and postal blocks use typed coordinates.
Offline comparison keys normalize manual and observed notation, including phone
extensions, postal separators and provider-specific identity forms. No permission is
granted by recording a coordinate.

Owner evidence and the final plan are checkpointed separately. Five bounded attempts,
leases and cancellation recovery preserve work across interruption. Application takes
an agent directory advisory lock before job/contact row locks; human merge and forgetting
take that same lock. Contact creation/enrichment and its job result commit together.
Manual edits invalidate stale plans. Forgetting cancels queued matching observations;
canonical merges rewire acquisition references along with conversations and Tasks.
Contact merges always refresh the Memory projection, including email-only mergers.

Dream registers `contact.reconcile`. Blocking by name tokens or exact coordinates
proposes pairs above `MEMORY_DUPLICATE_SIMILARITY_THRESHOLD` (default 0.92). This is the
single similarity setting shared with memory acquisition, recall, duplicate and contradiction
findings. Keep its existing administrator value and its Memory configuration privileges.
Retire the separate contact and contradiction threshold declarations and controls; DbAdmin's
authoritative parameter dataset removes their obsolete rows without changing the shared value.
Similarity still uses each domain's appropriate metric; the shared percentage selects candidates,
and never constitutes identity proof for contact merging. Pairs
stream rather than building a quadratic in-memory set; one candidate is claimed per
cycle. Similarity selects candidates and never authorizes a merge. Closed choices must
confirm the same owner from contact details and acquisition provenance. Homonyms,
shared family/company coordinates and conflicting identities remain separate. A closed
unresolved-identity decision blocks fusion; provider scores remain auditable annotations.
Only an explicit merge choice can pass the similarity and fresh-state guards. Receipts checkpoint the
decision and application rechecks both contacts before canonical merging. Lack of a
configured model causes a recoverable error rather than a heuristic identity decision.
Pair identities include acquisition-provenance counts: new ownership evidence reopens
a previously declined pair, and intervening evidence invalidates a prepared merge.

`CONTACT_CAPTURE_ENABLED` controls acquisition and contact reconciliation. Dream also
retains its global enable/idle policy. Functional settings use existing Memory and Dream
configuration privileges. `/contacts/discovery` exposes bounded coordinate/status data
only to contact readers/editors managing the owning agent; conversation context is not
returned there. LLM traces use dedicated purposes and stable job/receipt correlation.

Architecture review: Contact requires the public LLM boundary for attribution; Dream
requires the public Contact facade for candidate retrieval and canonical application.
These two edges are added to `architecture.toml`. The reverse dependencies are avoided
by the Agent capture port; no private import or dependency-cycle baseline is increased.
The domains retain their existing resource ownership and source-rewiring responsibilities.

Verification includes an expanded synthetic extraction corpus, generated-coordinate
invariants, real DB acquisition/replay/error cases, Dream refusal and stale-decision
scenarios, and the real durable text/native-decision lifecycles with only provider HTTP
replaced. Detection latency is separate from enqueue, model inference and startup;
3 ms is not a hard bound for arbitrarily large numeric input.
