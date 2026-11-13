# 0281 — Quiet document history and substantial Dream updates

Status: accepted. Date: 2026-11-13.

Text and Data document writes remain immediately durable. Preserve the public `revision`
content token and `lock_version`: optimistic writes, consent for executable HTML, stale-response
rejection, thumbnails and resource consumers depend on them changing with saved content.
Restorable history is a separate concern and may contain noncontiguous content tokens.

Keep the initial snapshot. Subsequent content writes replace one durable `document_revision`
job per document, in the same transaction, with a deadline five minutes after the latest
content change. Metadata writes do not extend this deadline. The existing leased Document
worker locks the source and snapshots its current state only if the claimed content token is
still current. Repeated or recovered executions do not create duplicate snapshots; returning
to the latest stored content also creates none. Attribution describes the final saved edit.
Intermediate content resources may be released when no current source or history references
them. Existing history is retained, without retrospective compaction.

Create a Dream receipt only after the quiet-period and substantial-change checks pass.
Initial creation must be five minutes old and the document must have no pending history job.
Source and apply checks repeat the freshness condition. Manual
summary edits and explicitly requested regeneration remain available immediately.

Replace the percentage policy in decision 0246 with
`DREAM_RESOURCE_SUMMARY_MIN_CHANGED_CHARS` (default 100, inclusive), keeping the existing
minimum source length of more than 1000 useful characters. Compare the normalized current
source to the source used for the last generated summary, independently of history. Count
unmatched characters with the existing bounded sequence matcher; a substitution counts once.
Presentation-only edits do not count, and manual summaries remain protected.

For unassigned Topics, retain the last model-classified source in the existing Dream receipt.
Later versions differing by less than the same character threshold create no Dream receipt;
small changes accumulate against the last actual model classification. Assigned Topics keep
the existing no-reclassification behavior. This decision does not change embedding policies.

Verification covers immediate persistence, timer reset, the inclusive five-minute boundary,
durable recovery, stale claims, duplicate execution, reverts, content concurrency, cumulative
character changes, manual summaries, stale model results and append retry idempotency.
