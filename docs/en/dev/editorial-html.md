<p align="right"><a href="../../fr/dev/editorial-html.md">Français</a> · <strong>English</strong></p>

# Editorial HTML contract

[Decision 0080](../../../project/decisions/0080-editorial-html.md) defines the scope.
For editorial fields and `html` documents, the authoritative body is a UTF-8 `text/html` fragment with `content_profile_version: 1`.
The `rich-text` profile covers all six Memory categories, Goal descriptions/tracking,
Task objectives and Agent job descriptions/personalities. The `document` profile adds
attachment images, forms, CSS and JavaScript to ordinary working documents. Goal documents always use `rich-text`,
including through the library or Chat. Native binary/JSON/code resources and all skills
retain their formats.

## Documents as the information hub

Agent profiles are virtual `galaris://agent/<id>` resources, without documents or folders
in the library. `agent_list`, `agent_get` and the Agent API's `resource_uri` field return
this URI. `file_read` reads the current personality and job description directly, preserving
their `rich-text` HTML inside the JSON snapshot and applying existing access rights.

Documents have an immutable type: `html` (the default, including existing documents) or
`dataset`. A Dataset is a JSON document in the same library, with the same title, icon,
classification, sharing and history. The library filters and sorts by type. CodeEditor in
JSON mode replaces CKEditor. UTF-8 JSON is validated before saving without rewriting its
formatting; invalid input remains a recoverable draft and is never converted to HTML.
Any JSON root value is supported; NaN and Infinity are rejected. The limit is 2,000,000 bytes,
subject to the storage quota. See [decision 0124](../../../project/decisions/0124-document-types-and-datasets.md).

Creation APIs and `file_create` accept `document_type="dataset"`; updates reject this field
and incompatible MIME changes. Example:
`file_create(path="document://", name="Scenarios", document_type="dataset", content='{"scenarios": []}')`.
Dataset `file_read` offsets count characters; `file_edit` ranges count lines. The complete
result must remain valid JSON. `file_write`, `file_edit` and `file_append` require the observed
revision. Prefer replacement or line editing to JSON concatenation. Copying an
`application/json` source to `document://` creates a new private Dataset.
PDF/HTML exports remain specific to HTML documents. Other document types remain out of scope.
[Interactive HTML](document-apps.md) now allows forms and declared Dataset access inside
an isolated document runtime; history and exports remain inert.

Create or enrich a document when the requested outcome calls for durable authored content to
retain, revise or share. A Task does not in itself require a document: self-contained answers and
completion confirmations stay in the conversation, operational state in the relevant business
record. Do not add a document solely to record an action or demonstrate completion. Preserve the
requested resource type; explain an unavailable operation instead of substituting a document.

Galaris documents are the canonical home for this durable content. Memory and File Sharing are
mandatory system services, alongside Galaris and Conversation. Their connections and functions stay enabled and read-only.
The effective catalog still applies context restrictions and resource ACLs; optional bridges
can still be disabled.

With the required functions available, search for and enrich the relevant document.
Create a new document only when the content needs a separate home, using
`file_create(path="document://", name="Title", content="<p>HTML content.</p>")`.
Its URI remains the reference across research, drafting, review, Tasks
and conversations. Keep sources and links to related documents in it; media remain canonical
resources or attachments. Conversations carry discussion and concise handoffs without maintaining
a competing copy of the document body.

A new document is private. `memory_sharing` resolves the human, agent or team recipient and
the sharing version; `document_share` grants `read` or `edit` before handoff. A link or
`document_show` grants no rights. External delivery is a separate operation whose success
must be confirmed by the transport.

Standalone Markdown/HTML files remain appropriate for an explicitly requested format, source
code or an interactive page. Short conversational answers stay in chat; concise durable facts
belong in `memory_remember`. Tool-produced technical artifacts, including transcripts and
`.summary.md` files, keep their contracts; authored synthesis from those sources prefers a
document. A temporary failure is not deactivation and does not justify silently replacing
the document with a file.

This policy guides agents; it neither converts existing files nor changes existing resource
ACLs. `document_show` remains independent of the Memory connection. See
[decision 0104](../../../project/decisions/0104-documents-information-hub.md).

## Inputs and normalization

Editorial HTTP writes require `X-Editorial-Profile-Version: 1`. Cached clients receive 409
and must preserve their draft before loading the new application. Internal services/tools
use explicit HTML contracts. Memory rejects downgrades from HTML to Markdown and format
changes without a replacement body. Imports call `convert_to_html` with the declared source MIME.

`core.util.rich_text` validates structures before nh3 and serializes deterministically.
Limits are 2,000,000 serialized bytes, 500,000 visible characters, 50,000 elements and depth 64.
Agentic Goal tracking allows 120,000 serialized and 30,000 visible characters. Colors accept
hexadecimal, RGB/HSL and an explicit set of CSS names; alignment is left/center/right/justify.
Styles are restricted to typography, colors, dimensions and table properties. CSS dimensions
are bounded to 1,600 units or 100%; natural image dimensions to 16,000 pixels.
Links support HTTP(S), mailto and implemented
internal references. The `rich-text` profile rejects scripts, event handlers, SVG and arbitrary
styles. Ordinary documents accept these and forms through an isolated runtime; see
[interactive HTML](document-apps.md). Iframes and remote images remain forbidden. API writes
are validated before a revision is created.

CKEditor 5 holds the temporary editing tree. Its HTML passes through the frontend sanitizer before
emission; backend validation remains authoritative. There is no HTML/Markdown round trip.
Historical readers use each revision's MIME. Active HTML artifacts remain separate from the
editorial reader. Existing Markdown readers and files remain available for skills.

`RichTextEditor` exposes two modes through `profile`: `rich-text`, the default simple mode
for enriched multiline fields, and `document`, the full mode with page layout, images,
attachments and exports. Non-document fields keep the simple mode. Both modes include the
Reading group with Source and Fullscreen; Full width is available only in document mode,
which has a page layout. The active `app.llm` module's `editorVoice.ts` contribution supplies
dictation and speech playback to both modes through the `core.util` `EditorVoiceProvider`
contract. Screens need no additional wiring. Changing the presentation does not emit content
changes. Replacing the external value, recreating or closing the editor cancels requests and
releases audio resources.

## Source code view

CKEditor's Source view uses a 12 px monospace font. `GalarisSourceEditing` highlights HTML and
embedded JavaScript/CSS with highlight.js, using the Solaire palette in both themes. Highlighting
is a separate visual layer over the native input: it changes neither the selection, typing
history nor saved HTML. The highlighting engine escapes source text, which is never executed
in this view.

## Code blocks inside documents

Code blocks and inline code use a 12 px monospace font. Blocks use Solaire syntax colors
while editing, reading and printing. The block language guides highlight.js; unlabelled
and plain-text blocks use automatic detection limited to common languages. Unknown languages
and blocks exceeding 50,000 characters remain readable without highlighting.

`GalarisCodeHighlight` uses temporary CKEditor markers converted only to the editing view,
without affecting data or undo history. Only changed blocks are highlighted again. Reading
and printing highlight a copy of sanitized HTML; syntax classes are never saved in documents.

Clicking inside a block shows a floating toolbar: language, line numbers, line wrapping and
copy. Changing the language explicitly targets that block without inserting or merging other
blocks. `Alt+F10` focuses the toolbar and `Escape` dismisses it. In read-only mode, copying
remains available while document options are disabled.

Options persist on `<code>` as `data-code-lines="true"` and `data-code-nowrap="true"`,
validated by both HTML filters. Line numbers are temporary display elements, excluded from
copied text, saved content and the semantic index. They follow logical lines even when a long
line wraps on screen.

## Revisions and agentic reads

MCP sharing uses `memory_sharing` to discover recipients and the current `lock_version`,
then `document_share` or `memory_share` with exactly one `agent_id`, `user_id` or `team_id`.
Access is `read`, `edit`, or `none` to remove that specific grant. Teams include their current
human and AI members. Sharing changes neither the HTML nor its content revision:
`expected_lock_version` protects ACL changes, while `expected_revision` protects content
writes. The Galaris system skill provides complete examples.

`file_read` returns HTML, profile, revision, `offset_unit: block`, numbered blocks and
`next_offset`. Offsets count blocks; block numbers start at 1 and belong to the observed
revision. The default budget remains 20,000 characters. An indivisible oversized block reports
its required size; an explicit read can request up to 2,000,000 characters. A cut tag is never
returned as an HTML fragment.

For document:// only, `file_edit` interprets `start_line`/`end_line` as block numbers.
`expected_revision` is mandatory for edits, replacements and appends. Text replacement matches
one unique occurrence in a text node, never an attribute. Immediate repeated appends by the
same author/task are idempotent. Canonically unchanged saves do not create another revision.

Each revision retains its MIME and `content_images` manifest. Removing an image from the body
does not remove its attachment. Explicit attachment deletion hides it from the current list,
but retains bytes until the document is forgotten. Restoration creates a compatible new
revision without restoring historical ACLs. Downloads apply current rights and use
`private, no-store`; temporary blob URLs exist only in memory and are revoked on unmount.

Uploads decode PNG/JPEG/WebP/GIF with Pillow and enforce existing attachment quotas, at most
40 million pixels and 16,000 pixels per dimension. Cancellation before publication cleans up
the unpublished resource. A published attachment whose body save failed remains available for
retry. Never purge a file merely because the current body no longer references it.

## PDF export

`POST /memory/documents/{document_id}/export-pdf` checks read access and the `document`
profile, then passes a static copy of the current content to `core.preview.render_html_pdf`.
The frontend shares print styles and embeds authorized images as data URIs; exporting does
not save the document. Chromium in `browser-executor` prints a temporary page with JavaScript
and network access disabled, then closes its context. Limits are 12 MiB of HTML including
images, 16 MiB of PDF, 30 seconds of rendering and two concurrent exports. Rebuild the
rendering service when its code changes.

## Attachments, link cards and portable export

Documents support forms and scripts in isolation, retaining the usual toolbar and editable
prose. Source is the only code view; history and exports stay inert. Restoration preserves source.
Source mode still accepts explicitly authored interactive HTML.

Pasting HTML source or content copied from a page into the body directly imports editable
blocks, without a dialog or isolated page block. Headings, paragraphs, lists, links and tables
are preserved; styles included in the clipboard become supported editorial formatting.
Scripts, interactive controls and external stylesheets are not imported. Pasting into a code
block remains literal. Pasted Markdown also becomes editable HTML: headings, lists,
quotations, tables, emphasis, links and code blocks. Already formatted HTML takes precedence;
plain source wrappers copied from a source editor do not prevent Markdown conversion.
Ordinary prose, inline code, code blocks and input in Source mode retain their literal
behavior. Markdown images follow the same attachment import path.
Embedded base64 raster images use attachment uploads. Public HTTPS
images use `POST /memory/documents/{document_id}/import-image`: user scope and write access
are checked before downloading through `core.preview.read_web_image` and File Share's
transport, which rejects private addresses and internal redirects. Downloads are bounded to
10 MB and 15 seconds, then validated and stored as attachments. Each source is imported once
per paste (at most 50 sources), and the body only retains its canonical
`document://…/attachments/…` URI. Unavailable images retain their descriptions and trigger a
warning without losing text. Cancellation or a document change prevents late responses from
changing the body; attachments already created remain available.

HTML files are accepted as attachments and opened by the existing isolated resource viewer.
Canonical attachment links are supported in `<a href>`. The attachment `/info` endpoint also
resolves retained files under current document permissions.

`POST /memory/documents/{document_id}/link-card` checks managed-agent scope and write access
before fetching. `app.file_share.web_metadata` shares Open Graph and YouTube oEmbed extraction
with Messenger through the public HTTPS transport, including its private-address and redirect
checks. Memory uses the `core.preview.preview_web_link` port registered by File Share at
bootstrap, avoiding a circular domain dependency. Pages are bounded to 1 MiB and 15 seconds;
thumbnails to 5 MiB and 40 million pixels,
then resized to at most 640 × 360 and converted to JPEG attachments. The returned
`blockquote.galaris-link-card` contains static text, links and a canonical image. Only inserting
the card into the body creates a content revision. Published thumbnails survive cancelled insertion.

Print and PDF exports contain only the document body. The `/export-bundle` POST endpoint
requires document read access and returns `document.html` plus attachments in a ZIP, without
creating a revision. Input is bounded to 64 MiB, including up to 12 MiB for the snapshot.
UUID-prefixed filenames avoid collisions; links become encoded relative paths. Removed files
still referenced by the text are included. External dependencies are not automatically embedded.

## Migration and operations

```bash
# Read-only format inventory and sampled conversion diagnostics.
docker compose exec backend python -m app.memory.html_migration
# Development: DbAdmin actions and reconciliation without restart.
make sync-db
# Production: new application and convergence before availability.
make update
```

The actions are `app.memory.editorial_html`, `app.agent.editorial_html` and
`app.task.editorial_html`. They are triggered by their owned column deltas, process at most
500 objects per batch and remain deferred until their postconditions hold. Repeat synchronization
for larger inventories. Memory preserves immutable source revisions; `profile_legacy_source`
and `objective_legacy_source` retain previous Agent/Task fields. Invalid legacy links become
non-clickable with a warning and their original destination preserved in the source revision.
Unmigratable images remain explicit exceptions and prevent convergence of the affected action.

Agent/Goal projections have their own rebuild version. Embeddings remain asynchronous and their
fingerprint depends on visible text instead of HTML styles. Monitor `scanned`, `queued`, `current`;
conversion does not invoke an LLM. Stop old workers during this transition's production deployment.
A rollback must preserve the HTML reader, new writes and images. Use preserved sources for
targeted restoration, never to overwrite the entire store with an earlier snapshot.

## Verification

```bash
make tests ARGS='core/util/tests/test_rich_text.py app/memory/tests/test_editorial_html.py app/memory/tests/test_html_migration.py app/agent/tests/test_prompt_tree.py'
make tests-front-components ARGS='rich-text.spec.mjs galaris-links.spec.mjs memory.spec.mjs skills.spec.mjs'
make typecheck
make architecture-check
make project-context-check
```

Browser tests run real CKEditor/Quasar components with explicit mocked APIs. They complement
DB persistence, authorization, restoration and concurrency tests; they do not qualify an
external provider. Check small viewports, both themes, keyboard use and the reference corpus
before changing the content schema.

The end-to-end recipe is `make tests-e2e ARGS='editorial-html.spec.mjs'`: ephemeral PostgreSQL,
the real API and a compiled frontend. It checks all six categories, rejects an outdated client,
and verifies document persistence after table editing and reloading. Prompt unit tests exercise
simulated transports and Hermes; they do not claim to run a real external provider.

CKEditor qualification on 9 September 2026: 44 HTML contract/document backend tests,
27 Chromium editor/Galaris links/Memory tests and the full API workflow in Chromium, Firefox and WebKit
passed; types, lint and translations checked. The development migration converged with
523 HTML Memory bodies, no remaining editorial conversion and no exceptions.
Vector reconstruction follows its usual asynchronous queue.
