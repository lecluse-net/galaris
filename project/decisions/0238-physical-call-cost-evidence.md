# 0238 — Physical-call cost evidence and benchmark economics

Date: 2026-10-25
Status: accepted

## Guarantee

A missing charge or tariff does not establish a free call. A failed attempt retains
its paid calls. Parent and child Task rollups are not additive billing evidence.
Benchmark judgments remain separate from candidate operating costs.

## Decision

`app.llm` owns a minimal `llm_call_costs` register keyed by physical call UUID.
Admission, streamed accounting, finalization and interruption persist it in the same
transaction as the trace. Deleting a detailed trace clears its optional foreign key
but keeps the amount, attribution, dates and pricing evidence; prompts, responses,
credentials and tool arguments are absent. Terminal accounting accepts enrichment
from an authoritative provider charge without reopening its terminal lifecycle.
Repeated provider receipts do not charge the call twice.

Provider-reported amounts, including explicit zero, precede estimates. Estimates
freeze rates, counters and the cache convention actually used in the trace's
`usage._galaris_cost`. Absent or invalid tariffs and missing token counters remain
unknown. Subscription billing is zero per call; inference value remains independent
and may be unknown. Historical traces are a read-through source when no register
entry exists; historical data already deleted cannot be reconstructed or repriced.

The Task cost endpoint follows both parent and source edges with distinct physical
identities and current management scope. It includes preparation predating a Task
only when its conversation round is linked unambiguously to that Task. It groups
recorded costs by purpose, exposes missing/running/estimated evidence and does not
claim that Task SUCCESS independently verifies a business outcome. Existing Task
rollups and admission-budget policy are not rewritten by a report read.

The Lab snapshots cost evidence independently for candidate and judge. A failure
retains every observed paid retry. Run/stage correlation also recovers unpublished
calls from workers that lost their lease, without weakening publication fencing.
Economic reports cover the whole run before pagination or risk filters. They deduplicate
snapshot/register identities, count failed candidate costs and all judgment campaigns,
and withhold cost per success for missing executions, verification, cost coverage or
zero successes. Cost medians/deltas likewise require cost provenance.
The denominator is benchmark successes according to its checks and judge, never
proof that simulated effects occurred in the application. Analysis cost remains separate.

## Verification and limits

Synthetic DB tests cover unknown versus free tariffs, provider precedence, frozen rates,
subscriptions, failed paid retries, duplicate identities, lineage, access denials, trace
deletion and unpublished attempts. Run-usage aggregation no longer applies the 10,000-call
display limit. Browser tests cover unknown amounts and late responses across Task changes.

This is recorded model-call spending, not a supplier invoice reconciliation or local
hardware accounting. Shared preparation without unique attribution, untraced operations
and independent verification of complete business Tasks remain outside this report.
No provider-queue delay or verified delivery timestamp is inferred from execution time.
The schema is declarative: `make sync-db` in development, normal `make update` on deployment.
