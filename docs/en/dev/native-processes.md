<p align="right"><a href="../../fr/dev/native-processes.md">Français</a> · <strong>English</strong></p>

# Native BPMN profiles and data contracts

## Resource ownership

Current BPMN is stored directly in `process_definitions.bpmn_xml`. Process owns its
revisions (`process_definition_revisions`) and access grants (`process_definition_grants`).
Creating, editing, sharing or restoring a definition never creates or modifies a Document.
Documents contain HTML and Datasets contain JSON. Launches freeze BPMN, graph and revision
without a Document reference.

The `app.process.native_definition_storage` DbAdmin action transfers former definitions,
revisions and grants in transactional batches. It detaches the former Document FK and
archives sources only after copying. Failure preserves the batch's sources; retries
never duplicate history or grants. The nullable legacy `document_id` field remains
reserved for migration recovery.

## Typed v2 profile

New definitions in the editor use `galaris.bpmn/v2`. Snapshots freeze their profile;
saving or converting a definition never changes an admitted run. Converting a v1
definition is explicit and initializes declaration lists for configuration.

The graph and each activity (`task`, `human_task`, `tool_call`, `rest`, `code`, `program`,
`call`) declare `inputs` and `outputs`, including empty lists. Each variable has `name`,
`type`, `nullable` and an optional typed `default`. Duplicate names, invalid default types
and null defaults for notnull variables fail at save time. Values use the envelope
`{"type":"int","value":7}`. Types are int, float, string, bool, Agent, File, User,
Document, array and object. Containers recursively retain each element's type.
Every type can represent null. An omitted value uses its default, else typed null if
nullable, else fails. Explicit null never uses a default. False, zero and empty values
are preserved; integers stay in the exact ±(2^53−1) range. The codec bounds size/depth,
rejects duplicate JSON keys and performs no implicit conversions.

The engine freezes local inputs, validates output before integration, and commits a
functional delta in `process_runs.data`, file links in `process_run_files` and its receipt
in `process_runs.execution_state` atomically. AI tasks submit ordinary JSON values with
`process_activity_complete(output={...}, message="...")`. The engine converts and validates
them against declared outputs, independently of the driver's final prose. Activities without
data outputs may finish with a natural message; historical typed JSON responses remain accepted.
Humans reply through messaging. Direct typed run data writes are rejected. Integration receipts support recovery without
reexecution, preserve disjoint updates and report conflicting writes to a variable.

`process_activity_question` asks the authenticated human launcher in the originating
conversation. The activity owns the wait; no auxiliary Task is created. The existing AI
Task is suspended for reason `input`, then resumes with the answer.
Resume context explicitly associates the question with its typed answer. Rephrasing a
question for the same variables returns the received answer without opening another wait;
a new stable `question_key` deliberately requests a new answer and stays identical on retries.
Different variables allow additional
information to be collected within the same activity.
Earlier answers remain activity receipts: retrying an old key or repeating an identical
reply never changes the next question. Local history is bounded to 2 MB and is not forwarded
to successor activities. Discovery, delivery and withdrawal check the question identity
as well as the attempt identity. The process launcher owns human exchanges in its originating
conversation even when another agent executes the activity; the reply wakes that executor's Task.
`conversation_process_respond` accepts ordinary JSON values such as `{"age": 27}`;
Conversation validates and converts them to typed values before checking file access.
`typed_values: true` accepts historical envelopes, including objects; an ordinary JSON object
containing `type` and `value` otherwise remains a business object.
The answer and Messenger receipt commit atomically, including duplicates and answers arriving
before the AI turn finishes. User holds remain effective. Questions are
correlated and idempotent; the activity completes after resumption and result submission.
Read-only context includes run data even without declared local inputs. Unused
actor lanes do not block admission.
Historical inert wait Tasks are retired when observing the run or recording a reply;
the question and its reference are preserved without a new execution.

After a successful turn, finalization preserves the identity and checkpoint cleanup performed
by the Agent facade. Refreshing concurrent replies applies local changes to fresh data instead
of restoring the old checkpoint. The human answer starts a new Harness turn on the same Task;
interrupted or authorization-waiting checkpoints retain their recovery policy and receipts.
After transport loss, observing the old turn's result does not mean that turn read a reply
received meanwhile. The input marker retains the identity of the turn that asked the question;
reconciling it leaves a fresh turn ready to use the reply. An explicitly submitted result
after consuming the answer may complete within the same turn. Asynchronously withdrawing an
old request cannot close the next one, including after transport failure and rollback.
At turn admission, the Task reads current data and revision under its lease before applying
local changes. A reply arriving during context preparation therefore does not cause a version
conflict; a concurrent human hold prevents the turn from starting.

`config.input_mapping` prepares local names with `{"$expr":"data.source"}` leaves.
MCP and REST explicitly adapt values to external contracts. `external_output` maps the
raw response (`result`) to declared names. `external_output_typed: true` explicitly
selects already typed envelopes; ordinary business objects containing `type` and `value`
keys otherwise remain objects. REST uses `tool_code` and `request` through
the existing Tools facade under the execution agent; HTTP errors are preserved.
Typed child calls receive local inputs; other profiles receive ordinary JSON.
Activated predecessors converge without a mandatory gateway, including nested splits;
an unselected IF branch does not block convergence. File references keep their
source URI without automatic transfers between activities. A link grants no resource access.

Configured IFs have exactly two outputs: `decision` for True and an unconditional False output.
`config.mode` is `ai`, `code` or `human`. AI actors permit AI or code; human actors require human
processing. Durable attempts require a boolean `decision`, without integrating it into run variables. Human decisions use Messenger's True/False buttons without an AI Task just to wait.
Historical IFs without a mode retain their expressions.

`preprocess`, `code` and `postprocess` use `IsolatedCodeRunner`. The Monty adapter starts a fresh
worker per invocation: a Python subset without mounts, networking, external functions or host
objects. Limits are 32 MB per VM, one second of execution, three seconds per request and two
concurrent workers. The worker closes before its result becomes usable. Intent and receipts
are durable; only pure computation may repeat after a lost result. Process integration remains
idempotent. Absent scripts retain default behavior; explicitly empty scripts prepare or
integrate empty values.

With `dataset_code: true`, a code task receives a detached JSON snapshot of its run data.
Keys valid as Python identifiers become local parameters; every key remains accessible via
`dataset["name"]`. An IF may use `return variable_2 != "pas mon projet"`; a task returns an ordinary
output dictionary, converted and validated before integration. Data never interpolates into source.
This runner provides neither general CPython, third-party packages nor MCP/REST capabilities.
Arbitrary code on a separate VM/host and its capability broker remain outside this scope.

## Historical v1 profile

`app.process.bpmn` compiles BPMN MODEL XML, Galaris extensions and BPMN DI placement
into `galaris.bpmn/v1`. This is an explicit executable subset of BPMN; other elements
are rejected. Graphs contain `nodes`, `flows` and actors. Identifiers are unique across
nested bodies. Graphs have one start, at least
one end, no unreachable nodes and no raw cycles. Business loops use structured FOR/WHILE.

| Node | Configuration |
|---|---|
| `task` / `human_task` | `prompt`, optional agent actor; automatic access to the run's shared pool. |
| `if` | Flow conditions and exactly one unconditional default. |
| `parallel` | Compatibility for existing gateways; unavailable when adding activities. Multiple outputs and activity convergence express parallel execution in the v2 profile. |
| `for` | Array expression `items`, sequential `body`. |
| `while` | `condition` checked before every `body` iteration. |
| `call` | `process_code`; current data and files copied into the child run, latest save at child admission. |
| `tool_call` | Declared MCP operation `tool`, arguments `input`, common governance. |
| `program` | `program_uri` and a qualified executor registered by its owning module. |
| `end` | Completes the flow; output is the current run JSON. |

Tool arguments may use `{"$expr": "data.amount"}`. Context contains `input`, `data`,
`results`, `files`, and activity-specific `output`, `error`, `item`, `index`.
Simple arithmetic, boolean operators, comparisons and JSON access are allowed;
calls, private attributes, comprehensions and exponentiation are rejected. Missing
fields are null; even short-circuited branches are validated. `data` is reread from the
run before every activity and condition. Legacy schemas, data mappings and result
formats are discarded when reading a definition and have no hidden effect.

Each run owns business JSON in `process_runs.data` and file links in `process_run_files`.
No Dataset or Document is created. Data and attachments inherit the parent Process's
existing read/edit policy. Historical v1 tasks can edit `galaris://processes/runs/<uuid>/data`
with `expected_revision` and use `galaris://processes/runs/<uuid>/attachments/` for files.
The engine preserves v1 task edits. Scheduler state and receipts remain separate from
business variables. Prompts contain canonical URIs without transport tokens or URLs.
The first execution failure prevents new
admissions and requests cancellation of active tasks and child runs. After confirmed
stops, the run becomes `error`. Inspection returns `error_code`, also shown in the UI.
A child's error code is preserved; an ordinary activity failure uses `node_failed`.
Legacy `catch`, `retry` and `error_handler` settings are ignored; their exclusive recovery
paths are removed when reading old definitions. Ambiguous Tool effects are not replayed.
A write against a stale revision fails; the task rereads and reapplies its
change while preserving other tasks' data.
An ambiguous effect also stops admissions and requests cancellation, returning
`effect_outcome_unknown`. The debugger refuses resume/step until reconciliation; requested
cancellation remains uncertain until external termination is confirmed.
Tool activities own a non-agent context Task under a lease and the Harness capacity
limit. An authorization request suspends that Task; its decision continues the same
attempt, while a known rejection closes both the Task and its attempt.

Routes under `/api/processes/internal` expose definitions, validation, history,
restore, sharing, launch, runs, occurrences, children, metrics and debugger.
PROCESS_READ/EDIT/LAUNCH/ADMIN combine with ACLs. Personal `galaris` MCP tools expose
these operations, including `process_definition_read` for audits.
The inspection's `operational` projection is shared with `processus_get`: phases,
occurrence counts, documented waits, last activity and available actions. Reading it
does not advance the engine or infer a blockage from elapsed time.
The Process's existing read/edit policy applies to its runs, data and attachments.
Sharing and revocation apply immediately to existing runs, without new privileges or run
grants. Dedicated `process_admin` access remains available. Filters precede counts,
pagination, child reads and inclusive metrics. Participant snapshots describe assignments
without granting an independent ACL. See [decision 0198](../../../project/decisions/0198-process-run-data-and-files.md).

Debugger commands accept `command_key` (UUID) and `expected_revision`. Their receipt
is saved with the state change; resending the same command after a lost reply returns
that receipt without a second step. The UI retains the key while the reply is uncertain
and detects concurrent debugger changes.

Metrics distinguish billed cost from inference value, including subscription calls.
They expose direct/inclusive totals, individual Tasks and exact activity occurrences
(including loops and retries), USD currency and the calculation timestamp. Unauthorized
descendants are excluded and the visible total is marked partial. Run elapsed time
starts at admission; cumulative LLM call durations remain a separate measurement,
without claiming to measure uncorrelated remote work.

Run data initialization is idempotent. For v1, File Sharing materializes incoming files;
the engine publishes managed bytes to `core.storage` and links them through
`process_run_files.file_id`. File links and copy receipts commit atomically; recovery
reuses receipts. Exposed URIs are `galaris://processes/runs/<uuid>/attachments/<file-uuid>`.
References retain origin URI, MIME type and SHA-256. Typed v2 external references keep
their original provider without a copy. Revocation or cancellation during preparation
admits no task.
Engine metadata is server-owned. Leases and short scheduling passes are not business
budgets; Process has no cost, token, duration, iteration or depth ceiling. Documentary
programs remain conditional on their executor. Native/linked runs are excluded from
automatic external retention purges.

Integration and file preparation receipts belong to the run: no execution state is
mixed into business variables. Internal processes have never been deployed:
no receipt migration or transitional table is retained.
See [decision 0196](../../../project/decisions/0196-process-run-execution-state.md).

See [decision 0197 on BPMN storage](../../../project/decisions/0197-process-owned-bpmn-storage.md)
and [decision 0174 on execution foundations](../../../project/decisions/0174-native-document-backed-business-processes.md)
and the [user workflow](../user/internal-processes.md).

## Actors and human activities

`execution_agent_id` is optional and defaults to null. Tasks use the launch agent unless
this field imposes one, or their actor has an explicit assignment, which takes precedence.
Loop bodies inherit this default; called processes apply their own definition.
XML and the run snapshot preserve this field. The agent launches the process from Chat;
Process pages do not provide manual launch controls.

`actors` contains graph-local roles: `id`, `name`, `kind: agent/human`, and `agent_id`
or `user_id`. `config.actor` references a role. When assigned, `task` requires an agent
actor; `human_task` requires a human actor. XML retains these assignments and exports
`laneSet/lane/flowNodeRef` and `userTask`. Assignment never converts an activity's type.
Existing graphs without actors remain valid. Admission checks managed agent scope and
active users; the engine rechecks these rights before each new effect. Data and file access follows the parent Process's policy; assignment creates no
additional grant.

A human attempt persists `human_waiting`, instructions, inputs and its assignee before a
reply. The Process outbox calls a messaging port registered at bootstrap. Conversation uses
canonical Messenger interactions: the launching conversation when its author is the assignee,
otherwise a reachable contact, then private Chat as fallback. The assignee remains an active
Galaris user; an external identity must be linked to that account. The `/human-work` routes
and their form are removed.

A `process_human_activity` request requires interpretation: the deterministic matcher never
consumes an arbitrary next message. Conversation context exposes pending requests in the
exact agent/connection/Tool/room/sender scope. `conversation_process_pending` provides full
contracts and pagination; `conversation_process_respond` accepts the selected reference and
typed outputs. File-only messages remain in history with their source URI; File Sharing checks
`File` values without downloading or persistently copying them. Incomplete or ambiguous replies
require clarification.

Recording locks the interaction, Run and attempt, rechecks outputs, active assignee and
cancellation, then commits the result and Messenger receipt together. Identical results are
idempotent; different results conflict. Delivery failures are retried without abandoning the
human wait. Obsolete requests are withdrawn.
