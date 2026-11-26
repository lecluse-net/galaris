# 0260 — Yield peer requests at a safe tool boundary

Status: accepted. Date: 2026-10-30.

## Context

Coordination previously suspended a parent only after its executor returned. An executor
could keep investigating and read a completed colleague's answer before fan-in launched
another inference to synthesize that same answer. Existing coordination tests covered
durable suspension and resumption, but did not check the intervening model-request boundary.

## Decision

`messenger_send_message_to_user` accepts `wait_for_reply=False` by default. Only an explicit
`True` after successful colleague admission marks native evidence with `wait_for_children`.
Choose it when remaining work depends on this reply. Existing calls and `task_run` keep the
current turn available for more contributions and independent work, while Task still awaits
peer results before completion. Errors and human recipients never request this early yield.
Proxied MCP tools cannot forge native execution evidence.

Both embedded harnesses drain the selected tool batch and yield before the next model
request. The Claude harness persists the native wait signal with the tool receipt. The
gateway checks that attempt's checkpoint before admitting another model call. A replacement
worker can apply the saved wait without starting the SDK again. Uncertain non-idempotent
sibling effects retain the existing reconciliation path. Managed network runtimes hold the completed
MCP response, stop admitting new actions, drain engaged MCP and local actions, persist
their receipts and close the current inference. A lost receipt remains an unknown outcome.

The portable v2 result uses `waiting_for_children`, with no successful Task outcome and
no terminal failure. The semantic run event records the same wait. Task retains ownership
of suspension, deadlines, peer completion and idempotent fan-in, including replies received
before suspension. Once the wait is applied, its finished inference checkpoint is removed;
resumption starts with the durable colleague results, without replaying the request.

Both embedded drivers persist the v2 wait result before the Task scheduler applies it.
Each completed tool receipt is recorded on the attempt that emitted it. The replacement
worker can finish applying the wait using the original run's provider accounting. The
call journal retains the Task requester when the scheduler's worker has no ambient caller.

## Verification and limits

Synthetic regressions cover sequential and parallel tools, no extra model request,
drained local/MCP effects, missing receipts, actor restart observation, the common driver
boundary and DB-backed peer admission and fan-in. Default calls, multiple delegations and
independent work retain their continuation behavior. This does not optimize investigations
before the peer request. Managed runtime images must be refreshed to consume the new
evidence; older images ignore it and keep the previous end-of-turn coordination behavior.
