# 0327 — Embedded harness inference origin

Status: Accepted

The embedded Claude SDK sends model requests through the backend's Anthropic gateway.
Each invocation receives an authenticated credential bound to the agent, round or Task,
attempt, run and model. The gateway resolves the requester from the owning operation and
rejects client-supplied routing metadata. A Task credential must match the admitted run and
model recorded on both the Task and its attempt. For a round, the driver is stored at
admission and the model code, model ID and reasoning effort are stored on the claimed
attempt before the SDK starts. A credential must match these values, the round's run and
conversation mode. Reassigning the agent affects future rounds. Old rounds default to `internal`.

Durable inference carries the origin to the provider admission step. After acquiring provider
capacity, the worker checks the original lease and any applicable contact authorization again
before it records and dispatches the physical call. Each call keeps its run, requester and
attempt reference. A Task call also retains the durable links to its original round or Process.

On the managed gateway path, call persistence resolves the source round from the stored Task
lineage after the gateway authenticates the live attempt. Caller-provided round hints cannot
change that attribution. An independent Task has no source round.
The credential stays outside the inference journal.

After provider failover, each new SDK request consults the physical call journal for its
admitted origin. If the configured fallback still permits the recorded secondary model,
the gateway routes the continuation directly to that model and keeps the original reason
and model in the call journal. Tool receipts continue through the same SDK session. A new
origin resolves its own route. Specialist calls keep their own model selection.
Task admission records the selected executor profile tier alongside the model and its
reasoning effort. The gateway checks the tier in the credential against the attempt and
uses it to select the fallback. The same primary model can serve both tiers. A high-effort
Task that starts on the standard tier uses the standard fallback. Older admissions and
credentials without this field keep the earlier model lookup until they are replaced.

The gateway enforces the embedded model request limit against the physical call journal.
Admissions for one logical run share a transaction lock and count calls from earlier attempts.
Provider errors and work cancelled after reservation consume the allowance. A model
request reissued by the SDK, retried after an optional parameter is rejected, or retried with
refreshed credentials needs a fresh call entry before it can reach the provider. An exhausted
allowance returns a nonretryable rate-limit response to the SDK and a quota failure to Galaris.
Attachment analysis keeps its separate purpose outside this allowance.
For a Claude Task, the allowance is recorded in both the run admission and checkpoint so a
retry of the same run keeps the original ceiling after result application clears the active
identity. A legacy run without either record of the allowance snapshots the current setting
on its next admission. Earlier physical calls remain counted.
Chat and voice rounds inherit the first recorded allowance across their attempt admissions.
Deep stores the allowance on the submission and carries it across lease changes. Each new
submission takes the current setting, including when it continues the same SDK history. The
gateway checks the credential's allowance against the recorded round or submission admission.

A Claude Task also keeps its original tool call limit in the run admission and checkpoint.
The adapter records each SDK tool call admitted to dispatch before invoking the tool.
A mutation records that reservation together with its start evidence. A read reserves a
slot while keeping the checkpoint safe to resume. A replacement worker inherits both the
limit and the spent slots. Resuming a pending authorization uses the original reservation
and retains the operation identity. A legacy checkpoint counts the effects it had recorded.

Chat and voice store the tool limit and used slots on the round attempt. A replacement
inherits the earlier attempt's limit and counter. Deep stores both on the submission. The
owner checks the live lease and reserves each slot before dispatch while holding its row
lock. Resolving an approval continues its original operation. New rounds and submissions
take the current setting, including voice after an interruption and Deep with existing
SDK history. Legacy admissions can account for the operations still in their effect checkpoint.

The Python SDK executes its bundled CLI through a launcher that supplies a limited,
invocation-local environment. The qualification uses the installed SDK and gateway with
PostgreSQL and a synthetic provider. Two simultaneous rounds for one agent and a Task from the
first round retain distinct request messages and physical calls. The Task uses the normal
agent facade. Missing, conflicting and stale contexts are refused. The driver is registered
as `claude_embedded`. Its availability and routing are specified in [decision 0328](0328-retire-containerized-claude-harness.md).

[Qualification test](../../back/tests/test_embedded_claude_lineage.py)

Embedded selections use `Agent.agent_driver` and the existing authorized Harness selection
endpoint. An embedded selection has no remote runtime assignment. When replacing a remote
runtime, the previous assignment remains the cleanup receipt until deprovisioning succeeds.
DbAdmin preserves the chosen embedded driver in either state. When the assignment changes,
existing rounds retain their admitted driver so they can finish or recover.

The embedded MCP relay uses the native Galaris catalog for Tasks and text rounds. It pairs
the SDK's `PreToolUse` event with the MCP request's `claudecode/toolUseId` metadata. Each call
must match its admitted name and arguments and can dispatch once. Galaris validates the owning
inference attempt and reuses the tool's live Service permissions. The tool ID also identifies
the normalized receipt. Identical calls with distinct IDs remain distinguishable.

The pinned SDK and CLI are exercised together because this metadata is a transport dependency.
An embedded Task with a checkpoint writer may mount authorized native mutations. It persists
an empty journal before inference so a replacement can recover the run if the worker disappears
before any effect. It commits each operation's identity and input before dispatch, then records
the outcome before returning the receipt to the SDK. Loss of the journal write before dispatch
prevents the call. An unresolved
effect prevents further tool execution and fresh inference after recovery. A complete checkpoint
can return its result to a replacement Task attempt without contacting the provider.
A replacement attempt may recover a recorded native document creation without the SDK
transcript. It verifies the current tool authorization and read access to the exact URI in
the receipt, exposes the verified receipt to the model, and fences an unchanged creation
request. A document created without a durable receipt remains unresolved.

The common Service authorization flow owns approval decisions. A waiting Task records the
original tool ID and arguments, the authorization request, and a sealed continuation and SDK
transcript bound to the run. A replacement attempt checks the decision, restores the transcript
in an isolated workspace, and revalidates its lease and the current Service policy before
dispatching the approved call with its original operation identity. The SDK receives the settled
receipt. An unchanged replay of a prior recorded call is fenced across attempts. A missing
transcript or an uncertain outcome prevents automatic re-execution.

Text rounds use the same journal through their existing encrypted checkpoint writer. The
native Service boundary checks round freshness after authorization and immediately before
the effect. Requested approval alone leaves the round free of effects. A superseding message
invalidates the earlier pending approval, even if the earlier worker has not parked the round
yet. A tool already running is allowed to settle before the response is interrupted.

Before executing a proposed tool, the relayed SDK hook checks the complete assistant response
that proposed its ID. An invented dialogue turn prevents that response's tool calls. The
inference gateway removes the invented text from subsequent assistant history for this round.

The speech-to-text and text-to-speech pipeline freezes the same conversation driver at the
start of each voice round. A Claude voice round owns a leased attempt independently of any
Task. Its credential includes the audio mode and the admitted conversation model. Interruption
or closure releases the attempt, so the previous credential cannot attach calls to the next
utterance. The live audio transport owns these direct attempts. Pending approvals use the
existing Voice authorization workflow.

Native speech-to-speech delegates inference and the tool loop to the voice provider. A new
voice call routed to embedded Claude uses speech-to-text and text-to-speech. A supported OpenAI
native voice is rendered by the Speech API with the selected voice code and the same provider
connection. The effective profile supplies the transcription model. With a supported OpenAI
transcription model, the bridge streams PCM through a dedicated WebSocket and commits at
Galaris's local turn boundary. After a socket failure, the current turn uses the existing
file transcription path when available. The next turn can reconnect to the live provider.

Deep keeps its direct harness selection. An embedded Claude submission owns a distinct lease
and freezes the admitted model and effort. Its gateway credential binds the session, submission,
lease and agent. `LLMCall` records the submission as a foreign key and keeps the session for
room-level history. Cost and usage are reconciled per submission. A new lease revokes the
previous credential even when the submission continues the same SDK session.

Each successful Deep submission stores an encrypted SDK transcript bound to its Deep session.
Tool authorization uses the submission as its context. A waiting submission releases its lease
and holds later submissions in the same session in order. After a decision, it restores its
encrypted checkpoint and SDK session, then uses the original operation identity. The native tool
boundary rechecks the lease, room and Service permissions before dispatch. Stopping an awaiting
submission invalidates its authorization and lets the next submission run.

Claude Tasks offer the standard and high execution tiers. The Task credential freezes the
resolved reasoning effort with the model. The gateway checks both before applying them.
Planned work uses the shared Galaris dispatcher, plan tree and synthesis. The scheduler gives
each executable child to the assigned harness and records inference against that child.
Each driver declares its own Deep model source and whether its actor stays live during an
authorization wait. Shared orchestration uses those declarations to select and stop runtimes.
Claude and Pydantic share the local run controller. The driver and run identify a cancellation
request. The receipt confirms closure of a local execution that the controller observed as active.

The embedded MCP relay mounts external Service tools through the same catalog and live
connection checks as the other runtimes. External tool calls use the durable effect journal
and a final run-ownership check before dispatch. Galaris keeps authorization continuations
and local operation metadata within its proxy. The proxy also reserves native tool names so
an external tool cannot replace a native function in the mounted catalog.

For a Task with planner-selected tools, Claude starts with the shared eager selection and
discovers other authorized tools through the shared catalog. Its MCP search and invocation
tools use a per-attempt set of disclosed names and a live permission check. The SDK relay
checks the search or invocation ID and inputs. The physical tool name and arguments govern
effects and approval recovery. The next attempt can search the current catalog while the
approved operation retains its original identity.

Embedded Claude uses the same library and personal skill assignment rules as Pydantic AI.
Eager guides enter the system prompt. Deferred guides are loaded by exact ID, and resources
are read through the same package storage and Markdown section logic. The tools recheck live
assignment on every call. The CLI reads the current system prompt in its temporary workspace
and disables prompt snapshots. When restoring native SDK history, Galaris preserves skill call
IDs and replaces their previous outputs. The model can load currently authorized content again.

[SDK skill qualification](../../back/tests/test_embedded_claude_skills.py)

Embedded Claude shares authorized attachment materialization with Pydantic AI. Input blocks
carry native images and PDFs when supported. Text prepared from sources and their native bytes
are scoped to the attempt and excluded from saved SDK transcripts. Deep reloads historical
resources from canonical messages under live access checks. The Anthropic gateway translates
PDF blocks into the existing document routing contract.

Attachment analysis inherits the admitted runtime owner. Vision uses the durable protocol
request and direct audio or video analysis uses the same physical-call admission. Each keeps
its specialist purpose and selected model. The owning lease is checked after provider capacity
is acquired. Exact embedded Task references are included in Task activity and cost views.

[Media qualification](../../back/tests/test_embedded_claude_media.py)
[Specialist inference qualification](../../back/tests/test_embedded_claude_specialists.py)
