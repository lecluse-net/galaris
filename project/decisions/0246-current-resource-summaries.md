# 0246 — Current descriptions for Documents and Datasets

Status: accepted. Date: 2026-10-29.

Documents and Datasets own one current shared description and current keywords. Only source
content has restorable versions. Retire `document_summary_revisions`, the independent summary
revision, `documents.summary_document_revision`, and keyword snapshots in Document content revisions. Preserve the current summary
before contracting the old table. Historical upgrade archives remain recovery evidence, not
an application history. Restoring content never restores old descriptions or keywords.

Two Dream parameters apply to both domains: `DREAM_RESOURCE_SUMMARY_MIN_CHARS` defaults to
1000 and `DREAM_RESOURCE_SUMMARY_CHANGE_PERCENT` defaults to 25. The comparisons are strict:
content must exceed the length threshold; an automatic description is refreshed only after
cumulative change exceeds the percentage threshold. Normalize visible HTML text and canonical
JSON first. The changed share is the unmatched character count relative to the larger source,
using a bounded repetitive-input sequence matcher. Presentation-only changes do not count.

Each source retains only its current generated/manual origin, pending flag, and normalized
source used for the last description. This single baseline is replaced after generation;
it is neither a summary history nor another resource. Keeping the baseline independent of
restorable history preserves cumulative comparison even when an old content version is removed.
Small resources require no generation. Existing/manual descriptions are preserved. Source
writes coalesce into one pending flag; Dream uses its ordinary sequential, idle-only scheduler.
Policy changes and DbAdmin reconcile eligibility, including existing resources.

Dream generates a short explanation of the resource's purpose plus useful search terms. It
covers long sources through bounded reduction, and checks the source lock and live eligibility
before publishing. A content, owner, permission or manual-description change invalidates a late
result. Description writes do not create a content version. Public source APIs retain their
rights and concurrency checks. Dataset descriptions are independently stored with Dataset JSON;
they are never represented by newly created Documents or personal memories.

This change adapts obsolete documentary-summary history consumers in Memory, but does not change
its recall selection or introduce agent-specific resource descriptions. That work is deferred.

Verification retains the permission, source persistence, content-history, restore, native storage,
retrieval and interrupted-upgrade contracts. Tests that required summary versions or historical
keyword snapshots intentionally retire those constraints in favor of current-only metadata.
