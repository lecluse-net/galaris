# 0302 — Weekly agent retrospective

Date: 2026-11-19
Status: Accepted

Each Agent owns a system-assigned Goal with a fixed weekly recurrence in the usual Goal agenda.
The Goal, private tracking document and initial schedule segment commit with Agent creation.
Goal's bounded scheduler reconciliation assigns the same default to Agents that lack it. An
owner lock and a partial unique index prevent duplicate assignment and preserve an existing pause.
Goal rejects deletion, completion, transfer and changes to the weekly cadence. Authorized users
can pause, resume or edit the schedule through the standard Goal controls. Each admitted Task
finishes with deterministic continuation and a normal cycle history.

The retrospective reads up to twelve terminal Tasks owned by the executing agent and selected
from the week ending at the passage. Only the exact running retrospective Task can use the
evidence, learning and tracking functions. The server checks the source Task and evidence again
at application time. Skill writes use the canonical personal package, its live management scope
and optimistic revision. Recorded source identities and fingerprints preserve idempotence.
The tracking document records the review and its next check.

This supersedes the Dream producer in [0251](0251-dream-personal-skill-packages.md).
DbAdmin retires unfinished Dream receipts, removes its mode setting and carries existing
activation thresholds into internal skill policy. Existing skills, evidence, scores, activation
choices and completed receipts retain their identities. The next eligible execution loads the
same personal packages through its normal harness projection.
