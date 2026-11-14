<p align="right"><a href="../../fr/dev/document-formats.md">Français</a> · <strong>English</strong></p>

# Document formats and contributions

A **document format** defines how content is represented. Built-in formats are
**Text format** (`text`, editorial HTML) and **Data format** (`data`, JSON).
A structured format, such as a future mind map, owns its codec; storing JSON does
not make it a Data-format document.

## Facade and ownership

The public `app.document` package and facade export `DocumentFormatDefinition`,
`register_document_format`, `document_formats`, `document_format_definition`,
`document_format_catalogue`, `document_source`, `extract_document_content` and
`remap_document_references`. Native modules and future plugins use the same contract.
Registration rejects collisions, reserved historical codes and incompatible versions.
It happens during generation composition; no plugin installer or arbitrary hot code
loading is introduced.

Documents owns identity, owners, ACLs, classification, revisions, conflicts and content
publication. Process retains BPMN definitions and Memory retains private memories.
A format never introduces another library or permission system.

Descriptors declare a stable code, provider, format and contract versions, MIME, storage,
initial content, validation and extraction. Textual content uses `documents.content`;
binary content uses immutable `core.storage` files. File-backed formats require a binary
validator and initial bytes. Revisions retain historical files and format versions.
Explicit binary saves publish their checkpoint immediately; textual saves retain
quiet-period batching. Publication failures discard unpublished bytes without deleting
an already registered source.

Textual formats enumerate references through `references` and rewrite them through
`remap_references`. Copies use these operations to publish independently owned assets.
External references retain independent rights; extraction must not resolve or copy
the content of referenced resources.

## Catalogue and frontend

`GET /api/documents/formats` exposes the catalogue and declared capabilities: editing,
preview, embedding, thumbnail, PDF, native export and import. Each distinguishes
`native`, `fallback` and `unavailable`. `capability_complete` describes a declaration,
not certification. The library offers **Document formats**, showing composed backend
and frontend capabilities with retry after errors. `file_schemes` also exposes
`document_formats` for agents.
File tools also read and replace binary formats with revision checks. Each base64 page
can be decoded independently, and offsets count bytes.

The public frontend package `@/app/document` exports `registerDocumentFormat`,
`findDocumentFormat`, the catalogue and contribution contracts. Provider, code and version
must match the backend catalogue. Heavy components may load lazily. A format supplies
its editor, draft validator, static snapshot and optional inert historical viewer and
embedded component. Ordinary saving remains owned by the host.

Binary editors receive a `DocumentContentSource`: context key, revision, readonly state,
authorized loading and revision-checked saving. They retain drafts after denial, conflict
or interruption. Local metadata is saved before binary publication; late responses cannot
update another document. Historical readers never receive a working save capability.
The sixth `snapshot` argument also supplies an authorized read-only source pinned to
the requested revision, allowing PDF and thumbnail renderers to read binary formats.
Editors expose `DocumentFormatEditorHandle.flush` and `discardDraft` to participate
in closing checks; `flush` must refuse to lose an unsaved draft.

Every format can be referenced inside Text. Specialized rendering uses the same resource
block and open actions; fallback rendering is a card/thumbnail. Nested integrations detect
repeated visits and bound depth. Sharing a host document grants no access to embedded resources.
Process input constraints compare the actual format code even when formats share a MIME,
while retaining resource access checks.

## Attachments, conversion and export

File readers are independent of document formats. The public `registerResourceViewer`
contract in `@/core/util` accepts a code, provider, version, priority, MIME/name detector
and component. It applies to shared `ResourceAttachments`. Readers receive an authorized
source rather than a server path, and clean up requests and resources on context changes.

Server converters reuse `core.preview.PreviewConverter`: deterministic selection,
version, preserved source and temporary derivatives cleaned on context exit.
Attachment previews (`preview=true`) and thumbnail generation use this port.
Ordinary downloads preserve original bytes. Thumbnails are disposable derivatives
subject to their source ACLs.

Formats declare import extensions and MIME. Native textual content is validated by its
codec; binary formats preserve bytes. Existing Office/PDF conversions and media imports
reuse prepared publication, original-file retention and cleanup after failed publication.

PDF uses a static snapshot and the existing isolated Chromium renderer. Rendering never
replays scripts or replaces the original. Formats may provide specialized snapshots;
literal fallback does not promise visual fidelity. Authorized source downloads remain
available without the plugin through `GET /api/documents/{uuid}/source`, optionally for
a historical revision.

## Format qualification

`qualify_document_format` executes synthetic `FormatExample` cases with independently
specified expected results: validation, extraction, references, remapping and invalid
content. Binary examples are supported. Diagnostics exclude source content. This codec
TCK does not claim to test permissions or UI behavior.

`document_format_conformance` aggregates `FormatSuiteEvidence` for the exact code, provider,
version and implementation SHA-256. Required suites cover codec, lifecycle, permissions,
concurrency, assets, import, preview, embedding, thumbnail, PDF, native source, browser
and missing-plugin behavior. Missing, empty, failed, duplicated or stale evidence never
passes. Declared capabilities remain separate from qualification evidence; the current
catalogue does not automatically publish local reports as installed certification.

`make tests-document-formats` runs backend documentary suites with ephemeral PostgreSQL,
then selected browser workflows. Actual results remain authoritative: interrupted or
failed runs are not successful. Test contributions `example.outline`, `example.binary`
and `example.note` prove extensibility without adding product formats. Future plugins
must supply their own examples, rendering tests and other suite evidence; this repository
battery does not certify unknown third-party code.

## Migration and limits

`document_format` is the sole name in code, APIs and storage. Former fields, imports
and `/documents/types` are removed. DbAdmin copies the former `document_type` column
into `document_format`, verifies the transfer, then removes the source column.
Former `html` and `form` codes become `text`; content, versions, owners, permissions
and identities are preserved. A Process action migrates constraints inside BPMN,
its revisions and frozen run graphs without changing run states or user values.
Interrupted transfers preserve their sources and resume. `document://` and `data://` remain stable. Missing formats/versions
are never interpreted as HTML; source, metadata, rights and revisions remain recoverable.

This contract prepares plugin contributions. Installation, signatures, effective
generations, untrusted-code isolation and certification publication remain part of the
[plugin work](../../../project/plans/infrastructure-plugins-galaris.md). Format-version
migrations and coherent multi-file snapshots require their own policy; silent conversion
is never allowed.
