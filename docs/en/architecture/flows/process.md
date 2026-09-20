<p align="right"><a href="../../../fr/architecture/flows/process.md">Français</a> · <strong>English</strong></p>

# Tool and Process Flow

A short tool call returns a structured output directly. An external or
long-running operation becomes a durable `ProcessRun`, so the Agent can wait, resume, cancel, and
analyze it without keeping a request open.

```text
Agent runtime
   → app.tools / MCP toolset catalog
   → @mcp_tool tool
   → app.process (definition + run + event + startup job)
   → engine registry
      ├── bridge.n8n
      └── test fake engine
   → callback or periodic refresh
   → durable transition + sanitized output/error
   → resolution of any waiting task
```

## Agent Discovery

The six personal `process_*` functions belong to the `galaris` core package: the optional
`process` connection no longer exists. The prompt inventory is produced from exactly the same
projection as the MCP server; it therefore cites no function that is inactive, incompatible with
the runtime, disabled, or removed from the Task scope.

If `process_list`, `process_get`, and `process_start` are all authorized, the prompt adds the
identifiers, labels, and descriptions of only the definitions assigned to the Agent. Up to ten
definitions, they are all injected without semantic ranking. Beyond that, the current request
ranks the set with the configured multilingual vector model, and the prompt receives exactly the
first ten, with no exclusion threshold; a model failure or absence uses deterministic lexical
ranking. The `galaris` system Skill then explains the detailed workflow. The presence of the
package never constitutes authorization for a definition: `list_for_agent`, `get_for_agent`, and
`start_process` filter or revalidate the durable assignment.

The same personal projection is available as a read-only tree under
`galaris://process/`. A definition uses its public `workflow_id` as its locator, for example
`galaris://process/Kw70xUO8uRWkXvtX`; internal SQL identifiers are not part of the contract.
`file_list` and `file_search` paginate on the server side and never reveal a definition assigned
to another Agent. Starting remains exclusively a `process_start` or
`conversation_process_start` action.

The conversational controller uses the same projection with its specialized launcher
`conversation_process_start`. The catalog is therefore injected when `process_list`,
`process_get`, and this launcher are actually visible. The specialized launcher forces
asynchronous execution, links the run to the round, and delegates its terminal notification to the
conversation outbox.
An assigned Process that matches the requested action has absolute priority over creating or
amending a Task. When more than ten definitions are assigned and uncertainty remains about the
projection, the model consults `process_list` and `process_get` before using a Task.

In the Chat interface, the executions sidebar does not traverse all historical runs in the room.
It starts from the oldest currently loaded message, resolves the visible rounds, then
collects their `ConversationProcessLink` objects and the runs linked to the Task tree derived from
those rounds.

The reduced scope of a scheduled leaf retains the six personal functions: a tool selection made
upstream therefore cannot hide the business catalog. The functions selected
by the planner remain eager; the other authorized functions remain in the internal toolset
with `defer_loading` and become accessible through `search_tools`. The common MCP projection
continues to apply function disablements and runtime constraints before this
discovery.

The planner always receives the exhaustive name manifest. `app.tools.catalog` derives its version
from the same effective MCP server. `app.tools.tool_search_service` enriches this manifest with a
hybrid FTS + pgvector search over bounded public metadata. Embeddings are shared by definition
fingerprint, never by Agent; for each request, candidate fingerprints come exclusively from the
Agent's effective catalog, the runtime, and the Task.
An outdated vector record therefore grants no rights. Without a vector model or in the event of a
semantic failure, the search becomes lexical; the exhaustive manifest remains available.

Connection, parameter, and authorization mutations trigger a targeted reconciliation of the
affected catalogs. This update accelerates search, but does not provide security: the effective
catalog and its rights are always recalculated at planning and execution time.

The **Refresh tools** button on the Connections screen launches the complete administrative
reconciliation. A single operation:

1. creates any still-missing built-in internal connections;
2. rebuilds the effective catalog for each Agent and queries its MCP servers again;
3. reindexes public definitions and recalculates their embeddings;
4. deletes records that are no longer observed only if all Agents and all
   sources have responded.

An unavailable remote source makes the result partial and therefore prohibits global pruning.
Historical records may remain stored, but they remain ineligible as long as their
fingerprint does not belong to the current effective catalog. The former
`POST /connections/sync-integrated` endpoint is a deprecated alias; the current contract is
`POST /connections/refresh-tools`.

The `process_admin` package, inactive by default, constitutes a separate surface. Its
`process_admin_*` functions can create, reassign, or delete a definition and manage runs for all
Agents. Its connections are created inactive so that no global rights are granted
implicitly.

The `galaris_admin` package follows the same explicit attribution rule. Its connections are
created inactive, and its two read functions, `conversation_round_get` and `voice_turn_get`,
recheck the active connection on the server side. They are used to analyze a complete text or
voice turn with its durable state, execution trace, and all its LLM calls, without making this
administrative dataset available to ordinary Agents.

## Startup

1. The tool validates its schema and resolves the `Connection` without exposing the secret to the model.
2. `app.process` verifies the definition and builds a startup snapshot.
3. An explicit idempotency key or content fingerprint prevents duplicates within the
   configured window.
4. The `queued` run and its `ProcessStartJob` are written before the remote call.
5. The worker starts the engine with a `correlation_id` and callback token specific to the run.

## Progress and Completion

An engine returns a snapshot through a callback or through `refresh_run`. Each event is added
to `process_run_events`, then the transition is validated by the common matrix. Payloads,
outputs, and errors pass through the sanitizer and its size limit.

The `success`, `error`, and `cancelled` states are terminal. A late callback is logged
but does not reopen the run. An external `event_id` makes redelivery idempotent. When a
Task is waiting for the Process, only entry into a terminal state resolves that wait.

Terminal output, errors, engine references, and metadata are also immutable, including
when a duplicate callback reports the same terminal status. After a remote call, the
service reloads the row under a lock before applying the snapshot, so an intervening
callback cannot be overwritten by stale ORM state.

## Correlation of LLM and Agent Calls

A Process that directly calls the OpenAI Chat Completions, OpenAI Responses, or
Anthropic LLM gateways must identify its `ProcessRun`. The contract accepts, in order of authority:

1. the canonical UUID in `X-Galaris-Process-Run-Id` or `galaris_process_run_id`;
2. the external pair `galaris_workflow_id` + `galaris_engine_run_id`, resolved by `app.process`
   under the caller's Agent scope;
3. the `process_run_id` fixed in the Task data when the Process triggered an Agent call and
   low-level LLM calls subsequently originate from that Task.

Each direct call carries `purpose=process.exec` and an `LLMCall.process_run_id` FK. An LLM call
belonging to the Task triggered by the Process cumulatively retains its Task, its attempt, and its
ProcessRun; its purpose remains `agent.exec`, because the Task owns the inference while the
ProcessRun expresses its provenance. The LLM service re-derives the ProcessRun from the Task for
both the internal harness and external runtimes and rejects a divergent explicit identifier.

Before contacting the provider, the API routes verify that the ProcessRun belongs to the token's
Agent scope and add the `llm.called` or `agent.called` observation event. The persistence service
verifies the existence of the ProcessRun and its consistency with the Agent again. The run details
then list all `LLMCall` objects carrying that `process_run_id`.

## Projection into Memory

Dream executes `memory.project_process` without an LLM and outside the execution path. An assigned
definition becomes a private, source-managed procedural memory. Only the sanitized output of a
`success` run becomes episodic memory: the input, raw snapshot, errors, and secrets
are never projected. The output is filtered again and then limited to 12,000 characters.

The result carries a `result_of` link to its definition. The projection retains the 20 most recent
successes per Agent and Process; older ones are forgotten without affecting the canonical
`ProcessRun` objects. Deletions and reassignments are reconciled through idempotent Dream receipts.

## Cancellation

- A run that is still `queued` can be canceled locally along with its startup job.
- A remote run transitions to `cancelling`, then waits for the engine's `cancelled`, `success`, or
  `error` confirmation.
- A new request for a terminal state returns the existing state.

Runs in `cancelling` remain eligible for polling, including after a network failure during
the cancellation request. Every terminal path resolves its optional waiting Task.
The durable `await_resolved_at` marker is written only after resolving the child and
resuming its parent. A duplicate callback, refresh or periodic reconciliation can finish
this interrupted step without changing the terminal output or rerunning the Process.

## Calendar triggers

The Calendar bridge stores its cursor and all discovered receipts in one transaction.
Each receipt contains an encrypted action snapshot and uses a recoverable dispatch lease.
Tasks and Processes receive a stable idempotency key; replaying receipts no longer requires
reading the remote calendar. ADR 0067 documents the recovery limits of historical receipts
created before this contract.

## Files

File inputs for a Process are canonical `app.file_share` URIs and can therefore come from
the console, Nextcloud, Mail, Messenger, HTTPS, or another
authorized provider. The snapshot preserves this URI and the actual name provided by the source
metadata. The bridge receives a temporary download URL attached to the run; when it is called,
Galaris materializes the resource in a bounded manner and deletes it after the response. It
receives neither the provider secret nor an arbitrary host path, and no prior local copy is
required. See [Media and resources](media-resources.md).

Immediate `app.file_share` operations manipulate canonical URIs and stream with a
bounded size and timeout. They do not artificially create a `ProcessRun`. A provider that
exposes a genuinely asynchronous conversion, export, or transfer must instead create a durable
Process, return its result reference as a URI after success, and preserve the same
idempotency, cancellation, and terminal-state rules as the other engines.

## Entry Points to Read

- Engine contracts: `back/app/process/engine.py` and `registry.py`.
- Persistence and matrix: `back/app/process/models.py`, `process_service.py`.
- Tools: `back/app/process/mcp.py` and `back/app/tools/mcp_loader.py`.
- n8n adapter: `back/bridge/n8n/`.
