<p align="right"><a href="../../fr/dev/agent-admin.md">Français</a> · <strong>English</strong></p>

# AgentAdmin

AgentAdmin (`agent_admin`) is an optional built-in Tool with 34 functions. Its connection
starts inactive for ordinary agents. The **Galaris** assistant proposed by the installation
receives an active connection when first created. Catalogue synchronization never reactivates
disabled connections or changes previously initialized agents. A human can enable it in
**Configure → Tools & connections → Connections**.
`agent_list` and `agent_get` remain in the mandatory Galaris system service.

## Delegation and privileges

Every invocation checks the active connection and effective function permission, then the
caller’s active human manager’s current privileges. That manager determines the target scope;
`AGENT_MANAGE_ALL` extends it to every agent. No HTTP identity is required and an HTTP-selected
role never replaces this delegation.

| Operations | Manager privileges, in addition to connection/function authorization |
|---|---|
| All | `AGENT_EDIT` |
| Tools and connections | `CONNECTION_EDIT` |
| Team and group reads | `TEAM_ACCESS` |
| Membership | `TEAM_ACCESS`, `TEAM_MEMBERS_EDIT` |
| Group creation/update/deletion | `TEAM_ACCESS`, `TEAM_EDIT`, `AGENT_MANAGE_ALL` |
| Title creation/update/deletion | `AGENT_MANAGE_ALL` |
| Manager changes | `AGENT_MANAGE_ALL` |
| Harness blockers | `TASK_EDIT` |

The caller cannot delete itself or change its own manager. System connections are protected.
Connections granting administrative capabilities are human-controlled: AgentAdmin cannot
grant itself rights, delegate AgentAdmin to another agent or enable another administrative
Tool. Connection targets are resolved by the server. Revocation also blocks invocations on
an already mounted MCP server, whose discovery evaluates current rights.
[Decision 0148](../../../project/decisions/0148-agent-admin-delegation.md) defines this contract.

## Catalogue

| Domain | Functions |
|---|---|
| Agents | `agent_create`, `agent_update`, `agent_delete`, `agent_options` |
| Avatars | `agent_avatar_set`, `agent_avatar_delete`, `agent_avatar_generate` |
| Membership | `agent_team_list`, `agent_team_set` |
| Tools | `agent_tool_list` |
| Connections | `agent_connection_list`, `agent_connection_get`, `agent_connection_create`, `agent_connection_update`, `agent_connection_delete`, `agent_connection_params_set`, `agent_connection_param_delete`, `agent_connection_function_list`, `agent_connection_function_set` |
| Harnesses | `agent_harness_get`, `agent_harness_set`, `agent_harness_reset`, `agent_harness_status`, `agent_harness_action`, `agent_harness_logs`, `agent_harness_blockers` |
| Titles | `agent_title_list`, `agent_title_create`, `agent_title_update`, `agent_title_delete` |
| Shared groups | `agent_group_list`, `agent_group_create`, `agent_group_update`, `agent_group_delete` |

Lists default to `skip=0`, `limit=50`, with a maximum of 500. Creation explicitly requires
a manager and starts with the internal Harness. `agent_update` cannot change permanent codes
or Harnesses. Omitted and null values differ; editorial fields remain HTML. Responses describe
persisted effects and available URIs. MCP errors include an `error` object with `kind` and
a technical reference, without secrets.

Parameters use existing encrypted storage; reads mask secrets and distinguish local, inherited
and forced settings. Function permissions are local (`default`, `enabled`, `disabled`, `ask`) and
never change global rules. Each agent/Tool pair has one connection. Group deletion detaches
legacy references and revokes associated access. Referenced titles cannot be deleted, including
those still used by archived agents.

Harnesses use existing selection, cleanup and blocker workflows. Actions require support from
the current provider and runtime state. Results distinguish `completed`, `in_progress` and
`error`. Logs are limited to 5,000 lines, 2,000 characters per line and 200,000 characters total,
with credentials and paths redacted. Blocking Tasks have complete URIs; no Task-stop command
is provided.

## Generated portraits and tracking

Only `agent_avatar_generate` disappears when the caller’s effective image usage has no
image-output model with an active provider and the credentials required by its provider
profile. This local check does not verify credentials with the provider.
Inherited profiles qualify; chat and executor
models never serve as fallbacks. Discovery and invocation recheck availability even within
a retained session.

Portraits use the target’s first/last name, title gender, personality and job. HTML is read
as descriptive text and remains unchanged in storage. Optional instructions, limited to
4,000 characters, specify appearance, framing or atmosphere.

The initial result includes `registered=false`, `status`, `run_id`, the workflow URI and
a `follow_up` pointing to `process_get_run`. The Galaris system service provides tracking
without granting ProcessAdmin. Final success includes `registered=true` and the target URI.
Technical avatar workflows stay outside the business-process catalogue.

A Process freezes the caller’s image model, provider-configuration fingerprint, manager,
target description and avatar revision. A durable claim precedes provider submission;
interrupted requests with uncertain outcomes become `unknown` without automatic resubmission.
Publication rechecks rights, target and fingerprints. The image, receipt and Process success
persist together. Late results, revocation, deletion or changed profiles fail and preserve
the current state.

`agent_avatar_set` materializes an authorized canonical URI through `app.file_share` into
a bounded temporary file, then cleans it up. Upload, URI and generation share actual
JPEG/PNG/GIF/WebP decoding, a 15 MiB byte limit and dimension limits (16 million pixels,
8,192 per side). Before each write, the Agent module applies EXIF orientation and converts
the image to optimized JPEG (quality 85), within 512 × 512 pixels, preserving proportions
without cropping or enlarging it. Transparency becomes a white background, animations use
their first frame and EXIF metadata is removed. HTTP POST, URI and generated portraits all
use this conversion. Monotonic revisions also detect replacement followed by restoration.
UI readers use the revision to load current portraits when reopened.

## Verification

`back/app/agent/tests/test_agent_admin.py` covers CRUD without HTTP context, scope, connection
protections, the exact 34 functions, revocation and image availability on a mounted server,
and durable publication with failure outcomes. `e2e/specs/agent-admin.spec.mjs` exercises
the assembled API/UI with a synthetic provider: creation, generation, replacement, reopening
through Vue navigation without a full reload, renamed titles and refusal after revocation.
Persistence tests also exercise real URI materialization behind a synthetic provider boundary,
temporary cleanup and the Harness MCP journey with blocking Tasks.
These tests do not measure a real provider’s photographic quality.

Commands: `make tests ARGS='app/agent/tests app/connection/tests app/harnesses/tests app/tools/tests app/image/tests app/process/tests core/team/tests'`,
`make tests-e2e ARGS='agent-admin.spec.mjs --project=chromium'`, `make typecheck`,
`make docs-prepare`, `make architecture-check`. The schema change is `agents.avatar_revision`,
synchronized by DbAdmin through `make sync-db` in development.
