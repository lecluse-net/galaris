# ADR 0202 — Native Process references in Documents

Date: 2026-10-17

Status: accepted

Documents cite native definitions with `galaris://processes/<code>` and runs with
`galaris://processes/runs/<uuid>`. The existing singular definition locator remains
readable. A reference opens the Process preview in read-only mode or the existing
Run modal. External engine definitions retain their existing presentation.

Citations are authored HTML references, independent of the uploaded-file inventory.
The attachment section below a Document has one localized Upload action and lists
uploaded files only. Internal resources, including existing managed files, are neither
listed there nor copied into the Document when selected for insertion.

The toolbar keeps its combined link/file insertion menu. Its internal action uses a
compact file_share browser with a directory tree, provider search and multiple selection.
Native Process and Dataset selections insert canonical title links directly in HTML.
Other provider files use a Files link retaining their source URI and selected Agent
context; opening it authorizes the source again. Insertion performs no attachment
membership write. Explicit uploads remain the only insertion path that creates a file
attachment. Existing Process/Dataset/generic membership manifests stay readable and
removable through their compatibility APIs, but are excluded from the Document file
collection and attachment UI.

Source authorization is independent of Document authorization. The internal picker
supplies a server-derived management scope for native Dataset and Process reads,
including personally owned resources. Connection-backed providers keep the selected
Agent context. Ordinary file browsing and agent tool calls retain their existing Agent
policy; a client cannot supply its own management scope.

An authored title link can become a diagram card with
`<blockquote class="galaris-link-card galaris-process-diagram">` containing the
canonical link. CKEditor preserves this portable HTML while the application
composition mounts a read-only BPMN view outside its data model. The plain reader
uses the same view. Zoom controls appear on hover and keyboard focus, and remain
available on touch screens. A title link remains available without a diagram.

Definition previews use current BPMN; run diagrams use their launch snapshot.
Thumbnails are derived from the parent's current graph, with an additional run
badge for executions. Optional thumbnails load only near the viewport and are
discarded on context change. They neither create stored files nor grant access.

The Process read policy applies before any diagram or operational data is returned,
including reads reached from Memory. Run mutations retain their existing privileges
and authorization. These references add no Document resource type or editor.

Coverage includes independent sharing and revocation, canonical membership,
concurrent changes and retries, frozen run diagrams, editable HTML round trips,
modal opening, zoom, small viewports and the assembled Document journey.
