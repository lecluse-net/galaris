# 0271 — Autonomous Goal conduct with durable review Tasks

Date: 2026-11-09
Status: Accepted

## Decision

Goals retain the original desired outcome. Agents own discovery and revision of the method,
including research, bounded experiments, useful improvement without external news, and peer
contributions. Strategy, approaches, decisions and rejected alternatives remain freely organized
in the existing tracking Document. No path, experiment or organizational entity is introduced.

The post-cycle judgement supports CONTINUE, STOP, PAUSE and REVIEW. Only satisfaction of the
original completion criteria permits automatic completion. Before completion, a proposed pause,
an explicit review request, or three consecutive unchanged cycles since the last review, Goal
creates an ordinary Task under the same owner in a fresh context. It inherits causal scope and
budget lineage, receives no additional rights, and can inspect resources with ordinary tools.
The agent may still delegate bounded contributions to authorized peers through task_run.

The cycle's nullable review_task_id and Task data record the review and its Goal/tracking
revision snapshot. Creation and linking commit together under Goal/cycle locks. No model poll runs
while it is pending. A stale review must settle before replacement, is excluded from the new
judgement, and remains billed. Review results and recorded tool observations inform final judgement;
success of a review Task alone does not prove the desired outcome. Failed reviews cannot authorize
completion. Blockers pause the Goal with an explicit reason, preserving history and resumption
conditions. Existing CONTINUE/STOP cycle verdicts remain compatible with consumers.

## Verification

PostgreSQL tests cover review lifecycle, revision invalidation, recovery, costs, manual control
and multi-cycle stagnation. A bounded synthetic real-model trial qualifies judgement decisions
separately from deterministic execution tests. Neither proves general autonomous goal attainment.

## References

- [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)
- [Harness design for long-running application development](https://www.anthropic.com/research/harness-design-long-running-apps)
