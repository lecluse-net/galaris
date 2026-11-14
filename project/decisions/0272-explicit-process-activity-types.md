# 0272 — Explicit Process activity types independent of lane placement

Date: 2026-11-09
Status: Accepted

## Decision

The internal Process editor uses an inline settings panel to the right of the diagram,
stacked below it on mobile and included in full screen. Selecting another node or flow
preserves its draft. Escape closes a select menu before clearing the panel selection.

Tasks expose four explicit types: agentic AI, single LLM call, Code and Human. Existing
BPMN kinds remain canonical: `task`, `task` with `ai_mode: llm`, `code`, and `human_task`.
Agentic tasks belong on AI lanes and human tasks on human lanes. LLM tasks and Code may
use any lane, including the unassigned process lane. Moving a node changes its actor,
never its execution type. Changing the type explicitly selects a compatible actor.
The default execution-agent lane is also an AI lane, including when human roles exist.
Creation and type conversion must not create an implicit role or lane. The agentic task
panel exposes the same agent assignment as its lane header: either the named role's agent
or the process execution agent. Existing named roles remain reusable.

New IF nodes offer Code or decision AI (one LLM inference), on any lane. Existing human,
agentic and expression IFs retain their execution semantics until explicitly edited;
admitted snapshots are unchanged. This supersedes the editor choices in decision 0231.

LLM tasks reuse the existing durable Process inference ownership and LLM lifecycle.
They require an explicit text model, no tools, one provider request, no output retry
and no model fallback. A registered structured output contract carries an `output`
object of ordinary JSON values. Process validates it against selected output variables
and integrates through existing receipts and conflict checks. Failed inference or
invalid output fails the activity, without treating it as a successful empty result.
Recovery reuses the deterministic inference identity; cancellation waits for it to stop.
No new database schema, Task, Document or execution framework is introduced.

## Verification

Backend integration tests exercise direct task outputs, human and delegated AI lanes,
selected input contracts, invalid outputs, scheduler recovery and cancellation. Existing
IF inference tests retain their branch, failure, recovery and authorization guarantees.
Frontend tests cover explicit creation, assignment restrictions, type preservation,
drafts, saving and reopening, keyboard selects, mobile and full screen.
