<p align="right"><a href="../../fr/components/claude-agent.md">Français</a> · <strong>English</strong></p>

# Claude Agent Harness

## Embedded Claude Agent

The backend installs the Python SDK and starts its local executable. Enable
`harness.claude-embedded.enabled`, then select **Embedded Claude Agent** in the Agent record. This assignment works without
a dedicated Claude container. Pydantic AI remains available in the same selector.

Calls use the local Galaris gateway. Use the LLM log to find the Task attempt, Chat or voice
round, or exact `@deep` submission. External MCP tools use the Service connections and
function permissions for the conversation or Task. Approvals use the standard approval interface.
See the [execution flow](../architecture/flows/agent-execution.md).

### Restoring the previous conversation routing

To restore Pydantic AI for new Chat and turn-based voice rounds, set
`harness.claude-embedded.conversations.enabled` to `false` through `PUT /api/params/{name}`
with permission to edit harness settings. This setting defaults to `true`.
Keep `harness.claude-embedded.enabled` set to `true` during the transition. Existing rounds
finish or resume with their original harness. Task assignments and `@deep` continue to use
their own harness. Set the conversation setting back to `true` to route new rounds to Claude
according to the agent's assignment.

Before disabling the SDK itself, let active Claude rounds, Tasks and Deep submissions
finish or resolve their recovery explicitly. To move future Task or Deep executions, change
the agent's assignment from its agent record.

If a Claude Task loses its worker before its first tool effect, the scheduler can restart
execution with the same run identity and request budget. If the final result is already in
the checkpoint, the replacement worker retrieves it without a model call.
Changes to the request limit apply to new Tasks, Chat and voice rounds, and Deep submissions.
A resumed execution keeps its recorded limit and counts earlier attempts' calls. A new Deep
submission takes the current setting even when it continues the session's history. Legacy
executions without a recorded limit adopt the current setting on their next admission.

A Task interrupted after creating a document can resume from its recorded receipt on either
embedded harness. Galaris checks that the tool is still authorized and the agent can still
read the document. Recovery uses the existing receipt without repeating the creation. If
the receipt is missing or these checks fail, recovery stops before another model call.
It keeps the original tool budget and accounts for previously recorded operations.

### Qualifying the backend image

`make tests-embedded-harness-image` exercises the local image selected by
`EMBEDDED_HARNESS_IMAGE` and checks its embedded `EMBEDDED_HARNESS_REVISION`.
Release qualification also runs this probe against the exact image in the bundle.
The probe uses isolated PostgreSQL and a simulated model provider. It checks physical
LLM calls for two concurrent rounds, restores Pydantic AI for new rounds, and runs a Task
that still uses Claude. While Claude is enabled, a Pydantic agent retains its engine in
Chat and Tasks. Agents assigned to Codex or DeepSeek Harness use Claude in Chat and send
Tasks to their assigned harness. By default the probe simulates the managed harness endpoints.
The test log includes the image identity, SDK and CLI versions, calls
reconciled with provider receipts, and the Tasks received by each managed harness.
The probe also submits an explicit `@task` request from Chat for each assignment. The
Task remains linked to its round, runs on the selected harness, and delivers one result
notification to the original room. The shared structured call that prepares the objective
is linked to the round. For an embedded Task, the execution call also identifies the Task
and its attempt.
The probe also sends a natural-language request for each assignment. It checks the
`task_run` call and receipt, Task dispatch and execution, and the result in Chat. It
exercises approval and denial in both embedded loops and verifies the resumed attempts
and the effects of each decision.

To exercise Codex and DeepSeek Harness, supply their local Docker image IDs through
`EMBEDDED_HARNESS_CODEX_IMAGE` and `EMBEDDED_HARNESS_DSH_IMAGE`. The probe starts their
actual containers on the test network, calls the Galaris gateway, and records all three
image IDs. Each managed Task call is then matched with a synthetic provider receipt and
checked against the Task, its attempt, and its source round when present. The Tasks use
agents and assignments created for the test.

Set `EMBEDDED_HARNESS_LOAD_ROOMS=8` to run eight new rooms per harness on the same profile
with the simulated provider. This number must exceed the conversation worker count and
must be at most 24. The report records each burst's duration and reconciles calls across
all rooms. If the probe fails, it also retains the test instance's PostgreSQL log.

## Managed Claude Agent

This bridge provisions an isolated Claude Agent SDK instance per Agent through the generic
`bridge.harness` manager. Galaris executes it through the shared `app.harnesses` Chat Completions
client; neither the Claude SDK nor its internal protocol leaks into `app.agent`.

The container exposes:

- `GET /health` for Compose health;
- `GET /v1/models` for the provider probe;
- `POST /v1/chat/completions`, as JSON or SSE.

The requested model is the execution model already resolved by `app.agent`. The SDK must use
`/api/llm/anthropic` with a rotating system token. Galaris internal models therefore remain
available, and every LLM call is correlated with the Task and run. The same token grants access to
the Agent's sole MCP endpoint. No direct Anthropic credential enters the container.

Authorized Skills are projected under `data/skills/.claude/skills`, the workspace under
`data/workspace`, and Claude state under `data/claude`. The container is unprivileged, read-only
outside the `data` volume, has no Linux capabilities, and has process, CPU, and memory limits.

## Telemetry

The transport remains compatible with an ordinary Chat Completions server. For this provider,
Galaris additionally enables two named and versioned SSE events:

- `galaris.agent-message/v1` carries completed Service calls and public reasoning blocks normalized
  as `AIMessage`;
- `galaris.agent-result/v1` carries the authoritative final response, usage, cost, SDK session,
  terminal status, and permission denials for the single `ExecutionResult`.

Text deltas remain standard OpenAI chunks and may contain provisional progress before a Service call.
At close, `ResultMessage.result` replaces that text in the durable result; the UI therefore receives
live progress followed by the exact final response. In parallel, calls to the Anthropic gateway
populate `LLMCall` records correlated with the `run_id` throughout execution. At termination, the
shared client aggregates these persisted traces and treats them as the primary token and cost
source. SDK usage remains a `partial` fallback when the gateway produced no trace; it therefore
cannot hide an exact provider cost or a pricing estimate explicitly qualified by Galaris.

The SDK uses `permission_mode="dontAsk"`. Claude discovers and reads skills with `skills_list`
and `skill_read`. The Galaris MCP server enforces the configured mode, scope, and rights for
each function. The harness admits tool discovery and workspace reads after checking the active
context. For local actions that require approval, the hook checks Galaris authorization for the
exact action. The MCP server
manages the approval request and continues the same call. Remembered local-tool grants
remain bound to the agent, harness and configuration. When a local tool needs approval, managed
Claude saves the continuation to its data volume and closes the SDK process. The decision wakes
the same Task. The harness resumes the deferred call with the same one-use authorization and
checks its context and action data again before executing it. Turn and tool counts follow the
limits frozen in `AgentRunEnvelopeV1`. The SDK manages request history and compaction within
the model's context window. If the harness checkpoint reaches its size limit, it preserves the
terminal result, the cursor, and recent tool results, with previews for older entries.

`start`, `restart`, and `update` build or recreate the image pinned by `requirements.txt`.
`refresh` reprojects configuration, MCP token, and Skills before restarting. Deleting the Harness
destroys the instance and revokes its system tokens.
