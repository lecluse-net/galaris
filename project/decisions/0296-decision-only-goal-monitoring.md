# 0296 — Decision-only Goal monitoring

Date: 2026-11-16

Status: accepted

## Context

Goal work already runs as ordinary Tasks. The former supervisor added generated tracking,
a fresh-context review Task and another judgement before completion, blocking or persistent
stagnation. A failed review could suspend otherwise feasible work with `REVIEW_UNAVAILABLE`;
a model-selected blocker could persist `BLOCKED`. Both required manual resumption. Existing
tests enforced those rules, rather than detecting their operational cost and loss of autonomy.

The requested policy is exclusive: monitoring must use a native decision model or be absent.
It must not generate commentary, tracking or additional review work.

## Decision

- A completed cycle may invoke the Agent profile's native **Decision** model once, for exactly
  one `CONTINUE`/`STOP` choice. No text companion, token-counting inference or text fallback is
  admitted, including when the profile allows text fallback for other mechanisms.
- The classifier receives the original Goal, existing tracking, Task result and recorded tool
  observations. An unmet or unverified criterion, blocker or unknown method means `CONTINUE`.
  `STOP` requires evidence of the original outcome. The decision is not an independent audit.
- Without a decision model, work continues on its existing schedule without automatic
  completion. A decision failure preserves its error and paid cost, records `CONTINUE` and
  leaves future work eligible. It does not trigger another model or demand manual recovery.
- Cycles remain Tasks. Their full results are retained as next-cycle context; monitoring never
  rewrites the tracking Document. Normal authorized document/Goal tools remain available to
  users and working agents when the work warrants an edit.
- Explicit pauses, global scheduling, permissions, human-question waits, revisions and leases
  retain their authority. Goal, tracking or work changes discard stale decisions. A late
  decision cannot undo a human pause or completion. Accounting updates alone do not change work.
- New cycles create no review Task. The `goal_cycles.review_task_id` column and relationship,
  API references, UI actions and review-specific runtime are removed. A DbAdmin action releases
  obsolete retention and removes the `goal_review` Task marker before contraction. It preserves
  all Task rows, their business state, content, costs, checkpoints and other retention owners;
  no cleanup-driven cancellation or waiting remains. The worker gradually resumes only obsolete
  `BLOCKED`/`REVIEW_UNAVAILABLE` pauses. Human and unanswered-referrer pauses remain intact.
- Lab Goal monitoring uses the same decision-only evaluator and accepts native decision
  candidates. Historical expectation payloads are projected to their closed action without
  deleting the stored source. Unused generative Goal output schemas are removed.

## Verification and measurement

The retired constraints are mandatory review creation, automatic blocking pauses, generated
tracking and text-model availability as a prerequisite to work. Their tests are replaced by
durable continuation, no extra Tasks, no generated tracking, native-only inference, preserved
costs, stale-decision rejection, lease recovery, human authority and legacy cleanup guarantees.
Review cancellation/accounting tests are retired in favor of PostgreSQL/Atlas contraction tests
that prove Task preservation, metadata cleanup, rollback and idempotence. Goal-specific generated
progress decoding is retired; generic structured-inference alias/JSON coverage remains in
`tests/test_structured_inference.py`, and editable tracking preservation remains covered by
Goal update/API tests.
Real scheduler/harness/MCP/Chat journeys continue to cover authorization and human answers.

Before/after measurement uses identical synthetic lifecycle scenarios with PostgreSQL and a
scripted external model boundary, plus the same semantic corpus with real configured models.
Report model decisions, costs and latency separately from Task orchestration counts. Synthetic
model-boundary prices are not monetary savings; a small real-model corpus does not qualify
arbitrary business completion. Local reports belong under `artifacts/`, not in tracked fixtures.
