# 0203 — Tiptap editing with portable HTML and an isolated document runtime

Date: 2026-10-18

## Context

Galaris needs a self-hosted HTML editor without mandatory vendor branding. The editor
must preserve existing editorial HTML, attachments, resource cards and interactive
HTML with custom CSS and JavaScript. A restricted rich-text schema must not discard
an authored application, including a Three.js scene.

## Decision

Replace CKEditor with pinned MIT-licensed Tiptap packages and Quasar controls behind
the existing `RichTextEditor` public component. HTML remains the canonical persisted
format; Tiptap JSON is an internal editing tree, never a new storage format.

The previous CKEditor integration is replaced as follows:

| Existing capability | Replacement |
|---|---|
| Headings, inline marks, fonts, colors, alignment, quotes and separators | Open-source Tiptap extensions and Quasar controls |
| Lists, numbering, nesting and paragraph indentation | List commands, preserved HTML attributes and document shortcuts |
| Undo/redo, find/replace, select all, clear formatting and symbols | Local editor commands and dialogs |
| Source, fullscreen, page width and grouped/mobile toolbar | Galaris-owned Vue components and styles |
| Tables, headers, merge/split, captions, properties and column resize | TableKit, portable table serialization and local controls |
| Images, captions, alt text, links, styles, resize and drag | Attachment-aware image nodes and local controls |
| File upload, HTML/Office paste, Markdown paste and image import | Existing upload/import and sanitization services, transaction anchors |
| Galaris citations, link/card conversion, Process/Agent diagrams and media players | Existing domain contributions hosted in atomic resource nodes |
| Code languages, highlighting, line numbers, wrapping and copy | Literal code nodes and highlight.js decorations |
| Personal dictation and reading | Existing application-owned voice provider |
| Printing, PDF/ZIP, native sharing and attachment materialization | Existing snapshot/export services |
| Arbitrary HTML/CSS/JavaScript and Three.js | Opaque source nodes and the isolated document runtime |

No paid Tiptap extension, cloud account or license key is used. Existing content is
parsed on opening; no database rewrite is part of this change.

Keep `protectInteractiveHtml` / `restoreInteractiveHtml`: related custom HTML, CSS and
scripts travel together as opaque nodes. Their editing DOM hosts the existing isolated
application runtime. Source is limited to non-document `rich-text` fields; documents expose
no source-code view. This does not change stored HTML or isolated rendering. No additional application
manifest, start button or read/edit mode is introduced. Other readers stay inert.

Split independent static objects at editorial prose boundaries. Keep the first-to-last opaque
region together when scripts, global styles, event handlers or SVG references may connect its
objects. Prefer preserving these dependencies over speculative code analysis. Safe inherited
colors remain native editorial styles instead of forcing ordinary tables into opaque objects.

Use the same licensed GNOME artwork for main and contextual commands where a suitable icon
exists, with Material fallbacks. Table command availability follows Tiptap's current selection;
disabled commands must never mutate the document.

Resource cards and attachment images also have distinct serialized and editing views.
Temporary players, diagrams, Blob URLs, syntax decorations and selection markers must
never enter saved HTML. Track asynchronous insertions through editor transactions and
invalidate them on content replacement, Source, read-only transitions and destruction.

Reader, print and snapshot styling belongs to Galaris and supports the existing portable
figures, table captions, image styles, callouts and highlighting without CKEditor CSS.

Bundle the project's pinned Three.js, OrbitControls and GLTFLoader locally at build time
and expose them as `THREE` in the opaque document runtime. Preserve the existing CSP,
network restrictions, Dataset ACLs and personal consent. CDN imports and worker-based
loaders remain outside the offline runtime contract. Native passive media materialization
continues to use the existing authorized attachment resolver. Preserve WebGL drawing
buffers for static snapshots rather than re-executing authored code on export.

## Acceptance and rollback

Qualify opening without writes, surrounding edits, Source and reopen against a synthetic
HTML corpus; exercise custom CSS and a real Three.js/WebGL scene, controls and a nonempty
static capture. Reuse existing editing, upload, card, voice, application and Chat scenarios,
adapting controls rather than retiring their behavioral guarantees.

No schema migration or batch rewrite of documents is needed. Existing HTML revisions and
resource URIs remain the interchange and rollback contract. Do not claim complete browser
or workflow qualification from static checks or a small targeted suite; execution evidence
belongs under `artifacts/`.
