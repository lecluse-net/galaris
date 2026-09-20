<p align="right"><a href="../../fr/dev/functional-tests.md">Français</a> · <strong>English</strong></p>

# Functional guarantees catalogue

Start with business behavior and module responsibility. The suites below are entry points,
not exhaustive certification or proof that a live external account works. The
[September 10 review](../../../project/audits/2026-09-10-functional-tests.md) records replacements
and actual execution results. Keeping an effective test is a valid decision; there is no
quota of new tests per module.

For each change, state the affected guarantee and the guarantees to preserve, inspect their
contracts and tests, then select the least expensive layer that proves the observable effect.

## Cross-domain workflows

Contextual help on business screens remains visible until explicitly dismissed,
permanently stored per account and help key. Familiar screens and the Preferences
menu have no help. The Lab explains its philosophy on its landing page only;
`lab-access.spec.mjs` covers this distinction and the incident journal without help.
`core/user/tests/test_help_dismissals.py` proves persistence, account isolation and
idempotence through the real API. `context-help.spec.mjs` covers closing, acknowledgement,
reopening, existing preferences, errors and retries, late responses and account changes
with real Vue/Quasar components. Domain catalogs own the text; translation changes
never reset an acknowledgement.

Document structure (#168) is covered by `back/app/memory/tests/test_document_structure.py`:
one memory companion per attachment, mandatory image-description persistence, deterministic
projection without models, recursive folder visibility derived from readable documents, and
separate personal classifications. Scenarios use PostgreSQL, including concurrent connections
and stale Dream replay. `memory.spec.mjs` checks open-view invalidation and rejection of a
response started before access revocation.

The [12 September campaign](../../../project/audits/2026-09-12-functional-regressions.md)
strengthens Process admission and recovery, media billing and delivery, evaluation
publication, sessions, resource limits and DbAdmin synchronization. Reproduced defects
are linked to behavioral scenarios and executable mutations in `project/regressions.json`.

Deferred loading is also covered by `select-lifecycle.spec.mjs` (close/reopen, late responses,
saved selections and permission revocation) and `e2e/specs/deferred-tabs.spec.mjs`
(Connections/Authorizations tabs against the real API and DB, selecting agents and preserving
filters when returning to a tab, on mobile and desktop).
The latter also reproduces a late Documents library response while the next page loads:
automatic selection must not cancel navigation. Push tests cover eligibility, deduplication
and the durable effects of provider responses (success, removed subscription, refusal and
unavailability), using a real DB.

| Workflow | Guarantee | Main evidence |
|---|---|---|
| Message → task | Source request and attachments survive an incomplete summary; context supplements them without downstream history. Redelivery retrieves admitted work without duplicating or rewriting it | `back/app/messenger/tests/test_journal.py`, `back/app/conversation/tests/test_task_admission.py`, `test_task_objective.py`, `test_service.py` |
| Dossier approval | The prompt preserves the chat language; the authorized participant can answer numerically without an LLM round, or use an interpreted choice; DbAdmin repairs legacy recipients without approving | `back/app/dream/tests/test_topic_classification.py`, `back/app/messenger/tests/test_service_incoming.py`, `front/app/chat/services/chatService.test.mjs` |
| Task → conversation | A durable completion delivers once and survives reload | `back/app/conversation/tests/test_service.py`, `e2e/specs/chat.spec.mjs` |
| Process → waiting task | An authenticated callback releases the wait; duplicates and late events preserve the outcome | `back/app/process/tests/test_recovery.py`, `test_worker_concurrency.py` |
| Document → file → agent | Content, revision, canonical URIs and ACLs agree across readers and writers | `back/app/memory/tests/test_editorial_html.py`, `back/app/file_share/tests/test_resource_service.py`, `e2e/specs/editorial-html.spec.mjs` |
| Dataset document | Immutable type, exact JSON source, invalid writes leave no revision, shared classification/icons/ACLs, copy/restore and conflicts; CodeEditor preserves invalid drafts | `back/app/memory/tests/test_dataset_documents.py`, `test_document_classification.py`, `test_document_library.py`, `front/browser-tests/dataset-documents.spec.mjs`, `e2e/specs/dataset-documents.spec.mjs` |
| Interactive document HTML | Ordinary HTML forms using shared Datasets, viewer ACLs and personal revision-bound consent; revocation, unapproved cross-Dataset copies, JSON validation and quotas across workers; editable prose and usual toolbar, code only in Source; static print/PDF with resource filtering; isolation, WebRTC, bridge saturation and late responses | `back/app/memory/tests/test_document_apps.py`, `front/browser-tests/document-apps.spec.mjs`, `e2e/specs/document-apps.spec.mjs` |
| Restart / concurrency | Stale workers cannot replace current owners; ambiguous effects are not blindly replayed | `back/app/task/tests/test_active_lease.py`, `back/app/harness/tests/test_checkpoint.py`, `back/tests/test_durable_concurrency.py` |
| Lost tool acknowledgement | An SSH command remains unique after a lost response and PostgreSQL reload; MCP timeouts after effects block replay; retry preserves the journal | `make tests-recovery`, `back/app/harness/tests/test_ssh_checkpoint_recovery.py`, `back/app/harness/tests/test_execution_evidence.py`, `back/app/console/tests/test_durable_operations.py` |

## Application modules

`app/harness/tests/test_conversation_interrupt.py` interrupts a real Pydantic AI agent
during blocked generation and checks that an already started tool finishes exactly once.
`test_conversation_prompt.py` covers wiring through the actual controller and retention
of the draft in its trace. Conversation integrations preserve bursts of messages, reject
a foreign lease and distinguish resumption before effects from consumption after effects.
`app/tools/tests/test_mcp.py` distinguishes authorized functions missing from a run from
mounted functions in EN/FR, without exposing denied functions. The aggregate server test
in `test_mcp_loader.py` verifies that discovery observes the actual run server.

`app/conversation/tests/test_service.py` covers repeated conversational stops of active,
successful, and failed Tasks: terminal results, causes, and revisions are preserved, and
agent scope remains mandatory. `app/tools/tests/test_mcp_loader.py` distinguishes remote
HTTP 403 responses from local denials in French/English diagnostics, without changing the
effect error category or exposing provider URLs or response bodies.

The September 16 dispatcher contract is covered by `test_dispatcher_planning.py` and
`back/tests/test_dispatcher_inference.py`: a human round produces `EXEC standard` without an LLM
call, AI peers retain their limits, and frozen v1 inferences remain reloadable.
`test_conversation_prompt.py` and `test_executor_streaming.py` verify that successful responses
without tools or with repeated wording trigger no judgment or retry, while the executor can
still admit work. Old tests of action/artifact rejection and wording comparison are retired
with those constraints. `test_action_guard.py` retains execution-error recovery and idempotent
delivery guarantees; `test_scheduler.py` checks that a legacy guard verdict no longer bypasses
the checkpoint requirement after an effect.
The following change adds each provider's capability matrix and distinct application of
EXEC standard, EXEC high, BRIEFING, and PLAN. `test_dispatcher_inference.py` proves persistence
of a single-choice Task decision without an LLM call; `test_registry.py` protects historical
decision recovery. The Lab checks the same pairs through `test_contracts_and_passes.py`.

Unless qualified, Python files are in `back/app/<module>/tests/` and browser specifications
are in `front/browser-tests/`.

| Module | Behavior and risks | Suites to retain or strengthen |
|---|---|---|
| `agent` | Authorized agent selection, policy and a coherent terminal result | `test_management_scope.py`, `test_facade.py`, `test_executor_lifecycle.py`, `agents.spec.mjs` |
| `harness` | Tools and streaming, safe recovery, resource cleanup | `test_checkpoint.py`, `test_runtime_cancellation.py`, `test_executor_streaming.py` |
| Harness boundary | Reject invalid results and events before publication, close streams, honor declared capabilities | `make tests-harness-contracts`, `app/agent/tests/test_driver_boundary.py` |
| Harness policies | Shared configuration, SQL conflicts, call-time tool restrictions, opaque checkpoints and safe retry | `test_execution_configuration.py`, `test_checkpoint_contract.py`, `harness-policy.spec.mjs` |
| Real Harness SDKs | Execute all four pinned images against a local model; verify DeepSeek MCP loading | `make tests-harness-runtimes`, `artifacts/harness-runtimes/summary.txt` |
| `harnesses` | Runtime selection and configuration without losing active work | `test_service.py`, `test_runtime_actions.py`, `test_router.py`, `configuration.spec.mjs` |
| `task` | Creation, pause, resume, completion and deletion; budgets and lease ownership | `test_task_service.py`, `test_workflow.py`, `test_active_lease.py`, `test_budget.py`, `task-panel.spec.mjs` |
| Task Working Set | Preserve root/child resources, checkpoints and the first capsule across concurrent commits; idempotent registration and rollback with the caller | `back/app/task/tests/test_working_set.py` (independent PostgreSQL sessions) |
| Conversation amendment | Tolerate only technical revisions with a known definition; reject incompatible checkpoints or executions without a verifiable recovery point before interruption, including concurrent starts; preserve the target and allow explicit idempotent independent creation in the same document | `back/app/task/tests/test_amendment_service.py`, `back/app/conversation/tests/test_service.py`, `test_task_admission.py`, `back/app/agent/tests/test_checkpoint_contract.py`, `back/app/agent/tests/test_realtime.py` |
| Explicit replacement | Persist one text/voice successor, wait for cleanup or valid stop evidence, recover across workers and preserve other holds and independent Tasks; block on predecessor restart, coordination or scope changes | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `back/app/agent/tests/test_driver_boundary.py` |
| Late owners and events | Reject expired lease renewal; an event from another round cannot replace the displayed round and requests server reconciliation | `back/app/task/tests/test_replacement.py`, `back/app/conversation/tests/test_service.py`, `front/app/chat/runtimeState.test.mjs` |
| Chat recovery | Preserve the current conversation against late HTTP successes/denials; retain a useful response when a newer request fails; rearm stream gaps during HTTP and across selection changes; current revocation still purges content | `front/browser-tests/chat-recovery.spec.mjs` (real page/store, replaced HTTP boundary) |
| Chat interruption and reconnection | A correction supersedes the active round; both inputs and one final response survive offline completion and reload across all three browser engines | `e2e/specs/chat.spec.mjs` (full stack, scripted controller at its public port) |
| Conversation commands | Preserve the entire request when stopping needs interpretation; immediately stop a unique target on a simple command; a superseded file resend preserves inputs without delivery or failure | `back/app/harness/tests/test_conversation_prompt.py`, `back/app/conversation/tests/test_service.py` |
| Conversation preparation | Interrupt dispatch/objective preparation without consuming inputs or admitting an obsolete Task; stop the owned inference and retain useful continuation resources | `back/app/conversation/tests/test_service.py`, `test_scheduler.py`, `test_task_objective.py`, `back/app/harness/tests/test_conversation_interrupt.py`, `back/tests/test_structured_inference.py` |
| `goal` | Pause/resume, schedule, cycle judgment and lineage | `test_goal_runner.py`, `test_goal_settings.py`, `test_referrer_wait.py`, `goals.spec.mjs`, `schedule.spec.mjs` |
| `messenger` | Admission, deduplication and delivery within the correct connection and room | `test_journal.py`, `test_ingest.py`, `test_interactions.py`, `test_mcp_routing.py`, `test_mcp_files.py` |
| `conversation` | Context, admissions, results and delivery resolution without repeated effects | `test_service.py`, `test_task_admission.py`, `test_delivery_resolution_http.py`, `e2e/specs/reliability.spec.mjs` |
| `chat` | Sending, archive/restore, streaming recovery, user/room isolation and choices without an LLM (buttons, recovery, expiry) | `test_authorization.py`, `test_events.py`, `test_native_facade.py`, `chat.spec.mjs`, `chat-interactions.spec.mjs`, `e2e/specs/chat.spec.mjs` |
| Chat and document | Open and edit in the full editor; save before sending and pass the URL to the prompt only while the document is displayed; preserve the draft on failure; reserve the integrated pane for desktop (≥ 1024 px), with controls in the document title bar; open a dialog on mobile; resize both desktop layouts with a mouse, touch and keyboard without losing edits; keep side-by-side documents at least 560 px wide, automatically stacking the panes when space is insufficient; keep the right sidebar visible on desktop and preserve content and conversation across reconnect | `front/browser-tests/chat-document-workspace.spec.mjs`, `back/app/conversation/tests/test_service.py`, `back/app/chat/tests/test_native_facade.py`, `back/app/memory/tests/test_document_library.py`, `back/app/memory/tests/test_document_grants.py` |
| `voice` | Call setup/cancellation, correct channel and media cleanup | `test_session.py`, `test_multichannel_routing.py`, `test_realtime_engine.py`, `voice.spec.mjs` |
| `memory` | Search, creation, sharing and restoration without losing content, revision or rights | `test_document_library.py`, `test_document_grants.py`, `test_editorial_html.py`, `test_semantic_search.py`, `memory.spec.mjs` |
| Document thumbnails | Reuse the print snapshot and its images for the beginning of the first page; persist the captured revision; renew the cache after edits; recheck permissions; load near visibility and discard stale responses while keeping documents accessible | `back/app/memory/tests/test_document_thumbnails.py`, `front/browser-tests/document-thumbnails.spec.mjs`, `browser-executor/pdf.test.mjs` |
| `contact` | Correct interlocutor and scope isolation | `test_service.py`, `test_router.py` |
| `topic` | Classification, search beyond the first page and stale-response rejection | `test_service.py`, `test_router.py`, `test_sequential_detection.py`, `topics.spec.mjs` |
| `dream` | Knowledge extraction/linking without rewriting existing content; resumable processing | `test_memory_extraction.py`, `test_claim_timeout.py`, `test_skill_learning.py` |
| `skill` | Author/read procedures, preserve files and permissions, apply learning decisions | `test_service.py`, `test_storage.py`, `test_learning.py`, `skills.spec.mjs` |
| `process` | Start, observe, cancel and recover external work; immutable terminal outcomes | `test_recovery.py`, `test_process_core.py`, `test_router_scope.py`, `test_worker_concurrency.py`, `execution.spec.mjs` |
| `tools` | Authorized discovery, access denial and secret redaction; revocation before effects on an already mounted native server, reactivation and agent isolation | `test_admin_access.py`, `test_agent_registry.py`, `test_secrets.py`, `test_resource_effects.py`, `test_live_authorization.py` |
| Web search | Preserve query, encoding, order and configured language; distinguish empty, partial, degraded and failed searches; retain valid sources, redact raw exceptions and cancel transport without blocking the event loop | `back/app/tools/tests/test_search.py` (replaced HTTP boundary, real client and tool) |
| Search availability | HTTP 200 without sources does not pass the probe; degradation retains sources and produces a distinct verdict | `back/app/tools/tests/test_search.py`; `make check-search` for the opt-in external corpus, with human relevance review |
| `connection` | Configure connections and functions without leaking secrets or another agent's scope | `test_connections.py`, `test_encryption.py`, `test_function_states.py` |
| `mcp` | Expose capabilities and propagate execution identity | `back/tests/test_realtime_security.py`, `back/app/tools/tests/test_mcp.py`, `back/core/authorize/tests/test_guard_provider.py` |
| `file_share` | Canonical URI operations, ACLs, limits and temporary-file cleanup | `test_resource_service.py`, `test_transport.py`, `test_web_transport.py`, `test_galaris_provider.py` |
| `console` | Scoped execution and file transport without path traversal | `test_console.py`, `make tests-executor` |
| `browser` | Navigation and resource retrieval with session isolation, limits and explicit failures; bounded public codes, expiry without automatic action replay and explicit reopening | `test_service.py`, `test_mcp.py`, `make tests-browser` |
| `llm` | Provider/model resolution, functional parameter preservation, budgets and access policy, traces and costs; pause/resume, readback and rejection of late writes | `test_subscription_policy.py`, `test_structured_service.py`, `test_call_lineage.py`, `back/tests/test_provider_catalog.py`, `back/tests/test_provider_parameters.py`, `back/tests/test_inference_lifecycle.py`, `back/tests/test_protocol_inference.py`, `back/tests/test_structured_inference.py`, `back/tests/test_dispatcher_inference.py`, `back/tests/test_briefing_inference.py`, `execution.spec.mjs` |
| `audio` | Canonical media transcription and result delivery | `test_audio_mcp.py`, `test_audio_service.py`, `test_summary_service.py` |
| `image` | Image generation/reading, resource identity and call trace | `test_image_mcp.py`, `test_image_service_trace.py` |
| Native multimodal inputs | Supply images, audio, video and PDFs to compatible models; retain provenance, access checks, byte budgets and media on resume without an analysis tool prerequisite | `app/harness/tests/test_native_media.py`, `test_media_resource_policy.py`, `tests/test_pydantic_ai_internal_model.py`, `app/messenger/tests/test_ingest.py` |
| `multimedia` | Long-running generations, authenticated callbacks and publication | `test_multimedia.py`, `test_callback_security.py`, `test_providers.py` |
| `lab` | Dataset/item isolation, parameters, rights and two passes; resume repetitions without duplicates, stop at budget and preserve independent reviews before judge disclosure | `test_authorization.py`, `test_contracts_and_passes.py`, `test_run_publication.py`, `test_stability_and_review.py`, `lab.spec.mjs`, `lab-access.spec.mjs`, `lab-insights.spec.mjs` |
| `incident` | Group, diagnose and resolve failures with authorization and correction evidence | `test_incident_service.py`, `test_router.py`, `test_retention.py`, `lab-access.spec.mjs`, `e2e/specs/incident.spec.mjs` |
| `dashboard` / frontend `index` | Scoped metrics with bounded aggregations; reuse visited months, refresh and invalidate the cache when access changes | `test_dashboard_service.py`, `dashboardStore.test.mjs`, `dashboard.spec.mjs`, `shell.spec.mjs`, `preferences.spec.mjs` |
| `onboarding` | Initialize without overwriting existing configuration | `test_services.py` |
| `webhook` | Authenticate and identify incoming deliveries without duplicate admission | `test_router.py`, `test_delivery_identity.py` |

### Topic selection and creation

`TopicSelect` centralizes paginated search and selection by topic ID. Entry forms enable
`allow-create`: new conversations, conversation preferences, messages with `@topic`, badge
reassignment, assignment editors for tasks and text/voice conversations, and merge targets.
The `+` button requires `TOPIC_EDIT` and `AGENT_MANAGE_ALL`, matching the global-topic creation
API. Readonly and disabled fields cannot create topics. Task and text/voice history filters
keep `allow-create=false` while remaining selectable.

The Memory filter is separate: its values are IDs of `MemoryItem` projections of topics,
authorized for the selected agent. It retains its Memory catalogue and never offers creation;
substituting topic IDs would break the filter contract. Laboratory topics are evaluation
dataset records.

Guarantees: the created topic becomes the form selection without losing its draft;
cancellation, errors, revoked privileges and context changes cannot replace the selection
with a stale response. Merging excludes the source topic and uses the shared paginated
search. Evidence: `topics.spec.mjs`, `chat.spec.mjs`, `select-lifecycle.spec.mjs` and
`filter-loading.spec.mjs` in `front/browser-tests/`.

The Conversation tool `document_show` is covered by `back/app/memory/tests/test_document_show.py`
and `front/browser-tests/chat-document-workspace.spec.mjs`: internal Chat-only availability independent of the Memory connection,
ignoring historical system-service function denials (ADR 0105),
document access and revocation checks, opening and reopening the viewer without losing drafts,
and ignoring requests for a different conversation.

## Shared infrastructure and UI

| Domain | Guarantee | Evidence |
|---|---|---|
| `core.user` | Login, MFA, concurrent refresh, revocation and last administrator | `back/core/user/tests/test_user_flow.py`, `test_refresh_concurrency.py`, `test_admin_invariants.py`, `e2e/specs/session-races.spec.mjs` |
| Public registration | A single initial administrator even under concurrent signup; subsequent signup disabled by default and configurable without granting permissions; closed page, network errors and late responses | `back/core/user/tests/test_registration_policy.py`, `back/core/params/tests/test_runtime_preferences.py`, `front/browser-tests/registration.spec.mjs` |
| `core.authorize` | Actual router and resource access denial | `back/core/authorize/tests/test_route_security.py`, `test_resource_rules.py`, `test_assertions.py` |
| `core.params` | Retain custom values or explicitly adopt new defaults; keep every setting accessible after expanding sections, preserving drafts and permissions on desktop and mobile | `back/core/params/tests/test_services.py`, `test_dbadmin.py`, `front/browser-tests/preferences.spec.mjs`, `params-layout.spec.mjs` |
| `core.dbadmin` | Lossless convergence, replay, dependency order and independent contributions | `back/core/dbadmin/tests/test_postgresql_transitions.py`, `test_actions.py`, `test_registry.py`, `make tests-upgrade` |
| Initial titles | Seed a fresh database once; preserve later changes to labels and genders, additions and deletions, even when every row is removed | `back/app/agent/tests/test_dbadmin.py` |
| Translated titles | Translate seeded keys in the frontend, preserve them when saving without renaming, and keep custom labels literal | `front/browser-tests/agents.spec.mjs` |
| DB / runtime | Isolated sessions, concurrency, timeout and cleanup | `back/core/tests/test_database_context.py`, `test_runtime_timeouts.py`, `back/tests/test_durable_concurrency.py` |
| i18n / navigation / API | Consistent catalogs, authorized navigation and responses bound to the correct account/request | `make typecheck`, `front/core/api.test.mjs`, `front/browser-tests/lab-access.spec.mjs`, `e2e/specs/session-races.spec.mjs` |
| Content / previews / files | Edit, read and print without corruption or unintended execution; adapt page width automatically to the container, including fullscreen and read-only views, while preserving content and the manual preference; release attachments | `back/core/util/tests/test_rich_text.py`, `back/core/preview/tests/test_conversion.py`, `front/browser-tests/rich-text.spec.mjs`, `document-print.spec.mjs`, `document-layout.spec.mjs`, `model3d.spec.mjs` |
| PWA / release | Version updates, exact release images, backups and restoration | `e2e/specs/pwa.spec.mjs`, `back/tests/test_release_qualification.py`, `make tests-release`, `make tests-restore` |

## Bridges: test each protocol adaptation once

Bridge suites are under `back/bridge/<module>/tests/`. Shared messaging and process rules
belong in their canonical domains. Network doubles prove local requests, conversions,
denials and retries, not delivery to a real remote account.

| Module(s) | Adaptation contract | Evidence |
|---|---|---|
| `matrix` | Identity, messaging and voice | `test_client.py`, `test_messenger.py`, `test_voice.py` |
| `nextcloud` | Talk credentials, messages, calls and signaling | `test_credentials.py`, `test_messenger.py`, `test_call_listener.py`, `test_signaling.py` |
| `one_bot` | Event/API routing and hub connections | `test_hub.py`, `test_router_routing.py`, `test_messenger_routing.py` |
| `telegram` | Messaging and delivery retry | `test_messenger.py`, `test_delivery_retry.py` |
| `whatsapp` | Bridge authentication, API and Messenger delivery | `test_router.py`, `test_client.py`, `test_messenger_send.py` |
| `mail` | MIME, identity, authorized connections and files | `test_assertions.py`, `test_connection_resolution.py`, `test_mime.py`, `test_messenger.py`, `test_file_transport.py` |
| `calendar` | Dates/recurrence, limits and authorized operations | `test_ical.py`, `test_calculation_limits.py`, `test_service.py`, `test_mcp.py` |
| `n8n` | Translate startup, callbacks and cancellation to Process | `test_n8n_bridge.py` |
| `harness` | Manager diagnostics and container lifecycle | `test_manager.py`, `test_diagnostics.py`, `make tests-harness-manager` |
| `hermes` | Execution, cancellation, history, secrets and session binding | `test_executor_cancellation.py`, `test_executor_history.py`, `test_session_binding.py`, `back/tests/test_driver_conformance.py` |
| `claude_agent`, `codex`, `deepseek_harness` | Provider and runtime adaptation contracts | Their `test_harness_provider.py`; `test_stream_trace.py` for Claude/Codex; `test_runtime_adapter.py` for DeepSeek |
| `openai` | Resources, authentication and realtime protocol | `test_resources.py`, `test_runtime_auth.py`, `test_realtime.py` |
| Other conditional providers | Shared catalogue registration, configuration, discovery and adaptation | `back/tests/test_provider_catalog.py` and `app.llm` / `app.multimedia` suites |
| `youtube` support | Transcript retrieval and errors | `test_transcript_service.py` |

Other declared providers are `openrouter`, `mammouth`, `anthropic`, `deepseek`, `fireworks`,
`groq`, `mistral`, `models_dev`, `together`, `cerebras`, `google`, `xai`, `nvidia`, `huggingface`,
`cohere`, `perplexity`, `elevenlabs`, `sunoapi`, `byteplus`, `azure_speech`, and `ollama`.
The shared suite does not exhaustively qualify every operation. Add a provider-specific case
when its protocol differs, not a duplicate canonical workflow. Frontend bridge configuration
modules follow the same functional form contracts.

## Maintenance rule

A guarantee has a primary proof and, when useful, an E2E assembly proof. A new private function
does not automatically need a test. A new business branch, denied operation, possible data loss
or replayable effect needs evidence. Intentional changes explain before/after behavior;
retired tests identify guarantees retained elsewhere and incidental constraints dropped.
Track escaped regressions, flakiness, feedback time and relevant mutations rather than test count.

### Personal chat document opening preference

The profile stores each user's split-screen or dialog preference, defaulting to split
screen for new and existing accounts. The setting is visible only when internal chat is
enabled and accessible. The primary document attachment action follows this preference
on desktop; mobile and users without co-editing access open a dialog. The icons still
allow an explicit choice of another available opening mode. Failed saves retain the
previous preference.

Coverage: `back/core/user/tests/test_user.py`, `front/browser-tests/preferences.spec.mjs`
and `front/browser-tests/chat-document-workspace.spec.mjs`.

Dependency review: `app/chat` consumes only the public `useAuthStore` and `DocumentOpenMode`
exports from `core/user` to read and save this preference. This application dependency on
user infrastructure adds neither private imports nor cycles.

### Personal document classification

- `back/app/memory/tests/test_goal_folders.py`: automatic filing per user and Goal, preserving
  manual folders and current access; paginated global catch-up, duplicate Goal names, renames,
  deletion/recreation, Goal/User/sharing/provenance triggers, concurrent manual moves, rollback
  and protected administrative launch.
- `back/app/memory/tests/test_document_classification.py`: private tags, read-only classification
  without document mutation, acyclic trees, recursive deletion with conditional confirmation
  returning documents to the orphan list while preserving other users' tags, filtering before
  pagination and effective removal of documents after access revocation; atomic replacement of
  the user's tags, persistent personal order for mixed siblings and the list, stale-anchor rejection,
  a durable private SVG palette and SVG validation.
  Folders always precede documents; alphabetical sorting in either direction persists privately,
  ignores case and accents, and preserves document content.
  Personal document icons survive classification changes without mutating content; revoked access
  prevents reading or changing them.
  Classification notifications reach only their owner and identify affected folders, without
  triggering the global snapshot invalidation reserved for access changes.
- `front/browser-tests/document-classification.spec.mjs`: drag/drop moves and unclassification,
  immediate folder/subfolder creation with inline rename and cancellation, Unicode emoji, colored folders, icon fonts and reusable uploads,
  compact filters, resettable unclassified toggle enabled by default, fully loaded lazy branches independent
  of list search, folder/document ordering preserved on reopening, immediate deletion of empty tags
  and confirmed deletion with cancellation, stale responses and recovery after request errors.
  The contextual toolbar supports hover, keyboard and touch, inserts a sibling immediately after
  its folder, and replaces double-click editing. Alphabetical sorting keeps folders first;
  recursive expansion/collapse stays within the chosen branch, with recoverable positioning/sort errors.
  Empty folders can be opened, collapsed and reopened without another request.
  Targeted refreshes preserve unrelated rows during slow responses, folder renames do not reload
  documents, and access invalidation still removes visible snapshots immediately.
  Document icon choices propagate between tree and list, persist on reopening and ignore stale
  reads or previous-session writes; resetting the default and retrying failures remain usable.
  In the tree, a document icon opens the document without an icon picker; folder icons remain editable.
- `front/browser-tests/memory.spec.mjs` and `document-sharing.spec.mjs`: on-demand pagination,
  mobile opening, creation and saving with a human identity.

### Mobile editing toolbar

Dialogs and their backdrop cover the split document's toolbar, including its sticky state
after scrolling. Closing and reopening preserve the document; formatting remains usable
inside the dialog. Coverage: `front/browser-tests/chat-document-workspace.spec.mjs`.

Below 1024 px, the shared editor places icons at their natural width and wraps them according
to available space, without visual groups or scrolling. Actions follow their function: editing,
formatting, voice, links, files and sharing, according to the field's capabilities. All actions
are directly accessible without an overflow menu. Changing width preserves content and ongoing dictation.

Sharing prepares the current content as a PDF and opens native sharing on an explicit user
action. The Galaris URL accompanies the share when supported, without being added to the PDF.
If file sharing is unavailable, the dialog offers to save the PDF. Cancellation and document
changes prevent an outdated PDF from being offered.

Coverage: `mobile-editor-toolbar.spec.mjs`, `document-voice.spec.mjs`,
`rich-text.spec.mjs` and `document-print.spec.mjs` in `front/browser-tests/`.
