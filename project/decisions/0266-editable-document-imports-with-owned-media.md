# 0266 — Editable document imports retain their own media

Status: accepted. Date: 2026-11-05.

Document import reuses `core.document` in an explicit editable preparation mode, separate
from LLM evidence and thumbnail checkpoints. The installed Pandoc converts DOCX, ODT,
RTF and EPUB to semantic HTML with extracted images, in sandbox mode. The import removes
Office styling, scripts and external embeds. Image references must resolve to extracted
media; an inaccessible image fails the import instead of silently disappearing.

PDFs and other supported Office conversions retain editable extracted text and cropped
illustrations instead of inserting full-page rasters alongside the same text. PDFium locates
raster and vector graphics, including nested and rotated objects; overlapping graphics are
grouped. Native text inside a figure remains in that crop rather than being duplicated as
editable paragraphs. Tesseract hOCR separates recognized text from detected pictures on scans
and tiled page images. Segmentation is heuristic and does not promise complete recovery of
every figure; a text-free picture can remain an image. The original attachment remains the
reference for complex layouts. Full-page evidence for LLM analysis and thumbnails is unchanged,
and editable checkpoints carry a separate converter version. Importer annotations, page headings,
structured extraction records and links to the original file are never inserted into the body.
The original binary file is retained as an independent immutable attachment. This preserves
source bytes without promising a lossless reconstruction of editable PDF layout or OCR.

Import publishes the HTML, document identity and newly owned attachments through the same
prepared-content path used for native document copies. Embedded images use the existing
retained-media manifest: they stay readable under the document's permissions and revisions,
without duplicating the visible attachment list. The original file remains visible there.
Native copies preserve this retained status. Ordinary editorial saves also move images
referenced by the body into this retained manifest. The editor hides them immediately
while the draft is being edited, without treating image-like text inside scripts as an
image reference. Standalone attachments and link references keep their visible actions.
Uploaded files remain visible until actually inserted, so an interrupted insertion does
not silently leave an unreferenced hidden upload. Failed or cancelled creation removes
unpublished media. Cleanup cannot delete already registered files. Source access and target
ownership checks remain authoritative; imported documents do not inherit source grants.
JSON and UTF-8 Markdown/text imports retain their established contracts. External HTML
files are cleaned before editorial validation: scripts (including local or unapproved CDN
sources), event handlers and active embeds are removed while displayable structure and
compatible styling are retained. This avoids rejecting an otherwise readable page at the
script-source validation boundary. Authorized native Document snapshots preserve their
existing application content instead of applying this external-file cleanup.
Unrecognized formats create an empty Text document with an independently owned original
attachment through this same publication path. A conversion failure for a recognized format
remains an error; it must not silently publish an empty substitute.

The application exposes the backend's supported formats to a compact import dialog. It
loads the import-specific FR/EN/ZH messages with this surface instead of adding them to
the startup catalogs. Registration is repeated on language changes so a downloaded root
catalog cannot erase these messages. The existing parity checker includes this scoped
catalog, and common labels continue to use the global messages. This keeps the feature
within the established startup transfer budgets.
The dialog
stages files without writing, shows format compatibility and current processing, and imports
files sequentially only on explicit launch. Non-convertible formats are explicitly labeled
as attachment-only imports. Closing the dialog preserves the
current batch while the page remains mounted. A session change stops subsequent work and
discards private UI state. Successful imports leave the queue; pending, unsupported and
failed files stay available. Repeated additions of the same local file or source URI do not
duplicate queue entries. Completed documents are never resubmitted as part of that batch.

ZIP files offer a three-way selection: keep the archive as a file, extract into the current
folder, or extract into a subfolder named after the archive (the default). The backend validates paths, entry
counts, expanded size and CRC before returning a multipart manifest and file blobs; it
never extracts archive paths onto the filesystem and this preparation creates no resource.
The client recreates the archive's folder tree through the existing folder API and imports the
expanded files through the same queue. Empty directories survive; nested archives are kept
as files rather than recursively expanded. Successful folder creations are retained across
an explicit retry; successful document rows leave the queue. No archive-wide atomicity is
claimed: partial directory creation and individual file errors remain visible and recoverable.
The modal names the destination; folders cannot be children of a Document, so that context
uses its known containing folder or the root. Declining expansion keeps the ordinary empty
document with the ZIP attached. Existing source ACLs also govern internal archive selection.
