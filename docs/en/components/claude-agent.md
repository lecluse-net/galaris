<p align="right"><a href="../../fr/components/claude-agent.md">Français</a> · <strong>English</strong></p>

# Claude Agent Harness

## Embedded Claude Agent

The backend installs the Python SDK and starts its local executable. **Claude Agent** is
always available under **General → Harness** in the Agent record. Select it to use Claude
Agent in Chat, voice, Tasks and `@deep`. Pydantic AI is also available in the same selector.

Calls use the local Galaris gateway. Use the LLM log to find the Task attempt, Chat or voice
round, or exact `@deep` submission. External MCP tools use the Service connections and
function permissions for the conversation or Task. Approvals use the standard approval interface.
See the [execution flow](../architecture/flows/agent-execution.md).

### Restoring the previous conversation routing

To restore Pydantic AI in Chat and turn-based voice, select another harness in the Agent
record after its open Tasks finish. New Tasks and `@deep` sessions follow the new assignment.
Existing rounds finish or resume with their original harness. Agents assigned to Codex or
DeepSeek Agent use Pydantic AI for Chat and turn-based voice and their selected harness for
Tasks and `@deep`.

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
LLM calls for two concurrent rounds, reassigns the agent to Pydantic AI for new rounds, and runs
a Task after reassigning it to Claude Agent. A Pydantic AI agent uses that engine in Chat and
Tasks. Agents assigned to Codex or DeepSeek Agent use Pydantic AI in Chat and send Tasks to
their assigned harness. By default the probe simulates the managed harness endpoints.
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

To exercise Codex and DeepSeek Agent, supply their local Docker image IDs through
`EMBEDDED_HARNESS_CODEX_IMAGE` and `EMBEDDED_HARNESS_DSH_IMAGE`. The probe starts their
actual containers on the test network, calls the Galaris gateway, and records all three
image IDs. Each managed Task call is then matched with a synthetic provider receipt and
checked against the Task, its attempt, and its source round when present. The Tasks use
agents and assignments created for the test.

Set `EMBEDDED_HARNESS_LOAD_ROOMS=8` to run eight new rooms per harness on the same profile
with the simulated provider. This number must exceed the conversation worker count and
must be at most 24. The report records each burst's duration and reconciles calls across
all rooms. If the probe fails, it also retains the test instance's PostgreSQL log.

## Switching from an older Claude container

The old containerized Claude harness has been retired from the catalog. If an
agent still uses it, let its open tasks finish, then select **Claude Agent** in
the agent record. Switching uses the standard process to remove the container
and revoke its token. Back up its workspace files before confirming the switch.
