# Changelog

All notable changes to Galaris are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The historical tags `0.1` and `0.2` remain aliases of `0.1.0` and `0.2.0`.

## [Unreleased]

## [0.3.1] - 2026-11-01

### Changed

- Require successful Quality and Security checks for the exact release commit,
  followed by a fresh source security scan, before publishing a GitHub Release.
  Missing or unsuccessful evidence blocks publication with retained diagnostics.
  Immutable image bundle builds also check committed sources before building.

### Security

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
