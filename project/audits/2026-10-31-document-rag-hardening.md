# Document retrieval hardening — 2026-10-31

The review reproduced a ranking defect: even opposite semantic vectors admitted a
passage when lexical evidence was absent. A conservative cosine admission floor now
rejects weak semantic-only candidates; lexical matches remain eligible. A small real
embedding calibration on synthetic FR/EN questions measured relevant similarities
between 0.695 and 0.807 and unrelated similarities between 0.130 and 0.347. This is
bounded calibration evidence, not a universal relevance or entailment guarantee.

Preparation workspaces now follow source retirement. Active conversion is cancelled
and drained before deletion, source-locked registration prevents late creation, and
shared-reader workspaces are discarded with their managed source. Immutable reuse
retains live access, source metadata and filesystem identity checks; changed or
untrusted sources require full reads. Manifest loading avoids retaining document
text in a process-wide memory cache.

On the same 1,080,000-byte synthetic source, an initial read followed by five warm
reads materialized 6,480,000 bytes before the change and 1,080,000 after it. The local
warm median changed from 1,506 ms to approximately 5 ms. These five-query measurements
are illustrative development observations; the avoided source reads are the durable
contract, rather than a general latency target.

A real Pydantic AI agent using the Galaris model adapter and MCP read functions passed
four synthetic journeys: evidence on page 20, OCR evidence on a scanned final page,
comparison across two files, and an absent fact. Facts, units and page/character
citations matched independent references and actual retrieval receipts. Initial
qualification exposed an unsupported full-reading assertion after raw binary delivery;
tool guidance and the independent checker now reject that assertion. The successful
run reported bounded selections and insufficient evidence instead of claiming global
absence. No personal memories or business entities were created by the qualification.

The filesystem provider was disposable; this run does not qualify the Task scheduler,
external runtimes or a real connector's ACLs. Separate integration tests cover managed
source access, sharing, revocation, concurrent deletion and Memory non-creation. The
default local embedding service was unavailable during the run, so the real semantic
qualification selected another already configured embedding resource without changing
the application's shared profile.
