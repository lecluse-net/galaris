<p align="right"><a href="../../fr/dev/README.md">Français</a> · <strong>English</strong></p>

# Developer Guide

See [Testing behavior](testing.md) for test commands, real Vue component scenarios,
concurrency fixtures and the limits of local bridge validation.

The [Lab reference corpus](lab-reference-corpus.md) supplies reproducible editorial and
resource-boundary cases. Frontend builds print `frontend_build_bytes` using
`scripts/report-build.mjs`: raw and gzip bytes for eager static JS/CSS imports, separately
from all chunks. The HTML editor loads asynchronously. Fonts, API calls and PWA precache
downloads are excluded from the eager graph; offline installation still precaches all assets.
Budget inspection and these measurements are described in the [operations guide](reliability-operations.md).

This document describes the architecture that exists in the repository. It serves as a contribution
contract: when an implementation requires a different flow, correct either the code or this
guide, but do not create a second implicit architecture.

To quickly find a surface, use the
[generated map](../architecture/generated/project-map.md). The
[invariants, flows, and state machines](../architecture/README.md) complement this guide,
and the accepted structural decisions are recorded in
[`project/decisions`](../../../project/decisions/README.md). The map is a static index; contracts and
tests remain authoritative for behavior.

## 1. Development Environment

The [Make command catalog](make-commands.md) lists every repository target, its purpose,
and simplification options. `make help` lists the root commands.

`APP_ENV` remains a free-form label for environment identity and future branding.
It defaults to `prod`. The sole derived application mode is `is_dev = (APP_ENV == "dev")`:
`pp`, `test`, `demo`, and every other value use the same protections and behavior as `prod`.

With `APP_ENV=dev` in `.env`, `make update` rebuilds the development images using
the Docker cache, recreates the backend and frontend, synchronizes the database before starting the API,
and waits for services to be ready. To force this mode, use `make APP_ENV=dev update`.
This also switches back to development after using production images.
Unchanged infrastructure services remain running. A failed build preserves running containers;
after a successful build, a single `up --wait` applies changes and waits for service health.
PostgreSQL and TURN are removed only when switched to external or disabled mode.
Production also reuses the Docker cache and checks base images for updates; `RELEASE_DIR` remains
restricted to environments whose `APP_ENV` differs from `dev`.

`make update` builds and deploys existing sources without fetching Git changes.
With a `.git` entry, `VERSION=<reference>` fetches and selects an exact tag, otherwise a remote
branch. Local modifications block only this explicit selection. Use plain `make update`
to deploy local work or configuration. `make start` always keeps existing sources, including when
it needs to rebuild an incomplete installation.

```bash
make install
# Configure .env, including APP_ENV=dev, APP_HOST and TZ.
make update
make typecheck
make tests
```

The backend and frontend use hot reload in `dev` mode. Do not restart the entire
stack after a simple Vue or Python change. After changing a SQLAlchemy model,
privilege, or reference data, run `make sync-db`: the command calls
`core.dbadmin` to converge the `public` schema and datasets without restarting. Use
the logs of the relevant service.

Main stack:

- Python 3.14, FastAPI, Pydantic 2, async SQLAlchemy 2, and asyncpg;
- Pydantic AI for the internal harness;
- PostgreSQL 17 with pgvector, Atlas declarative schema;
- Vue 3, Quasar 2, Pinia 4, Vue Router 5, vue-i18n 11, and TypeScript;
- MCP/FastMCP for tools;
- Playwright/Chromium in an isolated sidecar for the browser Tool;
- Docker Compose for the reproducible environment.

LangGraph and Alembic are not part of the architecture.

### Runtime Health and Supervision

The lifespan registers root loops with `core.runtime`. The supervisor starts them,
stops them in reverse order, and restarts a completed root with bounded backoff. This layer
never replaces domain-specific leases, transitions, or idempotency keys.

The three endpoints have distinct contracts:

- `/api/health` preserves the historical response;
- `/api/health/live` checks only that the ASGI process responds;
- `/api/health/ready` checks the supervisor, critical components, and PostgreSQL, while
  reporting optional bridges as `degraded`.

The backend container healthcheck uses local readiness. A synthetic test traversing the
frontend must remain separate so that a proxy failure does not falsify backend health.

## 2. Layers and Modules

```text
back/
├── core/                 reusable infrastructure
│   ├── api, database, authorize, user, params, i18n, websocket
├── app/                  Galaris business domains
│   ├── agent/            generic agent facade and orchestration
│   ├── harness/            internal Pydantic AI harness
│   ├── task/             task persistence and scheduler
│   ├── llm, tools, messenger, memory, process, browser, ...
│   ├── file_share/       resource URIs, providers, and streamed transfers
│   └── audio/            multimedia normalization and MCP transcription tool
└── bridge/               integrations with autonomous systems
    ├── hermes, n8n, matrix, one_bot, nextcloud
    └── youtube/          URL validation and public subtitle retrieval

front/
├── core/                 API, auth, RBAC, navigation, i18n, utilities
├── app/                  business-domain pages and state
└── bridge/               UI contributions from external integrations

bridge/
└── harness_manager/      generic host service for Compose instances and files
```

Backend modules are declared in `back/modules.py`. Each package can expose a
`router`, models, privileges, a listener, settings, or locales. The central
bootstrap loads only declared elements.

Frontend modules are declared in `front/modules.ts`. Pages are discovered through
file-based routing; navigation is aggregated from the `navigation.ts` files.

The agentic browser is described in
[`docs/en/architecture/flows/browser.md`](../architecture/flows/browser.md). Its container
shares Chromium, but each session has an isolated context and authorization tied to
the agent and task.

Dependency rules:

- `core` does not depend on `app`;
- an `app` domain uses another domain's public facades, not its ORM details;
- a `bridge` adapts an external system to Galaris contracts;
- `front/bridge` exposes the configuration and guide for its `back/bridge`, without duplicating
  the domain's business workflow;
- bootstrap imports may assemble modules, but business logic must not rely on their implicit
  import order.

These rules are also expressed as executable budgets in `back/architecture.toml`.
Each active module declares its permitted `app`/`bridge` dependencies and maximum fan-out there.
`back/architecture-baseline.json` isolates historical debt: inter-module imports that do not yet
pass through a public root, `contracts`, `facade`, or `interface`, as well as existing cyclic
components. `make architecture-check` rejects a new undeclared dependency, an increased budget,
a new private import, or a new or expanded cycle.

When debt is removed, run `make architecture-baseline`, review the reduction in the diff, then
keep the reduced budget in `back/architecture.toml`. This target must never be used to
mechanically accept a regression.

The frontend has the same progressive guardrail in `front/architecture-baseline.json`. The
map analyzes aliased or relative TypeScript/Vue imports and publishes fan-in, fan-out,
direct cycles, and strongly connected components. A new dependency, new private import,
or new/expanded cycle causes `make architecture-check` to fail.

## 3. Agentic Architecture

### Responsibilities

`app.agent` is the single entry point for the agentic subsystem. It contains:

- runtime-independent contracts (`AgentDriver`, `AgentRunRequest`, events,
  results, policies);
- the registry and availability state of drivers;
- model resolution and `standard` and `high` execution strategies;
- the dispatcher, planner, briefing, and common workflow;
- the public `run`, `stream`, and `cancel` facade, as well as task adapters;
- the port to durable persistence.

`app.harness` is the internal Pydantic AI harness: adaptation to the `AgentDriver` contract,
agent construction, toolset, history, media, streaming, registry of cancellable runs, and
effect checkpoints. `bridge.hermes` is its external counterpart. The dispatcher, planner, and briefing remain
in `app.agent`, because they prepare an `AgentRunRequest` before entering either driver.

`bridge.hermes` contains the client, driver, configuration, and adaptation of the
Hermes runtime. Its administration routes may be used by the Hermes UI; a functional
execution must never bypass `app.agent`.

The `harness_manager` host server is separate: it generically manages directories,
Compose containers, bounded actions, and files for any harness. It knows no Hermes
API or CLI. `bridge.hermes` generates Hermes artifacts and then consumes this generic contract
under `/instances`, with a separate instance and container for each agent.

The client for this contract lives in `back/bridge/harness`. Its coordinates and shared
secret are database Params shared by all harnesses, editable in Preferences → Harnesses.
The secret is encrypted at rest. The UI also prepares the local or remote host manager `.env`.

Preferences → Harnesses separates **Internal harness**, **Managed harnesses** and **External harnesses**.
Each technical policy is edited within the corresponding harness configuration and applies
to all harnesses using the same provider. The internal tab exposes the `internal` policy
and the binary file input limit.
**Tasks and execution** groups scheduling, retries, overall budgets, objective creation,
collaboration and per-run model request and tool call limits. The internal engine enforces
these limits; compatible network harnesses receive them and are responsible for enforcing
them. Legacy links to the harness `common` and `advanced` tabs redirect to this page.
It also contains Planner and Briefing blocks. Each lists the harnesses whose
pipeline policy uses that mechanism and is hidden when the list is empty. The API exposes
the provider policy in preference to its transport policy. Briefing also requires at least
one eligible effort level. Currently only the internal harness uses Planner; Briefing is hidden.
The briefing prompt is a persistent Param (`ai.briefing-system-prompt`) with a canonical default;
editing it does not activate the mechanism. Lab evaluations retain their explicit overrides.
Planner retains its prompt and depth, node and leaf limits.
Automatic incident and LLM trace retention is configured in Logs, separately
from manual cleanup. This organization preserves persisted keys and values and does not
introduce per-harness overrides for execution limits.

Displayed and editable sizes use decimal MB (1 MB = 1,000,000 bytes), including small
attachments. `core/util/fileSize.ts` centralizes localized formatting and conversions;
API contracts keep their units. Size `SettingField` definitions declare `sizeUnit` to
convert their bounds and step too. Legacy MiB settings accept fractions so users can enter
whole decimal MB. Defaults are 20 MB for the internal harness, 4 MB for inline attachments,
1 MB for webhooks and 0.064 MB for raw process data. DbAdmin replaces only exact former
defaults; other stored values and explicit resets are preserved. The manager keeps its
historical API and `.env` units, using fractions equivalent to 1 MB and 512 MB by default.
Avatars are limited to 5 MB, SVG icons to 0.064 MB, 3D previews to 32 MB and exports to
64 MB including at most 12 MB of HTML content.

The Hermes manager uses only the harness manager and controls one Compose project per agent. The
`BASE_DIR/<agent.code>/data` directory is mounted at `/opt/data` in the
`<agent.code>-agent` container; workspaces, skills, sessions, memory, and secrets are never
shared with another agent. Media passes through the manager's streamed file channel rather than
`/api/files`, whose 100 MiB limit is not part of the Galaris contract.

For execution, `standard` and `high` use `/v1/runs` sessions; `high` retains its
more powerful model. Kanban is disabled by an internal constant in the Hermes driver, not
configurable through deployment. Its adapter remains isolated without a production management
backend; re-enabling it would require a new decision compatible with container isolation.

The manager always injects the Galaris OpenAI proxy and the agent's effective model last,
then removes direct provider keys. Hermes no longer has a setting that allows bypassing this
gateway: all of its LLM calls therefore remain correlated and traceable in Galaris.
The URL, model, and port of its execution API remain internally generated data from the
provisioner; `/api/hermes/configurations` does not expose them to operators.

The direct run builds its trace from the stream and the persistent Hermes session. It no
longer reconstructs function calls from `LLMCall.tool_calls`. This fallback remains in the
Kanban code but returns immediately while the internal constant is disabled.

The harness manager, its authentication, and its systemd service are documented in
[`docs/en/components/harness-manager.md`](../components/harness-manager.md). The specifics
of the Hermes consumer are documented in
[`docs/en/components/hermes.md`](../components/hermes.md).

`app.task` owns the SQLAlchemy models, durable state machine, leases, attempts,
retries, administration commands, and scheduler. It does not choose the driver, model,
or whether to use the planner or briefing.

Its scheduling, retry, planning, budget, and collaboration limits are stored in `params` and
administered under **Preferences → Tasks**. Consumers read their typed view at the boundary of
a new action; an execution that has already started retains the bounds captured at startup.

Params declared with kind `prompt` follow a contract similar to Debian configuration files. A
durable `NULL` value automatically follows the English default shipped by Galaris. Prompts live
under `core.params`, never in i18n, and are not translated; only their UI labels and descriptions
are translated. A customization stores the fingerprint of this default; if the shipped bundle
changes, DbAdmin preserves the value and the UI offers the choice of keeping the customization
or adopting the new default after comparison. Startup always remains non-interactive.

### Shared Context, Session, and Durable Memory

`app.agent.context` composes named providers before entering a driver. A provider may
supply instructions, shared context, conversation history, structured candidates, and metadata,
but must not modify the Task. Each failure is fail-open and recorded in the run metadata.
`app.agent.observers` is a small projection bus, not a runtime lifecycle manager: it notifies
of profile changes and terminal Tasks. Its observers must schedule short, idempotent work,
never perform an expensive extraction on the response path. The Memory projection of agent
profiles is its primary active consumer.

For a human Messenger Task, non-conversational candidates form a continuity capsule strictly
bound to the canonical contact: recent root Tasks, active resources from their Working Sets,
and memories sealed to the contact. The Topic, assigned later by Dream, is never a filter for
this capsule. The composer deduplicates, ranks, and bounds excerpts, merges resources proposed
multiple times under the same canonical URI, then freezes the manifest on the root Task before
dispatch. All children and retries receive the same references; the current Working Set remains
dynamic. An unproven identity does not authorize fallback to the room's collective history. The
Task view renders the manifest and its provenance for inspection under “Provided context.”

Explicit exception: when a new conversation Task has already received a standalone objective
built by the admission call, this capsule and the source history are not rebuilt.
Providers retain only the Task's live context, notably its Working Set, and the server metadata
of the room and interlocutor.

`app.messenger.session` projects the recent session from the canonical journal. For an identified
human Task, reading follows the exact contact across rooms and connections; the room
continues to bound the conversational round and its routing. As soon as a canonical line exists,
local runtime histories are no longer merged:
they are only fallbacks. The internal harness supplies this snapshot as native
Pydantic AI history. Hermes receives the same canonical conversation, while its session cache
remains non-authoritative. Messages from this snapshot are never proposed a second time to the
continuity capsule. In the conversational prompt, durable recall and operational or documentary
continuity have the respective sections `Long-term memory` and `Continuity context`.
These ordinary exchanges do not become durable memories on every turn;
explicit promotion remains available through memory tools. Autonomous extraction is
performed outside the terminal path by `app.dream`, one historical Task at a time.

A session can be requested with the canonical UUID of `MessengerRoom` or its external identifier.
Resolution is always bounded to the connection, then the query accepts both corresponding
canonical columns. A local UUID must therefore never be compared only with the external
`Message.room_id` field, or history can be silently lost during a retry.

The Hermes binding does not reuse the room as a transcript identifier. A condensed key of the
full address remains stable in `X-Hermes-Session-Key`, while an opaque `session_id` follows the
compaction lineage. The checkpoint retains both the run origin and its effective tip. Historical
bindings are deduplicated by agent during upgrade, then a `room:*` scope can be claimed by only
one concrete connection. Final rotation always compares the checkpoint's origin pointer: a
late-retried task cannot move backward a conversation that a newer run has already advanced.

Real-time voice calls follow a lineage distinct from Tasks. `app.voice` persists the
session and each turn; the agent facade receives an `AgentRunRequest(task_id=None)` correlated by
`run_id` and `voice_turn_id`. A barge-in ends the turn as `INTERRUPTED` and carries its effective
objective into the next turn. The new transcript therefore completes the interrupted request
rather than replacing it, and no Task error is created for a normal dialogue interruption.

Before delegating substantial new work, the text and voice controllers read related Tasks that
are still active or upcoming, human pauses no more than 24 hours old, and at most the
two terminal Tasks completed less than one hour ago. Their projection contains the local creation
date and `state_since`, based on the last update with fallback to creation, as well as an
objective bounded to 250 characters, the revision, amendability, and operational state. The
model chooses `CREATE_NEW`, `AMEND_CURRENT`, or `AMEND_QUEUED`, or asks a question if the
relationship between deliverables is ambiguous. The Task service remains authoritative: it
checks scope and revision, notably refuses materialized plans, and records every accepted
amendment in `task_amendments`. Colleague or Process expectations are projected as `WAITING`
with their question and deadline; a human pause remains `PAUSED`.
An amendment strictly preserves the same artifact or primary target and substantially identical
success criteria. A target, repository, resource, deliverable, or separately verifiable result
requires `CREATE_NEW`, even when it extends the same incident. The round exposes the
`TaskAmendment` objects it produced. Resuming an amended Task preserves the effect replay
journal, but invalidates the old model history; the objective fingerprint prevents an obsolete
checkpoint or terminal result from overwriting the new run. The scheduler closes this
old attempt as canceled, without retry or error on the amended Task.

Any new root originating from a conversation then goes through a dedicated structured call using
the agent's `standard` model. It produces the label and standalone execution context from the
admitted turn, canonical history, Memory, continuity, related work, and their references. The
instructions for this construction come from the administrable Markdown Param
`ai.task-objective-system-prompt` and follow the shipped default when no customization is
registered. The server then composes the objective from two sections: the source request quoted
without rewriting and the generated context supplement. Admitted source messages and attachment
references are preserved before conversation budgeting and display annotations; any HTML in the
message is escaped as text. Voice uses the admitted request as its source.
`Task.data._original_demand` retains that source alone. The context resolves earlier references,
retains applicable constraints, and identifies this Task's scope when the message requests several
independent outcomes. The values sent to `conversation_task_submit` remain hints and cannot erase a
source constraint. The backend alone retains the connection, room, interlocutor, Topic,
contact, and the choices `@exec`, `@plan`, `@standard`, `@high`, `@effort`, or `@approve`. In
native Chat, `conversation_task_submit` exposes no effort choice: the Task dispatcher decides
between `standard` and `high`. Explicit directives override this conversational choice and remain
persisted as creation constraints, notably `@high`. `@plan` implies creation of a planned Task
and `@effort` implies creation of a Task with additional reasoning overhead; `@task` alone
retains the profile setting. The tags
`@task` and `@effort` are removed from visible text and their intent
is carried through server metadata. The parser preserves `@briefing` for compatibility,
but current policy refuses its admission. It rejects
invented URIs, checks idempotency before this call, and rechecks round freshness before directly
persisting the `Task`; no intermediate objective object exists.
This Task is then marked as carrying a standalone objective. The dispatcher reads this `label` and
`objective`, while the Messenger session, Memory, and continuity used by the admission call are
purged from downstream prompts. Server fields for the room and interlocutor remain in
`Task.data` and messaging context; future contributions from the planner, briefing, Working Set,
and harness remain independent.

For a numbered interaction, exact responses continue to be handled without a model. Text that
does not match any option is admitted as a conversational round with only the pending interactions
within its Messenger scope. The conversational LLM may resolve them through
`conversation_choice_resolve`, but only to a persisted option. An ambiguous intent
causes a question; an instruction such as “don't do that, do this instead” may reject the
current approval and then amend the Task through the durable path above.

For a human textual round, the dispatcher returns `EXEC standard` without loading a model or
performing inference, on every text channel. The executor chooses its tools and durable work
admission according to the action policy. The controller delivers a successful response without
judging its wording, repetition, or missing tool activity. Only an execution error can trigger
the scheduler's bounded retry, subject to its effect-safety conditions. Admission persists the
Task before acknowledging success. This Task retains the agent's driver, including Hermes,
while the short round runs through the internal controller. Technical conversation labels are
ignored as memory-recall subjects and injected recent candidates are bounded. For AI peers,
the dispatcher retains its `EXEC`/`END` gate and applies its deterministic fallback without
retrying malformed structured output.

The Param `ai.conversation-action-policy` alone arbitrates between a direct response, a small
governed conversational effect, an assigned Process, and a Task. An explicitly available Memory
search, read, capture, correction, or deletion can therefore be executed in the round without
creating a Task. A compatible Process retains absolute priority; the Task handles durable
resources, deliveries, third parties, external systems without a Process, and substantial work.
The conversational Process catalog remains a data projection and no longer repeats this policy.

The common prompt creates a single non-reliability boundary before histories, memories,
resources, and retrieved results. Conversation and voice prompts declare identity as direct
first-person speech, then briefly recall this embodiment at the end of the tree,
before the configurable suffix. This intentional reminder avoids character prefixes and role
narration without changing the textual inventory of tools.
For Tasks, the same builder renders name, gender, position, personality, and job description in
the common system foundation. The profile also governs the writing, formatting, and author of
deliverables, including an explicit signature preference when relevant. Internal, Hermes, and
network harnesses receive this canonical profile; a signature modifies content and never by
itself constitutes an instruction to send or deliver.

Native conversation messages use a compact envelope
`[local ISO timestamp | author]` shared by the internal harness and Hermes. Roles remain native,
attachments remain linked to their message, and complete canonical metadata remains internal to
routing and tracing. The system prompt renders language, channel, room, current sender,
location, and continuity once in `Turn context` or `Call context`; the output parser
continues removing old envelopes for session compatibility.

Commands to stop an active Task and resend an existing attachment bypass the model: the
controller uses canonical Messenger room links and UUIDs, executes the idempotent effect, then
responds from its receipt. Admission refuses to convert a simple resend of an existing version
into a new generation Task. A dispatcher inference failure for an AI peer produces `END`;
other execution errors propagate to the scheduler. Narrations preceding a tool call remain only
in the audit trace.

`app.memory` separates identity and governance from content storage. PostgreSQL owns
items with their direct owner, grants, revisions, sources, links, usages, idempotent acquisitions,
and jobs. There is no intermediate memory space. `ResourceStorage` manipulates
only bytes by opaque identifier; the `native` provider writes atomically under the fixed
`/data/memory` directory. Search applies owner, access, visibility, and validity in SQL before
ranking. The automatic brief ranks `core` memories with the other types instead of reserving
them an unconditional place. Ranking first requires direct and informative lexical evidence—not
a simple conversational word—or sufficient semantic proximity, then combines topic membership,
confirmed links, provenance, freshness, and local centrality before discarding near-duplicates.
The result can therefore contain zero to eight items by default, without an LLM call. The Agent
profile's Memory projection is excluded from this automatic brief: its identity and personality
already come from the canonical profile in the system prompt. It remains available through an
explicit Memory search.

Bounded agentic recall always uses the hybrid. Every `file_search("memory://", ...)`
and `POST /memory/search` merges FTS candidates with an exact cosine search in the
`app.memory` pgvector projection. No HTTP, Python, or MCP contract allows choosing a lexical
mode: it remains only the automatic fallback reported when unavailable. The Python facade
`search_memory(text, agent_id=..., ...)` directly returns a list of ranked items,
without a public score. Pool size, semantic length, weights, and diversity come exclusively from
the global Params in the Memory section. Chunks are versioned by fingerprint, model, and
dimension, produced by the worker after commit, then replaced atomically. ACLs and dates remain
SQL filters applied before ranking. If the current profile's Vector usage, the index, or the
provider is unavailable, the contract reports degradation and returns the lexical result. The
automatic brief uses the same hybrid recall;
`/memory/browse` retains paginated lexical browsing. `/memory/recall` is a deprecated
HTTP alias for ranked search without a score.

With a current Topic, recall separately merges FTS and pgvector within the dossier, then FTS and
pgvector within the permitted global scope. Dossier membership is a first-class weighted signal,
configurable through `MEMORY_RECALL_TOPIC_WEIGHT`, without removing the global path. A
positive membership suggestion can also break ties between already relevant candidates using the
`MEMORY_RECALL_SUGGESTED_LINK_WEIGHT` discount, without becoming a canonical link. Without
a current Topic, the engine preselects the closest public Topic by the same vector that contains
at least one accessible memory, then applies this prior with a strength proportional to
similarity. An exact contact excludes conversational memories from other interlocutors from the
global path. Public Topic projections remain indexable for dossier preselection but are excluded
from factual recall. Dream also produces `suggested=true` attachment, anomaly, merge, or split
links from these vectors; none of these signals alone modifies a canonical `topic_contains`.

Working HTML documents are `MemoryItem`s with `node_kind=document` and type
`working`. They are the canonical home for content authored and shared by agents, even within
a single Task. Memory and File Sharing are mandatory system services; resource ACLs and
context restrictions still apply. See the [document contract](editorial-html.md).
They remain private at creation, are neither deduplicated with ordinary memories, targeted
by Dream, nor automatically forgotten due to inactivity. `file_create`, `file_edit`,
`file_read(document://...)`, and `file_append(document://...)` maintain
atomic revisions without exposing a complex patch protocol to the model. `document_share` creates a direct
`read|edit|none` grant after resolving the target human, agent or team; only the owner administers these grants
and can forget the document. `file_search` provides discovery and the brief injects only bounded
excerpts. Each revision retains the agent and, when it exists, the authoring Task.
Attachments are exposed under `document://<uuid>/attachments/`: `file_list` enumerates them,
`file_read` and specialized tools consume them, while `file_create`, `file_copy`, and
`file_delete` require write permission on the parent document. Adding or removing them does not
create a content revision.

Each Task tree also has a versioned Working Set in its root's data.
It centralizes active references—primary document, auxiliary documents, provider resources,
final artifact, destination, and delivery receipt—without copying their content. A new resource
with the same role leaves the old one in `superseded` state. The
`task_working_set` provider injects this bounded registry into every step and related
conversational retries. In direct conversation and real-time audio, where no current Working Set
exists, providers inject documents recently handled by Tasks and tool traces from completed
rounds for the same agent and contact under their `document://` URI, without broadening selection
to the room or extracting a URI from free text. The first document created in a Task takes the
canonical role `primary_working_document`; subsequent documents receive a distinct reference role.

File references for this Working Set and the tools follow the URI contract of
`app.file_share`:
`console://path`,
`<code-tool>://room-provider/attachment-uuid`, `memory://uuid`, `document://uuid`,
`document://uuid/attachments/attachment-uuid`,
`galaris://task/uuid`, `galaris://process/workflow-id`,
`galaris://skill/skill-code/SKILL.md`, a public HTTPS URL, or
`<code-tool>://locator`. The code of a Tool
that provides file sharing or Messenger is its scheme and must be lowercase;
protocols (`http`, `https`, `file`, `ssh`, etc.) and native schemes are reserved.
Messenger and file sharing are capabilities of the same Tool: they never add a generic scheme.
Thus, a Talk attachment uses `nextcloud://<room-token>/<file-uuid>` and a
Telegram attachment uses `telegram://<chat-id>/<file-uuid>`.
The integrated `file_sharing` Tool, implemented by `app.file_share`, exposes `file_schemes` and
all `file_*` operations on both runtimes. This property does not depend on the manipulated
scheme: `galaris://` is a provider for business projections, while the `galaris` Tool retains
its business actions. `file_create` creates and returns a complete URI, `file_write` replaces an
existing resource, and `file_read` returns paginated UTF-8 text or a small binary as base64;
`file_copy` is the sole primitive for persistent streamed copying. Specialized tools that consume
bytes (`image_read`, `image_generate` attachments, `audio_transcribe`, Messenger sending)
accept these same URIs directly and use `materialize_resource` to create a bounded,
automatically cleaned temporary. They never ask the agent for a preparatory local copy. A
collection destination preserves the name returned by source metadata, including when its locator
is opaque. `galaris://` projects Tasks, conversation rounds, Goals, Goal cycles, and assigned
Processes as read-only, with their domain ACLs. Under `galaris://skill/`, an active
`skill_management` connection additionally allows reading and modifying user skill files; system
definitions remain read-only. The integrated `console` Tool declares its `file_share_config`
flag with the native `console` service; `console://` directly designates the SSH home and is not
duplicated as an external provider. Thus, `console://my_file` means exactly `~/my_file`, and no
layer prefixes its URI with a virtual `main/` segment. When available, the console is the only
local space announced to the agent and the automatic destination for tools that allow a default.
Without a console, no local fallback exists: `file_list` requires a provider URI, producer tools
require a writable destination, and attachments retain the exact scheme of their originating
Tool. Relative paths and former implicit local schemes are rejected.

All native MCP functions pass through the same error rendering. A failure exposes to the runtime
a categorized cause, technical type, next action, and a short correlatable reference; a file
error adapts its advice notably for `file_create`, reads, and replacements. The server log repeats
this reference with the Tool, category, type, and only the code locations from the stack. It
records neither arguments, content, nor arbitrary provider text. Only explicitly declared safe
business errors may transmit their details to the model; the others remain scrubbed while
retaining an actionable diagnosis.

The file inputs of `process_start` and `process_admin_start` also use the `uri` key and the
`app.file_share` facade. The run snapshot retains the source reference, and the machine endpoint
materializes a bounded temporary copy for the engine on demand. A workflow can therefore consume
a console, Nextcloud, Mail, Messenger, or HTTPS resource directly without a preparatory copy
step.

To avoid turning a very long Goal objective into an impossible FTS query, the brief uses a
bounded seed: the Goal title, otherwise the Task label without a cycle suffix, otherwise a short
excerpt of the objective. A common system policy asks the model to evaluate recall relevance for
`high`, recurring, or long-running work, but to call `file_search(memory://)` only if the
brief is insufficient and durable context could change the work. Authoritative business tools
remain mandatory for current state.

The trace distinguishes the automatic brief from MCP calls. `context`, `search`, and `read`
usages are separate, and the execution result retains the bounded query, the numbers retrieved
and actually injected, truncation, and the brief UUIDs, never its text. Logfire and
`/memory/metrics` expose only counters and histograms with bounded labels; `/memory/retention/preview`
estimates the effect of a global duration without mutation before activation.

Eligible acquisitions are applied immediately and refusals are automatic. Their internal journal
serves provenance, idempotency, and retry, never as a human validation queue. The interface
allows auditing, correction, and forgetting.

Dream's automatic extraction covers successful Tasks, textual conversation rounds, and
transcribed Voice turns. It requires a source only when its `topic_id` is non-null; conversational
sources also require their exact contact. Text rounds and Voice provide at most five prior
messages, separate from the current turn. The server first recalls permitted ordinary memories.
Only candidates with strong semantic similarity or substantial lexical overlap may still be
proposed to `LINK`; Topic proximity is insufficient. The output chooses `CREATE`, `LINK`, or
an empty list equivalent to `IGNORE`.
It must be a complete JSON object: after a second invalid attempt, the receipt enters
retry or error instead of silently repairing a fragment. `LINK` only adds the new provenance to a
candidate and does not rewrite its content. Any target outside recall or not owned by the current
agent is rejected. Creations and attachments are counted separately in Dream. A creation must
declare high future utility and a closed retention rationale; searches, public facts, deliverable
summaries, and one-off details are excluded. The prompt is administrable under
`ai.memory-extraction-system-prompt`. `MEMORY_CAPTURE_ENABLED` controls these three extractors
without disabling other Dream work.

Dream requests only one operation per pass and alternates fairly between its mechanisms.
The four mechanisms `memory.attachment_text`, `memory.attachment_document`,
`memory.attachment_image` and `memory.attachment_video` fill empty memory items belonging to
active attachments, including existing attachments. `DREAM_ATTACHMENT_TEXT_ENABLED`,
`DREAM_ATTACHMENT_DOCUMENT_ENABLED`, `DREAM_ATTACHMENT_IMAGE_ENABLED` and
`DREAM_ATTACHMENT_VIDEO_ENABLED` all default to false. Dream preferences expose four checkboxes
and a cost warning recommending suitable local models. They share Dream's idle gating and rotation.
The composition root injects Image and Audio services through Dream's public ports. Audio decoding
runs in a bounded process, killed and reaped on cancellation before temporary files are cleaned up.
UTF-8/UTF-16 text, text PDFs and DOCX/XLSX/PPTX/ODT/ODS/ODP documents are extracted in a bounded
process and summarized by the owner's Dream model (the current profile for human-owned documents).
Documents without extractable text use the native document model; images use vision; videos use
audio transcription followed by Dream summarization. Provider-rejected formats and videos without
audio retain empty content and follow the existing bounded retry policy. Extraction limits are
32 MiB, 500 PDF pages and two million characters; native document input is limited to 16 MiB and
video to 1 GB. Exceeding a limit never produces a silently truncated summary.
Writes recheck the document, ownership, active attachment and empty revision, preserve an HTML
revision and trigger reindexing. Concurrently added text is never overwritten. Checkpointed results
resume without new inference; disabling an option prevents application until it is enabled again.
Sharing permissions and the parent document remain unchanged.

The rotation nevertheless preserves a strict dependency between the two classifications:
when they occur in the same pass, `topic.classify_message` is always attempted before
`topic.classify_task`. A Task originating from a conversation therefore cannot precede its source's
Topic; other mechanisms retain their relative order in the rotation.
A Task extraction remains ineligible while its Topic classification receipt is `running` or
`retry`; counters therefore do not simultaneously count both steps for the same subject.
`DREAM_POLL_SECONDS` is a pause from end to start: it begins when the current operation is
completely finished, then must elapse before the next one. It is not a periodic window in which
a long LLM call would consume part of the interval.

`skill.learn_task_outcome` complements factual extraction with separate learning based on
observable evidence: attempts, tool results, children, Goal verdict, human correction,
and Memory usages. An LLM-free filter removes weak signals, then the structured output cites its
evidence before creating, strengthening, revising, or weakening a `LearnedSkill`. The material
fingerprint makes rescanning idempotent and allows a separate late correction. Dream also traverses
historical terminal Tasks from oldest to newest, one per pass; receipts prevent counting the same
material twice. This mechanism creates no `MemoryItem`.

`DREAM_SKILL_LEARNING_MODE` is `off`, `observe`, or `learn` and remains `off` by default. `observe`
retains only Dream diagnostics and `learn` applies the checkpointed decision. A skill is first
stored as a non-injectable candidate. It is promoted and injected in addition to assigned
skills when at least `DREAM_SKILL_MIN_EVIDENCE` distinct Tasks have confirmed the same
procedure and it reaches `DREAM_SKILL_ACTIVATION_SCORE`; the repetition threshold is 3 by
default and `DREAM_SKILL_MAX_ACTIVE` bounds the number of active procedures. These settings are
administered in `params`, not `.env`.

When a Memory tool writes during a Task, it immediately associates the created or merged item with
the provenance `task:<uuid>`. The `app.memory` reconciler then derives Topic, contact,
Contact–Topic, Goal, and Process edges, as well as authoritative conversational scopes.
It is idempotent, calls no model, processes touched nodes after each Dream success, and performs
a scheduled global sweep only during zero load. Triggers after Dream and scheduled triggers are
configured with `MEMORY_LINK_RECONCILIATION_TRIGGER_MODE`; the global interval uses
`MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS`. The Dream preferences page exposes the status and
immediate manual launch, executed within the request without waiting for zero load. The reconciler
has neither a receipt nor a Dream gauge. The command
`make rebuild-memory-links` enables the same global processing; `ARGS='--item-id <uuid>'` bounds it
to one node.

In the graph, the selected agent remains implicit because it already bounds accessible data.
Public Topics are additionally limited to those containing memory owned by or directly shared
with this agent; another agent's dossier does not appear through visibility alone.
Topics, contacts, and documents have distinct shapes; their structural relationships are
strengthened and labeled, while suggestions remain fine-grained and discontinuous.

`app.memory.source_projection` adapts canonical `Agent`, `Goal`, and `GoalCycle` data into
private Markdown. Sources retain their `memory_item_id`; the item in turn retains a unique source
identity. `app.memory.messenger_contact` separately projects the minimal identity of human
senders observed in `social` memories, with a hashed key based on the owning agent, bridge code,
and exact native identifier. Connection, room, and message content are excluded.
`memory_contact_identities` then associates multiple Messenger addresses or a proven `USER`
identity with the same canonical item. `app.contact` provides administration and transactional
merging; this operation repoints all memory scopes and conversation lineages before forgetting
the duplicate. These `source_managed` items never pass through public mutations, even with
administrative rights. Agent/Goal observers only schedule a durable job after the business
commit. The worker always reloads the latest source version, making delayed or reordered jobs
safe. It retains a revision only when the projection changes, links a cycle to its Goal through
`cycle_of`, and forgets resources when the source is deleted. Cycles are loaded by a dedicated
query, sorted by descending sequence, and limited to the 100 most recent. This window is also
projection retention: older items are forgotten in bounded batches and their source pointer is
reset to `null`, without deleting the canonical cycle. Messenger observes contacts before
interactions with a fail-open fallback; its journal enables idempotent replay.

The canonical Markdown description and tracking of a Goal no longer live in these projections:
each Goal references two private working Memory documents. Their content can be modified from
the Goal and Documents UIs, but their owner, title, and path remain exclusively controlled by
the Goal. The folder bears the scrubbed Goal title and the documents are titled
`<Goal title> — Description` and `<Goal title> — Suivi`, updated when the Goal is renamed.
DbAdmin reconciliation also updates existing titles to this format.
They also have deletion protection independent of
`source_managed`.
A direct document edit revises the Goal and requeues its deterministic projection. The
`app.goal.document_store` port maintains the business boundary; its concrete adapter is supplied
by `app.memory` during bootstrap.

The durable `goal_folder_reconcile` job files Goal documents and deliverables identified through
their Task provenance under each user's personal `Goals / <Goal title>` folders. Optional
`user_id` and `goal_id` filters combine; omitting both requests a global sweep. Current read access
and existing personal classification are preserved, and empty folders are not created. Goal,
document, user and access changes enqueue work; DbAdmin queues the global catch-up. Opening the
page does not trigger a scan. Deleted folders may be recreated on a later pass. Administrators
can enqueue work through `POST /api/memory/goal-folders/reconcile` (`MEMORY_ADMIN`, `{}` for all,
response `202`). See [decision 0107](../../../project/decisions/0107-personal-goal-folders.md).

Dream also examines completed Voice turns that have a textual objective, then associates new
memories with the structural node of their conversation. Realtime turns without a transcript
remain subject to explicit memorization. Finally, `memory.project_process` projects without an
LLM the assigned definitions and sanitized successful outputs: never inputs or raw snapshots,
12,000 characters maximum and 20 results per agent and process.

Backfill and provider changes use the same path as runtime:

```bash
make rebuild-source-memory
make rebuild-source-memory ARGS='--all'
make rebuild-source-memory ARGS='--recreate --provider native'
make rebuild-messenger-contacts
make rebuild-memory-index
make rebuild-memory-index ARGS='--all'
```

The three `rebuild-source-memory` modes process, respectively, missing pointers, all
projections without changing UUIDs, and a recreation with source UUIDs rewritten. The Messenger
command replays the latest human senders from the journal without depending on the bridge
registry. The two index commands repair or recalculate the semantic index for the selected
vector model. Dataset synchronization automatically reconciles source projections, assigns
public Topic projections their owner key `topic_id`, then reconciles Messenger contacts and the
index. Goal Tasks are excluded from generic terminal capture because their result belongs to the
`GoalCycle` projection.

The MemoryProvider plugin projected into Hermes retrieves exactly this brief already calculated
for the active Task. It exposes no second set of tools: complete actions pass through the
`memory_*` MCPs, and native Hermes writes become immediate acquisitions. See the
[memory flow](../architecture/flows/memory.md) and
[ADR 0010](../../../project/decisions/0010-governed-agent-memory.md).

The manager selects `memory.provider: galaris`, maintains the explicit activation
`plugins.enabled: [galaris-memory]`, and projects the same provider under the layouts
`plugins/memory/galaris` and `plugins/galaris`. The former is the current specialized layout; the
latter preserves compatibility with Hermes 0.18, which discovered user providers at the root of
`plugins/`. By default, it also sets `memory_enabled=false` and
`user_profile_enabled=false`, then removes the native `memory` toolset: `MEMORY.md` and `USER.md`
are therefore neither injected nor modified. This layer precedes `hermes.default.config`, then
`Agent.hermes_config`; an explicit global or agent-specific value can therefore re-enable file
memory, with the agent configuration remaining authoritative. A profile synchronization restarts
Hermes after this projection.

### Execution Flow

```text
Task SQLAlchemy
    │  app.task.agent_adapter
    ▼
AgentTask + app.agent facade
    │
    ├── dispatcher ──► EXEC / PLAN
    ├── driver policy ──► optional briefing
    ├── model_resolver ──► model frozen for the run
    ├── DriverSpec ──► direct strategy frozen
    ▼
Immutable AgentRunRequest
    │
    ├── InternalHarness ──► Pydantic AI
    ├── HermesAgentDriver  ──► standard: /v1/runs
    │                         high: /v1/runs + high model
    └── Codex Harness ──────► App Server ──► Galaris Responses gateway
                              standard: Agent Executor
                              high: high Agent Executor
    ▼
AgentEvent* + a single terminal ExecutionResult
    │
    ▼
app.agent applies the result, app.task persists it and resumes the workflow
```

The model and the `reasoning_effort` associated with its tier are resolved once before
entering the driver. These two values remain independent of the Task's execution effort.
The Hermes and Codex LLM gateways use this frozen trace context; they must not recalculate a
different model or reasoning effort in the middle of the run. Codex uses the provider name for
App Server capabilities and simultaneously passes the stable Galaris code to the Responses
gateway. Internal selection of the Kanban adapter belongs exclusively to the Hermes driver and
remains disabled.

The canonical scale is `none`, `low`, `medium`, `high`, `xhigh`, `max`. An absent value means
“automatic” and leaves the choice to the harness or provider. The former `minimal` value is
accepted only when reading historical data, normalized to `low`, and never emitted again. Managed
bridges and harnesses translate this scale when a runtime uses different levels.

### Streaming Contract

A driver emits zero or more `message` events, followed by exactly one `result` event. The
facade rejects:

- a stream without a terminal result;
- multiple terminal results;
- an event after the result.

The `result` text is authoritative. An agentic runtime may have streamed provisional text
before a tool call; its adapter then retains this progress as a semantic `thinking` block
and replaces the terminal text with the exact final response. For network Harnesses,
`galaris.agent-result/v1.result` carries this authoritative response while Chat
Completions chunks remain ephemeral live events. Tool completions and public reasoning
use `galaris.agent-message/v1` and are never reconstructed from the final text.
The frontend retains these live events exclusively as a list of `AIMessage`s; it does
not create a partial `ExecutionResult`. At termination, only the persistent `ExecutionResult` of
the Task or round becomes authoritative.
The live projection is append-only: an already streamed fragment is neither replaced nor deleted.
Divergent revisions are retained in a new semantic block, notably for Codex reflections
segmented by `itemId` and `summaryIndex`. The optional `stream_id` of an
`AIMessage` attaches live fragments to this block: the frontend concatenates them immediately
and the Harness client compacts the terminal trace, without persisting one timeline event per
delta.

The facade observes `thinking` blocks and generated text from all drivers. If the same reasoning
pattern repeats more than 30 consecutive times without tool activity, it immediately closes the
stream and fails the run with an explicit degeneration error, without automatically retrying
the Task. The pattern content is not copied into the error or guardrail logs.

A driver declared without streaming automatically uses its non-streamed result. Cancellation
capability is refused until `supports_cancellation` is explicitly enabled. The internal and
Hermes drivers enable it. The internal driver cancels the run coroutine and then cleans up
console, MCP, and browser sessions; Hermes temporarily associates the Galaris UUID with the
direct `run_id` and calls `/v1/runs/{id}/stop`. An old Kanban retry retains its historical
processing: worker reclaim followed by card archiving.

The internal harness checkpoints each MCP effect before and after execution. A retry reloads
typed Pydantic AI history and reuses completed results. A checkpoint stopped between the two
writes is not automatically retryable, because the external effect may have succeeded without
its result being persisted. Fallback Messenger delivery uses the same journal and, once confirmed,
resumes directly from its terminal result.

After a genuinely successful tool result, a generic projection records its references in
the Working Set. Business errors from documents, shared files, and Messenger deliveries are
tool errors, not strings resembling success. File production cannot complete the root Task
without a final artifact; a Messenger origin additionally requires a receipt. Subtasks never
automatically emit their terminal text into the conversation, even though they may explicitly
use a Messenger tool required by their step.

Tools in the internal harness explicitly declared `safe` may execute in parallel under
a bounded limit; `exclusive` tools remain barriers. Each native call opens its own short
SQLAlchemy session. The checkpoint journal serializes only its writes and persists them in
independent transactions that reload the locked Task. An error and its rollback therefore cannot
contaminate another tool or the scheduler session. The driver retains this sequential session
during initialization, then the internal harness releases its transaction before model execution.
Each parallel branch explicitly replaces the context with its own short session; it never uses the
scheduler's inherited session. Three identical failures or three identical successes without
progress interrupt a tool loop; the document creation signature groups drafts with the same title
and role even when their generated content varies. A stop for success without progress triggers
one bounded finalization pass from the acquired history. When a scope selects a file or document
write tool, the read and inspection tools needed for verification are included as companion
capabilities.

### Static Policies

Helpers are not selected by `app.task`. They are hard-coded in the driver's descriptor:

```python
DriverPipelinePolicy(
    use_planner=True,
    use_briefing=False,
    briefing_efforts=frozenset(),
)
```

Current matrix:

| Driver | Planner | Briefing | `standard` | `high` | Workspace |
|---|---:|---:|---|---|---|
| `internal` | yes | never (disabled for evaluation) | direct | direct | per agent |
| `hermes` | no | never | direct `/v1/runs` | direct `/v1/runs`, `high` model | shared by runtime |

The dispatcher filters routes according to this policy and annotates its decision with the driver,
permitted routes, and policy notes. Workflow transitions then honor this decision; they do not
make a second hidden decision.

### Task Port

`app.agent` never imports `app.task`. It depends on `AgentTaskPort`, registered by
`app.task.agent_adapter` during bootstrap. The port exposes only the required operations:
load, list candidates, create, amend, read operational state, save, change phase,
suspend, resume, and coordinate children.

SQLAlchemy represents attributes using `Mapped[T]`, which does not directly satisfy the
mutable protocol in Pyright's view. Static conversion is centralized in
`as_agent_task`; do not scatter `cast()` calls across consumer domains.

### Adding a Future Driver

When another driver is implemented:

1. create its concrete package without modifying `app.task`;
2. implement `AgentDriver` with `run`, `stream`, and `cancel`;
3. define an `AgentDriverSpec` in the registry: factory, policies, capabilities, and
   configuration;
4. adapt the `AgentRunRequest` input and return only common contracts;
5. add stream, policy, error, and availability conformance tests;
6. for an optional external runtime, declare its activation parameter in the spec; the
   internal harness remains unconditionally available.

A driver must not import the `Task` ORM model. An optional capability uses a dedicated
protocol, such as `DriverConfigurationProvider`, not
an `if driver == ...` test in the facade.

## 4. Dispatcher, Planner, and Briefing

`EXEC high` requires the harness to declare `uses_llm_calls=true`: execution calls must use
Galaris model routing and its `LLMCall` journal. An external runtime using its own API or
subscription keeps standard execution only; without planner or briefing, dispatch requires
no LLM call. Managed providers, including Claude Agent, currently enforce the Galaris gateway
and retain both effort levels.

The Task dispatcher builds the route/effort pairs exposed by the selected harness:
`EXEC standard`, `EXEC high`, `BRIEFING` with a supported effort, and `PLAN high`. Provider
capabilities refine the shared network driver's policy. After constraints are applied, one
remaining choice requires no LLM; multiple choices permit inference limited to that list;
zero choices produce an explicit error. Every result is persisted. Without a dispatcher model,
the first permitted choice is selected after these checks. Tasks cannot select `END`.
The rule distinguishes difficulty from decomposability.
An explicit, bounded, mechanical, and simply verifiable operation remains `EXEC standard`, even
if it uses multiple tools or applies an already authorized destructive action: risk determines
guardrails, not effort level.
A site, visual, report, document, code change, or other coherent deliverable remains in
`EXEC high` when research, production, refinement, verification, and delivery contribute to
the same result. `BRIEFING` is a separate choice from `EXEC high`: it prepares one execution
without planning multiple tasks. It remains disabled in the internal harness. `PLAN`
is reserved for multiple independently executable units whose durable results require
coordination; in case of ambiguity, `EXEC high` is preferred. Conversational exchanges no
longer pass through a Task; their separate restricted profile may still arbitrate EXEC/END to
avoid an AI→AI loop. This conversational profile always imposes direct `standard` execution
and disables planner, briefing, and `high` effort. When no dispatcher LLM is configured, the
service produces a traceable and deterministic direct-execution decision. For humans, this
decision never consults the dispatcher model. Explicit `@plan` and `@exec` directives follow
deterministic admission without routing inference. Current contracts, including Tasks, omit
`requires_action`. On Tasks, a textual directive
is applied only after routes exposed by the driver's policy have been resolved; it can never
activate an absent planner. A creation `forced_route`, on the other hand, remains a strict
constraint and is explicitly incompatible if the driver does not expose it. `@briefing` remains
recognized for compatibility but is refused while no driver exposes it.

Each agent references a personal LLM profile or retains `profile_id = NULL` to follow the
current profile. Text usages share four levels: `ultra-low` for Dream; `low` for the
dispatcher and quick conversation; `standard` for briefing, executor, and Goal tracking;
`high` for the high executor, planner, and AI Lab. Specialized models (media,
transcription, and embeddings) retain their dedicated columns. An empty value in a personal
profile remains empty and never falls back to the current profile. Planner selection also covers
final plan synthesis. Gateways also recognize Claude families
(Haiku/`ultra-low`, Sonnet/`low`, Opus/`standard`, Fable/`high`) and Codex
(Luna/`low`, Terra/`standard`, Sol/`high`) as aliases for these levels; an explicitly
configured LLM code retains priority.
Driver policy remains higher priority than activation:
configuring a briefing or planner model does not activate them for Hermes.

The planner produces a mission brief and then a bounded tree. All tasks are
materialized durably, but only one leaf is activated at a time. Results from previous steps
feed the next; the parent performs the final synthesis. It builds the complete tree in one pass
and evaluates decomposition based on substantial, verifiable components of the work. A single
file or deliverable is therefore not treated as a single leaf when it requires multiple coherent
construction, refinement, or validation passes; the affected leaves then modify the same durable
resource sequentially. The Markdown decomposition instruction is the Param
`ai.planner-system-prompt`. Size limits and clarification-cycle state are added by the server.
A Lab Planner dataset copies the runtime instruction at creation, can edit it independently,
then freezes it into every run so comparisons are reproducible.
The planner receives all names from the effective MCP catalog with compact descriptions, plus a
detailed hybrid top-k. This search is applied after authorization and never replaces the
exhaustive manifest. The catalog version accompanies the plan and selected names are validated
before materialization. Retry is idempotent and the scheduler reconciles a missed wake-up.

A leaf reporting `BLOCKED:` triggers one planner recovery decision. An alternative is inserted
only if it is safe, authorized, and materially different from the blocked action; otherwise the
plan fails explicitly. This retry cannot loop and can never weaken a security control. Failures
of Tasks originating from a conversation are notified through their durable link after lease
release; older Messenger Tasks without a link receive a direct notice.

In a planned leaf, selected tools remain eagerly loaded. Other permitted MCP tools are no longer
removed: Pydantic AI marks them deferred and exposes `search_tools`, whose strategy uses the
same hybrid search. The actual call always passes through the filtered MCP toolset and server
controls.

A connection, parameter, or authorization change automatically reconciles the index for the
affected agents. The **Refresh tools** button on the Connections screen is the authoritative
catch-up mechanism: it creates missing internal connections, re-queries all accessible MCP
servers, forces embedding recalculation, and prunes missing definitions. If an agent or remote
source fails, the operation is reported as partial and does not prune the index. This projection
remains an optimization: the effective MCP catalog is recalculated with current permissions
before every selection and call.

Briefing can prepare one complex execution of the internal harness. It selects only genuinely
available resources and cannot execute, send, or conclude the task.
It is currently disabled in all production policies; its implementation, historical results, and
benchmarks remain available for evaluation. No driver receives an old briefing result when its
policy does not allow it.

Neither the plan nor the briefing can replace the user's objective. Common prompts instruct
the agent to ask a concise question when essential information is missing.

### AI Lab and Mechanism Benchmarks

All eleven LAB treatments use the typed contracts in `app.lab.contracts`: one business variable
per case, parameters exclusively on the dataset, and a separate output reference.
Registry descriptors drive the shared `LabWorkbench.vue` UI, including algorithm parameters
and resolved input preview.

The common worker persists two passes: all candidate outputs and objective checks, followed by
independent judgments. New campaigns can rejudge saved outputs without calling the candidate.
Snapshots freeze resolved inputs, profiles, instructions and rubrics; fingerprints distinguish
corpus, context, candidate and judge. Costs are separate. Critical check failures prevent a
passing verdict regardless of semantic score. Judge failure remains inconclusive and lowers coverage.

Task, conversation and voice captures preserve provenance. Incomplete evidence remains
a draft. Captures do not modify business sources.

Changes must verify input contracts, the actual shared services invoked, absence of external
effects, versioned rubrics and tests for both passes, failures and permissions.
See [Lab architecture](../architecture/ai-lab-evaluation.md) and
[ADR 0078](../../../project/decisions/0078-lab-variable-and-judgment-campaigns.md).

From a text round or voice turn, **Add to Lab** selects a corresponding executor dataset before
copying the case.

The text and voice modals also offer copying the complete JSON and deleting the turn.
Deletion routes require `TASK_EDIT`, reject active executions, and retain already produced
Tasks, ProcessRuns, and audit LLM calls. LLM calls are detached from the deleted turn so their
global journal remains usable.
The interface flow is available in the [operator guide](../user/lab-ai.md).

## 5. Database and Synchronization

SQLAlchemy models are the declarative target for the entire `public` schema.
`core.dbadmin` calculates transitions and then uses Atlas internally; do not add Alembic,
call Atlas directly, or write manual DDL during application startup.
The complete cycle, conditional actions, and transformation patterns are described in
the dedicated [`core.dbadmin`](dbadmin.md) documentation.

After a model change:

```bash
make sync-db
git diff -- back/core/authorize/definitions.py front/core/authorize/definitions.ts
```

A new `NOT NULL` column without a default is automatically added as nullable, then tightened
as soon as its backfill is complete. A destructive ENUM evolution requires a complete mapping
declared by the developer.

### Unversioned Conditional Actions

DbAdmin does not replay a sequence of numbered migrations. On each synchronization, it compares
the current database with the SQLAlchemy target of the current branch and produces a
`SchemaTransitionSet`. An idempotent `DbAdminAction` uses its predicate to decide whether the
current delta concerns it. The phases before/after Atlas, backup tables outside `public`, retry,
and tests are described in the [dedicated `core.dbadmin` documentation](dbadmin.md).

> **Current security limitation:** an action error with `required=True` produces a fatal verdict,
> but does not immediately stop the orchestrator. The first Atlas application may therefore
> still remove an old table or column after its `BEFORE_EXPAND` backup fails.
> Until the orchestrator blocks Atlas in this case, do not use this pattern as the sole
> protection for a destructive contraction. Such an evolution must retain the old object
> in the declarative target or be delivered in several non-destructive stages.

All permanent data comes from a registered `DbAdminDataSource` in the
`<module>.dbadmin` file. Its factory produces one or more `DbAdminDataset`s, each with a stable key,
a table, a natural key, static or computed rows, and explicit `depends_on` entries.
DbAdmin compiles sources from all active modules, rejects collisions and cycles, then
applies the generic merge: validation, `INSERT`, update of owned columns, `HistoryMixin`
restoration, and opt-in removal.

Row providers are evaluated immediately before their dataset. The integrated connections
dataset can therefore resolve the real tool and agent IDs after tool merging. The
`column_mergers` cover rare per-column policies, such as adding new global parameters for a tool
without overwriting administrator values.

Privileges, roles and administrator grants, parameters, LLM profiles, mandatory tools, integrated
connections, skills, and assignment matrices are real tabular datasets. Memory projections,
Messenger contacts, and Hermes compatibility processing are named
`DbAdminReconciler`s because they rebuild derived state and are not datasets. The
FastAPI lifespan does not resynchronize any of this data.

For a broader business transformation, contribute an idempotent DbAdmin action with
a predicate and postcondition:

1. add the new table or column;
2. dual-write if necessary;
3. perform an idempotent backfill with metrics and no secrets in logs;
4. verify the postcondition and switch reads;
5. remove the old object in a separate delivery after convergence is proven, as long as the
   barrier on required actions documented above has not been implemented.

Hermes configuration migration follows this model. Historical flat fields are not
removed in this version.

Each service writes within its caller's transaction. Do not open a new session
to bypass a business transaction, except for an explicitly autonomous worker.

## 6. API, Services, and RBAC

A backend module generally follows:

```text
models.py       persistence
schemas.py      API inputs/outputs
service.py      business logic and transactions
router.py       HTTP and authorization dependencies
privileges.py   RBAC constants
tests/          domain tests
```

Routers remain thin. They validate, authorize, call a service, and serialize the
response. Visible HTTP errors must pass through the i18n catalog when intended for the user.

Declare privileges with stable codes. `make sync-db` regenerates and synchronizes backend/frontend
definitions. Do not rename an existing code as a simple translation:
codes are persisted identifiers; labels are translatable.

### Agentic Management MCP Packages

Native MCP functions are discovered in the `mcp.py` of each declared module. The decorator
`mcp_tool(tool_code, name=...)` attaches a function to an integrated tool; the agent's active
connection then selects the groups actually mounted in its toolset. Function states at the
tool and connection levels further refine this exposure.

Each driver's prompt receives a compact inventory built from this same authorization projection:
active connection, runtime capability, function state, and any task scope. It must never contain
a static list of functions. `tools_list` follows the same principle and completely omits
unauthorized groups and functions instead of reporting them as unavailable.

The internal harness exposes exact native names (`task_get`, `file_read`, `process_start`, etc.)
without adding a `galaris_` prefix. Historical names already present in a trace or checkpoint
are normalized on read. An external MCP server, however, retains its connection code as a
namespace to avoid collisions between providers.

Self-service Goal reads pass through the `file_sharing` Tool, via
`file_list`, `file_search`, and `file_read` on `galaris://goal/` and `galaris://goal_cycle/`.
The commands `goal_update_suivi`, `goal_run_now`, and
`goal_ask_referrer` belong to the core `galaris` package. `app.goal` enforces server-side that
the Goal belongs to the calling agent. `goal_ask_referrer` additionally requires the Goal's
current task and never receives administrative elevation.

Assigned Process definitions also pass through `galaris://process/`; each resource
is addressed by the same `workflow_id` as `process_get` and `process_start`. This projection
remains read-only and its pagination is executed in the SQL query.

Tasks are fully discovered and read through `galaris://task/`. The core
`galaris` package nevertheless retains `task_get` as a compact operational view: it projects
progress, expectations, pause, and amendability without replacing the complete snapshot from
`file_read`.

Browser, Search, Image, and Multimedia connections start active by default. The
embedded Console is provisioned when an agent using the internal harness is
created and activated after SSH/SFTP verification. If the executor is unavailable,
the connection remains inactive; provisioning can be retried from Connections.
These five Tools are enabled for conversations on first initialization. Existing
settings and restrictions are preserved.

The `goal_management`, `skill_management`, and `process_admin` packages are declared in
`app.tools.mandatory_tools` with `default_active=False`. Synchronization therefore creates a
connection for every compatible agent, but grants it no functions by default. An active
`goal_management` connection broadens shared Goal functions to all owners and exposes only the
administrative commands `goal_create`, `goal_update`, `goal_delete`, `goal_pause`,
`goal_resume`, and `goal_complete`. Preserve this property for every delegated administrative
capability. This active connection is the administrative witness: `app.goal.mcp` rechecks it
when each administrative command is called, even if the function had already been mounted in a
toolset. Without this witness, shared functions inject the calling agent's identifier into the
service request and respond as if every foreign Goal were nonexistent.

The `galaris`, `conversation`, `memory` and `file_sharing` Tools carry `can_disable=false`.
This persisted property is software-owned and absent from write contracts. Their connections are
created for every agent and converge to active, including previously disabled connections. Their
functions are enabled at both cascade levels; historical denials are ignored. The API rejects
changes or deletion of the Tool, its connections, parameters and authorizations. All three UI
tabs retain them as read-only entries with a mandatory-service icon. Optional Tools retain
administrator-owned activation and restrictions. Business ACLs, harness compatibility and
context restrictions still apply.

The nine `conversation_*` control functions belong to the `conversation` Tool alongside
`document_show`; they remain limited to the conversation controller. Clicking a described Tool
opens its description; empty descriptions have no link. The shipped catalog describes every
native Tool and known messaging/file bridge. Synchronization fills empty bridge descriptions
and upgrades unchanged original short defaults without overwriting custom prose. Descriptions
use Markdown headings and lists for purpose, capabilities, example use cases and access conditions.
Source descriptions live in `app.tools.descriptions`; UI translations live in
`front/app/tools/i18n.ts`.

`memory_summarize` synthesizes up to 200 messages and the latest 32,000 characters through the
agent's model. Attributed facts, decisions, commitments and open questions are stored as editorial
HTML through Memory acquisition. The ineffective `replace_existing` argument is removed; normal
deduplication rules apply. Model failures store neither a raw transcript nor a partial memory.

`galaris_admin` is a fourth management package, also inactive by default. It exposes
`conversation_round_get` and `voice_turn_get`, two primary-UUID reads intended for
complete analysis of text and voice conversational datasets, plus `llm_call` and `llm_calls` for
model-call inspection. They include execution traces and
all correlated `LLMCall`s. Each wrapper rechecks the active `galaris_admin` connection at call
time; prior function discovery alone is not durable authorization.

`app.goal.mcp` adapts the existing business service without duplicating its persistence:

- creation with explicit and distinct owner and agent referrer;
- lists and inspection bounded to the owner, except with `goal_management` elevation;
- cycle history separate from the Goal record and explicitly editable Markdown tracking;
- update and pause/resume/close/immediate-execution commands protected by
  `expected_revision`;
- logical deletion rejected when a cycle is unfinished.

Goal responses retain the text fields `description` and `tracking_markdown`, resolved from
their canonical documents, and also expose `description_document_id` and
`tracking_document_id`. The initial transition backed up the old columns in
`galaris_migration.goal_markdown_backup`, created protected documents, then allowed
Atlas to remove the text columns and enforce UUID foreign keys. The temporary hook was removed
after validating this contraction in production; the backup remains available for audit.

`app.skill.mcp` exposes exactly two reads: an agent's effective authorization matrix and the
single `SKILL.md` file of a core skill. `skill_read` must never become a generic file browser:
scripts, references, and assets remain outside this management contract.

The central MCP wrapper opens exactly one short session with `get_db_session` for each call.
The MCP function and all services it calls reuse this session with `get_db()`: they
never open a nested session. Errors remain recoverable by the central wrapper, which alone
performs commit or rollback. Explicitly safe calls may run in parallel, but each then has
its own session. Tests must verify discovery by tool code, FastMCP mounting, default inactivity,
and mapping of contracts to services.

### Audio, Video, and Large Files

`app.audio` exposes `audio_transcribe` as a native MCP tool under the integrated `audio` code. Its
`file` argument is either a readable canonical URI from `app.file_share` or a YouTube HTTPS URL,
never binary content in the tool schema. The MCP contract remains unique so the model does not
have to choose between multiple functions depending on whether the source is audio, video, or
a link. For a file, transport is resolved by `app.file_share`, preserving the same contract for
the internal and Hermes drivers. For a URL, `app.audio` delegates all source-specific logic to
`bridge.youtube`.

Executor preparation applies an absolute rule: `audio/*` or `video/*` categories and MIME types,
as well as extensions recognized as such, remain with their provider even if the primary LLM
announces audio/video capability. `runtime.Agent._build_file_input_part` repeats this
check as defense in depth and refuses to build a `BinaryContent`. A byte threshold is
insufficient: the provider may convert a relatively small media file into many tokens and return
its content on every tool turn.

The absence of `audio_transcribe` from the toolset is terminal for any request. The absence of
an STT model is terminal only for an audio or video file; a subtitled YouTube URL does not call
STT. Attachment prompts explicitly prohibit fallback through `console_*`, the executor LLM,
generic readers, and video downloaders: the agent must report the error without bypassing the
intended pipeline.

```text
file_share source URI (audio or video)
        │ materialize_resource to a bounded temporary file
        ▼
PyAV: first audio track, video ignored
        │ resample mono 32 kHz + libmp3lame rotation at 96 kbit/s every ~10 min
        ▼
bounded temporary MP3 files
        │ sequential STT + immediate summary of each segment
        ▼
timestamped verbatim .txt + hierarchical reduction → .summary.md synthesis
```

```text
YouTube HTTPS URL
        │ bridge.youtube: allow-listed host + identifier extraction
        ▼
youtube-transcript-api: requested language preferred, manual before automatic
        │ no audio/video download, no STT
        ▼
timestamped .txt transcript
        │ text segments of approximately 10 min + video-summary prompts
        ▼
hierarchical reduction → .summary.md synthesis
```

`bridge.youtube` is a pure client with no router, model, or startup registration; it is
therefore not declared in `back/modules.py`. It accepts only HTTPS, rejects ports and
credentials in the URL, allow-lists YouTube hosts, and recognizes `watch`, `youtu.be`, `shorts`,
`live`, and `embed`. Because the client library is synchronous and creates a non-thread-safe
`requests.Session`, each call constructs its own instance in `asyncio.to_thread`. Its errors are
reduced to localized categories: invalid URL, missing subtitles, unavailable video,
blocked access, and temporary failure.

Conversion is disk-to-disk and runs with `asyncio.to_thread` so as not to block the
async loop. PyAV is already provided by the `aiortc` dependency; the implementation does not
launch an `ffmpeg` process. OpenAI-compatible and ElevenLabs branches transmit the multipart
file from disk. Because the OpenRouter API requires base64 JSON, only that branch loads the
normalized MP3 into memory.

The output format is deliberately MP3 rather than Opus: Opus provides a better quality/size
ratio, but MP3 remains the format most widely accepted by STT endpoints. The 96 kbit/s mono
bitrate preserves speech sufficiently and greatly reduces a PCM or video source. Do not,
however, present this reduction as a guaranteed cost saving: many providers bill by the minute.

The service must close containers and delete all temporary files on every exit path. Empty,
undecodable media or media without an audio track raises `AudioConversionFailed`; the
tool then transforms this exception into a localized operational error. Module tests
create a real video container with an audio track and verify that the result contains no video,
uses a single 96 kbit/s mono MP3 track, and rejects silent video.

Splitting occurs during a single decode: resampled frames are distributed across successive
MP3 encoders, without first creating a giant MP3 and without retaining audio in memory.
`summary_service` applies map-reduce: bounded summary of each segment transcript, then
limited groupings of 42,000 characters until the final synthesis fits within one request. The
`meeting` profile retains decisions, owners, and actions; the `video` profile preserves ideas,
claims, examples, caveats, and timestamps without presenting the video's statements as verified
facts. In both cases, content is marked as untrusted data and cannot provide instructions to the
synthesis model. The complete transcript is written as the stream progresses and is never
provided to this reduction.
The progress message passes directly through Messenger without calling `note_reply`, so that
automatic final delivery is not suppressed by the deduplication guard.

Large deferred skills must not cancel this context saving. Beyond
12,000 characters, `app.harness.skills` injects only a title index into the
Pydantic AI capability. The `skill_<code>_read_file` tool then accepts `section` to read one
Markdown chapter. In parallel, the history processor clears content already reinjected from the
typed `load_capability` result, while retaining the call and its identifier so the capability
remains active. Do not remove either protection: active instructions would otherwise be duplicated
and re-billed on every tool turn.

### Processes and n8n

`app.process` owns definitions, runs, the outbox, callbacks, and engine registry. `bridge.n8n`
adapts the n8n API and webhooks to the `ProcessEngine` protocol; it must not contain business
persistence logic.

The six personal `process_*` functions belong to the core `galaris` package; there is
no longer a `process` connection to activate. The definition explicitly associates a workflow
with an agent, and list, read, launch, and tracking tools systematically filter or revalidate
that agent. Both drivers add to the prompt a compact catalog of only the processes assigned to
the caller, including when the caller has administrative rights. All are displayed when the
agent has at most ten; beyond that, the configured multilingual vector model selects the ten
most relevant to the request, without a threshold, with deterministic lexical fallback. A
compatible Process retains priority over any Task creation or modification.

The separate `process_admin` package is auto-connected **inactive**. Explicit activation gives
the administrator agent functions for discovering engines, CRUD of definitions with a target
`agent_id`, and managing runs for all agents. These functions all carry the `process_admin_`
prefix so a model never confuses them with personal access. The `galaris` system skill
documents both surfaces, but the prompt and actual tool list remain the access authority.

The canonical API is `/api/processes/...` and the frontend page is `/process`. The former
`/api/processus/...` prefix remains a hidden, deprecated alias so already deployed callbacks
do not break. Never use this alias in new code.

Delivery of starts is at least once: every integration must honor
`Idempotency-Key`. Galaris also provides `X-Galaris-Run-Id`, `X-Galaris-Callback-Url`, and the
configured callback authentication header. The token is specific to the run and also protects
linked files; it must not be replaced with a global secret exposed in a URL.
The exact body, callbacks, and importable template are described in
[`docs/en/n8n/README.md`](../n8n/README.md).

## 7. Frontend

The [Solaire palette](palette-solaire.md) is the mandatory color reference throughout the
interface: 11 colors, each with an accent and backgrounds for light and dark themes.
Its exact values and usage rules govern visual changes.

Domain structure:

```text
front/app/<domain>/
├── components/
├── pages/
├── services/       HTTP calls and transport types
├── stores/         Pinia state
├── navigation.ts
└── i18n.ts         en/fr objects with the same keys
```

Use `<script setup lang="ts">`, typed props, and Quasar components. Pinia stores
group shared state and actions; services contain no UI state.
Routing is file-based: do not add a second manual route table.

Modal actions use Quasar's native dimensions and shapes: standard text buttons, round
icon buttons, and `flat round dense` header close buttons. Do not impose a height, `size`,
or `dense` variant on ordinary actions. Add `galaris-dialog-actions` to modal
`q-card-actions` to retain native button padding on mobile. Popovers, controls embedded
in fields, filters, pagination and editor toolbars retain their specialized layouts;
do not apply a general rule targeting every button descending from a modal to them.

All visible text passes through `t()` or `$t()`. Purely technical values such as
`MCP`, a filename, or a model code remain literal. When the language changes, the HTML
`lang` attribute and API requests are synchronized by the i18n core.

`DEFAULT_LANGUAGE` and `LOCALIZATION` are optional and empty by default. Existing saved
values are preserved; “Not set” clears the fallback language. The user's profile language
takes priority over context and routing detection. Conversation and Task admission preserve
it for background processing. Without an associated user, the context language is retained,
then the configured fallback applies; English is used when no language is known. An empty
location does not imply any place.

### PWA and Session Renewal

`vite-plugin-pwa` generates the manifest and service worker from `front/vite.config.ts`. Normal,
maskable, and Apple icons are versioned in `front/public/pwa`. Workbox caches the static
interface, but explicitly excludes `/api`, `/socket.io`, `/ws`, and
`/openapi.json` from the navigation fallback: no business data must be presented as
available offline. The service worker uses `autoUpdate`, including in the shared development
deployment without breaking HMR.

Chat notifications use the service worker in `injectManifest` mode and Web Push.
DbAdmin stores the VAPID pair in the encrypted internal `WEB_PUSH_VAPID_KEYS` parameter:
the pair is generated once when absent, without importing old environment variables.
Preferences never expose the private key. Configure `WEB_PUSH_VAPID_SUBJECT` (a `mailto:`
or HTTPS contact) and `WEB_PUSH_DELAY_SECONDS` (1 to 30 seconds) in Chat preferences without
restarting. A changed delay applies to subsequent notifications. Updates remove the four old
variables from `.env` only after verifying the persistent keys. Invalid persisted pairs stop
startup instead of being silently replaced. The first transition from old keys requires disabling
and re-enabling device notifications; subsequent updates preserve the internal pair.

The browser permits subscription only in a secure context (HTTPS, or localhost in
development) and after an explicit user gesture. Push endpoints and device-specific keys
are encrypted with `ENCRYPTION_MASTER_KEY`. VAPID rotation invalidates existing
subscriptions; it must therefore remain an exceptional and announced operation.

The browser authentication flow is:

```text
login
  ├── short-lived access token → localStorage
  └── refresh token → HttpOnly cookie + hashed database row

PWA startup or API 401 response
  └── POST /api/auth/refresh → atomic rotation → new JWT + new cookie

logout, password change, or deactivation
  └── revocation of the family or all persistent sessions
```

`front/core/api.ts` centralizes JWT storage, enables `withCredentials`, and serializes
concurrent renewals into a single promise. Its interceptor retries a 401 request
only once. `authStore.initialize()` first attempts the persistent cookie, then accepts the
historical JWT as a fallback during the transition of existing installations. The role present
in an old signed JWT may be requested during renewal, but the backend always verifies
that the role still belongs to the user.

The backend never retains the opaque token: `refresh_session_service.py` stores its
digest, rotates under a SQL lock, and uses a short deterministic grace period for concurrent
bursts. A late replay revokes the family. Any change to this contract must preserve
the original controls, cookie attributes, and tests in
`back/core/user/tests/test_refresh_session.py`.

Passwords must be at least 12 characters. A password or second-factor failure increments a
persistent counter under a SQL lock; from the fifth failure onward, the account is subject to
bounded exponential lockout. Successful authentication resets the counter.

TOTP second factor is optional per user. The TOTP key is encrypted with
`ENCRYPTION_MASTER_KEY`, a counter rejects replay of an already accepted code, and recovery codes
are hashed, consumed under a lock, and displayed only once. Configuration endpoints live under
`/api/auth/mfa`; JSON login accepts `otp_code`. The fixed login lockout policy governs bootstrap
protection only and cannot be weakened through the environment.

### Observability

`core.observability` configures Logfire locally before integrations; `LOG_LEVEL` is read from
`.env` immediately at startup. After preferences load, the encrypted `LOGFIRE_TOKEN` enables
remote export. A listener reacts to edits in System preferences: the SDK replaces exporters
without reinstalling instrumentation, outside the API event loop. An empty token explicitly
disables export even if old environment variables or Logfire credentials files remain.
With this token, the backend
centralizes FastAPI traces, SQLAlchemy and HTTPX spans, Pydantic AI events, system metrics, and
Loguru logs. Headers, HTTP bodies, prompt contents, and binary contents are not collected.
Without a token, instrumentation remains local. `APP_ENV=test` retains normal instrumentation.
Only automated test compositions explicitly isolate telemetry and HTTP quotas, supply their
own secrets, and request DbAdmin's `--mode test`.

`app.incident` complements this telemetry with a durable PostgreSQL journal of every failed LLM
or tool call. Capture occurs before harness event compaction and retains correlations for Task,
attempt, run, agent, provider, model, and tool, as well as the available retry policy. Secrets
are masked and bytes are replaced with their size and fingerprint. A global 8 MiB limit,
reported in the record, protects the database from an accidentally unbounded payload.

The **Preferences → AI Failure Log** menu displays occurrences and grouped patterns.
The maintenance routine consists of processing `new` and `regression` patterns, documenting
the diagnosis and root cause, scheduling and referencing the fix and its test, and finally moving
the pattern to `resolved`. A new occurrence automatically reopens it as `regression`.

## 8. Code Language and i18n

Source code is written in English: names, comments, docstrings, technical logs, and
internal error messages. Public and persisted identifiers are not renamed for
cosmetic reasons. When removal or renaming is genuinely necessary, it requires an
explicit compatibility or revocation strategy for old access.

Visible text is not “translated in code”:

- frontend: each module exports exactly the same `en` and `fr` keys in `i18n.ts`;
- backend: `core.i18n.t()` loads module catalogs and receives an explicit language
  for workers without HTTP context;
- contract prompts: stable English, with an instruction to produce the response in the
  detected language;
- user-requested content: never translate it implicitly.

A complete French translation is mandatory for every new English key. Avoid
text built through concatenation when word order may vary by language; use named parameters.

## 9. Tests and Typing

See the [reliability operations guide](reliability-operations.md) for budgets, retention,
image promotion and upgrade/restore rehearsals. `make lint` blocks high-confidence Python errors;
`make tests-coverage` measures branches in DbAdmin, Task budgets and the Task state machine,
with a blocking 95% threshold.

```bash
make typecheck
make tests
make tests ARGS='app/agent/tests/test_registry.py'
make tests-browser
make quality
```

`make typecheck` runs strict Pyright on the production backend, `vue-tsc` on the
frontend, then frontend catalog parity checks. The latter verify keys, value types,
and named parameters between English and French. Python tests use many dynamic mocks and
monkeypatches: they are validated by pytest, while the runtime remains strictly typed.

`make tests` starts an ephemeral PostgreSQL pgvector database, runs the same DbAdmin as
production, then runs pytest in a one-shot container. Its self-contained Compose file uses one
default network dedicated to the test project, removes it systematically after the run, and
does not load any application-stack network.
`back/conftest.py` rejects a database whose
`APP_ENV` is not `test` or whose name is not `test_db`. Fixtures wrap every
test in an external transaction with savepoints and rollback, even if a service calls
`commit()`. `core.i18n` tests also enforce key and placeholder parity for all backend
English/French catalogs.

GitLab and GitHub CI configurations define these gates for merge requests: typing and production build,
generated map, architecture boundaries, backend tests with ephemeral PostgreSQL, and browser
sidecar tests. A dependency review blocks new high-severity vulnerabilities;
Dependabot tracks Python, npm, Docker, and GitHub Actions lockfiles.
Runner and branch protection activation on the GitLab remote is described in
[the testing guide](testing.md); versioned YAML does not prove activation.

Do not run pytest in the development backend: the former behavior could create
tasks and modify real data.

Expected tests for an agentic change:

- driver × effort × route matrix;
- durable transitions and retry after error;
- terminal stream conformance;
- absence of forbidden imports between layers (AST tests);
- missing/disabled/unknown configuration;
- driver behavior with simulated dependencies;
- DB integration test for any new persistence.

## 10. Contribution Workflow

1. inspect `git status` and preserve unrelated changes;
2. write or adapt the test that expresses the contract;
3. make a coherent change limited to the module's responsibility;
4. run targeted tests, then `make typecheck` and `make tests`;
5. check `git diff --check` and review schema/configuration changes;
6. document any architectural choice or new variable.

Suggested commit format:

```text
refactor(agent): isolate runtime drivers behind the agent facade
fix(task): keep pytest writes out of the development database
docs: rebuild user, administrator and developer guides
```

A refactoring must not silently change a business policy. If behavior changes,
make it explicit in the contract, tests, and documentation.

## 11. Known Pitfalls

- importing `app.task.models.Task` in a driver recreates the coupling that the facade eliminates;
- choosing a model in the proxy after the run has begun makes traces inconsistent;
- having the briefing or planner decide a second time cancels the dispatcher's choice;
- retaining a silent fallback for an unknown driver code masks a configuration error;
- treating final text as proof of an action allows hallucinated confirmations;
- persisting a test fixture to the development database creates stray tasks;
- adding a visible English string without a French key breaks the i18n promise;
- shrinking a table in the same version as its backfill prevents a safe rollback.

Dependency, secret, SAST, image and restore checks are described in
[Security validation](security-validation.md).

## Editorial content

The [editorial HTML contract](editorial-html.md) covers content profiles, validation, revisions,
attachment images and DbAdmin conversion of rich content.
