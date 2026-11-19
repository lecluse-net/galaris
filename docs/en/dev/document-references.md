<p align="right"><a href="../../fr/dev/document-references.md">Français</a> · <strong>English</strong></p>

# Document references and display modes

A reference stores its URI and display mode in the host content. Two occurrences of the same URI can use different modes and appearance settings. Text documents store editorial HTML. Mind maps use the same HTML in the node's `body_html` field. Data documents keep their free-form JSON and can be cited from either editor.

## Available modes

| Type | Modes | Insertion default |
|---|---|---|
| Web page | Link, Card when the host offers the preview service | Link |
| Recognized YouTube video | Link, Card when a preview is available, Embed | Link |
| Supported image | Link, Card, Embed | Embed |
| Supported audio, video or PDF attachment | Link, Card, Embed | Embed |
| Other attachment | Link, Card | Card when inserted from the resource picker or the attachment list |
| Native process or run | Link, Card, Embed | Link in Text, Card in a mind map |
| Text and Mind map documents | Link, Card, Embed | Link in Text, Card in a mind map |
| Data document, folder or contact | Link, Card | Card in the resource picker |
| Agent, task, goal, topic, discussion, text exchange, call, voice turn, calendar | Link, Card | Link in Text, Card in a mind map |
| Private memory or a resource with navigation support only | Link | Link |
| Other document format | Link, Card, Embed if it declares a compatible reader | Link in Text, Card in a mind map |

The default applies to the object picker. Pasting a URL in a sentence, inserting an explicit link and reading older occurrences keep their established rules. Authorized document reads supply the actual format and version for document URIs. The file MIME type determines the attachment reader. Provider images use the File Sharing APIs with the selected context and check the MIME type and size before loading the original.

## Components and commands

`DocumentLink`, `DocumentCard` and `DocumentEmbed` compose the same contextual toolbar with `DocumentReferenceToolbar`. Each base sets its active mode. The editor supplies the available modes and applies changes as content mutations with Tiptap history, revision checks and focus restoration. In a mind map, the same mutation updates `body_html` for the selected node. Legacy anchors and blocks use the reader and Tiptap render adapters to preserve portable serialization.

Selecting a reference in a mind map keeps its reader mounted. Tiptap handles selection and contextual commands while the reader displays the preview and, for an image, the resize handle. Typing or changing the content activates the editor’s rendering.

The mind map reads the portable URIs and titles carried by library drops. It applies each resource type’s insertion mode and uses the host document’s attachment upload for local files and its existing import service for supported web images. Moving branches is internal to the map and preserves identifiers and descendants. Outside editing, system clipboard text becomes one child per line and a standalone URL becomes a link. The branch clipboard preserves subtrees for operations in the same map. The rich content editor handles paste while active.

A specialized view contributes buttons through `RegisterDocumentReferenceActions`. It supplies `DocumentReferenceAction` entries with an `id`, a translated `label`, an `icon` and a `run` callback. It republishes actions when availability changes and clears them on unmount. For example, `ProcessPreview` offers fitting the BPMN diagram to the viewport and returning to the parent diagram. Commands belong to the mounted occurrence. The editor receives the commands for the selected block. [Action contract](../../../front/core/util/documentReference.ts) · [Process example](../../../front/app/process/components/ProcessPreview.vue).

Appearance belongs to the host and occurrence. An explicit Card uses the yellow Solaire accent in Text. In a mind map, the node uses its branch accent and supplies a single border for a standalone card, embedded document or embedded process. This border appears in read mode, when selected and in graphic exports. Mind map images appear without a border, including in Card mode. An explicit Embed is transparent by default. The **Appearance** command offers a border color where the host supports one and an independent shadow control. Readers keep their own controls.

In Text documents and mind maps, `ProcessThumbnail` sizes process cards to the proportions of the preview. `ProcessPreview`, used in Embed mode and older cards, follows the height of the zoomed diagram. In Embed mode, the `BpmnCanvas` scroll area receives focus and scrolling gestures inside its host. Scrollbars appear where the zoomed diagram exceeds the available space. Full screen uses the available viewport height.

The Text format provides the `DocumentTextEmbed` reader. It renders content through `EditorialContent` in a rounded page with internal scrolling. `DocumentEmbed` supplies the shared resizable frame for document and process readers. In an editable host, releasing the handle or pressing an arrow key saves the dimensions on the reference. Read-only views apply the saved dimensions. A size change updates the frame of the mounted reader. A static Text capture includes reader content beyond the visible area and omits the handle.

## Persistent HTML and compatibility

```html
<p><a href="galaris://processes/review" data-resource-mode="link">Review</a></p>
<blockquote class="galaris-link-card" data-resource-mode="card">
  <p><a href="galaris://processes/review">Review</a></p>
</blockquote>
<blockquote class="galaris-link-card" data-resource-mode="embed" data-resource-border="#854CF0" data-resource-shadow="true">
  <p><a href="galaris://processes/review">Review</a></p>
</blockquote>
```

`data-resource-size="640x360"` stores width and height as integer CSS pixels, from 1 to 4096 per axis. It follows the occurrence across anchors, cards and embeds. The Embed frame applies the dimensions within the available width and height. An occurrence with no saved size uses the reader's defaults.

`data-resource-mode` accepts `link` on an anchor, `card` or `embed` on `blockquote.galaris-link-card`, and `embed` on a document image, its figure or its inline wrapper. `data-resource-border` holds a six-digit hex color. `data-resource-shadow` is `true` when enabled. An occurrence can retain an inert editorial fragment in `data-resource-image` or `data-resource-card` to restore its caption, size, click destination or authored metadata after reopening. The frontend sanitizer and backend codec validate placement and values. Fragments are limited to 32,768 characters. Image URIs in these fragments participate in attachment checks and copy remapping. Rendering and snapshots keep these fragments inert.

Existing links, figures and `galaris-link-card` blocks remain compatible. Older process, media and YouTube cards retain their readers. Explicit Card uses a compact preview and Embed mounts the reader. Reading, printing or editing another part of the document leaves an old occurrence in its original form. The display mode, appearance and authored fragment belong to the host revision. The current content belongs to its owner, including BPMN definitions and frozen run graphs. [Editorial HTML codec](editorial-html.md).

## Add a resource type or format

1. Declare URI resolution and navigation in the domain's `richContent.ts` contribution. Provide `card` and use `canCard` to filter when a contribution covers multiple types. `defaultMode` overrides the host default when the domain calls for a different choice.
2. Declare `embed` for a type that supplies a complete reader. Connect the reader to `resourceEmbeds.vue` through the app's composition point. Use the domain's authorized source and existing reader components. Provide an authorized static capture when supported and contribute view-specific commands through the action port above.
3. For a Document format, declare `embed` in the format contribution and server capabilities. A native archive reader receives the authorized read-only source for the loaded revision through `DocumentContentSource`. `createFormat(host)` can use `host.DocumentLink`, `host.DocumentCard` and `host.DocumentEmbed` to compose references in its own editor. Formats with an HTML composition surface can use the shared reference contract. [Format facade](document-formats.md).
4. Verify the offered modes in both hosts, save and reopen an occurrence, exercise access denials and static output. Add a scenario for any distinct durable behavior the new type can affect.

## Access, nesting and export

A single click in a document's editorial surface selects a document reference.
A Ctrl or Cmd click uses the document navigation port. The workspace owns both
navigation history and fullscreen mode. `DocumentEditor` moves its content into a
fullscreen container shared by all formats and exposes history controls there.
The Text and Mind map toolbars control that shared state.

A reference uses the reader's current permissions on the target. The host and the embedded document retain independent access rules. A document reader loads its target in the reader's context through the preview queue and cancels superseded requests. It reloads on document invalidation. Each branch keeps a path of documents used for embedding. A repeated document or excessive depth leaves a link fallback. Embedded document readers use an inert view of interactive HTML blocks.

Print, PDF and HTML ZIP use static snapshots. Mounted previews and readers can contribute authorized captures within the capture budget. An unavailable capture for an explicit occurrence leaves its editorial fallback. Structural mind map exports retain portable references. A published host thumbnail uses its static snapshot, with linked documents kept as references to respect their own audience.
