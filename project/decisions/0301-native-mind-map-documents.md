# 0301 — Native mind map documents

Status: accepted for structural editing and interchange.

A mind map is a versioned Document format named `mindmap`. The canonical
`application/vnd.galaris.mindmap+json` source keeps a root and an ordered list of
branches with stable local IDs. Each branch has a title and can have a plain-text note,
a link, an icon from the library and a Document-profile HTML fragment. Inline images
use the map's own attachments. Canonical links to other resources use their live ACL.
An optional `checked` boolean distinguishes checked and empty boxes. An omitted or
null value represents a node without a checkbox.
Document identity, sharing, indexing, autosave and immutable revisions
use the normal library and persistence. The layout is derived from the tree.

The optional `theme` reference stores a palette ID and version with the revision.
Version 1 offers Solaire, Ocean, Forest and Monochrome. The view resolves the light
or dark variant from Solaire tokens. Missing and unknown references render with
Solaire. Branch commands retain the original reference.
The independent `background_color` field stores an optional RGB hex color for the
canvas. Legacy Solaire keys follow the application mode. Missing and unknown keys
render with the host background. Branch commands retain the stored value. A fullscreen
map uses the Text editor's viewport layout and keeps its mode out of persistent content.

Freeplane and FreeMind XML, OPML and modern XMind ZIP with `content.json` are
interchange formats. The isolated codec projects their branch trees to the native
format. It ignores source scripts, presentation, diagrams and embedded resources.
Exports retain portable links, and the native source remains available for full
fidelity of Galaris content. A workbook with several XMind sheets is imported
as one map with the sheet roots below an enclosing branch.

The Documents Service exposes `mindmap_create`, branch reads, and atomic editing
batches. Every batch needs the previously read revision and the same write access
as the editor. Zoom and pan are view state. Executable application blocks in nodes
use an inert reader. Additional integration with Text documents and theme authoring
are tracked in the [mind map plan](../plans/cartes-mentales-documentaires.md).

Rich node editing uses the same full editorial toolbar and command handlers as
Text. The embedded editor surface owns the body of the active branch. The map
hosts the main and contextual toolbars and owns navigation, resources and map
export. Selection of a reference keeps the rendered preview mounted. See the
[editorial host contract](../../docs/en/dev/editorial-html.md#full-editor-inside-a-host).
