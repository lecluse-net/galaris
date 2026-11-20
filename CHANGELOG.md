# Changelog

All notable changes to Galaris are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Set a **Default fallback profile** in **Configure → Providers & models → Models in use**.
  Agents without a secondary profile inherit it. Eligible calls can switch to the model
  for the same usage if the primary provider fails or access to the ChatGPT subscription
  is refused. Automatic Mail Tasks and their child Tasks that would use a personal
  ChatGPT subscription switch to an eligible API fallback when available. Task details
  show whether the switch was possible.
  [Fallback profiles](docs/en/reference/functional-catalogue.md#fallback-profiles)
- **Deep conversations** send messages directly to the agent's harness with
  `@deep`. Each private Chat conversation remembers the mode and has its own
  resumable session. Deep sends the message and its attachment links, with the
  agent's personality and job description as system instructions. Chat streams
  replies and shows harness activity, approvals and failure reasons. LLM Activity
  can filter the calls recorded by Galaris by conversation. Existing managed
  harness instances need a rebuilt image to use the Deep adapter.
  [Deep conversations](docs/en/reference/functional-catalogue.md#deep-conversations)
- **Managed harness multitasking** lets one agent run several Tasks at once
  with Codex, Claude Agent or DeepSeek Harness. The scheduler supplies available
  slots, and administrators can set a per-agent limit in the harness policy.
  LLM Activity attributes each call and its usage to the exact Task and attempt.
  Update older harness instances to enable the capability. This recreates the
  instance and clears its local data.
  [Harness multitasking](docs/en/reference/functional-catalogue.md#harness-multitasking)
- A **Windows and Linux desktop client** connects to your Galaris server over
  HTTPS. It adds tabs and French and English spellchecking. Windows and AppImage
  can download client updates and install them after you approve a restart.
  [Desktop guide](docs/en/user/desktop.md)
- Create **mind maps** in Documents, edit and reorder branches, embed resources,
  and restore saved revisions. Import and export Freeplane/FreeMind, OPML, modern
  XMind and native mind maps. Agents can read and edit branches with revision
  checks. [Document guide](docs/en/user/documents.md#mind-maps)
- Import **PDFs, Office and OpenDocument files, RTF, EPUB and supported images**
  from your computer or a connected file space. Converted documents retain the
  original attachment and have editable content with their own images. Scanned
  PDFs can use OCR. ZIP imports can recreate folder trees, and retrying skips
  files that were already imported. [Import guide](docs/en/user/documents.md#import-a-file)
- Every agent has a **personal agenda**. View appointments, dated memories and
  Goal cycles together, and schedule Tasks from event starts or reminders.
  Connect CalDAV, Google Calendar, Microsoft 365 or iCloud for background
  synchronization, or subscribe to read-only iCalendar feeds. Authorized upcoming
  events can inform the agent's work. [Agenda guide](docs/en/user/calendar.md)
- Browse bundled **Service presets**, configure a local copy and exchange custom
  Services as standalone YAML with their icons. GitHub refresh keeps the last
  usable catalogue on failure. Each Connection holds its own credentials and
  permissions. [Service guide](docs/en/user/services.md)
- Install and activate **signed plugins** from ZIP files or an operator-managed
  catalogue. Plugins can contribute Service presets, Data templates, document
  formats, model providers, preview converters and file-sharing protocols.
  Executable contributions require separate publisher trust. Removing a plugin
  preserves existing documents and local Services. [Plugin guide](docs/en/dev/plugin-bundles.md)
- Configure **multiple IMAP/SMTP mailboxes per agent**, including accounts with
  the same provider. Each Connection keeps its own credentials, allowed folders
  and permissions. Test saved protocol credentials and inspect effective function
  permissions from the Connection editor. [Service administration](docs/en/admin/service-administration.md)
- Agents can convert supported files to **PDF** or render a PDF page as PNG.
  Both operations respect file permissions and preserve the original.
- **Goals** support weekly, monthly and yearly intervals and private categories.
  Subgoals follow their root Goal's category for filtering without changing access.
- **Chat** saves private drafts across navigation and reloads, including uploaded
  attachments. Reply-needed badges remain visible after messages are read. Planner
  clarification questions can send reminders in their original conversation.
  [Task guide](docs/en/user/tasks.md)
- View and filter **MCP tables** in internal Chat. On desktop, insert the displayed
  rows and their source into an open Text document as editable HTML.
  [MCP tables in documents](docs/en/user/documents.md#insert-a-table-from-an-mcp-service)
- Search the **agent directory** by team, manage the current team's membership
  from Agents, and browse team rosters through read-only agent tools. Give avatar
  generation appearance and style instructions. Administrators can customize
  shared operating guidance for Tasks and text and voice conversations.
- The **Administration Service** can list incidents and inspect individual traces
  within the agent's delegated administrative scope.
- Limit **transcription** to the start of a source and include supplied subtitles,
  embedded captions or speech transcription in video analysis. Add Hugging Face
  embeddings, transcription, speech and image inference on supported routes.
- Plan compositions with **Eleven Music**, supply authorized reference frames to
  Seedance, and configure Suno through its official MCP Service preset.
- Use **`make save` and `make restore`** for verified offline backup and recovery
  of PostgreSQL, configuration, keys and application data. Back up `/data/files`
  separately at the same logical point. Restore retains a recovery copy and
  leaves services stopped. [Backup and restore](docs/en/admin/installation.md#backup-and-restore)

### Changed

- The **Tools configuration domain becomes Services**. Update integrations from
  `/api/tools` to `/api/services`, from `tool_id` and `tool_code` to `service_id`
  and `service_code`, and from `tools_list` and `tool_admin_*` to `services_list`
  and `service_admin_*`. Replace `TOOL_ACCESS` and `TOOL_EDIT` with
  `SERVICE_ACCESS` and `SERVICE_EDIT`. MCP tool calls retain their protocol. The
  upgrade migrates Service identities and privileges in place and converts legacy
  Mail and Calendar connections to provider Services with their settings and history.
  The built-in administration Service changes from `galaris_admin` to `platform_admin`.
  [Service migration contract](docs/en/dev/service-catalog.md)
- **`document_format` replaces `document_type`** in document contracts.
  Use `/api/documents/formats` for format discovery. The upgrade maps
  legacy `html` and `form` to `text`, preserving content, URIs, revisions and
  access. Update integrations that use the old field, codes or discovery route.
  [Document format migration](docs/en/dev/document-formats.md#migration-and-limits)
- Browse the **document library** by folder, topic or agent, and move selections
  atomically. Text documents and mind maps share link, card and embed controls.
  Chat can send the current selection and saved document revision to an authorized
  agent. Text and Data saves remain immediate, while content history groups rapid
  edits into a checkpoint after five quiet minutes. Dream waits for substantial
  edits before refreshing summaries. [Document guide](docs/en/user/documents.md)
- New personal and synchronized **agendas** enable background Task launches at
  event start by default. Existing reminder timing and explicitly disabled
  launches are preserved. [Agenda settings](docs/en/user/calendar.md#replace-a-notification-with-a-task)
- **Goal monitoring** carries each Task result into the next cycle and uses the
  configured Decision model to choose whether to continue or stop. If that model
  is unavailable or unconfigured, cycles continue on schedule. Human pauses and
  pending replies remain in force. Goal tracking documents can hold attachments.
- A **weekly retrospective Goal** lets each agent apply verified lessons to its
  personal skills. Users can reschedule or pause it. Existing learned packages,
  evidence and activation thresholds are retained. [Skills guide](docs/en/user/skills.md)
- **Managed agent harnesses** now use Hermes 0.23.2, DeepSeek Harness
  0.2.2-rc.5 (prerelease), Claude Agent SDK 0.2.185 and Codex SDK 0.170.0.
  To upgrade an existing instance, wait for the agent's Tasks to finish and
  choose **Update** in the harness supervision view. This recreates the instance
  and clears its local data. [Harness Manager guide](docs/en/components/harness-manager.md#runtime-versions)
- **`make update`** builds the selected checkout on any branch or tag, independently
  of `APP_ENV`. It builds before replacing services, requires complete database
  convergence before startup and waits for readiness. Use `VERSION` to select a
  Git reference explicitly, or `RELEASE_DIR` to deploy qualified immutable images.
  Before upgrading, check that `flock` from `util-linux` is installed and back up
  the database, files and keys together.
  [Update guide](docs/en/admin/README.md#10-update)

### Removed

- Dream's per-Task skill learner and its settings. Skill learning now runs through
  the weekly retrospective.
- Automatic Goal review Tasks and generated monitoring summaries. Historical
  reviews and their costs remain available.

### Fixed

- Preserve recorded Tool results when amending a Task and preserve pending
  authorizations while child Tasks finish. Report required blocked objectives
  separately from runtime errors. Blocked optional milestones can leave the main
  result successful.
- Keep clarification follow-ups on the original Task, recover referrer answers
  after failed Goal cycles and show the next cycle within the allowed schedule.
- Count unread internal Chat messages separately from external messages and
  preserve clickable resource links in agent replies. Keep private drafts scoped
  to the active account and browser session.
- Preserve table formatting when pasting across documents, support formatting
  shortcuts on AZERTY and the numeric keypad, and preserve in-progress document
  drafts during navigation and delayed refreshes.
- Show approval actions and their scope in the approver's language. Preserve
  the chosen decision after replying and show it in the conversation.
- Preserve provider subscription confirmation during pricing refreshes. Improve
  multimedia recovery after temporary provider or download failures while
  retaining receipts for deliveries with uncertain outcomes.

### Security

- Isolate the built-in Galaris assistant from peer messages, Tasks and files.
  Apply consistent sender scopes across native and external peer messaging,
  including recipient opt-outs and Connection availability.
- Add repository-wide `make dependencies-audit` reports for locked dependencies
  and optional built-image scans. Update OpenTelemetry API, minimatch and glob
  to address CVE-2026-126360, CVE-2026-118764 and CVE-2026-118773.
  [Security validation guide](docs/en/dev/security-validation.md)

## [0.3.1] - 2026-11-03

### Changed

- Require successful Security checks for the exact release commit,
  followed by a fresh source security scan, before publishing a GitHub Release.
  Missing or unsuccessful evidence blocks publication with retained diagnostics.
  Immutable image bundle builds also check committed sources before building.
- Keep automatic CI checks focused; complete functional qualification remains
  available through an explicit full Quality run, with its results reported separately.

### Fixed

- Fix upgrades from 0.2.0 containing Data documents: preserve historical sources
  before schema expansion, then copy contents, revisions and permissions after
  destination columns exist. Resume unfinished 0.3.0 transfers safely.
- Preserve new Agent HTML profiles and allow Goal creation and editing while
  database cleanup is deferred. Keep transferred tracking documents and their rights.
- Preserve revoked Agent team memberships when an interrupted upgrade resumes,
  including transfers already completed by a previous version.
- Retain backend startup output and fatal and nonfatal database synchronization
  errors in private update logs, without a last-lines limit. Redact recognized
  secrets, reprint recorded causes before retrying unfinished actions, and report
  diagnostic collection failures without replacing the original update error.
- Allow long Goal descriptions and tracking reports without blocking agent updates.
- Preserve early history navigation while conversations finish loading, and apply
  editor toolbar formatting to the current text selection after dismissing a menu.
- Preserve the reading position when late content expands a partly visible Chat message.
- Recheck open Memory details after access refreshes and reconnects, preserving authorized
  drafts and closing revoked details instead of leaving an empty dialog.
- Keep the folder name field focused when renaming from its context menu.
- Preserve native text selections while the editor updates, so formatting
  applies to the highlighted text.
- Preserve the requested initial focus in nested confirmation dialogs.
- Preserve file selection when a thumbnail finishes loading during a click.
- Keep Dream monitoring available when no vector model is configured.
- Preserve Goal edit revisions when asynchronous Memory projections are attached or removed.
- Group realtime subscription updates during page startup to preserve Chat room
  joins over long polling.
- Keep custom Tools classified separately from built-in Tools when opening Connections.
- Display avatars in scoped Agent selectors without requiring Agent administration rights.
- Avoid loading document previews and personal icons without Documents privileges,
  and ownership editing options for read-only Document roles.
- Verify upgrades from an earlier release with that release's own dependencies,
  including rollback, instead of importing historical code with candidate packages.

### Security

- Move backend and SSH runtimes to a supported Ubuntu LTS with corrected OpenSSH
  and libxml2, while retaining Python 3.14 and PostgreSQL 17 clients. Remove unused
  vulnerable GStreamer codecs from the Chromium executor. Preserve raw image
  inventories and restrict kernel-header assessments to reviewed CVE/package
  versions after verifying that no kernel implementation is shipped.
- Replace python-jose with PyJWT 2.15.1 to remove the dependency affected by
  CVE-2026-85394 and reject DER public keys used as HMAC secrets. Existing HS256
  access tokens remain compatible. Remove the unused ecdsa dependency and its
  former vulnerability exception.
- Update the locked follow-redirects dependency to 1.16.2 for CVE-2026-116689.

## [0.3.0] - 2026-11-01

### Added

- **Document retrieval:** automatically select bounded, cited RAG passages when
  document inputs exceed the model's available context. Agents can search authorized
  files again through `file_search`; retrieval creates no personal memories. Source
  deletion purges derived indexes and temporary preparations, including active builds.
- **Document import and copying:** create independent Text or Data documents from
  HTML, Markdown, text and JSON files, or copy an existing document with its images
  and attachments.
- **Equations:** visually edit inline and block formulas, with LaTeX preserved in
  saved versions and offline exports.
- **Group document moves:** select documents with Ctrl/Cmd or Shift and drag the
  selection together. Failed moves remain selected for retry.
- **Private address books:** manage phone numbers and postal addresses alongside
  email identities, find platform users and agents, and insert Contact cards in
  documents. Sharing a document does not expose private contact details.
- **Mail browsing in Files:** read IMAP folders and messages, preview attachments
  and download original emails without marking messages as read or authorizing
  agent processing.
- **Permissions dashboard:** inspect each agent's effective Tool policies, local
  administration scopes, pending approvals and remembered decisions. Permanent
  denials are available for Tools, harness actions, network access and mail processing.
- **Direct repository access:** open Git repositories from Files in the code editor;
  closing and reopening it preserves unsaved buffers.
- **ChatGPT Fast models:** select advertised Fast variants separately in model
  profiles, with higher subscription usage for priority service.

### Changed

- **Welcome:** keep the setup journey as each user's home page until they explicitly
  confirm completion, including on preconfigured instances. The Galaris logo returns
  to the journey while setup is pending.
- **Connections:** expose agent permissions directly and retain tool-catalogue refresh
  results, with retry after failures without losing the connection list.
- **One document library:** Text and Data documents now live together in
  **Knowledge → Documents**, with type filters, folders, sharing and content history.
  Existing Dataset links and `data://` references remain usable. Shared folders can
  be browsed and cited by agents, and documents can be placed explicitly at the root.
- **Current document summaries:** read, edit or regenerate a document's summary
  beside its content. Summaries and keywords are current metadata, independent
  of document content versions.
- **Skills:** Dream's learned procedures now use personal skill packages, with
  their evidence and activation controls. New Skills connections allow personal
  package management by default; existing restrictions are preserved. Administrators
  can disable a generic skill for everyone without deleting it or its assignments.
- **Goals:** edit descriptions directly in the Goal, with shorter tracking reports
  and a configurable tracking prompt. Existing tracking documents remain available.
- **Files and attachments:** use the same resource picker across Chat and editors,
  browse document folders, and open resources in their own viewers. File indexing
  settings now live in **Preferences → Files**.
- **Memory continuity:** improve conversational follow-ups, contact discovery and
  structured Data retrieval, while retaining corrected facts and their sources.
- **Messaging:** improve Matrix session reuse and contact attribution. OneBot and
  WhatsApp receive connection and delivery fixes and are explicitly marked experimental.
- **Editor interactions:** contextual tools follow the selected object while native
  browser menus remain available; mobile text selection and deletion are preserved.
- **Upgrade preparation:** back up the complete database, stored files and encryption
  keys together before upgrading. Use `make update` to apply the resumable Text/Data
  document migrations, and keep older backends from writing during that transition.
  Existing Dataset links and historical source data are retained; see the
  [upgrade guide](docs/en/admin/README.md#upgrade-0-3).

### Removed

- Separate document-summary history. Current summaries and keywords are preserved;
  document content keeps its restorable versions.
- The separate learned-skills catalogue. Learned procedures are managed through
  personal skill packages, with their evidence and activation settings retained.
- Automatic document filing when creating a Goal.

### Fixed

- Resume the original operation after action approval, including document creation
  followed by background editing, without replaying completed actions. Obsolete
  approval waits are cleared.
- Preserve attachments and internal resource references through sending, reloading
  and agent execution. Fix first-tap sending and keyboard focus in mobile Safari.
- Retain document-analysis output for reasoning models and report empty or failed
  analyses explicitly. Image generation can recover from an unsupported OpenRouter
  resolution by retrying with the provider's default.
- Keep explicitly blocked Task milestones from being reported as successful.
  Agents awaiting a colleague can suspend and resume without sending the request again.
- Keep consented document applications usable after saving Data, enforce their write
  limits before consuming quota, and preserve access revocations. Browser Back from an
  invalid JSON draft offers staying to correct it or explicitly discarding it without
  replacing saved data.
- Restrict active Process work to the agent's participation and current access rights,
  restore authorized Process browsing in Files, and retain Lab campaign references to
  Data documents after migration.
- Make secondary-profile failover reliable after provider connection errors, timeouts
  and eligible HTTP failures while preserving completed Tool actions.
- Show inherited global Tool parameters to authorized connection editors while keeping
  secrets masked and connection-only readers restricted.
- Preserve requested Tools/LLM tabs while permissions load or refresh, and restore
  keyboard folder renaming and context-menu focus.
- Restore managed external Console editor installation and updates after runtime
  security upgrades by including their complete build dependencies.

### Security

- Update PDF and ASN.1 dependencies and bundled Browser, SSH and Code executor
  runtimes to include available security fixes.

## [0.2.0] - 2026-10-25

### Added

- **Document workspace:** organize documents in folders and nested documents,
  manage ownership, keywords and sharing in bulk, and discuss a document with an
  agent in a contextual conversation that can be reopened later.
- **JSON Datasets:** create, edit, share and version structured data independently
  of Text documents, and reuse it in document applications and workflows.
- **File browser and indexing:** explore an agent's authorized files, including
  Samba/SMB shares, with previews, downloads and private indexing. Office files and
  spreadsheets gain thumbnails; shared videos support seeking during playback.
- **Memory exploration:** navigate a progressively loaded 3D graph, retain personal
  layouts, inspect resource previews and run Dream maintenance on selected items.
- **Personal skills:** create and edit private skill packages for individual agents,
  control activation and transfer ownership separately from generic shared skills.
- **Native business workflows:** design BPMN processes combining agents, humans,
  Tools and REST calls, with branches, typed data and live run inspection. AI decisions
  can use a selected model directly. Creation through the UI is temporarily restricted
  to development mode; existing processes remain available for authorized use.
- **Conversational code editor:** work with an agent on the same SSH Git checkout
  through an integrated VS Code workspace.
- **Delegated administration:** optionally let agents manage agents and Tools within
  explicitly granted scopes. REST API Tools and per-connection MCP OAuth extend the
  available integrations.
- **Guided first missions:** start from an editable example request and follow it
  through to its document deliverable.
- **Model resilience:** configure a secondary LLM profile for provider failures.
  Provider concurrency controls prioritize voice, then text conversations, then
  background work; balances, usage and pricing refresh automatically.

### Changed

- **Documents and memory are separate:** shared documents own their content,
  revisions and permissions; an agent's personal memories remain private. Folder
  and parent-document access can extend access to documents beneath them.
- **Document editing:** a new editor preserves rich HTML, embedded applications and
  attachments, with formatting shortcuts, find/replace, object links and resource
  cards.
- **Approvals and permissions:** review readable action requests, remember consent
  per connection and revoke it centrally. Mail sending can be approved from private
  Chat or the mail journal. Functional privileges allow more precise delegation
  without granting full administration.
- **Incoming communications:** unknown email senders require processing consent by
  default, separately from permission to send. External contacts require manager
  consent before agents reply. External messaging starts disabled on new installations;
  Telegram connections support a bot token without a preconfigured chat identifier.
- **Task supervision:** track milestones, guide recovery from silent model calls,
  and control conversation responses. Explicit stop and force-termination actions
  have stronger guarantees.
- **Upgrade:** document and memory text, revisions and attachment storage are
  migrated. Back up both the database and stored files before updating. Use the
  normal `make update` procedure and do not leave an older backend writing during
  migration; interrupted transfers can resume.
- **Browser authorization:** rebuild the browser executor as part of the update
  to activate its new authorization proxy.

### Removed

- The Source view in document editors.
- Agent YOLO mode; actions follow the configured authorization policies.

### Fixed

- Preserve Chat drafts and attachments after interrupted sends, and restore browser
  Back/Forward navigation in Chat, Documents, Datasets and Files.
- Improve recovery after backend interruptions, provider errors and authorization
  waits, preserving completed work and delegated results.
- Make voice interruptions and hangup more reliable, reduce false speech turns,
  stream transcriptions and restore Android system-volume control during calls.
- Repair media references and file delivery, strengthen Nextcloud file operations
  against data loss, and preserve read-only document interactions.

## [0.1.0] - 2026-10-25

### Added

- Initial tagged release of Galaris: self-hosted agents, text and voice conversations,
  durable Tasks and Goals, tools, memory, documents, external messaging and AI Lab.

[Unreleased]: https://github.com/lecluse-net/galaris/compare/0.3.1...HEAD
[0.3.1]: https://github.com/lecluse-net/galaris/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/lecluse-net/galaris/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/lecluse-net/galaris/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/lecluse-net/galaris/tree/0.1.0
