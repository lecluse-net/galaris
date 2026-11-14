# 0283 — Goal series and durable agenda passages

Date: 2026-11-13
Status: Accepted

## Decision

Goal owns its planning and remains the only creator of its cycles and Tasks. Agenda
displays a Goal layer, authorized separately by Goal privileges and Agent management
scope. It never wraps those passages in ordinary calendar actions or VALARMs.
This supersedes the prohibition on displaying planned Goal cycles in decision 0278;
ordinary event reminders still have no implicit Goal association.

A Goal chooses exactly one automatic trigger: delay after work, completion of a parent
cycle, or fixed local-clock recurrence. The initial fixed profile supports daily,
weekly, monthly and yearly cadences with an interval, anchor, timezone and bounded
lateness. Existing delay and parent contracts retain their meaning. Fixed occurrences
are eligibility times, not reservations or guaranteed Task start times. Global pause,
allowed schedules, agent availability and the single unfinished cycle gate still apply.

Immutable `goal_calendar_plans` segments snapshot the recurrence and title. Editing,
pausing or closing a Goal closes the current segment at the mutation boundary and only
replaces the future. Resuming creates a segment starting at resume time. The worker can
recover elapsed passages from closed segments even if it was offline during an edit.

Future passages are calculated without persistent expansion. At their due time the worker
materializes `goal_occurrences`, even before work can start. The deterministic identity
derived from segment and scheduled UTC instant survives this transition. Goal locks,
a unique segment/instant key and a unique cycle association prevent duplicate passages.
Cycle creation, ordinary Task creation and occurrence attachment commit together.
The scheduled instant never moves to actual admission or completion time.

Late passages are retained as skipped and never cause unbounded catch-up. Work remains
non-overlapping. Manual cycles have distinct occurrences and do not consume a future
scheduled passage. Existing cycles remain readable at their actual creation time; their
historical schedule and original titles cannot be reconstructed and are not invented.
The required DbAdmin expansion action snapshots their current title, actual creation time
and exact cycle link once. Renaming also snapshots any subsequently restored legacy cycles
before changing the title. Replays never overwrite existing passages.
Delay-based Goals expose only their next known eligibility, not a fabricated fixed series.

The read-only bounded `/goals/agenda` endpoint includes cycle, work Task and review Task
references. Task routes retain their own authorization. Goal content and history stay in
Goal, not Calendar's disposable projections, Documents or Process definitions. The
frontend uses shared timezone conversion for ordinary events and Goal recurrence editing.

## Qualification

Synthetic DB scenarios cover projection/materialization identity, exact per-cycle Tasks,
manual work, pending and running passages during edits, recovery from closed segments,
lateness, pause/resume, completion, timezone transitions and invalid monthly dates. Legacy
snapshot tests verify rollback, idempotence and retained titles after renaming.
HTTP tests cover Goal authorization, managed scope and bounded windows. Browser scenarios
cover cadence save/reopen and Task navigation from projected then materialized passages.
Executor prompts and agent usage habits remain a separate integration step.

## Frontend dependency review

The reviewed `app/calendar` → `app/goal` edge consumes the public agenda client,
event type and passage panel. Goal does not import Calendar: timezone conversion is
shared through `core/util`. The edge creates no cycle or private import. Only this
public dependency is added to the frontend inventory; no coupling debt ceiling changes.
