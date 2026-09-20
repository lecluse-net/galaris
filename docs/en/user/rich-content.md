<p align="right"><a href="../../fr/user/rich-content.md">Français</a> · <strong>English</strong></p>

# Writing and linking rich content

Memories, documents, Goal descriptions/tracking, Task objectives, job descriptions and
personalities use CKEditor 5 with its native interface. Headings, lists, underlines, highlights, quotes, code and
tables survive saving. The Table menu adds/deletes rows and columns, merges/splits cells and
toggles header rows. Drag a column boundary to resize it. The toolbar also includes alignment,
find/replace, undo/redo and fullscreen mode.
Commands are grouped into **Reading**, **Editing**, **Text**, **Paragraph** and **Insert** blocks,
with small titles and tooltips, including in fullscreen mode. Blocks adapt to the available
width without a menu bar. Focusing the document keeps its neutral border.
**Simple mode**, used for enriched text fields, includes the **Reading** group with
**Source** and **Fullscreen**. **Full mode** for documents adds page layout and its
**Full width** button, document insertions, printing and PDF/ZIP exports in **Editing**.
Dictation and speech playback appear in **Reading** in both modes, using your personal models.
In read-only mode, **Read text** remains available and dictation is hidden. Select a passage
to read only that passage, or leave the selection collapsed to read the entire text.
The toolbar stays accessible while scrolling through the document, even after clicking the page background.
Heading and font size selectors display their current value as text. Their dropdown lists
preview headings and font sizes at their respective sizes.

## Folder colors

Document folder colors indicate their role: **blue** for custom folders specific to one
agent, **red** when they contain at least one document shared between agents, and **green**
for goal folders regardless of sharing. The tooltip explains both role and sharing. Actual
document access determines sharing; matching folder names across agents do not imply sharing.
“Goals” and “Objectifs” represent the same category. Colors stay consistent in the tree and
folder picker, including when a search hides some documents.

## Links

The **Galaris link** button opens accessible content search: enter at least two characters,
filter by type, select a target, then adjust the link text before inserting it. Selected text
and its formatting are preserved. Clicking the backdrop also closes the dialog.
Use the native link button to enter a URL or Galaris reference. The label belongs to your text; renaming the target does not break its reference. A link
does not share the target: access is checked when it opens. In reading mode, click to open;
links open in a new tab while the document stays open. In editing mode, click positions the cursor
and Ctrl/Cmd-click opens the target in a new tab. The link dialog offers explicit Open, edit,
and remove actions.

## Callouts and attachments

The **Styles** menu offers Information, Warning, Question, Error, Stop, Forbidden and
Investigate. Select one or more paragraphs and choose a style to wrap them in a card with
an icon and theme-aware background. Choose another style to change the card, or select the
active style again to remove it.

To insert new files directly in the text, drop them at the desired location or place the cursor
and paste copied files. Multiple files keep their chosen order and insertion position while
uploading. Upload progress
includes cancellation; images also retain CKEditor’s native upload controls.

The document body remains rich text. Interactive HTML pages, 3D scenes, videos and other
content are attachments opened with their resource viewer. The toolbar’s **Attachments** button
opens file management: drop files into this dialog or use **Add**, then the **Insert into document**
icon in the preview actions. Images appear in the text; audio, video and PDF files have inline
players. Other files become clickable cards opening their viewer.
Files absent from the content remain listed below the text with actions to open and remove them.
Inserting an attachment hides it from this list; removing its insertion shows it again.
The management dialog gives access to all attachments. Each upload shows progress and can be cancelled. Pasting a complete HTML page
into the editor or its source offers a choice: attach the intact page, extract rich text,
or cancel. Scripts in historical versions remain readable as literal code.

Paste a URL on its own into the document: it becomes a clickable link without a modal.
Click the link and choose **Show card** in CKEditor’s floating toolbar to insert its title,
available description and thumbnail, including for YouTube. **Show URL** on the card’s toolbar
converts it back to a link. The card is fetched only after you choose it. You can repeat these appearance
changes: a card with a thumbnail is reused during editing without downloading the page again or
duplicating its attachment. If a site refuses automated previews, the card retains its address without
inventing metadata. Web pages use the same page capture generator and cache as conversations;
YouTube uses the video thumbnail. Cards also share the conversation preview styling.
The site’s published description is kept with the capture and displayed in both contexts.
URLs pasted into code blocks remain text.
YouTube cards display the official player directly in the document, in reading and editing modes,
below the title and description. The player occupies the card’s full width and hides the separate
thumbnail. Videos fit entirely without cropping; PDF attachments also have full-width previews
in a golden-ratio frame (width / height ≈ 1.618). **Open PDF in fullscreen**, to the right of the title, opens the existing
viewer using the already loaded file.
Printing and PDF export retain the static thumbnail or link.
The **Insert into document** icon is available in the preview actions only for files that are not
already present in the document body.
Previews require public HTTPS URLs; plain links remain available. Thumbnails are stored
with the document. Attachment links open their viewer (Ctrl/Cmd-click while editing).

Previews have two shared presentations: **in-page blocks**, within the content with a player when
appropriate, and horizontal **below-page blocks**, with the thumbnail on the left, information
on the right, and icon actions. Attachments below documents and
conversation previews use the same component.
When present, the URL appears on its own line below the other information.
Thumbnails preserve the file’s proportions and transparency, fitting within 520 × 320 pixels
without added white bars. They fill the available height or width according to their shape
while keeping the entire image visible.

The editor’s **Print** button opens the browser print dialog with the current content,
including unsaved changes. Printing retains images, tables and callouts on a light background,
without editor controls. It uses the document’s static content: scripts and the elements they
generate are not printed.

In the **Editing** group, **Export as PDF** downloads the current content directly using the
document title and a `.pdf` extension. Text remains selectable; images, tables and callouts
are retained on light A4 pages. As with printing, only static content is exported. Exporting
requires read access and does not create a document revision.

Bootstrap Icons’ filled compressed-file icon, with the **Export document and attachments (ZIP)** tooltip, downloads `document.html` and an `attachments/`
directory. Extract the entire archive to keep file links working. The limit is 64 MiB,
including up to 12 MiB of text and embedded images. External dependencies of attached files
remain external.

Documents open in **Fixed width**: an A4 page with 10 mm margins, suitable for printing.
A single icon button toggles **Full width** to use all available space when working on wide
tables; it is active in full width mode. It also works in fullscreen and leaves the saved
content unchanged. On mobile, the page fits the screen width.

## Document images

Ordinary working documents accept local images through CKEditor's native selection, paste or
drop controls. The contextual toolbar provides alternative text, captions and width settings.
Uploads show progress. Images remain available through the **Attachments** button.

Images are unavailable in other memories, agent profiles, tasks and Goal descriptions/tracking,
even when opening a Goal document through the library. Remote image URLs and SVG are unsupported.

Removing an image from the text preserves its attachment. Explicit deletion hides the attachment
from the list but keeps historical versions restorable under current access rights. Forgetting
the document permanently removes these resources, subject to business protections.

## Saving and history

Documents save automatically. Wait for the saved status before closing the browser. A draft is
also retained within the tab so interrupted editing can be recovered. If two people change the
same content, a message preserves your draft and offers a choice between your version and the
latest remote version. No automatic choice overwrites a concurrent edit.

History displays versions in their original format and compares content, links, tables and
images. Restoring creates a new revision without restoring old sharing permissions. Agent job
descriptions and personalities also remain HTML inside system prompts. Inspection offers the
exact source and a rich preview.

Reload the application or PWA after this update. An old client is rejected on editorial writes;
first preserve any draft still open in that old screen. Skills and their Markdown editing
remain unchanged.

Rich content automatically follows the application's light or dark theme while reading,
editing and using fullscreen. Text, backgrounds, links, tables and code change together;
highlights retain readable dark ink on their pastel colors. Switching themes does not change
the saved content.

Select an image to show the native resize handles: drag a corner to change its width while
preserving its aspect ratio, or use the size menu. Move images by dragging and dropping them.
The contextual toolbar also controls wrapping, captions and alternative text. Changes can be undone.

Inside a table, the contextual toolbar exposes rows, columns, headers, merge/split and deletion.
Drag across multiple cells before merging them; drag a vertical cell border to resize a column.
Unavailable commands are disabled. Active formatting is shown in blue in the main toolbar,
with grouped commands and compact icons.


## Dictating and listening to enriched text

Open the **Models** section in **My profile**. To configure another user, open
**Users → Edit → Models** with user update permission. Both forms offer the same profile and
voice choices as agents, including the current profile option. Select a profile
with a configured transcription model and a speech synthesis voice. An empty profile selection
follows the current profile; an explicitly selected profile never borrows missing models from
another profile. These choices belong to your user account. The voice selector includes TTS
and native realtime voices; document reading requires a TTS voice. Settings are located in
the user forms rather than documents.

Place the cursor in the text, click **Dictate** in the **Reading** toolbar group and allow
microphone access. Speech appears automatically at the cursor as transcriptions arrive,
and is saved like other edits. The icon changes to **Finish dictation**; click again to finish.
Recordings are limited to five minutes and 20 MiB. Dictation requires write access, a compatible
browser and HTTPS or localhost.

**Read text** reads only the selected text when there is a selection, or the whole editor content
otherwise, using your voice. The selection is captured when reading starts. HTML formatting and scripts are removed
before synthesis; headings, paragraphs, lists and tables retain their text and order. Line breaks
separate blocks, list items and table cells; existing text line breaks are preserved. Long
documents are read in successive chunks. The reading button starts playback, then pauses or resumes it.
Its separate arrow opens the **Pause** / **Stop reading** menu without starting playback.
**Resume** continues from the paused position. Replacing the content or closing the editor
also cancels recording or playback. Audio uses the providers configured in Galaris.

## Sharing a document or memory item

New resources are **Private**. Click the **Sharing** field to open the choices:

- **Public**, with read or write access, includes application users and Agents.
- **Groups** adds the owner's current groups with the chosen permission.
- Filtered search lets you select a group, person or Agent. Click the eye to grant read access,
  or the pencil to grant write access, which includes reading.

Each grant appears in a gray chip with an avatar for people and Agents. Its icon toggles the
permission; its remove button revokes that grant. Changes save immediately. A failed save
preserves the last confirmed permissions and offers a reload. Owners always retain access.

Selected groups remain selected when ownership or the owner's memberships change. Access follows
the groups' current members: leaving a group revokes the access it provides. Already covered
permissions are excluded or disabled in search. Search displays ten recipients per page,
with pagination and a page size selector.

**Public/Read** allows additional individual writers. Toggling their chip to read removes the
redundant grant. **Public/Write** replaces individual grants and offers no additions. Removing
Public keeps any remaining individual grants.

Humans find accessible documents under **Shared with me**, even without managing an Agent.
Permissions cover content, attachments, previews, exports and history. Writing permission does
not grant permission to share; owners and authorized administrators manage recipients.
Public access still requires application authentication.
