# 0288 — Document format contributions and qualification

Status: accepted. Date: 2026-11-14.

The product and public contract call authored representations **document formats**.
Text and Data remain the built-in formats. `document_format` is the sole spelling in
code, APIs and SQL. Former fields, routes and imports are removed. DbAdmin transfers
the original column before contraction, together with persisted Process format constraints;
no runtime naming adapters remain. Source identity, contents, history, permissions and
existing URIs are preserved, including interrupted-upgrade recovery.

Documents owns the shared envelope: policy, classification, revisions, optimistic
concurrency and content publication. Native modules and future plugins register format
definitions through the same public facade. Definitions own codecs, initial content,
extraction, resource references and remapping. Text lives in PostgreSQL; binary content
uses immutable managed files retained by revisions. Unknown codes load through the
generic envelope and never select the HTML editor implicitly. Native source recovery
remains authorized and independent of the plugin.
Explicit binary saves publish an immediate content checkpoint; textual autosaves retain
quiet-period history batching. Failed publication discards only unregistered bytes.

Frontend contributions match the backend provider, code and format version. They supply
editing, draft validation and static snapshots, with optional inert previews and embeds.
Binary editors use a host-owned source/save capability with revision and context guards.
Every format remains referenceable in Text, with bounded nested embedding and generic
fallbacks. File-reader contributions are separate from Document ownership. Attachment
previews and thumbnail generation reuse the existing server preview conversion port.

The catalogue distinguishes native capabilities, host fallbacks and unavailable surfaces.
Declarations are never certification. A reusable codec TCK executes independent synthetic
examples. Conformance aggregates required workflow, ACL, concurrency, asset, import,
rendering, export, browser and missing-plugin evidence for an exact implementation digest.
Missing, duplicated, failed or stale evidence cannot qualify a release.

This prepares extension contracts, not a dynamic plugin installer. The existing plugin
plan still owns packaging, signatures, effective generations and trust/isolation policy.
Format-version transformations and coherent multi-file project snapshots remain explicit
future policies. Process definitions and private Memory retain their existing domains.

Qualification: `make tests-document-formats`, plus static and documentation checks.
The third-format fixtures are entirely synthetic and are never installed product formats.
