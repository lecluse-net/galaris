<p align="right"><a href="../../../fr/architecture/flows/dream.md">Français</a> · <strong>English</strong></p>

# Dream Flow

`app.dream` runs enrichments that can wait for a period of inactivity. It does not create
agentic Tasks and never goes through a driver.

```text
runtime supervisor
       │
       ▼
app.dream scheduler ──► guards Voice + Task activity
       │                         │ activity
       │                         └──────────► waiting / preemption
       ▼
ordered mechanisms, one at a time
       │
       ├─► Topic classification of messages, Voice turns, Tasks, and Voice sessions
       ├─► Memory extraction from Tasks, text rounds, and Voice turns
       ├─► learning based on observable Task outcomes
       ├─► deterministic projection of Processes
       ├─► deterministic Memory-driven detection and maintenance
       ├─► triggering of Memory link reconciliation
       └─► no destructive inactivity-based forgetting
```

## Cycle

A wake-up calls the mechanisms in registration order. Each claims at most one
subject. A mechanism without a subject makes no LLM call. New priority activity stops
the sequence. The start of a Voice conversation also cancels the current subtask.

Dream does not infer inactivity from an approximate timeout: it reads the presence of active calls in
`app.voice` and the existence of runnable or leased agentic work through the public
`app.task` surface. The worker is non-critical for readiness.

## Receipt and resumption

`dream_receipts` is the durable source of coverage. A receipt's identity is
`(mechanism_key, subject_kind, subject_id)`:

- no row: subject never examined by this mechanism;
- `running`: lease in progress, recoverable after expiration;
- `retry`: deferred retry;
- `success`, `result_count=0`: subject examined without a result;
- `success`, `result_count>0`: effects applied;
- `error`: retry budget exhausted.

Mechanism identifiers are stable and contain no version. A code change
does not implicitly rescan subjects already processed. When reprocessing is necessary, it
must be triggered by a new subject identity or an explicit business operation.

The prepared output is retained as JSON before it is applied. Effects use idempotency keys
derived from the receipt and their position. An interruption between two writes therefore
does not request a new decision from the model.

## Classification and extraction

The mechanisms `topic.classify_message`, `topic.classify_task`, and
`topic.classify_voice_session` assign activities to a global topic folder. The
messages cover both text and voice conversations. Their
creation policy is checkpointed before application and respects
`DREAM_TOPIC_CREATION_MODE`.

The mechanisms `memory.extract_task` and `memory.extract_conversation_round` wait for a Topic and,
for text and voice conversational sources, the
exact contact. They use a single structured decision `CREATE`, `LINK`, or `IGNORE`, without a tool or
MCP. Each acquisition retains the receipt and the mechanism's stable key, without version
metadata.

`skill.learn_task_outcome` transforms only bounded, observable evidence into reusable procedures
specific to the agent. CREATE, REINFORCE, REVISE, and WEAKEN feed the dedicated tables
`learned_skills` and `learned_skill_evidences`, never Memory. The evidence fingerprint is part of
the subject's identity: late-arriving material evidence creates a new subject, while an identical
rescan remains ineffective. All terminal Tasks are eligible, including those completed
before learning was enabled; Dream processes them from oldest to newest,
one per pass. `observe` mode retains the checkpointed proposal; `learn` can then
apply it without a second LLM call.

The smoothed score `(positive + 1) / (positive + negative + 2)` makes reinforcement and
weakening visible. A first occurrence creates only a candidate. An unsuspended
procedure is added to the agent's ordinary skills only if `DREAM_SKILL_MIN_EVIDENCE` distinct
Tasks have confirmed the same repeated action and it reaches `DREAM_SKILL_ACTIVATION_SCORE`,
within `DREAM_SKILL_MAX_ACTIVE`. The repetition threshold is 3 by default. Its file
projection under `.learned/` is rebuilt from the database and never joins the index of
administered skills.

## Deterministic effects

`memory.project_process` projects eligible Process definitions and results. After each successful Dream operation, the
scheduler registers a targeted reconciliation in `app.memory.automation` for each affected Memory
node. Maintenance of `topic_contains`, `contact_contains`, `cycle_of`, `result_of`, and
topic suggestions is therefore no longer a Dream mechanism: it has neither a receipt, nor a
Dream gauge, nor a model call. `MEMORY_LINK_RECONCILIATION_TRIGGER_MODE` allows this
targeted hook to be retained or disabled. A global sweep can also be registered according to the
`MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS` interval; it always waits until Tasks and Voice are inactive.
The Dream preferences page displays the next due time and allows an immediate manual launch,
executed within the HTTP request without waiting for inactivity.

Duplicate, contradiction, and aging policies belong to `app.memory`.
The Dream mechanism `memory.maintain_findings` executes them sequentially during inactivity:
Memory drives, Dream executes. It makes no generative LLM calls and reads only the
embeddings already calculated when a semantic comparison is necessary. Its receipts ensure
resumption and prevent reprocessing the same revision with the same policy; this high-volume
mechanical work is intentionally excluded from Dream gauges. Aging marks a memory as old without
deleting it from RAG.

## Operational monitoring

The read-only routes `/api/dream/overview` and `/api/dream/receipts` expose the scheduler state,
coverage, and paginated receipt history. The HTTP contract, filters, and
Dream page expose no mechanism version. Receipt details show its prepared output, its
cost, its attempts, and its latest error. These routes require `TASK_ACCESS`.

The page loads these projections when opened, then listens for `dream.update`
events from the authenticated websocket. Runtime transitions and terminal receipt changes
trigger a grouped refresh. Reconnection resynchronizes the complete projection.
This reading adds no worker and never wakes a Dream mechanism.

## Extension

A future mechanism implements `DreamMechanism`, provides a stable key, registers in the
ordered registry, and uses the same generic receipt. Subjects may be memories,
groups of memories, agents, or other durable objects. No new root worker should
be added.
