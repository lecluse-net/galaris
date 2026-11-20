<p align="right"><a href="../../fr/dev/document-formats.md">Français</a> · <strong>English</strong></p>

# Document formats and contributions

A **document format** defines how content is represented. Built-in formats are
**Text format** (`text`, editorial HTML), **Data format** (`data`, JSON)
and **Mind map** (`mindmap`, structured JSON). Mind maps have their own codec,
interchange conversions and branch commands. [Decision 0301](../../../project/decisions/0301-native-mind-map-documents.md)
describes the contract.

In the native source, a node's optional `checked` field is `true` for a checked box
or `false` for an empty box. An absent or `null` value means the node has no checkbox.
Revisions and the `.mindmap` source retain this value. The PDF rendering shows the state.
When the editor creates a sibling from a node with a checkbox, it initializes the new box
to `false`. In an `edit` command, omitting `checked` keeps the state and `checked: null`
removes the checkbox.

The optional `theme` field contains a stable `id` and a positive `version`. The editor
uses the Solaire palette when this reference is absent or unknown. The codec preserves
unknown references during branch edits. **Apply** saves the theme in the document revision.
Solaire tokens supply the light and dark variants for the map editor and reader.

The optional `background_color` field stores the canvas RGB color as `#rrggbb`.
The editor and reader display this value in light and dark mode. Solaire keys from
older maps follow the application mode. An absent or unknown key uses the host background.
The codec preserves the setting during branch edits. Fullscreen uses the Text reader's
layout and remains view state.

The [document reference contract](document-references.md) describes available modes by resource type, per-mode commands and composition across formats. Formats with a full reader declare `embed` in their contribution.

## Mind maps and agents

The **Document** Service declares the following MCP tools. They can be mounted in Chat and in
a Task according to the allowed functions, the map's permissions and the runtime rules.
Read is enabled by default. Creation and editing default to **On request**, subject to
the effective connection policy.

| Tool | Contract |
|---|---|
| `mindmap_create` | Creates a private document for the agent and returns its `document://` URI, revision and `root` ID. Accepts up to 100 initial branches in parent-first order. |
| `mindmap_read` | Reads the current saved revision. The list returns stable node IDs, parents and summaries. Follow `next_offset` to read more. With `node_id`, the tool returns the node's HTML body in chunks. Follow `next_body_offset` until the end. |
| `mindmap_add` | Adds 1 to 50 branches in one revision. Supply `expected_revision` and the `branches` list. |
| `mindmap_edit` | Applies 1 to 50 `add`, `edit`, `move` or `remove` commands in one revision. Supply `expected_revision` and the `operations` list. |

Supply a new ID, the parent ID and a title for each addition. Put parents before their
children in the batch. An `edit` command targets an existing node and supplies at least
one field to change. Removing a branch removes its descendants. If a command is rejected
before saving, the whole batch is rejected. On a revision conflict, reread the map and
reconcile the changes.

An agent can choose a mind map when a durable result naturally fits into branches, such
as a decision tree, an investigation or a plan grouped by workstream. It respects the
requested format and reuses a suitable accessible map. Choosing a format and authorizing
the write are separate decisions. A new map stays private until it is explicitly shared
with the intended recipients.

When a message is sent in internal Chat, its context can carry the open map's URI and
the displayed revision. The attention contract carries neither the active node ID nor
the multi-selection. For a request such as “add a child to this branch,” the agent resolves
the target from the message and `mindmap_read`. If the target remains ambiguous, it asks
for the branch title or path before writing. Display context grants no access, and tools
check both revision and permissions.

## Facade and ownership

The public `app.document` package and facade export `DocumentFormatDefinition`,
`register_document_format`, `document_formats`, `document_format_definition`,
`document_format_catalogue`, `document_source`, `extract_document_content` and
`remap_document_references`. Native modules and signed plugins use the same contract.
Registration rejects collisions, reserved historical codes and incompatible versions.
Archive-loaded formats require signatures from publishers authorized by the
[bundle contract](plugin-bundles.md).

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
not certification. The catalogue remains available through the API; the library no longer
has a **Document formats** button. Creation and format filtering remain available through
the ordinary Documents controls. `file_schemes` also exposes
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

## Chat context and revisions

An editor can expose `DocumentFormatEditorHandle.captureFocus()`. It returns a
`DocumentFocusAnchor` (`point` or `rectangle`) or `null`. Coordinates are zero-based
integers in the document's coordinate space. Drawing reports pixels of the saved image.
The host binds the anchor to the current revision after `flush` or reports the revision
loaded in history. The anchor grants no access rights.

A codec can provide `compare_revisions(before, after, region)`. Galaris checks current
permissions and passes the bytes of two saved revisions compatible with the codec version.
Return a JSON object of at most 12,000 serialized characters. Drawing reports the changed
pixel count and its bounding rectangle. Without a compatible codec, the result tells whether
the content hashes differ. Agents use `document_revision_list`, `file_read(revision=…)`, and
`document_revision_compare`. An analysis task with a vision model can use
`document_analyze(revision=…)` on a historical image revision.

## Document toolbar

Use `DocumentToolbar` for the format's main toolbar. The component follows the visual
reference and provides groups, tooltips and keyboard navigation. The declarative
toolbar stays at the top of the editing area while scrolling. A native editor imports
it from `@/app/document`. A browser module compiled for a ZIP uses the same component
from `host.DocumentToolbar` in `createFormat(host)`.

The format supplies reactive `DocumentToolbarGroup[]` groups with an `id` and a
`label`. Each command has an `id` unique within the toolbar and a translated
`label`. The component emits `command(id, value?)`. The format runs the action and
publishes the updated state through its groups.

| Command kind | Properties |
|---|---|
| `button` | `icon` from the visual reference catalogue and optional `showLabel`, `primary` or `busy` |
| `toggle` | Button properties and the controlled `pressed` state |
| `color` | `value`, a CSS hex color supported by a native color input |
| `range` | `value`, `min`, `max` and optional `step` |

A button or toggle marked `secondary` moves into **More tools** below 1024 px.
Secondary commands also have an icon and a label. Color and range inputs remain
in their groups. Use `disabled` when an action is currently unavailable. Pass
`readonly` for read-only content. A command that still applies, such as Copy,
declares `readOnly: true`. The historical reader renders its own read-only view.

```vue
<DocumentToolbar
  :label="t('editor.tools')"
  :groups="toolbarGroups"
  :readonly="source.readonly"
  @command="runCommand"
/>
```

Drawing uses this contract for canvas commands and tool state. Revision control and
saving continue through `DocumentContentSource`. Text and Mind Map use the same
toolbar container for their specialized tools. Data uses the declarative toolbar
for copying JSON.
[TypeScript contracts](../../../front/core/util/documentToolbar.ts)
· Example in `plugins/sample/drawing/DrawingEditor.vue`

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
a historical revision. Frontend contributions may declare `nativeExtension` for
the editor's download filename.

Mind map graphics start from the complete in-memory tree. `prepareMindMapGraphic`
uses the portable editorial snapshot to sanitize node contents and resolve images in
the current reading context. The diagram shares the editor's connector
styles and uses its theme and background. Raster export bounds the PNG resolution.
Printing fits the diagram on one A4 landscape page and uses the same script-free
print frame as Text documents. Interactive objects use the title and text of their
references. The existing PDF export preserves the textual projection of the tree.

The ZIP archive reuses the graphic diagram and the attachment inventory. The shared
export API retains its access checks and rewrites links to files included in the archive.
Mobile PDF sharing uses the same dialog as Text, with the map outline as its PDF source.

The editor keeps a bounded in-memory history. Every map operation publishes its source
through the existing autosave channel. Undo and redo publish valid source through that
same channel. Each rich-text editing session forms one group in map history and retains
the editor's local history. Global replace validates every changed node before publishing
and works on text ranges that preserve HTML structure and attributes.

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

Untrusted-code isolation and certification publication remain part of the
[plugin work](../../../project/plans/infrastructure-plugins-galaris.md). Format-version
migrations and coherent multi-file snapshots require their own policy; silent conversion
is never allowed.
