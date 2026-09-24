<p align="right"><a href="../../../fr/architecture/flows/agent-execution.md">Français</a> · <strong>English</strong></p>

# Agentic Execution Flow

Before each fresh execution, the facade checks the selected
provider's skill revision. Content and authorization changes are projected before
the driver starts, without interrupting an active Task. The receipt is invalidated
before copying; a failed projection prevents stale execution. Refresh requests are
persisted independently of the UI, and runtime status includes skill readiness.
A checkpoint continuation retains the skills and credentials of the remote
operation it reconciles.
See [0131](../../../../project/decisions/0131-harness-skill-reconciliation.md).

The shared harness validator holds the candidate result until the stream ends normally
and adapter cleanup completes. Messages are still forwarded immediately. An invalid
or stalled tail fails before any success is published;
`AgentDriverSpec.stream_close_timeout_seconds` bounds closure for every driver. See
[decision 0098](../../../../project/decisions/0098-harness-stream-acceptance.md).

Every harness, including the embedded implementation, has a policy in the harness
catalogue. Effective capabilities intersect implementation, configuration and the
selected target's verified capabilities. Checkpoint payloads are opaque to orchestration;
their driver decides whether recovery or objective amendment is safe. Cancellation
receipts distinguish a request from a confirmed stop. See
[0100](../../../../project/decisions/0100-harness-capability-and-recovery-contract.md).

## Elementary inference

Internal Chat/Responses models use the durable inference facade in `app.llm`. Dispatcher
and Briefing also use the structured adapter with a frozen schema and validation context.
Admission is committed before the worker starts; its leases, events and results replace
neither Task attempts nor tool checkpoints. `LLMCall` remains the cost authority for physical
calls. The Lab Memory extraction pilot uses the same journal while preserving business retries.

Reading an attempt returns messages followed by exactly one terminal result. Reconnection
continues from a cursor; `resume` creates a new attempt of the frozen request. The service
never replays tools. Synchronous and HTTP adapters request stop when cancelled; closing a
plain journal subscription leaves autonomous inference running. See the
[inference states](../state-machines.md) and
[0097](../../../../project/decisions/0097-durable-inference-lifecycle.md).

## Task activity and provenance

The internal harness returns structured tool errors to the model, including errors
whose effects remain uncertain. The model decides whether to verify, correct, continue
or stop. The v4 checkpoint distinguishes these acknowledged errors from calls interrupted
without a response; the stream still reports a tool failure without automatically failing
the Task. See [0103](../../../../project/decisions/0103-tool-errors-return-to-agent.md).

The chat and task detail hydrate `POST /tasks/activity` on opening and reconnecting, then share
subscriptions to active runs. The common projection exposes operational state, requested or
acknowledged pauses, waits, the latest attempt and the next retry. `task_get` also exposes this
activity for active and terminal tasks. The terminal result remains authoritative, and the facade
rejects late events before publishing them.

Conversations display text fragments immediately. Task views wait for block completion
(`AIMessage.stream_complete`) before displaying text or reasoning; states and tool results
keep updating during execution. Legacy drivers without markers wait for the next operation
or terminal result, and call-based views wait for `completed_at`. Internal fragments remain
available to guards and checkpoints. See [0087](../../../../project/decisions/0087-task-activity-snapshots.md).

The visual `TaskAttempt.data.live_activity` checkpoint is limited to 40 messages of 4,000 characters,
without prompts or structured tool payloads. An independent JSONB write preserves effect receipts
and checkpoints. Custom Harnesses can select correlated LLM calls with `streams_ai_messages=false`;
built-in Harnesses retain their native messages. The frontend indicates the 500 loaded call limit
and never combines the two sources.

The detail shows the original demand preserved when new tasks are admitted, their provenance,
and recorded resources/receipts. Historical tasks are not retroactively rewritten.
Task and round details also show the initial startup of conversation-created Tasks: objective
preparation, admission after preparation, and an upper bound on waiting before the first claim.
`Task.data._startup_timing` stores the three observed UTC timestamps; `TaskAttempt.data.claimed_at`
stores the actual claim time independently of PostgreSQL transaction start time. Enqueue is
observed before INSERT/commit, so the following interval includes persistence and any pauses;
it does not prove scheduler saturation. Only attempt 1 counts. Retries and updates never reset
these measurements. Every ORM insertion also records enqueue in `Task.lifecycle_timing`, a
nullable column separate from business data. Phase, lease, pause and backoff changes accumulate
intervals by state and phase without changing scheduler decisions. The projection identifies
when observation began; a pause during an active lease remains processing until lease release.
Time after a backoff deadline counts as queue time again. For historical Tasks, the LLM facade
recovers actual persisted call timestamps, including preparation when the originating round
belongs unambiguously to one Task. It does not manufacture a claim time from `created_at` or
`updated_at`. Views present available intervals with their source instead of “not measured”
cells. Queries are batched over authorized Tasks; historical call recovery is unnecessary when
enqueue has already been observed.
See [decision 0087](../../../../project/decisions/0087-task-activity-snapshots.md) for limits,
rehydration and the distinction from future generic effect authorization.

## Requester authority

An `openai-codex` connection represents a personal subscription and identifies its holder in
Galaris. Before any transport, the LLM facade cross-checks this holder against the durable
requester of the Task and its lineage. A Goal freezes the requester of its referent during its
configuration and passes it to each cycle. Children, delegations, Processes, and harnesses thus
retain the same authority without accepting an identifier declared by the runtime. On a
single-user instance, internal work without an explicit author may fall back to the sole holder;
this fallback never applies to Messenger origins.

This flow explains the common path of a task, independently of the concrete runtime. The text
control plane of `app.conversation` has a separate internal controller; real-time voice
conversations retain their specific path without a Task.

```text
Task PostgreSQL ── app.task scheduler/agent_adapter ──► AgentTaskPort
       │                                                │
       └──────────────► app.agent facade ◄──────────────┘
                              │
                 dispatcher + driver policy
                              │
                   optional planner / briefing
                              │
             shared context providers, fail-open
 governed history if required + current Working Set
                              │
              model and strategy resolved once
                              │
                 AgentRunRequest local
                  ├─ AgentRunControl local
                  └─ validated V1 envelope
                      ┌───────┴────────┐
                      ▼                ▼
       app.harness           app.harnesses
        Pydantic AI        Chat Completions
                         ├─ configured URL
                         ├─ bridge.deepseek_harness
                         ├─ bridge.claude_agent
                         └─ bridge.codex
                      └───────┬────────┘
                              ▼
              messages* + unique ExecutionResult
                              ▼
                application then durable persistence
```

## Decision Owners

| Decision | Owner |
|---|---|
| Phase, lease, attempt, pause, resumption | `app.task` |
| Available driver and descriptor | `app.agent` registry |
| EXEC/BRIEFING/PLAN route and effort | `app.agent` dispatcher bounded by the selected harness policy |
| Planner and briefing activation | `DriverPipelinePolicy` |
| All LLM usage | Text level or specialized column of the effective profile, except for the durable reasoning override carried by the Task |
| Standard/high model | `app.agent` resolver, once per run |
| Direct adapter or internal Kanban in Hermes | `bridge.hermes.driver` |
| Conversational session | `app.messenger` journal projection |
| Durable memory recall | `app.memory`, ACL, and budget before the driver |
| Active work resources | Root Working Set owned by `app.task` |
| Adaptation to the Pydantic AI runtime | `app.harness` |
| Adaptation to network Harnesses | Shared `app.harnesses` client |
| DeepSeek Harness provisioning | `bridge.deepseek_harness` via `bridge.harness` |
| Claude Agent SDK provisioning | `bridge.claude_agent` via `bridge.harness` |
| OpenAI Codex SDK provisioning | `bridge.codex` via `bridge.harness` |
| Historical adaptation to the Hermes runtime | `bridge.hermes` |
| Stream validation and result application | `app.agent` facade |
| Projection of a terminal result into a conversation | `app.conversation` |

`app.task` chooses neither the driver, the model, nor the activation of assistance features. A
driver does not recalculate these decisions after receiving the `AgentRunRequest`.
The Hermes driver rejects any `AgentRunRequest` without a `task_id`: conversational and voice
rounds without a Task explicitly select the internal harness before calling a driver.
The LLM proxy applies the same invariant to authenticated requests from a managed runtime. The MCP
handshake remains authorized before a Task, because the Hermes client initializes when the
container starts; the active Task is injected into the tool request context. MCP tokens explicitly
created by a user retain their generic contract.
Implicit correlation by `agent_id` alone is accepted only when a single Task is active.
The gateway first consults the local run registry, then that agent's single durable lease so that
correlation remains valid across multiple HTTP workers. Multiple matches cause this closed path to
fail. Each external Harness provider therefore currently declares
`max_parallel_tasks=1`; the scheduler checks this limit under the agent's transaction lock by
counting unexpired leases. The internal harness exposes `max_parallel_tasks=null` and can execute
multiple Tasks for the same agent because each explicitly carries `task_id` and `agent_run_id`.
The LLM service additionally resolves the active attempt and derives the round again from the
Task. A Harness never executes a conversational round and therefore never carries a
`conversation_round_id`: text and voice conversations use only their dedicated internal
controller.
The low-level calls of the internal conversational controller, on the other hand, retain their
`agent_id` correlation for auditing without becoming Harness executions or managed-runtime
requests: a conversational or voice round without a Task therefore remains authorized regardless
of the driver configured on the agent. Hermes operator configuration is owned by
`/api/hermes/configurations` and is no longer exposed by the generic Agent CRUD. Its presentation
remains a contribution from `front/bridge/hermes` to the Agent record tab and the
`Preferences > Harnesses` submenu, without an independent navigation entry.
The OpenAI-compatible Hermes target—URL, token, model, and published port—is internal data
generated by Galaris and belongs neither to this operator configuration API nor to its form.
The bridge must inject the effective model through the Galaris LLM gateway after all Hermes
overrides and remove direct provider credentials; this policy is not configurable per agent.
When an external Console connection is active, the same bridge resolves its effective parameters
through the public surface of `app.connection`, then projects them into Hermes's native terminal
backend after operator overrides. The decrypted private key and host trust remain in
instance-bounded files (`0600`); only their path appears in the Hermes environment. Instance-local
OpenSSH wrappers enforce the Galaris `known_hosts` for both `ssh` and `scp`. An embedded
connection does not modify the native terminal, and removing the external target restores the
previous values.

Operational monitoring is separate from this configuration. The Agents screen calls the generic
`/api/harnesses/agents/{id}/...` routes of `app.harnesses`. The facade resolves the driver's
contribution and exposes only the capabilities actually available. Hermes contributes its adapter
and uses exclusively the host manager `bridge.harness`. Each Hermes agent has its own instance and
container `<agent.code>-agent`; the status, logs, start, stop, update, and restart buttons do not,
however, depend on the Hermes name in the frontend.

The `app.harnesses` catalog merges two sources without conflating them: each bridge provider
supplied by the code has a global activation Param of type bool, while the `Harness` table is
reserved for reusable OpenAI Messages configurations and permits multiple occurrences.
They all share the same card grid, and each agent has at most one runtime `AgentHarness`
assignment. Activation makes a card selectable without hiding it when inactive. An OpenAI Messages
configuration, its secret, and its model are entered only on its catalog page, never on the Agent
record. Disabling a card or deleting an OpenAI Messages configuration destroys the assigned
runtimes and then switches their agents back to the internal harness; the operation remains
forbidden during a nonterminal Task.

Editing an agent never provisions a container. A Harness change first persists the new preference,
marks its runtime `absent`, and destroys the old runtime in the background after explicit
confirmation of data loss. The Agent card's `restart` and `update` actions are the only
recreation commands: they remove any existing instance, then reprovision it in the background. All
containerized providers use the single instance directory `<agent.code>` and the single container
name `<agent.code>-agent`, regardless of the selected Harness. Non-containerized OpenAI Messages
configurations become directly `ready` because they have no local runtime to build.

The Agent record checks nonterminal root Tasks before this change. When they are paused, it names
them, explains that forced termination will mark them as failed, and requests explicit confirmation
before executing that command and then resuming the save. Active Tasks are never terminated
automatically; they remain flagged as blockers until completion.

## Nominal Sequence

1. The scheduler claims an eligible task with a durable lease and creates a `TaskAttempt`.
2. The adapter converts the ORM model into an agentic contract without exposing SQLAlchemy to the
   driver.
3. The dispatcher builds the route/effort pairs declared by the selected harness, applies
   constraints, and calls a model only if multiple choices remain. One choice is deterministic;
   incompatible constraints fail even without a configured model. The decision and available
   choices are persisted. It distinguishes difficulty from decomposability:
   an explicit, bounded, mechanical, and easily verifiable operation remains `EXEC standard`,
   including when it uses multiple tools or applies an already-authorized destructive action.
   Risk determines the safeguards, not the effort. A genuinely complex, coherent deliverable
   produced through multiple research, construction, verification, and delivery passes remains
   `EXEC high`. `PLAN` requires multiple independently executable units of work whose durable
   results benefit from coordination. If there is ambiguity between these two routes, `EXEC high`
   is preferred. An explicit forced choice is honored without hidden reevaluation.
4. The planner or briefing runs when the dispatcher selects that route from the harness's
   capabilities. `EXEC high` implies no automatic briefing for new decisions. The
   planner receives all names from the effective MCP catalog, without a global cap, followed by a
   detailed hybrid top-k calculated after permission filtering. The catalog version is persisted
   with the plan, and each selected identifier is validated against it. The model tier and its
   `reasoning_effort` are two independent LLM profile settings: the pair is resolved and frozen in
   the run identity before entering the driver.
   The canonical scale is `none`, `low`, `medium`, `high`, `xhigh`, `max`; an absent value means
   “automatic.” The historical `minimal` value is normalized to `low` and is no longer emitted.
   Managed bridges and harnesses adapt this scale when their runtime uses different levels.
   A Task may nevertheless carry an explicit `reasoning_effort_override`, selected at Chat
   admission with `@effort`. This command directly implies `@task`, while `@task` alone retains
   the profile's reasoning effort. Both control tags are removed from visible text and their
   intent is carried in server metadata. The durable value takes precedence over every text level
   of the profile for constructing the objective, the dispatcher, the planner, the briefing, the
   synthesis, and the executor. It is inherited by planned or delegated descendants; it changes
   neither the `standard`/`high` execution effort nor specialized image, audio, or vector usage.
   Once `PLAN` is selected—automatically for multiple genuinely decomposable units or explicitly
   by the creator—the planner produces the complete tree in a single pass. It judges depth based
   on the complexity and verifiable components of the work, not on the number of files or
   deliverables: a single explicitly planned artifact can therefore become a group of sequential
   substeps that share and refine the same durable resource.
   This policy comes from the Markdown Param `ai.planner-system-prompt`, also copied into the
   Planner datasets in the Lab. The server separately adds the effective limits and the
   clarification-cycle contract; these safeguards are not experimental text.
   Each text mechanism reads its shared level from the agent's single effective profile:
   `ultra-low` for Dream, `low` for the dispatcher and rapid conversation, `standard` for the
   briefing, executor, and Goal tracking, and `high` for the high executor, planner, and Lab.
   `Agent.profile_id = NULL` selects the current profile; a populated identifier selects only that
   profile, and an empty column consults no other profile. The planner's model is reused for its
   final synthesis.
5. The registered providers compose the session, shared context, and their metadata. Messenger
   context is frozen at the position of the triggering message and inherited by every plan leaf;
   more recent messages therefore cannot retroactively modify an execution that has already been
   admitted. The canonical journal remains the source of truth. A Task originating from the
   conversational control plane retains the triggering message and its server metadata in
   `Task.data`, but no longer duplicates the complete history in `Task.messages`. If admission has
   already produced a standalone objective, the dispatcher receives that label and objective
   directly; providers no longer reread the Messenger, Memory, or historical continuity session
   consumed by that call. Room and interlocutor context remains deterministic in `Task.data` and
   `messaging_context`, while the Working Set and contributions from the plan, briefing, and
   harness may still enrich the current work. For other Tasks, the Memory provider receives
   structured identifiers so that a name included in the request can never serve as an identity
   boundary. For a human Task, recall combines nonconversational memories and those of the
   current contact while excluding those of other contacts; the Topic assigned to the Task is
   deliberately ignored as a hard boundary, but recall may infer an additive thematic prior from
   the request. Contact labels do not dilute the semantic request. The automatic brief retains at
   most one `core`, then directly injects the already merged bounded top-k from lexical, vector,
   and graph ranks, without a second absolute threshold.
   A local failure is recorded but does not block the Task. The Working Set provider additionally
   reads the root Task registry and injects the exact references of active documents, files,
   recipients, and receipts; all leaves of the same plan therefore see the same working state.

   Outside admission with a standalone objective, providers also publish structured
   nonconversational candidates for a human Messenger origin. The composer deduplicates, ranks,
   and bounds them, merges resources sharing the same canonical URI, then freezes one capsule per
   exact contact on the root. It brings together recent Tasks, resources from their Working Sets,
   and memories sealed to the contact, never filtering by Topic. Messenger history remains the
   distinct native projection, and its messages do not enter this capsule. Children and retries
   reread the manifest; only the current Working Set continues to evolve. Without a proven
   contact, the collective room is not used as a fallback. A direct conversation, including a
   real-time audio session, has no root Task in which to freeze a capsule: providers then search
   recent documents from completed Tasks and rounds for that agent and contact, render their
   `document://` URIs in the session's continuity section, and exclude temporary files and
   unverified free text. Related Tasks presented to the controller retain all active or upcoming
   entries, human pauses no older than 24 hours, and the two most recent terminal ones if they are
   less than an hour old. Each exposes its local creation date and `state_since`, based on the
   latest update with creation as fallback, with an objective limited to 250 characters. The
   prompt distinguishes this `Continuity context` section from durable recall rendered under
   `Long-term memory`.
   The catalog of assigned Processes follows a separate rule: all are injected up to ten; beyond
   that, exactly the ten most relevant to the current request are retained through multilingual
   semantic ranking with lexical fallback, without a threshold. A matching Process has absolute
   priority during Task admission.
6. The resolver freezes the model, target, effective capabilities, limits, trace context, and
   `AgentRunContext` in the `AgentRunRequest`. The canonical agent snapshot—name, gender,
   position, personality, and job description—is rendered in the Task system prompt foundation.
   It governs, in particular, style, writing choices, author, and any explicit signature
   preferences for produced content. The facade binds the logical `run_id` to the current
   attempt, then validates its serializable, secret-free `AgentRunEnvelopeV1` projection. This
   envelope carries the complete system prompt to network harnesses; Internal and Hermes
   reconstruct the same tree from the same snapshot before their runtime additions.
   Progress, checkpoint, and event-projection callbacks remain isolated in the local
   `AgentRunControl`.
   An `LLMCall` is a low-level inference trace, independent of the Harness concept. A direct
   conversational call carries its `ConversationRound` without a Task; a Task call carries the
   Task and its attempt; when that Task originates from the conversational control plane, the same
   call cumulatively retains the Task, attempt, and originating round. The round expresses
   conversational provenance, while the Task and its attempt remain the owners of execution and
   its accounting. The Harness receives only the Task and run identities; the LLM service derives
   the round again on the server, cross-checks the durable `ConversationTaskLink` against the
   `conversation_round_id` frozen in the Task data, and rejects any divergence. The `purpose` field
   distinguishes, in particular, `agent.dispatch`, `agent.briefing`, `agent.planning`, and
   `agent.exec`, independently of the concrete Harness.
7. The facade invokes the registered driver, normalizes its streamed or nonstreamed mode, enforces
   a single terminal result, and projects semantic events into the `TaskAttempt` timeline. Token
   deltas are not persisted. A shared safeguard observes reasoning blocks and generated text:
   beyond 30 consecutive repetitions of the same pattern without tool activity, it closes the
   stream and fails the run for degeneration without an automatic retry.
   The live Conversation and Task surfaces strictly share the same content contract: each
   interaction is an `AIMessage`, their accumulation is an `AIResult`, and the authoritative
   terminal result is also an `AIResult`. WebSocket envelopes may add ordered control signals
   (`started`, `reset`, `finished`), but never define a second message DTO, never reconstruct a
   false stream from terminal text, and never mix `thinking` blocks into the visible
   conversational response.
   A Galaris-owned Harness may activate the shared client's optional SSE extension. The Claude
   Agent runtime thus publishes tool completions and public reasoning blocks as `AIMessage` during
   the run, then the authoritative final response and its session identifier in the terminal
   result. Its model calls pass through the Galaris Anthropic gateway. DeepSeek consumes the
   notification callback from its pinned SDK: its actual `assistant/chunk` deltas, reasoning, and
   tool results replace the former content-free keepalives. Its model calls likewise pass through
   the Galaris gateways and populate correlated `LLMCall` records.
   The Codex runtime embeds the official Python SDK and its local App Server in a dedicated
   container. It translates its final response into Chat Completions chunks and its public
   reasoning comments or summaries into semantic `thinking` events, retained in the Task's
   reasoning steps. Public deltas are streamed immediately with a stable `stream_id` per block;
   live projections concatenate them without persisting a step for each fragment. No
   `agentMessage` delta is considered terminal before the end of the turn: the last final item
   becomes the response, and all its predecessors remain reasoning. Each App Server
   `itemId` + `summaryIndex` pair forms a distinct block; late completion never replaces an
   already observed fragment, and every divergence is added as a new block. It interrupts the
   turn if the client closes the stream, mounts the runtime's own persistent working directory,
   and projects skills into `CODEX_HOME`. Its Galaris MCP server is mandatory and authenticated
   with an agent-specific system token; canonical resources and memory therefore remain governed
   by Galaris. This token also authenticates the App Server's private Responses provider at
   `/api/llm/openai`. Codex receives the native model name frozen by `app.agent`, while the
   corresponding Galaris code is propagated in a correlated header: the gateway thus resolves
   exactly the `Agent Executor` model in standard mode or `Agent Executor high` in high mode of
   the effective profile, without a second resolution in the runtime. Each Responses request
   produces an `LLMCall` correlated with the run; its native usage and any provider cost are
   retained before falling back to configured pricing. The Codex runtime therefore no longer
   contacts ChatGPT authentication directly.
   The internal harness applies the same terminal invariant to Pydantic AI events: deltas
   preceding tools remain visible as progress, then the `AgentRunResultEvent.output` exactly
   replaces the final result. For a profile and model whose bridge declares a native Responses
   policy, it directly uses Pydantic AI's Responses adapter through Galaris's in-process proxy,
   without Chat Completions conversion. The policy selects the routed model profile and compatible
   extensions so that reasoning and tool calls are preserved without sending a field specific to
   another provider. Other models remain on the compatible Chat Completions adapter. Hermes
   retains `assistant.completed` as authoritative and now publishes the `thinking` blocks and
   tool completions restored from its session live.
8. The structured result is applied to the task contract, then the SQLAlchemy port persists the
   transition and produced data.
9. Terminal observers record only the necessary deterministic projections. No driver or Harness
   implicitly transforms terminal text into a Messenger send: it returns the `ExecutionResult`
   and retains only the room context required for explicitly called attachments, interactions,
   and tools. For a Task originating from a text round, `app.conversation` guarantees projection
   of the result into Messenger and skips it when the terminal result already contains proof of
   successful delivery. A direct Messenger Task without a conversational link must perform any
   requested send through an explicit tool. Searching for new memories in Tasks belongs to the
   opportunistic `app.dream` scanner and does not run on this path.
10. The scheduler closes the attempt, releases the lease, and optionally schedules the next step.

## Run Identity, Envelope, and Timeline

`AgentRunIdentityV1` distinguishes four levels that must not be merged: the durable Task, its
lease-bound attempt, the logical run retained during a compatible resumption, and the opaque
identifier possibly assigned by the runtime. Resuming the same objective with the same driver
retains the logical run; changing the driver creates a new identity.

`AgentRunEnvelopeV1` is the future transport boundary. It contains neither secret driver
configuration, nor a SQLAlchemy object, nor a Python callback, nor a host path. Resources are
referenced by canonical URI, and variable fields are bounded. `AgentRunRequest` remains the local
contract so that current drivers retain their control plane without accidentally making it
transportable.

The durable timeline is a bounded projection in `TaskAttempt.data`. It retains identifiers,
sequence, event type, tool summaries, and the compact terminal result, with normalized usage when
available. The `ExecutionResult` carried by the Task remains the complete source of truth; a
timeline projection error never turns a successful external effect into a replayable failure.

## Checkpoints, Effects, and Concurrency

Internal checkpoint version 3 logs each call before execution and then its result. Unknown tools
are considered non-idempotent and exclusive. Standard MCP annotations
`readOnlyHint` and `idempotentHint` from an external server supplement the native tool policy,
without ever making a tool marked destructive replayable. Only tools whose contract explicitly
attests to a read or idempotent operation may be retried after interruption; only those marked
`safe` may share a bounded concurrency window. A non-idempotent call left `started` becomes
`outcome_unknown` and requires a visible resolution rather than automatic replay.
A previous conservative classification may be repaired on resumption when the current native
contract now explicitly declares the same tool `read` or `idempotent`; the interrupted call is
then closed as retryable. A tool that remains unknown or non-idempotent stays blocked.

The execution barrier allows multiple safe readers to progress together, but gives priority to a
waiting writer and returns results to the model in invocation order. This policy remains
deliberately pessimistic: declaring a function safe is a contract decision, not an inference from
its name.

Before each model request, history is compacted according to the resolved context window.
Tool call/return pairs remain atomic units, and the most recent elements are retained within the
remaining budget. The JSON arguments of a tool call remain structurally valid: compaction bounds
their large values without removing required fields. The historical Chat adapter locally
summarizes large old results with their fingerprint. When the provider policy permits it
(OpenAI/Codex and xAI), the Responses adapter calls `/responses/compact` on the old prefix,
retains the last two atomic blocks, and reinjects the encrypted element. Other Responses policies
use local bounding. Storage, summarization, context, and reasoning replay options are likewise
specific to each policy. If native compaction fails, local bounding remains the explicit fallback.

## Usage and Cost

Drivers report a shared `AgentUsage`: input and output tokens, cache, reasoning, requests, tool
calls, and cost. Each dimension carries an explicit quality. The internal harness normalizes
Pydantic AI usage; Hermes aggregates its correlated LLM calls through the Galaris gateway and
marks missing dimensions as `partial` or `unknown`. The shared client for managed network
harnesses similarly aggregates the `LLMCall` records for the `run_id` used by Claude Agent,
DeepSeek, and Codex;
runtime-specific telemetry is used only as a fallback when no correlated call exists. The exact
cost reported by the provider takes precedence over token-based estimation, preserving dynamic or
tiered pricing when exposed.

Each `LLMCall` separately retains the decoded provider body in `raw_response` for an ordinary
response. A Responses stream retains only the JSON value of the SSE `data` field from its terminal
event (`response.completed`, `response.failed`, `response.incomplete`, or `error`), without the
`event:` and `data:` prefixes or the SSE separator. This value carries the complete final state
without repeating deltas or intermediate envelopes; a Chat Completions stream, which does not
always have an autonomous final object, retains all observed SSE lines in their original order.
This audit trace is captured before normalization into text, reasoning, and tool calls; it is
neither reconstructed from these projections nor used as the Task's business result.

A planned leaf that finishes with a result beginning with `BLOCKED:` gives the planner one
recovery opportunity. It receives the cause, acquired results, remaining steps, and effective
catalog, then chooses either to insert a safe, materially different action or to stop the plan.
A newly blocked leaf never triggers a second replanning. Unexecuted steps are marked as skipped in
their metadata and excluded from the synthesis; terminal failure remains communicated through the
durable conversation link, or directly for legacy Messenger Tasks that do not have that link.

## Working Set and Deliverable Postconditions

The Working Set is a versioned registry stored in `Task.data["working_set"]` on the plan root. A
typed entry carries at least a stable role, a resource type, an exact reference, a state
(`active`, `superseded`, `stale`, or `failed`), and the producing Task. It copies neither a
document's content nor a file's bytes. A new active reference for the same role marks the old one
as `superseded` without deleting it; subtasks read and update their root's registry under a lock.

After the actual success of a native tool, `app.tools.resource_effects` promotes its effect into
this registry. The first document created receives the `primary_working_document` role; subsequent
creations each retain their URI and a reference role. Later steps must read or edit them by UUID.
File writes record the exact provider URI. A Messenger delivery or sharing upload separately
produces an `artifact` and a `delivery_receipt`; a textual success message is not sufficient
proof. A business error from a file, document, or Messenger tool must propagate as a tool error
and produces no active resource.
A mutation directly applied to the exact durable URI named by the objective, however, constitutes
the requested placement: it must not be artificially copied into Messenger. For a repository
manipulated through `console://`, a `console_exec` completed with exit code zero and containing
`git push` records a durable `git_remote` receipt; command text without a successful result never
qualifies as a receipt. The terminal guard correlates each produced source with its destination or
receipt: delivering another file, copying only to `console://`, or obtaining a nonzero exit code
does not satisfy the contract.

Each materialized leaf additionally carries `artifact_policy` (`none`, `intermediate`, or
`final`) and `delivery_policy` (`forbidden` or `required`), normalized by the server from the
plan's exact tools. An intermediate leaf receives no delivery tool, even if the runtime
spontaneously wants to publish its file. Only a leaf that explicitly declares a send or sharing
tool may produce the final artifact and its receipt. Messenger sending copies the file to the
destination provider without deleting its source.

The planner cannot finish a plan announced as successful if its deliverables require a document
without a primary document, if a produced file has no active final artifact, or if a Messenger-
originated Task has no delivery receipt. The action guard applies the same requirement to direct
executions that produce a file. Plan leaves retain explicit messaging tools, but their terminal
text is never sent automatically: only the root Task carries the automatic fallback delivery.
A separate progress message does not qualify as delivery of the result: the fallback is removed
only if the exact terminal text has already been successfully sent through Messenger.

If the latest work produced a verified file but stopped before any delivery call, the root retains
a `delivery_recovery` marker with the path, destination, and producing leaf. An explicit retry
reopens only that leaf, preserves its effect journal, and directly executes the single authorized
native tool with those verified arguments, without an LLM request. This deterministic execution
reuses the MCP authorization projection and effect record. A delivery already attempted without a
receipt remains ambiguous and is never blindly replayed. The terminal pass triggered by a budget or
no-progress guard is strictly tool-free and limited to one request: it reports persisted facts
without performing new work.

## Conversational Rounds and Real-Time Audio Sessions

Tool cards represent invocation updates rather than text fragments. `tool_call_external_id`
(together with the retry number when present), or otherwise `stream_id`, matches live events
with snapshots without concatenating or double-counting the result. Hermes preserves this
identity through session history and checkpoints. The terminal Task projection includes
AIMessages with bounded content and without arguments or structured results; its tool list is
authoritative, including for harnesses without invocation IDs. Distinct invocations of the
same tool remain separate cards even when their content is identical.
Hermes also publishes text and `thinking` blocks with a persisted identity and
`stream_mode="snapshot"`: their cumulative content replaces the block already received
over HTTP. The default `delta` mode appends only the incoming fragment. Terminal results
remove extra live copies of legacy reasoning blocks; the HTTP snapshot of a completed
Task applies the same reconciliation when the terminal event was missed.

Streaming preserves the structure `AIResult → AIMessage → fragments`. A `stream_id`
identifies a text or reasoning part: deltas extend that message, even when other messages
interleave, while HTTP and terminal snapshots replace its cumulative content without
duplicating it. The internal harness publishes reasoning from its first fragments and
preserves message identities when batching text over time. The conversation scheduler and
both voice engines use `ConversationRuntimeStream` to publish the same result to Chat.
Audio turns therefore publish their messages before speech synthesis completes. Each event
is ordered by round, attempt, and sequence; the client retains observed reasoning and rejects
events from older attempts. The stream remains ephemeral; the final trace and Messenger
messages provide persistence.
During a run, the activity API provides the current snapshot to recover from a reconnection
or a missing sequence. Slow publication coalesces subsequent fragments into a cumulative
snapshot without blocking generation. Every critical write checks the lease token,
including finalization after transport.
See [ADR 0062](../../../../project/decisions/0062-identified-message-streams.md).

A human Messenger message is linked directly to a round in its `Room` by `app.conversation`.
Its scheduler claims neither a Task nor an agent slot and launches a short round with the internal
Pydantic AI harness and the effective agent profile's `low` text level. An empty column is a
configuration error and does not fall back to the executor or current profile when the agent has a
personal profile. The Hermes driver is never used as a fallback. The toolset is a dedicated
projection: active connection, `Tool.conversation_enabled` flag, function declared `short` or
`deferred` for native functions, effective permissions, and runtime profile. An explicitly
checked external MCP connector is mounted with its current function states; unchecked functions
are not even resolved.

The conversational dispatcher profile responds directly to humans and arbitrates `EXEC`/`END`
for a message emitted by another AI. This `END` terminates only the conversational round without
a response; `EXEC` always launches the direct controller with `standard` effort. This profile
exposes neither `PLAN`, nor `high` effort, nor briefing. `END` is no longer part of the active
Task dispatcher contract, which is limited to `EXEC`/`BRIEFING`/`PLAN`. Neither structured output asks the
model for a justification: they contain only the routing fields that are needed and are capped at
256 tokens. The historical field on the durable decision remains reserved for locally produced
diagnostics and deterministic decisions.

The conversational system prompt is distinct from the executor's, but reuses its identity
contract: name, gender, position, personality, and job description. It adds the current temporal
and social context, the authorized native inventory, and the compact catalog of Processes
assigned to the agent. It separately renders the Tools from active connections reserved for Task
mode, without repeating those authorized in conversation, and prohibits inferring a lack of access
from this: if the request requires one of them, admission through `conversation_task_submit` is
mandatory. Its rules require an immediate response for short work; long work first launches a
matching Process with `conversation_process_start`, or otherwise creates a Task with
`conversation_task_submit`, without ever waiting for completion.

For a human, the dispatcher returns `EXEC standard` before loading any model and without
inference, on every text channel. The executor chooses tools and durable work admission.
The controller no longer judges a successful response: missing admission, missing tool activity,
or repeated wording never trigger another execution. Execution errors reach the scheduler,
whose retry budget and protections against duplicated effects remain applicable. `requires_action`
also disappears from Task dispatcher and Lab contracts. Internal and Hermes drivers accept a
successful result without subsequent action or artifact judgment; effect receipts and delivery
recovery retain their own contracts.
A directive containing `@task`, `@plan`, or `@effort`, regardless of its position in the message,
short-circuits the dispatcher and conversational runtime even earlier. In native Chat, these
controls are removed from the visible message and projected into metadata before admission;
tags still present on external transports are parsed deterministically, then the canonical
operation creates a Task linked to the round before its confirmation is published in the room.
The prompt proactively requires fresh wording in a single pass. For AI peers, the dispatcher
retains its loop limits and `EXEC`/`END` gate. It performs no validation retry: malformed
structured output immediately triggers its deterministic `END` fallback.
Every new root, including one requested by `conversation_task_submit`, nevertheless goes through a
dedicated structured call at the effective profile's `standard` level. This call directly
reconstructs the standalone `label` and `objective` from the canonical chronology, frozen turn,
Memory, continuity, related work, URLs, and attachments. Tool arguments are only hints, and
references absent from the context are rejected. Its system instruction is the administrable
Markdown Param `ai.task-objective-system-prompt`. The server separately injects the room,
interlocutor, and dispatch controls. It verifies idempotency before the call and round freshness
afterward; no intermediate object is persisted.
These directives never make the conversational controller plan: they use a deterministic `EXEC`
path, then call the canonical admission operation before any
conversational LLM runtime. On a durable Task, a message directive is a preference negotiated
after resolving the routes declared by `AgentDriverSpec.pipeline_policy`; it therefore cannot
activate a step that the driver does not expose. `@briefing` is currently unavailable because no
active driver exposes briefing. Only an explicit creation `forced_route` remains a strict
constraint.

Explicit stop commands and commands to resend an existing attachment are also deterministic
controls executed before the dispatcher and before the conversational model. Stopping targets
the most recent active Task already linked to the room; resending targets the canonical UUID of
the requested file. A dispatcher-model failure immediately applies the bounded fallback route:
`EXEC` for a human and `END` for an AI peer. Text emitted before a tool call remains in the
audit trace but is removed from the Messenger response; only the response produced after the last
successful effect is visible.

Option-based interactions follow the same separation. An exact number or alias is applied without
an LLM. An unrecognized free-form response continues the conversational flow with the pending
choices projected into its exact scope. The conversational model may then select only an option
persisted by `conversation_choice_resolve`; it must request clarification rather than infer
ambiguous consent. When the message redirects the work, it may reject the now-obsolete approval
and call `conversation_task_submit` with `AMEND_CURRENT` or `AMEND_QUEUED`. `app.task` remains the
sole owner of durable interruption and resumption.

The three executor system prompts—Task, text conversation, and voice—are built as ordered JSON
trees `galaris.system-prompt/v1`, then converted to Markdown by a single renderer at the model
boundary. Each tree ends with a `raw_markdown` node fed by the Param corresponding to the
executor. This suffix is never selected by an LLM: `ai.executor-system-prompt` covers Internal
and Hermes, the conversation Param covers text rounds, and the voice Param covers both the
pipeline and native realtime. The common rule separating immediate dialogue from background
action comes separately from `ai.conversation-action-policy`; it is injected into the
conversation and voice prompts and frozen in the corresponding Lab runs.
This policy classifies each requested result into four paths: direct response, small governed
conversational effect, assigned Process, or background Task. Bounded Memory operations, state
consultation, and explicitly exposed interaction resolution remain foreground operations; an
external effect corresponding to a Process retains absolute priority over a Task. The Process
catalog no longer repeats this arbitration in short prompts: it provides only the selected metadata,
while the conversational policy is its sole owner.

The three executors share a single `Untrusted data boundary` node placed before context data.
Memory headers and conversational rules no longer repeat this hierarchy. Short prompts also open
with a first-person declarative identity and add an embodiment reminder immediately before the
configurable suffix; this recency repetition is intentional and distinct from policy duplication.

In text and voice conversations, each native message exposes only a visible envelope
`[local ISO timestamp | author]`. Pydantic AI simultaneously retains its timestamp and
structured sender data for the trace; Hermes receives the same textual projection. The human/
assistant role remains that of the native protocol, and attachments remain in their original
message. Language, channel, room, current sender, location, and continuity state are rendered
once in the `Turn context` or `Call context` system node. Terminal cleanup still accepts legacy
cartridges and `<galaris_message_context>` for historical sessions.

Before the runtime call, the text controller also composes the shared context providers.
Governed memory recall is injected into the prompt, and its safe telemetry (query, count,
truncation, identifiers, and any error, without copying recalled content into metadata) is
retained in the `ExecutionResult`. Voice receives the same projection through its
`AgentRunRequest`. Monitoring therefore always displays a memory tab for both surfaces,
including when memory is disabled, empty, or not consulted. Technical labels such as
`Conversation — <agent>` are generic: the recall query uses the bounded user objective so that
it does not replace the current subject with the runtime name. The initial Task projection
filters older work by state and bounds each objective, without limiting the number of still-active
work items. The model may call `conversation_task_list` to find an older Task. This call remains
limited to root Tasks in the current conversational context, omits their large results, and
retains active Working Set references; `conversation_task_status` provides bounded detail by UUID.

Galaris imposes no output cap or cumulative token budget on Task, conversation, and voice
executors, or on specialized LLM mechanisms. An already assembled history or prompt must never
prevent a response because of an application bound. The physical context window and provider-
specific limits still apply. Dream mechanisms likewise do not add a Pydantic AI
`request_limit`: their validation retries remain bounded by the output contract or by their
explicit business loop. In their tracking, `attempts` counts claimed executions of the mechanism,
while correlated LLM requests are counted and displayed separately: one execution may contain
several. A text round, which must remain short and delegate substantive work, nevertheless has a
five-minute wall-clock timeout: it prevents a suspended runtime or tool from renewing its lease
indefinitely and blocking all subsequent room messages. Its scheduler renews the durable lease
during execution and also cancels the stream if the ownership token disappears; a single round
therefore cannot continue in two provider calls.
Each native MCP tool additionally has a wall-clock timeout bounded by
`TASK_TOOL_TIMEOUT_SECONDS` (300 seconds by default), shorter than the action inactivity timeout.
A suspended file provider or network call thus returns a recoverable tool error to the runtime
instead of immobilizing the entire Task. `TASK_ACTION_TIMEOUT_SECONDS` is a durable progress
watchdog: each checkpoint or semantic event resets it. Total duration is therefore not bounded,
and a Task may remain active for several days; only continuous absence of progress for the
configured duration ends the attempt with an explicit diagnostic.
When a provider stream is canceled, the `LLMCall` trace is first finalized as
`cancelled` within a cancellation-protected HTTP scope, then transports are closed with a
separate timeout; reconciliation of orphaned traces remains a safety net, not the nominal path.
The real-time runtime also interrupts significant prose repeated three times without action, so
that a looping model cannot keep a stream open indefinitely. At startup, the scheduler also closes
as `cancelled` any LLM trace still marked `running` while its round is already terminal. The
periodic job immediately applies the same rule to an `agent.exec` call whose Task is already
`SUCCESS` or `ERROR`.

A substantive request first compares recent Tasks in the same context. The controller explicitly
chooses to complete the same active deliverable, modify a deliverable still in the queue, create
an independent Task, or request clarification. The backend validates scope, revision, and
amendability. Creation returns its identifier without waiting; an amendment retains the UUID and
records an idempotent `TaskAmendment` row. This Task returns to the nominal flow above and
therefore uses its usual driver. It remains an execution mode of the same agentic identity and
fully retains its Messenger address: the planner, driver, approval interactions, and tools may
speak, ask a question, and publish the final result through the ordinary Task flow. The
conversation link serves lineage and tracking; it does not make the Task silent or duplicate its
output.

The controller admitting it always remains internal, including when the agent is configured with
Hermes; only the newly persisted Task then goes through normal resolution of its driver. The
conversation guard therefore modifies neither the `AgentDriver` contract nor the Hermes path.

An LLM call from the controller carries `agent_run_id` and `conversation_round_id`, with
`task_id=NULL`. The proxy therefore cannot assign it the active external Task heuristically. The
external Harness limit of one Task and the search for its single durable lease correlate its work
calls, including when the request reaches another backend worker.
The round also retains the normalized `ExecutionResult` of the internal harness (prompts, tool
trace, memory operations, cost, and terminal result). The visible projection available on request
to an authorized room participant exposes bounded reasoning, tool calls, and results after
credentials are removed; it never exposes the system prompt. It remains distinct from the
`LLMCall` records correlated with the round. An internal failed attempt also passes its partial
`ExecutionResult` to the scheduler: reasoning and tool messages, error, cost, and duration are
accumulated with those of the next attempt. After attempts are exhausted, the round exposes the
fallback response actually sent, remains marked as resolved failure, and retains failed LLM calls
separately.

A voice call is persisted by `app.voice` in a `VoiceConversationSession`; each of its processing
operations is a `ConversationRound`. For the STT → agent → TTS pipeline, the facade directly
builds an `AgentRunRequest(task_id=None)` with `ConversationRound.id` as `run_id` and
`conversation_round_id`, composes the same context providers, then freezes the `internal` driver
and the effective profile's conversation model (with the same no-fallback behavior as text).
The Pydantic AI executor uses the conversational prompt and exactly the `conversation_only`
projection; the configured Task driver, especially Hermes, and its full catalog never participate
in the round. The terminal stream contract remains unchanged. The scheduler, leases, and
`TaskAttempt` do not participate in this path.
The normalized terminal result is retained on the round and loaded on demand in monitoring,
without inflating the call list. `LLMCall` records remain a separate correlated projection.

`LLMCall` traces are audit and accounting records: deleting a Task never deletes them. It
immediately closes any calls still marked `running` as `cancelled`, without modifying usage,
token counters, cost, or partial output.
The presentation `prompt` field of an `agent.exec` call projects the Task's durable objective;
the exact messages sent to the provider remain separately in `request_messages`, including
technical reminders added by a Harness. Provider-reported cost takes priority over estimation
from configured pricing; a registered adapter in `app.llm.provider_facade` may normalize a
provider-specific format. `inference_cost` retains this comparable amount and `cost` represents
the billed amount. For a model marked `is_subscription`, each trace freezes this choice and
retains `inference_cost`, but its billed `cost` is zero. The dashboard sums the historical
`cost` of each trace; changing the current subscription never changes past months.
Its aggregate API cost remains based on `inference_cost`. Periodic
reconciliation applies the same treatment to traces without persisted activity beyond the
configured action timeout plus a finalization margin, and also serves as a safety net if the
process crashes between Task deletion and this closure.

Speaking during the response cancels the current run and ends the round as
`INTERRUPTED`, not as `Task.ERROR`. Its effective objective remains pending in the session and
is prefixed to the next transcript. Only a complete response clears this objective. The shared
prompt authorizes speech and bounded consultations. Any other action must launch an assigned
Process asynchronously through `conversation_process_start`, or a self-contained Task through
`conversation_task_submit`; the conversational runtime never performs this action directly.

The `realtime` voice mode does not split audio into text executions. `app.agent` composes the
identity, shared prompt, and context providers once in a `RealtimeAgentContext`. `app.voice` then
opens a session through the provider contract of `app.llm.provider_facade`; the concrete bridge
translates only the remote protocol.

The session receives only the necessary bounded conversational functions: memory search, listing,
creation, amendment, and reading of a Task, discovery/reading of assigned Processes, and
asynchronous launching of a Process. The control names (`conversation_task_list`,
`conversation_task_submit`, `conversation_task_status`, `conversation_process_start`) and the
action policy are the same as for the pipeline. `conversation_task_submit` uses
`AgentTaskPort`, creates or amends the durable Task before returning its UUID, then wakes the
scheduler. Process functions go through the `app.process` facade. The provider model therefore
has no direct access to `app.task`, ORM models, or PostgreSQL.

The agent's single voice selector determines the architecture. A TTS resource uses the
STT → conversational executor → TTS pipeline. A native voice associated with a real-time model
opens an audio → audio session; no artificial transcript is created. Both variants retain the
same context, the same conversational policy, a tool surface bounded to conversations, and the
same voice-session persistence.

## Execution Matrix

| Driver | `standard` effort | `high` effort | Briefing |
|---|---|---|---|
| `internal` | Direct Pydantic AI execution | Direct Pydantic AI execution | never (disabled for evaluation) |
| `hermes` | Direct `/v1/runs` session | Direct `/v1/runs` session, `high` model | never |

The mechanism, its contracts, historical results, and Lab benchmarks remain present, but the
internal driver's static policy no longer routes new Tasks to `BRIEFING`.

The internal constant `HERMES_HIGH_KANBAN_ENABLED` is currently disabled. It is neither an
environment parameter nor an administrable parameter: new Hermes `standard` and `high`
executions therefore both use the direct runtime. The Kanban code remains isolated without an
active management backend, and recovery of its function calls from `LLMCall.tool_calls` is
inactive; the direct path relies on the Hermes stream and persistent session.

The PostgreSQL Task remains authoritative for the lease, attempts, and final state. A card
created before this deactivation remains a subordinate runtime handle. It is never converted
into a direct run at the risk of replaying its effects, but its former shared transport has no
longer been available since ADR 0058, and resumption fails explicitly.

## Error, Cancellation, and Resumption

- A retryable error schedules `next_attempt_at` and preserves the resumption phase.
- A transport failure during the initial decomposition of a plan has produced neither a child nor
  an effect: the planner therefore lets the scheduler apply its bounded network retries. An
  already aggregated plan result, by contrast, remains terminal and is never replayed.
- An expired lease makes an action recoverable after the worker stops.
- A run whose objective was replaced during execution is published as `cancelled` and feeds
  neither incidents nor failure counters.
- `cancel_requested` is durable; the driver's cancellation capability must be declared.
- The internal harness records every active run under its `run_id` and `task_id`.
  A cancellation requested from the driver uses the Pydantic AI `CancellationToken`; a Task pause
  or lease loss may retain its external asyncio cancellation. In both cases, the runtime
  retrieves the run's detached history, persists an `interrupted` checkpoint, interrupts the
  current provider request and MCP call, stops the active console command, then closes all
  registered resources. Resumption provides this history to Pydantic AI, which repairs incomplete
  tool calls before the next turn; the Galaris effects journal remains solely authoritative for
  deciding whether resumption is safe.
- The internal harness accepts parallel tool calls and bounds them to the run limit.
  The central MCP wrapper gives each native tool its own short SQLAlchemy session; the MCP
  function and its services retrieve it only with `get_db()`. Checkpoints and events are locked
  in journal order and then persisted in an independent transaction. A local failure therefore
  rolls back without invalidating another tool's session or the Task's durable transaction.
  Tools declared `exclusive` remain barriers, while only tools explicitly marked `safe` execute
  simultaneously. The Task scheduler and conversation controller sequential sessions remain
  available during runtime initialization (catalog, model, context), then their transaction is
  released before the first model request; no parallel branch uses them.
- Three identical consecutive failure results for the same tool and arguments interrupt the
  internal run: the model cannot turn a deterministic error into a loop of thousands of calls. An
  invalid skill-resource read additionally uses the Pydantic AI retry protocol with at most two
  retries and provides the list of paths that actually exist.
- Three identical consecutive successes without progress for the same tool and arguments also
  interrupt exploration. For `file_create`, the signature ignores generated content and compares
  the path and name to prevent a series of equivalent new drafts. The runtime then grants one
  bounded finalization from the history already captured; if it succeeds, the produced work
  remains deliverable instead of ending in failure.
- A provider response ending with `length` or `content_filter` is an incomplete result and
  therefore a failure. Its partial text remains observable in the trace but is never delivered
  as a terminal Messenger response.
- Before an internal tool call, a durable checkpoint marks the effect `started`. Its result and
  Pydantic AI history make the checkpoint resumable after it changes to `completed`, or to
  `failed` for a proven rejection before effects. `ModelRetry` alone proves no such rejection:
  a timeout may follow a mutation. Native rejection evidence is tied to the operation UUID.
  Historical structured validation errors can repair matching calls; text errors are insufficient.
  Resumption reinjects this history and serves already journaled results without calling the tool
  again. An effect left `started` must first be reconciled; without a receipt it remains blocked.
  Console helper v2 retrieves receipts using the UUID persisted before dispatch on the same SSH
  target. Manual retries retain the journal, and stale or expired attempts cannot write checkpoints.
  Each attempt archives its latest checkpoint. Unanswered tool arguments are never compacted.
  See [ADR 0093](../../../../project/decisions/0093-tool-outcome-evidence-and-console-recovery.md).
- Fallback Messenger delivery, executed outside MCP, follows the same protocol. After durable
  acknowledgment, resumption returns the terminal result directly without calling the model or
  resending the message.
- Hermes resumption follows the checkpoint strategy. Historical checkpoints without a strategy
  remain direct runs; an existing Kanban checkpoint is neither recreated nor converted and fails
  explicitly because its management transport is no longer available.
- Cancellation of a direct Hermes run stops `/v1/runs/{id}`. Cancellation of a Kanban run reclaims
  the worker and then archives its card to prevent new distribution.
- `Task.paused` and pause reasons suspend scheduling without replacing the phase.
- `PAUSE` remains a legacy PostgreSQL value and must not be reused.
- Expected coordination suspends progress and then returns through the explicit
  `RESUME_COLLABORATION` event, without replaying tools that have already run.

## Entry Points to Read

- Contracts: `back/app/agent/contracts.py`, `task_port.py`.
- Orchestration: `back/app/agent/facade.py`, `dispatcher.py`, `planner_service.py`,
  `briefing_service.py`, `model_resolver.py`.
- Internal harness: `back/app/harness/driver.py`, `executor.py`, `run_control.py`,
  `checkpoint.py`.
- Tool discovery: `back/app/tools/catalog.py`, `tool_search_service.py`, and
  `back/app/harness/mcp_toolset.py`.
- Persistence: `back/app/task/agent_adapter.py`, `workflow.py`, `scheduler.py`, `models.py`.
- Boundary tests: `back/app/agent/tests/test_architecture.py`.
- Context and observers: `back/app/agent/context.py`, `observers.py`, and
  [memory flow](memory.md).
- Voice conversation: `back/app/voice/conversation_service.py`, `engine.py`,
  `realtime_engine.py`, and `session.py`.
- Text conversation: `back/app/conversation/`, `back/app/harness/conversation.py`, and
  [Messenger flow](messaging.md).
