<p align="right"><a href="../../fr/architecture/state-machines.md">Français</a> · <strong>English</strong></p>

# Durable State Machines

This document makes states searchable, but the code constants and tests remain authoritative. Any matrix change must update this file in the same diff.

## LLM inferences

`LLMInference` owns the request and `LLMInferenceAttempt` each attempt. Operation states are
`queued`, `running`, `pausing`, `stopping`, `paused`, `stopped`, `completed`, `failed` and
`interrupted`. The attempt remains `running` while a pause or stop is requested.

| Event | Source | Target |
|---|---|---|
| Committed admission | absent | `queued` |
| Lease claim | `queued` | `running` |
| Result | `running` | `completed` or `failed` |
| Pause | `queued` / `running` | `paused` / `pausing`, then `paused` |
| Stop | `queued` / `running` / `pausing` | `stopped` / `stopping`, then `stopped` |
| Stop after suspension | `paused` or `interrupted` | `stopped`, previous result preserved |
| Worker shutdown or lease expiry | `running` | `interrupted`; pending pause/stop takes precedence |
| Explicit resume | `paused` or `interrupted` | new `queued` attempt |
| Explicit replay | any state | new `queued` inference, original unchanged |

Commands are idempotent by UUID. A requested stop cannot become a pause. Completed attempt
results are immutable; writes using a lost lease are rejected. Resuming submits the frozen
request again, without resuming remote computation. Each attempt streams committed messages
followed by exactly one terminal result. Unsubscribing does not stop autonomous execution.

Authority: `back/app/llm/contracts.py`, `inference_store.py` and `inference_execution.py`.
See [0097](../../../project/decisions/0097-durable-inference-lifecycle.md).

## Agent Harness

Persisted states of `AgentHarness.lifecycle_status`: `absent`, `provisioning`, `ready`,
`deprovisioning`, `error`. The absence of a row selects the internal harness.

| Event | Sources | Target |
|---|---|---|
| `SELECT_CONTAINERIZED_HARNESS` without an old runtime | internal | `absent` |
| `SELECT_CONTAINERIZED_HARNESS` with an old runtime | `absent`, `ready`, `error` | `deprovisioning`, then `absent` after cleanup |
| `SELECT_REMOTE_CONFIGURATION` | internal, `absent`, `ready`, `error` | `ready` after any required cleanup |
| `SELECT_INTERNAL` | `absent`, `ready`, `error` | `deprovisioning`, then assignment deletion |
| `RESTART` / `UPDATE` | `absent`, `ready`, `error` | `provisioning`, then `ready` or `error` |

A selection never provisions. Cleanup, restart, and update respond with
`202` and then run in the background. `restart` and `update` destructively recreate the single
stable container `<agent.code>-agent`; no non-terminal Task may overlap a transition.

## Tasks

Phases: `CREATE`, `DISPATCH`, `BRIEFING`, `EXEC`, `PLAN`, `SUCCESS`, `ERROR`. `PAUSE` is a
historical PostgreSQL value; current suspension uses `Task.paused` while preserving
the resume phase.

| Event | Sources | Target |
|---|---|---|
| `ROUTE_TO_EXECUTION` | CREATE, DISPATCH | DISPATCH |
| `ROUTE_TO_BRIEFING` | CREATE, DISPATCH | BRIEFING |
| `ROUTE_TO_PLAN` | CREATE, DISPATCH, PLAN | PLAN |
| `START_EXECUTION` | DISPATCH | EXEC |
| `BRIEFING_SUCCEEDED` | BRIEFING | DISPATCH |
| `BRIEFING_FAILED` | BRIEFING | ERROR |
| `EXECUTION_SUCCEEDED` | EXEC | SUCCESS |
| `EXECUTION_FAILED` | EXEC | ERROR |
| `PLAN_SUCCEEDED` | PLAN | SUCCESS |
| `PLAN_FAILED` | PLAN | ERROR |
| `FAIL` | any active phase | ERROR |
| `INTERRUPT_EXECUTION` | EXEC | DISPATCH |
| `RECOVER_EXECUTION` | EXEC | DISPATCH |
| `RETRY` | ERROR | DISPATCH |
| `RETRY_PLAN` | ERROR | PLAN |
| `RETRY_DELIVERY` | SUCCESS, ERROR | DISPATCH |
| `RETRY_ROUTING` | ERROR | CREATE |
| `REVISE` | DISPATCH, BRIEFING | CREATE |
| `CANCEL` | any active phase | ERROR |
| `FORCE_TERMINATE` | any active phase | ERROR |
| `ACTIVATE_PLAN_STEP` | PLAN, DISPATCH | DISPATCH |
| `RESUME_COLLABORATION` | suspended DISPATCH | DISPATCH |
| `COORDINATION_SUCCEEDED` | CREATE, inherited PAUSE, DISPATCH | SUCCESS |
| `COORDINATION_FAILED` | CREATE, inherited PAUSE, DISPATCH | ERROR |

Scheduler actions: `CREATE → dispatch`, `BRIEFING → brief`, `DISPATCH → execute`,
`PLAN → advance_plan`. `SUCCESS` and `ERROR` have no action. The `EXEC` phase represents an
execution that has already been claimed; recovery explicitly goes back through `DISPATCH`.
The current production policy no longer routes new Tasks to `BRIEFING`. The phase and
its transitions remain available to resume and inspect historical rows while
this deactivation is being evaluated.
When a harness declares briefing, the dispatcher may explicitly select `BRIEFING`, which
applies `ROUTE_TO_BRIEFING` then `BRIEFING_SUCCEEDED` before execution. A new `EXEC high`
choice follows `ROUTE_TO_EXECUTION` directly. Historical decisions without an available-choice
list retain the previous recovery policy.
Coordination discovered at the end of an execution applies `INTERRUPT_EXECUTION` and suspends the
Task in `DISPATCH` **before** any terminal transition. `SUCCESS` and `ERROR` are immutable for
all automatic events; only the explicit human retry commands declared above can create a new
execution.
For `RETRY_DELIVERY`, the `DISPATCH → execute` action recognizes the server contract and directly
calls the only authorized native tool: no driver or AI model participates in this resumption.

For an internal execution, the effect checkpoint follows `absent → started → completed`.
`completed` authorizes resumption and the return of the logged result without re-executing the tool.
In v4, an observed tool error gives `started → error_reported`, preserving a structured
result with a `rejected` or `unknown` outcome. The model receives that error and decides
whether to continue or stop; it does not terminate the run or consume schema-correction
retries. Resumption returns the recorded error without executing the call again.
Historical proven rejection before effects gives `started → failed`; disconnection without
a recorded response gives `started → outcome_unknown`. `ModelRetry` alone does not prove rejection. A console v2 receipt
allows `outcome_unknown → completed` through reconciliation on the same target. Without a receipt
or replay-safe policy the Task fails explicitly. Manual retry retains the journal, and replaced
or expired attempts cannot overwrite checkpoints.
A console receipt can also resolve `error_reported → completed`. See
[0103](../../../project/decisions/0103-tool-errors-return-to-agent.md).
If the current native contract explicitly corrects an earlier conservative classification to
`read` or `idempotent`, resumption reclassifies that effect, closes it as interrupted, and allows
the model to call the tool again. Unknown and non-idempotent tools never benefit from this fallback.
A Pydantic AI or asyncio cancellation additionally persists the run history with the status
`interrupted`. This history allows a partial response to continue and incomplete tool calls to be
closed, but never makes a non-idempotent effect that remained `started` resumable.

Attempt statuses: `CLAIMED`, `SUCCESS`, `ERROR`, `RETRY`, `CANCELLED`,
`WAITING_CHILDREN`.

An explicit deletion is authoritative in all phases. The service first applies
`FORCE_TERMINATE` to active Tasks in the eligible subtree, cancels their local action, closes any
`CLAIMED` attempt, invalidates the durable lease, and then performs logical child-before-parent
deletion. A late worker therefore cannot rewrite or resume a deleted Task.

An accepted conversational instruction on an unscheduled Task uses `REVISE` to
pass back through the dispatcher. If the Task was in `EXEC`, it is first interrupted to
`DISPATCH`. A Task suspended on coordination, by contrast, retains its phase and
correlation until fan-in. The operational states `QUEUED`, `RUNNING`, `WAITING`, `PAUSED`, and
`TERMINAL` are read projections, not new PostgreSQL phases.

A conversational amendment tolerates a newer technical revision only when the server-frozen
definition fingerprint for the requested revision still matches under the row lock. Changes
to objective, plan, overrides, scope or terminal state remain conflicts; without a known
fingerprint, revision checks stay strict. The amendment receipt preserves idempotency.
An unavailable amendment returns `CONFLICT` without an implicit new Task, including generic
live voice submission. Independent creation requires an explicit `CREATE_NEW` decision,
which remains available after a conflict. See the
September 19 addendum to decision 0029.
Amendability also checks checkpoint rebasing with the driver, both on inspection and under
the row lock before interruption. A lease or execution identity without a checkpoint, or an
incompatible checkpoint, makes amendment unavailable without changing the Task. Independent
outcomes within one document use `CREATE_NEW`; the new objective retains only its scope and
requires reading the current resource when execution starts. The existing per-agent external
runtime limit keeps the second Task queued.

`REPLACE` is a separate explicit decision. The stop and paused successor are persisted
together; `source_task_id` links the roots. Reconciliation requires lease release and stop
evidence for the captured execution. `requested`/`unknown` cannot release the successor,
and removing its pause cannot bypass the scheduler guard. Confirmation removes only the
replacement pause. A scope change or predecessor restart causes a conflict. Active children,
Goals and external waits remain outside this initial scope. The barrier checks the entire
descendant tree, remaining leases and Process-owned evidence registered at bootstrap: an
active Process or logical cancellation with `remote_may_continue` still blocks replacement,
even after soft deletion. Independent work and terminal Processes without uncertainty remain
available. See [0123](../../../project/decisions/0123-explicit-task-replacement.md).

Task and round heartbeats only renew a still-valid lease: an expired owner cannot regain
authority by sending a late heartbeat.

The `conversation_task_stop` tool reads the Task under a row lock after freshness and scope
checks. If it is already in `SUCCESS` or `ERROR`, it returns its state without another
transition or changes to its revision, result, or termination cause. An active Task keeps
the existing `CANCEL` command. This does not change the HTTP expected-revision contract
or prove that a worker still performing cleanup has physically stopped.

Authority: `back/app/task/models.py` and `back/app/task/workflow.py`.

## Text Conversations

A Messenger `Room` is ready when it has at least one incoming message without a consumed link.
Admission creates or enriches a `FROZEN` round; the scheduler claims it as `CLAIMED`, then its
recoverable lease moves to `RUNNING`. While a round is being processed for a room, no other round
for that room is claimed. A heartbeat renews the lease with its owner token throughout
execution; loss of that token cancels the local flow before any concurrent recovery.

| Round state | Transition |
|---|---|
| `CLAIMED` | turn construction → `RUNNING` |
| `RUNNING` without new input | response delivered → `SUCCEEDED` |
| `RUNNING` with new input, without effect | final guard → `SUPERSEDED` |
| `RUNNING` with new input, after effect | response deleted → `SUCCEEDED` |
| active without effect, recoverable error | lease expired → new `CLAIMED` attempt |
| active after effect or budget exhausted | degraded resolution → `ERROR_RESOLVED` |

`SUPERSEDED` does not consume its input links: the next round re-aggregates the same messages
with the new ones. After an effect, the current round's links are consumed and the new message
remains available to its successor. Terminal statuses are
`SUCCEEDED`, `SUPERSEDED`, `ERROR_RESOLVED`, and `CANCELLED`.

Chat accepts an HTTP projection only for the selection and viewer that requested it,
and only if no newer projection has already been accepted. The same guard covers errors:
an old access denial cannot clear another conversation, while a current denial still
purges protected content. A failed newer request does not itself invalidate a useful older
response. Purging or changing the viewer invalidates pending reads. Stream gaps rearm
recovery when received during an HTTP request; a new selection does not wait for a blocked
request belonging to an older selection.

While generating a text response, the harness checks every 250 ms whether a `FROZEN`
successor has been admitted in the same room under the current lease. This short-session
read also works across workers and never marks an effect. The signal cancels inference
through the Pydantic AI token; hooks between inference and tools prevent a newly stale
call from starting. An already started tool finishes before interruption. The final guard
preserves the transitions above and the partial trace, marked `interrupted_by_new_input`,
without publishing the draft as a durable answer. Administrative cancellation, lease loss
and audio retain their own paths.
If the successor has disappeared at completion, an interrupted round without effects returns
to `FROZEN` with unconsumed inputs; after effects, it closes without publishing the draft.

Each failed attempt may enrich the round's partial `ExecutionResult`. At the
`ERROR_RESOLVED` transition, the delivery state of the fallback response is carried by the
round and its text is derived from its language; the
`LLMCall`s from the attempts remain separately queryable.

Round and Process notifications use `PENDING → SENDING → DELIVERED`. Terminal
results of Tasks launched by a conversation use on their link
`IDLE → SENDING → DELIVERED`, or `IDLE → SKIPPED` when their terminal result already carries
proof of a successful Messenger delivery. The worker claims the notification only after the
Task lease is released and a final durable attempt is in `SUCCESS` or `ERROR`; a
cancellation and an error that is still retryable therefore produce no message. A distinct
progress message does not mask the terminal result. A transport exception after dispatch or
expiration of a `SENDING` lease produces `UNKNOWN`, never a blind retry. The Task attempt
number rearms a new notification after a subsequent human retry. The fallback state is carried
by the round, and that of a Task or Process result by its link; there is no separate
Conversation outbox anymore. Task links predating this contract retain a zero notified-attempt
counter and trigger no retroactive message.

An authorized operator can resolve `UNKNOWN → DELIVERED` or `UNKNOWN → SKIPPED` from the round
detail, including Task/Process links. This command records evidence per attempt, rejects active
leases and stale or conflicting decisions, and replays neither a send nor a Task/Process
transition. Repeating the same decision with the same evidence is idempotent.

Authority: `back/app/conversation/models.py`, `service.py`, and `scheduler.py`.

## Mail Sending

Each `mail_send`, `mail_reply`, or `mail_forward` call has a durable row identified by
`(connection_id, idempotency_key)`. The final MIME content is persisted before entering a state
that authorizes sending.

| Event | Source | Target |
|---|---|---|
| claim without human approval | absent | `claimed` |
| claim with human approval | absent | `pending_approval` |
| approval by the responsible USER | `pending_approval` | `submitting` |
| rejection by the responsible USER | `pending_approval` | `rejected` |
| SMTP submission | `claimed` | `submitting` |
| SMTP acceptance | `submitting` | `sent` |
| definitive SMTP rejection | `submitting` | `error` |
| unknown network issue | `submitting` | `uncertain` |
| Message-ID found in Sent | `submitting`, `uncertain` | `sent` |
| Message-ID not proven | `submitting`, `uncertain` | `uncertain` |

`sent`, `rejected`, and `error` are terminal. `uncertain` remains a safety state: a replay
never starts SMTP again; it only attempts IMAP reconciliation. Two concurrent approvals are
serialized by a row lock; once the first enters `submitting`, the second can no longer approve
the mail.

Authority: `back/bridge/mail/models.py` and `service.py`.

## Voice Conversations

A call session uses `ACTIVE`, followed by exactly one terminal state among `COMPLETED`,
`CANCELLED`, and `ERROR`. Each call has its own session, but multiple successive sessions
may reference the same Messenger room to continue a single multimodal conversation.

A turn uses `RUNNING`, followed by exactly one terminal state:

| Event | Source | Target | Effect on pending objective |
|---|---|---|---|
| complete response | RUNNING | COMPLETED | consumed |
| user barge-in | RUNNING | INTERRUPTED | retained for the successor |
| technical failure | RUNNING | FAILED | retained for the successor |

Terminal transitions are idempotent. At the start of a turn, its
`effective_objective` immediately becomes the durable pending objective; a subsequent interruption
therefore cannot lose any user fragment. A successor references the previous turn through
`source_turn_id`, which in turn points back through `resolved_by_turn_id`.

Authority: `back/app/voice/models.py` and `conversation_service.py`.

## Objectives

| Object | States |
|---|---|
| Goal | `ACTIVE`, `PAUSED`, `COMPLETED`, `ERROR` |
| GoalCycle | `RUNNING`, `JUDGING`, `DECIDED`, `ERROR` |
| Verdict | `CONTINUE`, `STOP` |

A cycle creates an ordinary Task, waits for its terminal state, moves to judgment, and then
persists a verdict. `CONTINUE` schedules the next time-based cycle when a frequency exists; `STOP`
closes the objective. A pause prevents the creation of new cycles without erasing history.

Each Goal chooses exactly one automatic trigger mode. The time-based mode requires a
frequency and may use the default global window or add a Goal-specific weekly restriction. The
relational mode designates a single parent Goal, with neither its own frequency nor window.
Each completed parent cycle idempotently deposits a durable trigger for each of its
direct children. The runner consumes it to create a `RELATIONAL` cycle carrying the source
cycle's identifier; cascading to subsequent levels occurs only once their own cycle
is completed. Relationships are acyclic, and the tree API exposes descendants to the interface as well as the parent and child count in a Goal's details. A manual command remains possible
in both modes and does not constitute a third configuration mode.

A global weekly schedule bounds
new cycles and reruns for all Goals. Each Goal may add an individual weekly restriction,
without ever reactivating a slot closed globally. A manual cycle request is persisted until its
Task is created and bypasses global and individual time restrictions, but never the explicit
global pause.
If “Run a cycle now” first needs to recover a failed evaluation, the manual request remains
pending: `CONTINUE` allows a new Task to start without waiting for the schedule, while `STOP`
cancels the request. “Retry tracking” only retries the evaluation. Both commands preserve the
previous Task and its result.
Force-closing a Task makes its attempt terminal, releases its lease, and
immediately closes its open cycle with `CONTINUE`, without assigning progress to it. The Goal
remains paused if it was paused voluntarily; otherwise its tracking is rescheduled for the next
cycle.
An explicit resumption of `COMPLETED` retains documents, costs, and historical cycles, clears
`completed_at`, returns the Goal to `ACTIVE`, and makes a new cycle immediately eligible according
to the pause, global schedule, and individual restriction.

Authority: `back/app/goal/models.py`, `goal_service.py`, and `runner.py`.

## Dream

| Receipt state | Transition |
|---|---|
| absent | topic claim → `running` |
| `running` | successful application → `success` |
| `running` | recoverable error or preemption → `retry` |
| `running` | error with budget exhausted → `error` |
| `retry` | new claim → `running` |
| `running` with expired lease | reconciliation → `retry` or `error` |
| `success` | terminal, except for explicit resumption of a missing derived projection |

For `topic.classify_message` and `topic.classify_task`, a reuse decision is
applied directly. A creation proposal follows the checkpointed policy: `forbid`
terminates without assignment, `auto` creates and then assigns, and `propose` persists a Messenger
`PENDING` interaction before the Dream receipt becomes `success`. The authorized response moves
the interaction through `PROCESSING`, applies at most one creation or reuse, and then makes it
`RESOLVED`; a rejection resolves it without `topic_id`. An application error leaves `PROCESSING` for
idempotent resumption after its lease expires.

If an already successful direct assignment (`reuse` or `create/auto`) disappears from the topic, the
scheduler may claim the `success` receipt again, reset its attempt counter to zero, and
reapply its checkpoint without a new LLM call. The `pending` count includes only this
resumption or a topic that still has no receipt; `error` receipts, successes without direct
assignment, and human approvals are not presented as claimable work.
During a database synchronization, the DbAdmin reconciler restores still-active targets in one
pass; the scheduler retains single-item resumption for checkpoints that cannot be resolved by
this direct projection.

A Task created by a conversational round directly receives the Topic and contact persisted
by the round in the creation transaction. Creating a child Task likewise copies the scope of
its parent or source Task. If classification of a message or Voice turn finishes after the Task
is created, that same classification pass propagates its scope to derived items still without a Topic;
no separate Dream inheritance mechanism is executed. Automatic memory extraction
still waits for a non-null `topic_id`: before that, it creates neither a receipt, nor a reminder, nor
an LLM call. This dependency is carried by the predicates of the Task, text-round, and Voice-turn
extractors, not by the scheduler's rotation order. Conversational sources additionally require the
exact contact that seals their memories; an ambiguous voice identity intentionally remains blocked.

Link maintenance has no Dream state machine. A durable `link_reconcile` job converges
directly from current provenances, projections, and vectors. Targeted jobs follow successful Dream
operations; a daily global job is admitted and executed only when no Task or Voice conversation is
active. Deferral due to foreground load returns the job to `pending` without consuming its attempt
budget.

Voice preemption makes the receipt immediately available without consuming its failure budget. The
prepared output may exist as early as `running` and remains reusable during resumption.
For `skill.learn_task_outcome`, the first checkpoint contains the evidence and its fingerprint,
then the prepared checkpoint contains structured operations on the skills. An `observe`
success may be claimed once during the transition to `learn`, without rerunning the model. The
application adds idempotent evidence and recalculates the score; it does not touch Memory. A new
late-arriving piece of evidence does not reopen the terminal receipt: it creates another topic
`<task UUID>:<fingerprint>`. All terminal Tasks without a receipt are therefore traversed, including history,
from oldest to newest. The scheduler maintains its throughput bounded to one operation per pass;
catch-up is not a massive parallel process.
The scheduler executes only one operation per pass and rotates the priority mechanism to
prevent starvation. `DREAM_POLL_SECONDS` starts after that operation finishes before another
can start; the operation duration therefore never consumes this pause.

Authority: `back/app/dream/models.py`, `service.py`, and `scheduler.py`.

## Processes

Terminal states: `success`, `error`, `cancelled`.

Waiting-task finalization is separate from run status: `await_resolved_at` remains null until
the child Task is closed and its parent resumed. Callbacks, refresh and periodic reconciliation
can replay this step. Runs in `cancelling` remain eligible for polling.

| Current state | Allowed targets |
|---|---|
| `queued` | running, waiting, success, error, cancelled |
| `running` | waiting, success, error, cancelling, cancelled, unknown |
| `waiting` | running, success, error, cancelling, cancelled, unknown |
| `unknown` | running, waiting, success, error, cancelling, cancelled |
| `cancelling` | cancelled, success, error |
| `success` | none |
| `error` | none |
| `cancelled` | none |

A transition to the same state is idempotent. Every attempt, accepted or rejected, may
be logged as an event. `started_at` is set upon the first entry into `running` or
`waiting`; `finished_at` upon entry into a terminal state.

Authority: `TERMINAL_STATUSES` and `TRANSITIONS` in
`back/app/process/process_service.py`.

## AI Lab Evaluations

A Lab evaluation run follows `queued → running`, then exactly one terminal state among
`completed`, `partial`, `failed`, and `cancelled`. A cancellation request is durable; a run in
the queue is cancelled immediately, while a run already in progress completes the current
isolated call before stopping.

Each run freezes the cases, the candidate LLM, the Lab analysis LLM automatically used as
judge, and the rubric version before starting. The judge is resolved from the **Lab** usage of the current profile; there
is no separate selection in the Lab. A case result constitutes a single durable
checkpoint for the run/case pair.
The registry covers Dispatcher, Briefing, Planner, topic classification, memory extraction,
learning, and objective tracking. Each mechanism declares the
native format of its input and output (`text` or `json`), its production system prompt, and
its output schema. Dispatcher workers and generic mechanisms have disjoint claims. They process
only one case per pass and have a recoverable lease, without creating or transitioning a Task and
without triggering a tool or message.

Planner benchmarks have an editable copy of the decomposition system prompt, initialized
from the production Param. The run freezes the exact value before any execution, as with
memory extraction.

The `memory_extraction` benchmark is specialized: each case contains a classified source and its
own corpus of existing memories. It classifies this local corpus and then directly evaluates
`CREATE|LINK|IGNORE`, without reading or modifying production memory. Its prompt belongs to the
dataset and its exact value is frozen in the run.

For mechanisms other than Dispatcher, `score_percent` is semantic relevance weighted
by a rubric specific to the mechanism. The expected output is a non-normative reference example:
another correct answer loses no points for its wording, order, or strategy. Structural similarity
to this reference remains a separate diagnostic and does not contribute to the main
percentage. A failure that the judge qualifies as invalidating caps relevance at
50%, so that it is not diluted by good secondary subscores.

`completed` means that all cases received an actionable result and judgment; `partial`
means that at least one candidate case failed or that its semantic judgment is unavailable. An error by
the judge alone preserves the candidate output and similarity diagnostic, but leaves its relevance
score at null (`null`) instead of substituting a misleading percentage. A candidate error is worth
0% and remains explicitly distinguished from an incorrect answer.

Authority: `back/app/lab/models.py`, `dispatcher_evaluation_service.py`,
`mechanism_registry.py`, `mechanism_rubrics.py`, and `mechanism_evaluation_service.py`.

## AI Failure Patterns

Each failed LLM or tool call adds an immutable occurrence. Its aggregate pattern follows the
review cycle below; this status never modifies historical occurrences.

| Event | Source | Target |
|---|---|---|
| first occurrence | absent | `new` |
| human analysis | `new`, `regression` | `triaged` |
| fix decided | `new`, `triaged`, `regression` | `fix_planned` |
| fix verified | `triaged`, `fix_planned`, `regression` | `resolved` |
| decision not to act | any state | `ignored` |
| new occurrence | `resolved` | `regression` |
| new occurrence | other state | state unchanged |

A terminal success of the same run marks its earlier occurrences as recovered without
deleting them or resolving their pattern. Reopening `resolved → regression` is atomic with
the addition of the occurrence. The other transitions are administrative review decisions and
may be corrected manually.

Authority: `back/app/incident/models.py` and `service.py`.
