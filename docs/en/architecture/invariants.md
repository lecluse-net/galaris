<p align="right"><a href="../../fr/architecture/invariants.md">Français</a> · <strong>English</strong></p>

# Architecture Invariants

These invariants reduce the ambiguities that are most costly during diagnosis or modification. They describe the current runtime; an evolution must change the contract, tests, and this documentation together.

| ID | Invariant | Primary authority |
|---|---|---|
| INV-01 | PostgreSQL is the durable source of tasks, goals, processes, and business logs. | SQLAlchemy models and services |
| INV-02 | `back/core` never depends on `app` or `bridge`. | `architecture_check.py` |
| INV-03 | Domains communicate through a public package, `contracts`, `facade`, `interface`, or port. | AST tests and reviews |
| INV-04 | `app.agent` orchestrates; `app.task` persists and schedules, with no direct reverse dependency. | `AgentTaskPort` and agent tests |
| INV-05 | The driver, policy, and model of a run are fixed before the runtime call. | `app.agent` contracts |
| INV-06 | An agentic stream has exactly one terminal result and nothing after it. | Streaming facade and tests |
| INV-07 | A scheduler job is protected by a lease and audited by a durable attempt. | `Task`, `TaskAttempt` |
| INV-08 | All conversational transports converge on `app.messenger`. | `Messenger`, `BridgeSpec`, `dispatch_incoming` |
| INV-09 | Durable deduplication of a message includes the connection, remote identifier, and direction. | Messenger journal constraint |
| INV-10 | Process transitions are monotonic; a terminal state does not reopen. | `process_service.TRANSITIONS` |
| INV-11 | A temporary path materialized by the server is bounded, cleaned up, and never becomes a URI. `console://` is the only visible local filesystem, and only with an active console. | `app.file_share` transports |
| INV-12 | `core.dbadmin` converges the entire PostgreSQL `public` schema from the models with encapsulated Atlas; no other schema or Alembic migration coexists within this scope. | `core.dbadmin`, `make update`, `make sync-db` |
| INV-13 | The backend enforces RBAC; frontend navigation is only a representation. | Routers and access tests |
| INV-14 | Every visible string maintains English/French parity. | `make typecheck` i18n checks |
| INV-15 | Any tool that exchanges a file receives and returns an `app.file_share` URI; a local need is satisfied by bounded, cleaned-up temporary materialization, without imposing a persistent copy on the caller. | `resource_service.materialize_resource`, image/audio/Messenger tools |
| INV-16 | A plan describes an intention until its status and the code prove its delivery. | `project/plans/README.md` |
| INV-17 | Configurable functional settings use `params` as their durable source; `.env` remains reserved for bootstrap and infrastructure. | `core.params`, ADR 0005 |
| INV-18 | Every registered root runtime loop is supervised without moving its business state outside its domain; only a critical failure blocks readiness. | `core.runtime`, lifespan, and health tests |
| INV-19 | A cursor-based listener advances its durable acknowledgment only after complete batch admission; a restart replays from the last confirmed cursor and relies on canonical deduplication. | `app.messenger.journal`, listeners, and bridge tests |
| INV-20 | A voice turn is a conversational entity, not a Task; the pipeline uses the internal harness, model, and tool projection of conversation mode, while native real-time retains the same bounded policy. A barge-in marks it `INTERRUPTED` and defers its durable objective to the next turn. | `app.voice`, `app.agent` facade, and `app.harness.conversation` controller |
| INV-21 | Dream enrichments are sequential, idempotent, and preemptible; they do not pass through `app.agent`, a driver, or MCP. Deterministic link reconciliation belongs to the Memory worker and appears neither in receipts nor in the Dream gauge. | `app.dream`, `app.memory.automation`, `DreamReceipt`, and Voice guard |
| INV-22 | The social address of a human account is `(messaging_id, user_id)` with the bridge code and exact native identifier, except for Mail, whose validated RFC address is normalized case-insensitively. Each strong address and each `galaris_user_id` resolves to a private Memory contact per agent; only this proven user link or an explicit administrative merge can unite multiple channels. The merge atomically repoints scopes, links, messages, rounds, and Tasks before forgetting the duplicate. Administrative forgetting erases sealed memories, clears these references, then purges the contact and its identities; a future observation starts from a new contact. Connection, room, and message remain technical routes or events and never enter this identity. | `app.messenger.contact_memory`, `app.memory.contact_directory`, `app.contact`, and merge/forgetting tests |
| INV-23 | Memory links derived from provenance link a memory to its Topic and, for a conversational source, to its exact contact. They remain bounded and idempotent and never modify the ACLs of the private memory. | `app.memory.link_reconciliation`, Topic/contact scopes, and reconciliation tests |
| INV-24 | A Process projection never contains the input or raw snapshot; only an assigned definition and a successful, sanitized, bounded output become source-managed private memories. | `app.memory.process_projection`, Process sanitizer, and projection tests |
| INV-25 | A working document is a `document/working` memory node, private upon creation and modified through atomic revisions. Only its owner manages grants and forgetting; collaborators access only bounded passages and write only with an explicit grant. | `app.memory.document_service`, MCP Document tools, and integration tests |
| INV-26 | Semantic tool discovery ranks only the already-filtered effective MCP catalog. The planner retains all authorized names; an index or top-k grants no permission and never hides the exhaustive manifest. A full reconciliation prunes the index only when all sources have responded. | `app.tools.catalog`, `tool_search_service`, `catalog_refresh_service`, planner, and internal toolset |
| INV-27 | A self-learned skill derives only from observable, bounded, redacted evidence. It belongs to an agent in the dedicated `learned_skills` and `learned_skill_evidences` tables, receives idempotent positive or negative reinforcements, and is injected only after confirmation by the configured number of distinct Tasks and crossing the score threshold. Dream also traverses terminal history, one Task per pass. Learning writes no Memory node. | `app.dream.outcome_evidence`, `skill.learn_task_outcome`, `app.skill.learning_service`, and ADR 0047 |
| INV-28 | Every executor system prompt derives from an ordered JSON tree rendered in Markdown by the common boundary. Its administrable suffix is the last node, depends on the executor, and never on the LLM. Conversational action policy is a shared Param between text and voice; a Lab run freezes the effective values and rendering. | `app.agent.prompt_tree`, `app.agent.executor_prompts`, `core.params`, `app.lab`, and ADR 0023 |
| INV-29 | A new conversational instruction explicitly arbitrates between creation and amendment. An amendment preserves the UUID, verifies scope and revision, rejects unsafe active structures, and produces an idempotent audit before resumption. `WAITING` and `PAUSED` are operational projections, never persisted phases. | `TaskAmendment`, `app.task.operational_state`, Conversation tools, and ADR 0025 |
| INV-30 | The implicit context of a human Task is selected by canonical contact, never by Topic or a room alone. Its bounded manifest is frozen at the root before dispatch and shared by the entire plan; only the current Working Set remains dynamic. Without a proven contact, no collective history is injected. | `app.agent.context`, Messenger/Memory/Task providers, and ADR 0032 |
| INV-31 | Every file resource exchanged between domains, tools, or steps has a canonical URI resolved by `app.file_share`. The external scheme is the connected Tool code; native protocols and schemes are reserved, relative paths are rejected, and no URI bypasses ACLs or SSRF validation. | `app.file_share`, Working Set, and ADR 0046 |
| INV-32 | An effective connection parameter follows a single cascade: imposed global value, otherwise non-empty local override, otherwise non-empty global value. Secrets remain encrypted, and synchronization of an integrated Tool never replaces its administered global values. | `app.tools.global_params`, `app.connection.connection_service`, and ADR 0035 |
| INV-33 | The host harness manager knows no runtime: it manages Compose instances, bounded actions, and their files. Images, configuration, CLI, and specific APIs remain in `back/bridge/<runtime>`. | `harness_manager`, `back/bridge/hermes`, and ADR 0038 |
| INV-34 | Inter-domain dependencies remain below the declared ceilings; no new private import or new or expanded cycle is admitted without an explicit reduction of the backend and frontend baselines. | `back/architecture.toml`, `back/architecture-baseline.json`, `front/architecture-baseline.json`, `architecture_check.py` |
| INV-35 | Every agentic stream is interrupted and fails without automatic retry when the same reasoning or generated-text pattern repeats more than 30 consecutive times without tool activity. | `app.agent.reasoning_guard`, `app.agent` facade, and `app.task` scheduler |
| INV-36 | A prompt-type Param follows its default while its durable value remains `NULL`. A customization retains the fingerprint of the localized default bundle on which it is based; DbAdmin advances only followers, and the administrator explicitly resolves any newer default without overwriting at startup. | `core.params`, `PromptSettingEditor` component, and ADR 0048 |
| INV-37 | An application service, called facade, or MCP function exclusively consumes the contextual session with `get_db()`. Only audited autonomous boundaries—special request, scheduler/worker, listener, detached callback, runtime, or CLI/infrastructure—open a transaction with `get_db_session()`; no SQLAlchemy session is shared between concurrent branches, and long-lived MCP/WebSocket channels do not inherit the HTTP session. | `core.database`, central MCP wrapper, and session-boundary AST test |

## Persistence and concurrency

In-memory caches, registries, and listeners accelerate or connect the runtime; they do not replace durable rows. Recovery after a crash relies on statuses, leases, attempts, cursors, idempotency keys, and events recorded in PostgreSQL.

Any write that may be replayed must have a stable identity or a uniqueness constraint. A late external notification must not regress delivery or reopen a terminal process.

## Runtime supervision

The generic supervisor knows only the lifecycle and current state of root tasks. It may restart the scheduler or listener supervisors, but it never modifies a task, message, call, or business process. Before a restart, it always calls the domain's shutdown so that the domain cancels and waits for its children.

Liveness describes the HTTP process. Readiness adds PostgreSQL and critical components. An unavailable optional bridge produces a `degraded` state, not global unavailability. Public responses contain neither exception messages, configuration, nor secrets.

## Agentic boundaries

`app.task.agent_adapter` registers the durable port consumed by `app.agent`. The scheduler may call the agentic facade, but agentic contracts and drivers do not know the SQLAlchemy `Task` model. The internal Pydantic AI harness remains in `app.harness`, and Hermes in `bridge.hermes`.

A controlled exception exists for `RESUME_COLLABORATION`: it may reopen the phase of a completed task in order to aggregate coordination children without replaying effects that have already succeeded. This is not a general authorization to rewrite a terminal state.

Reads intended for agents supplement the durable phase with derived operational state. A wait exposes its nature, question, interlocutor, and deadline from coordination children; a human pause remains distinct. Conversational policy compares these candidates before any creation. Amending the same deliverable goes through `AgentTaskPort`, preserves the root Task, writes `TaskAmendment`, and goes through `CREATE` again when the dispatcher must reevaluate the objective. Materialized plans, active delegated children, and terminal Tasks are never silently rewritten.

## Messaging and file boundaries

A bridge authenticates and translates its protocol. The Messenger domain logs, deduplicates, and triggers the common workflow. Attachments retain the original Tool URI; bounded temporary materialization never changes their identity.

The cross-domain reference is a canonical URI.
`<tool.code>://room-provider/attachment-uuid` designates a persisted attachment. Relative paths and old implicit local schemes are rejected. Tool codes carrying Messenger or file-share serve directly as schemes and cannot impersonate either `http`/`https` or a native scheme. Only the public `app.file_share` facade resolves them.

After resolving the kind and AI identity, Messenger projects only human senders through the public Memory facade. This dependency exists in no conversational bridge. The projection is private per agent, idempotent, and fail-open; the canonical journal allows it to be replayed.

Persistent voice calls belong to `app.voice`. Each processing operation is a `ConversationRound` invoked with `task_id=None`; its `conversation_round_id` ensures LLM correlation. A new utterance cancels the turn's computation and audio playback, but never produces a `Task.ERROR` status. The interrupted objective remains in the session until a complete response.

## Verification

```bash
make project-context-check
make architecture-check
make typecheck
```

Add an AST test when an invariant concerns a dependency, a matrix test for a state machine, and a PostgreSQL integration test for a persistence guarantee.
