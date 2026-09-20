<p align="right"><a href="../fr/features.md">Français</a> · <strong>English</strong></p>

# Galaris Feature Tour

Galaris is a self-hosted control center for AI agents. It brings models, agentic runtimes, tools, conversations, durable Tasks, memory, and business Processes together on a single platform. The goal is not only to obtain an answer: it is to transform a request into a traceable, recoverable, and governed result.

This overview is updated through **17 September 2026**, incorporating the commits since the 12 September review. The [detailed French catalogue](../catalogue-fonctionnel-fr.md) preserves the earlier module and native MCP inventory. Some capabilities require an explicitly configured model, bridge, or connection; experimental or future features are described separately in the [plans index](../../project/plans/README.md).

## From Message to Result

Galaris separates three work rhythms that can take turns without losing their context:

| Rhythm | Usage | Control provided by Galaris |
|---|---|---|
| **Conversation** | question, short exchange, guidance | message aggregation, durable history, loop prevention, inspectable LLM calls and effects |
| **Task** | action, research, production of a deliverable | routing, effort, tools, possible plan, delegation, resumption, persisted result and costs |
| **Goal** | long-term objective pursued over multiple cycles | owner, coordinator, schedule, verdicts, evidence, rich-text tracking, pause, and manual triggering |

A Conversation can launch a Task or background Process and then respond immediately with its reference. A complex Task can become a plan of actual subtasks and call on other agents. A Goal creates successive cycles until success or explicit termination.

## Agents, Models, and Runtimes

Each agent has a stable identity, role, instructions, access level, model, skills, and tool connections. Galaris preserves this identity during delegations and prevents a call from silently modifying the agent executing the work.

Agent runtimes share the same business facade:

- the **internal Pydantic AI** driver, with Dispatcher, Planner, streaming,
  tool checkpoints, and safe cancellation;
- managed **Hermes**, **Codex**, **Claude Agent**, and **DeepSeek Harness** runtimes,
  with isolated execution environments and model access through the Galaris gateway;
- a generic **OpenAI Messages / Chat Completions** transport for compatible external runtimes.

The internal harness and managed runtimes support standard and high execution through Galaris model selection and call accounting. The generic transport exposes standard execution only. Planning is currently available through the internal harness; Briefing remains disabled in the current runtime policies. Managed external runtimes are limited to one simultaneous Task each.

Harness settings use a shared administration form, including execution, inactivity, stream-closing, and output-volume limits. Available features reflect what the runtime implements, what is configured, and what has been verified for the selected target. A setting cannot enable an unsupported capability. Cancellation records whether stopping was requested, confirmed, or remains unknown, and distinguishes local interruption from remote termination.

LLM providers are replaceable bridges. OpenAI, Anthropic, Google, Mistral, OpenRouter, Ollama, and many compatible providers can coexist. Different models can be assigned to standard or high execution, fast Conversations, the Planner, the Dispatcher, Briefing, Goals, the Lab, Dream, embeddings, media, and images.

Text requests use SDK profiles and endpoint constraints for reasoning, token limits and sampling. Unknown extensions pass through; only an explicit rejection before generation allows an optional setting to be removed. Messages, tools, budgets and output formats are preserved. The [parameter matrix](dev/provider-parameters.md) is exercised through simulated transports without paid provider calls.

**Durable LLM inferences**

Text, structured-output, and protocol requests can be admitted as durable inferences before execution. Each inference preserves its original request, caller authority, attempts, messages, terminal results, and associated physical provider calls. Structured outputs use versioned schemas and validators; an unknown or incompatible contract is rejected explicitly.

The authenticated API under `/api/llm/openai/inferences` supports creation, inspection, control, and streaming. A saved stream cursor allows a client to reconnect and replay persisted events without generating another answer. Disconnecting an autonomous stream leaves its worker running; synchronous and ordinary HTTP call adapters retain their cancellation behavior. Chat/Responses replies expose `X-Galaris-Inference-Id` for correlation.

Pause and stop can interrupt a silent provider. Resume creates a new attempt from the saved request, and replay creates a separate linked inference. Earlier attempts remain immutable. Resuming may incur another provider charge: it does not resume the provider's computation token by token. A lost worker lease prevents late writes and does not silently repeat the provider request. These controls currently concern inference; tool effects remain governed by the agent harness and its checkpoints.

## Durable Orchestration and Collaboration

A Task records its objective, assigned agent, routing, effort, attempts, LLM and tool calls, related Processes, subtasks, and terminal result. The scheduler uses persisted leases: a Process incident does not make the work disappear, and a blocked execution can be explicitly released.

Task details and the chat task panel restore activity on opening and reconnection: requested or effective pause, waits, latest attempt, next retry, and a bounded history of progress messages. Newly admitted Tasks retain their initial request alongside provenance, resources, and receipts. `task_get` also exposes activity for active and terminal Tasks; late events cannot replace a terminal result.

The Dispatcher chooses only among the route/effort combinations supported by the selected harness and allowed by the request. With one available choice, routing is deterministic and requires no dispatcher LLM call. With several choices, the model receives that exact list; a missing model or invalid answer falls back only to an allowed choice. Incompatible explicit constraints produce an error. High effort requires Galaris model selection and LLM accounting. Direct high execution, Briefing, and planning are distinct routes; declaring the Briefing route does not reactivate it for a harness where it is disabled.

The Planner creates bounded steps with deliverables and success criteria, then synthesizes the result. Briefing remains available for evaluation and historical inspection. Agents can delegate a subtask or wait for a colleague's response without creating an infinite loop. Human-facing Task references use the full `galaris://task/<uuid>` URI. File tools can inspect Task and text/voice round snapshots through canonical Galaris resources, while `task_get` provides a compact operational view.

The internal harness checkpoints every MCP effect before and after the call. After a cancellation or resumption, an already obtained result can be reused instead of blindly repeating an external effect.

An ordinary tool failure returns a structured error to the agent, which can correct its input, verify the outcome, choose another approach, or stop. Repeated tool errors do not by themselves exhaust schema-correction retries or force termination; global budgets and cancellation still apply. Errors distinguish a proven rejection before effects from an uncertain outcome. Resumption restores recorded errors without repeating the call. A crash with no recorded result still requires reconciliation before a potentially non-idempotent action can be repeated, including after a manual retry.

Successful execution is accepted after the runtime stream has ended and cleaned up correctly. Missing or duplicate terminal results, events after the result, and invalid closure fail before a candidate success is published. Progress and checkpoint snapshots are bounded individually and do not repeatedly consume the stream's cumulative byte budget. Successful responses do not trigger another execution merely because they lack tools, artifacts, or new wording; transport receipts remain the evidence for actual delivery.

Task timing distinguishes preparation, admission, first claim, processing, waiting, pauses, and retry backoff. Historical processing can be reconstructed from retained LLM calls without inventing missing timestamps. Costs come from persisted gateway calls, including preparation and dispatcher calls whose output could not be parsed.

**Goals and continuing work**

Goals retain their owner, coordinator, schedule, cycle Tasks, evaluation verdicts, evidence, and editable description and tracking documents. Global and individual schedules govern automatic cycles. A manual cycle request is persisted until its Task is created and can bypass time restrictions while respecting an explicit global pause.

If running a cycle first requires recovery of a failed evaluation, the manual request remains pending: a continue verdict starts the new cycle, while a stop verdict cancels it. Retrying tracking alone evaluates the existing work without requesting a new cycle or replacing the previous Task's result.

Documents linked to a Goal, including deliverables traced to its Tasks and delegated work, are automatically filed in each eligible user's personal `Goals / <goal label>` hierarchy. Filing runs in the background and rechecks current access. Existing manual classification, custom folder names, and moves are preserved; generated names follow Goal renames until customized. No empty folder is created just for opening the library. Administrators can request a catch-up for all users or a selected user/Goal. Filing changes neither document content nor sharing rights.

## Text and Voice Conversations

The Messenger journal is the canonical entry point for all channels. The internal Messenger, Nextcloud Talk, Matrix, OneBot, Telegram, and WhatsApp Business can be active simultaneously. A response is sent back through the original connection and Conversation; a new message to another channel requires an explicit target. The internal channel provides private or group rooms, files, voice notes, redacted activity, and WebRTC calls; its rounds are strictly isolated from Tasks.

Short text Conversations have their own control plane: received messages, aggregations, rounds, attempts, deliveries, LLM calls, and errors are visible in real time. The controller responds directly or creates a durable Task/Process for asynchronous work. Responses between agents are filtered to prevent endless automatic exchanges.

Human text messages enter the standard conversation executor directly, without an extra dispatcher inference. The executor chooses whether tools or durable work are needed. Explicit `@task`, `@plan`, or `@effort` directives admit a Task before publishing its confirmation; the resulting Task still respects its harness capabilities. Conversation attempts have a fifteen-minute execution allowance. Normal lease release preserves a completed round's success, and earlier failed attempts remain inspectable.

Internal Chat includes a document workspace. Search, linked documents, and message previews open the full editor beside or below the conversation on desktop; mobile uses a document dialog. Desktop panes can be resized with mouse, touch, or keyboard and stack automatically when side-by-side editing would be too narrow. Layout changes and reconnects preserve the current conversation and document context.

Before sending, Chat saves pending document edits and attaches the reference of the document currently displayed to the message context. A failed save preserves the draft. Closing the document or losing access removes that context from later sends; an older message's document is not treated as the current selection. An agent in its own internal text room can request that a document be opened with `document_show`. This checks current access, grants no sharing rights, and is unavailable to Tasks, voice, and external channels.

For live voice, Galaris can use:

- an **STT → agent → TTS** pipeline, which allows providers to be freely combined;
- a native **speech-to-speech** session, which preserves prosody and reduces latency when
  the selected provider and voice allow it.

Matrix and Nextcloud Talk calls are tracked with their turns, interruptions, possible transcriptions, responses, and incidents. Voice notes received through other messaging systems follow the canonical media path.

Browser voice preserves the beginning of speech across different audio-frame sizes. Permission checks run independently of audio transport and close a call when access is denied or can no longer be verified. ICE candidates are sent in ordered batches, including late relay candidates; a signaling error is reported without automatically ending a connection that still works. Hanging up stops capture and clears queued audio.

## Governed Memory and Topics

Galaris distinguishes recent session data from durable memory. The session is reconstructed from the canonical journal and transmitted in the same way to the different drivers. Durable memory is private by default and associates each item with:

- an owner, a type, and a memory role;
- revisions, provenance, and relationships;
- direct read or edit access;
- usage traces and explicit permanent forgetting.

Recall combines full-text search and vector similarity when the embedding model is configured. ACLs and limits are applied before ranking; if the semantic index is unavailable, lexical fallback is announced instead of being hidden.

**Topics** connect memories, Tasks, and Conversations around the same global subject, independently of the channel or room that produced them. They are separate from each user's personal document folders. The memory graph makes it possible to explore relationships and their time period.

Memory and documents use their title, keywords, and current content for discovery. Separate summaries and free-form change reasons have been removed, while revision contents, dates, authors, Tasks, and sources remain traceable. Memory previews use content excerpts; document cards can display a thumbnail of the saved revision. Content deduplication also respects validity dates, so a newly confirmed fact does not silently reuse an expired memory.

The shared memory form supports viewing, creation, editing, individual keyword values, and saving without closing. Its History tab displays earlier saved content while preserving the current draft, supports readers without edit privileges, and offers retry after a failed load. Search results distinguish documents from memory types, and relationship labels are localized in French and English.

Agents, Goals, cycles, messaging contacts, and Process results can be projected idempotently into this memory without replacing their business source.

Conversation summarization uses the agent's model to retain attributed facts, decisions, commitments, and open questions as editorial HTML. Input is bounded to 200 messages and the latest 32,000 characters. Existing room memories are preserved, and a model failure stores no substitute transcript.

Shared topic selectors provide paginated search and, in entry forms, topic creation for users with the required global management and topic-edit privileges. A newly created topic becomes the selection without losing the form draft. History filters remain selectors only; Memory keeps its own agent-authorized topic projection filter. Cancellation, revoked privileges, and late responses cannot overwrite a newer selection.

**Documents as shared working material**

Documents are the canonical home for agent-authored reports, analyses, articles, plans, notes, and drafts, including work completed in a single Task. A stable `document://` URI follows the same content through research, writing, review, delegation, and conversation. Agents create or enrich it through File Sharing and keep sources and related-document links in the document. Chat carries discussion and handoffs. Explicitly requested file formats, source code, interactive pages, and technical artifacts such as transcripts retain their own formats.

Documents use versioned semantic HTML and a rich-text editor. The library, Chat workspace, Task views, and Memory details reuse the editor with the same access rules. Users can create, read, edit, save without closing, and inspect revision history. Viewing an older revision preserves an unsaved draft. Goal description and tracking documents retain their stricter editorial profile wherever they are opened.

New documents are private. Sharing grants read or edit access to an identified user, agent, or team. Sending a link or opening a document in Chat does not grant access; agents must establish the required sharing before handing work over. Sharing conflicts can be refreshed and retried without discarding pending choices. External delivery is a separate operation with its own transport result.

The editor adapts page width to its container and offers printing, PDF export, attachments, and image previews. Mobile toolbars wrap the available editing, formatting, voice, link, file, and sharing actions. Resizing preserves content and ongoing dictation; desktop toolbars remain aligned with their pane. Images open in a fullscreen viewer. Document sharing prepares a PDF of the current content for native sharing, adds the Galaris URL when supported, and offers a download fallback. Obsolete preparation is discarded if the document changes or sharing is cancelled.

Document thumbnails render the beginning of the first printed page, including embedded images, and are tied to the saved revision. Visible previews refresh after edits and recheck access; offscreen thumbnails load on demand. The navigation tree stays compact with document titles and icons, while the lower list retains ownership and dates.

**Personal document library**

Each user organizes accessible documents in a personal hierarchy of folders and subfolders. The library combines direct access with access through managed agents without duplicating the same document. Read access is sufficient to classify a document or choose a personal icon: neither operation changes its content, revision, dates, or permissions.

- Create folders and subfolders immediately, rename them inline, and move them by drag and drop.
- Drag documents into folders, reorder them among subfolders, or return them to the unclassified list. Personal order persists across visits; moving a document replaces only the current user's folder assignments.
- Use the lower list's default **Unclassified** filter or turn it off to see all accessible documents. Search, owner, folder, creation-date, and modification-date filters apply before pagination and counts. The list defaults to 50 items with choices of 10, 20, 50, 100, and 500.
- Expand a folder to load all its direct documents independently of the lower list's search and pagination. Resize the divider between tree and list; its position is remembered per user.
- Personalize folders and documents with searchable Unicode emoji, icon fonts, or private validated SVG uploads. Folders also offer the Solaire folder palette. Document icons remain consistent across library, editor, Chat, Tasks, topics, and Memory views.
- Delete an empty folder directly, or confirm deletion of a populated branch. Documents return to the unclassified list; their content and other users' organization remain intact.

Folder membership never grants document access. Revocation hides inaccessible documents even if a personal classification already exists. Personal icons survive folder moves and deletion. Existing documents are not automatically assigned personal folders from their old metadata paths, and Goal filing respects folders the user has already chosen.

**Document structure and attachment memory**

Memory represents each document, its attachments, and its personal folders as distinct, stable items. Explicit document references, attachment ownership and use, folder membership, and parent folders create deterministic graph links without an LLM or embedding call. Supported document and classification writes update these links in the same transaction; existing content is initialized during database convergence, and Dream can repair the projection later.

Every supported attachment has one Memory companion containing its resource identity, MIME type, size, and any acquired text. This does not automatically transcribe or describe every binary. When `image_read` describes an active document image, it saves the description with agent/Task provenance before reporting success. For other image URIs, the description is stored as private agent memory without granting access to the original resource.

Recall can follow authorized structural links from lexical or semantic matches to related documents, attachments, and folders, even when those related items contain no matching text. Detailed results expose the permitted structural path. An unreadable item cannot bridge two readable results. Agents see a personal folder and its ancestors only when readable documents justify that path; this exposes neither inaccessible sibling branches nor a new folder-sharing mechanism.

Removing an attachment retains its identity and acquired text for old document revisions while hiding it from current recall. Permanently forgetting the document also removes its attachment descriptions and revisions. Open Memory, graph, and document views revalidate after changes or reconnects and discard responses made obsolete by access revocation.

## Dream: Maintenance and Learning

Dream uses only the available background capacity and runs one mechanism at a time. It can classify topics, extract and consolidate memories, link topics, project Processes, repair document structure, and forget items that have become inactive. Its monitoring page exposes the current mechanism, subject, phase, attempts, and any errors in real time. Document-structure repair is deterministic and preserves manually established relationships; background execution does not promise an immediate repair deadline.

Learning goes further than summarizing a response. It examines observable evidence—attempts, tools, subtasks, Goal verdicts, human corrections, and Memory usage—and then creates or strengthens a candidate dedicated to the agent, including by progressively reviewing historical Tasks. Each procedure has a score and a log of positive or negative evidence. It becomes a Skill injected in addition to the assigned Skills only when multiple distinct Tasks confirm the same action—3 by default, with an adjustable threshold—and when its score reaches the configured minimum. This feature is **disabled by default** and separates observation and learning modes; its tab is then hidden and it writes no node to Memory.

## Tools and Connections

Not all functions are sent to the model on every turn. Galaris builds a catalog, first filters it according to permissions, context, and active connections, then loads the relevant capabilities on demand. Optional tools and bridges can be disabled at connection or individual-function level. Restrictions are checked again when a function is called, so an earlier catalog cannot bypass a later revocation.

**Galaris, Conversation, Memory, and File Sharing are mandatory system services.** Every agent receives their connections; database convergence repairs missing or disabled connections and ignores obsolete function denials for these services. Their configuration and authorization controls are read-only in the interface and protected by the API. This does not change resource ACLs, harness compatibility, or context-specific restrictions.

Conversation control functions belong to the Conversation service. Detailed LLM, conversation-round, and voice-turn inspection belongs to the optional **Galaris Admin** tool, disabled by default and checked at each call. Delivered tools expose business descriptions from the Tools list, explaining purpose, capabilities, examples, and limits. Standard descriptions can be updated without replacing customized descriptions.

The delivered surfaces notably cover:

| Domain | Capabilities |
|---|---|
| **Web** | local SearXNG metasearch, isolated interactive Chromium browser, accessible snapshots, and bounded visual captures |
| **Files** | canonical URIs, connected providers, streamed transfers, and incoming/outgoing attachments |
| **Documents and Memory** | document creation and revision, explicit sharing, resource search, durable facts, conversation synthesis, and structural recall |
| **Media** | audio/video transcription, public YouTube subtitles, long-form segmentation, verbatim transcripts, and hierarchical summaries |
| **Images** | generation, modification, description, and transport by file identifiers |
| **Console** | controlled SSH sessions, embedded executor, and home files without exposing credentials to the model |
| **MCP** | native Galaris tools and remote servers, connection diagnostics, and per-function restrictions |
| **Processes** | personal definitions, separate administration, durable runs, events, callbacks, cancellation, and n8n bridge |
| **Organization** | specialized management of agents, Goals, Skills, Tasks, and LLM inspections according to granted permissions |

The Console supports short commands and separately launched long-running jobs with polling. Its versioned SSH helper can be installed or upgraded without root access after a successful connection test. A recovery-capable helper preserves operation receipts on the same target, allowing interrupted calls to be reconciled without rerunning a command. A still-running long job acknowledges launch; it does not prove completion of an interrupted synchronous command. Missing historical receipts cannot be recreated by upgrading the helper.

The browser uses a shared Chromium sidecar, but each agent/Task pair receives an isolated, ephemeral context. It can open any HTTP(S) URL reachable from the sidecar's networks, including Docker services, the local network, and the host through `host.docker.internal`, in order to produce previews of tools under construction.

## Files, Audio, Video, and Images

Incoming media is bounded and retains the exact URI of the Tool that received it. A consumer can materialize it in a temporary server location cleaned up after the call, without creating a new resource or modifying the identity presented to the model. Large files remain referenced by URI and are not copied into each model message.

Specialized tools accept the original resource URI directly, so a local copy is unnecessary merely to send or analyze a file. For staged transfers, failure to download the source is a recoverable rejection before any destination upload. Once upload begins, an uncertain outcome must be checked before repeating a mutation. SFTP operations create missing parent directories while preserving confinement to the configured home.

Successful Messenger uploads record delivery receipts so a Task's final notification does not resend media already delivered; an explicitly requested repeat send remains possible. Receipts identify the actual destination and transport result. Shell text that merely resembles a successful command is not a delivery receipt.

Chat and document attachments support fullscreen Markdown and source previews. Markdown is rendered for reading; source code, JSON, and plain text open as read-only text with copy and original-file download. HTML retains its separate isolated preview. Preview failures can be retried, and late reads from another resource cannot replace the current preview.

`audio_transcribe` accepts an audio file, a video file, or a public YouTube URL. For a local file, Galaris extracts the first audio track, normalizes it, segments long durations, preserves the verbatim transcript, and produces a hierarchical summary. For YouTube, it retrieves available subtitles without downloading the video or calling STT. Analysis and image generation also use dedicated models and the shared file transport.

## Business Processes and n8n

A Process definition describes its input, owner, and engine. Each launch creates a persistent run with status, events, output, error, and links to the relevant Tasks. The n8n bridge provides idempotency keys, authenticated callbacks, and immutable terminal states. Personal Processes and their global administration use distinct permissions.

A terminal callback retains its result, error, and external identity even when the start response arrives later or is lost. Concurrent discovery resolves to a single run and rejects collisions with another workflow.

## AI Lab and Observability

The AI Lab is used to understand and compare the mechanisms actually used by Galaris. It can import a Task, a Conversation round, or a voice turn into a dataset, freeze a reference, run a candidate model, and produce a detailed semantic judgment. Dispatcher, Briefing, Planner, executors, and Dream/Goal mechanisms have separate datasets so that different contracts are not mixed.

Runs are persisted by case, resumable, and analyzable. A score is never presented as absolute truth: dimensions, coverage, errors, strict similarity, and judge calibration remain visible.

Dispatcher experiments use the same effective harness route/effort choices as real Tasks, including deterministic routing. Experiment creation waits for initial data to load so an existing experiment is not accidentally replaced by an empty state.

In daily operations, real-time monitoring screens bring together Tasks, Conversations, voice calls, LLM activity, Processes, and Dream. Run identifiers link calls and effects to their origin. Application logs and Logfire traces complement this view when configured.

A Conversation round that succeeds after a retry is shown as successful; earlier errors remain in its attempt history. API diagnostics expose the available error detail, route, and HTTP status, and distinguish network failures from timeouts.

Tasks and conversation rounds share execution-detail views for progress, calls, results, token usage, and billed costs. Execution traces are the default view; recorded Memory operations can be inspected separately, and linked documents open with their current permissions. Reopening, reconnecting, or loading a late snapshot preserves newer activity. LLM details expose request and response data alongside the normalized terminal result.

## Security and Data Control

- self-hosted Docker deployment with PostgreSQL 17 and pgvector;
- RBAC by privileges, roles, and assignments, enforced in both the API and navigation;
- encrypted connection secrets that are never read in plaintext by the API;
- optional TOTP second factor, one-time recovery codes, and progressive lockout of failed
  connections;
- persistent PWA sessions using a rotating refresh token, protected cookie, and family revocation;
- explicit login waits for the current identity to load; failures keep the login form open, and stale session responses cannot replace the current account;
- optional tools and functions explicitly authorized per agent, with mandatory system services still subject to resource and context checks;
- approvals that cannot be automatically passed to delegated agents;
- workspaces, browser sessions, and memories isolated by owner;
- cancellation, limits, idempotency, and terminal states to reduce duplicate effects.

Galaris remains a platform for probabilistic agents: traces and controls make the work auditable, but an important action must always be verified at the appropriate level.

## User Experience and Operations

The Vue/Quasar interface is bilingual in French and English, uses the shared Solaire palette, supports light/dark mode, and can be installed as a PWA on Android and iPhone. Mobile layouts apply below 1024 CSS pixels; desktop starts at 1024, independently of device type or orientation. The welcome flow verifies the model, the first agent, its tools, and messaging. Lists and dashboards use the current permissions, and active streams are updated in real time.

Agent and topic selectors load options when opened, preserve existing selections, and support retry after errors. Relevant filters discard responses from a previous context. Dashboard monthly queries are batched, and recently visited months are cached with refresh and access-change invalidation. WebSocket subscriptions send domain events to active consumers, preserving authorization checks and restoring subscriptions after reconnect. Dream monitoring updates are limited to displayed monitoring pages; background Memory computation is isolated from interactive request handling. Shared authentication and privilege loading avoid duplicate request storms.

PWA updates refresh cached assets and reload tabs after installation while preserving sessions; save open forms before deployment. Update checks retry even when the browser's offline indicator is stale. Development disables PWA caching, and internal Chat still requires an authenticated viewer.

Only the exact value `APP_ENV=dev` enables development behavior; other labels retain production protections. `make update` supports development and production, reusing Docker's build cache and preserving production HTTPS configuration. `RELEASE_DIR` deploys previously qualified images unchanged. DbAdmin retains bounded error details with the synchronization verdict for diagnosis and recovery. The base deployment includes SearXNG configuration for both environments.

`make validate` runs local checks against an isolated snapshot including uncommitted changes, with source fingerprints and reports under `artifacts/validation/`; it creates no commit or deployment. `make tests-coverage` measures all backend sources, including unimported modules. The blocking **95%** combined line-and-branch threshold applies to the critical subset, with additional domain floors and changed-critical-branch checks. Functional and mutation scenarios cover retries, concurrency, sessions, document history, Lab publication, media, storage, transfers, and DbAdmin. See the [functional guarantees](dev/functional-tests.md) and [testing guide](dev/testing.md) for scope and commands.

Validation also includes shared harness contracts and the four pinned runtime images against a deterministic local model. Recovery scenarios cover lost SSH acknowledgements, durable checkpoints, and uncertain external effects. These checks establish local protocol compatibility; they do not qualify a live provider account or guarantee third-party runtime behavior. Generated architecture maps are independent of the checkout path.

To go further:

- [user guide](user/README.md);
- [installation and operations](admin/installation.md);
- [administrator guide](admin/README.md);
- [developer guide](dev/README.md);
- [architecture flows](architecture/README.md) and
  [project decisions](../../project/decisions/README.md).
