<p align="right"><a href="../../fr/user/rich-content.md">Français</a> · <strong>English</strong></p>

# Writing and linking rich content

Document text, memories and historical versions are stored in the database.
Attachments remain separate files; saving, restoration and access rights retain
their existing behavior.

Memories, documents, Goal descriptions/tracking, Task objectives, job descriptions and
personalities use Tiptap with a Quasar interface and no editor badge. Headings, lists, underlines, highlights, quotes, code and
tables survive saving. The Table menu adds/deletes rows and columns, merges/splits cells and
toggles header rows. Drag a column boundary to resize it. The toolbar also includes alignment,
find/replace, undo/redo and fullscreen mode.
The four **Left**, **Center**, **Right** and **Justify** icons are directly accessible,
including on mobile, without a submenu. The active alignment is highlighted.
Commands unavailable for the current selection are disabled: **Merge cells** requires
multiple selected cells, and **Split cell** requires an already merged cell.
In the table context menu, **Table styles** opens a preview gallery: **Contrast**, **Banded**
or **Minimal**, each available in **Ocean**, **Iris**, **Forest**, **Amber**, **Coral** and
**Graphite**. Choose a presentation, then a palette to apply it. The style follows new rows
and survives reading, reopening, PDF and exported HTML. **Remove preset style** clears it
without changing cells, dimensions or the caption. Style changes can be undone. Palettes
and their previews automatically follow the light or dark theme, with visible borders and
contrasting text. Switching themes does not change saved content. Printing and PDF exports
keep the light presentation even when started in dark mode.
Commands are grouped into **Reading**, **Editing**, **Text**, **Paragraph** and **Insert** blocks,
with small titles and tooltips, including in fullscreen mode. Blocks adapt to the available
width without a menu bar. Focusing the document keeps its neutral border.
**Simple mode**, used for enriched text fields, includes the **Reading** group with
**Source** and **Fullscreen**. Documents offer no Source view, whether editable or read-only.
Their **Full mode** adds page layout and its
**Full width** button, document insertions, printing and PDF/ZIP exports in **Editing**.
Dictation and speech playback appear in **Reading** in both modes, using your personal models.
In read-only mode, **Read text** remains available and the dictation microphone stays visible but disabled. Select a passage
to read only that passage, or leave the selection collapsed to read the entire text.
**Reading controls** opens a menu with icons and labels for **Pause**, **Resume** and **Stop reading**.
The toolbar stays accessible while scrolling through the document, even after clicking the page background.
While editing, right-click links, cards, images, tables, code blocks and HTML objects to open
their context menu. **Shift+F10** or the Menu key opens this menu for the current selection;
**Escape** closes it and returns focus to the editor. Menus share the main toolbar’s GNOME
icons wherever a suitable icon exists. **Alt+F10** focuses the main toolbar.
Right-click also works in paragraphs, headings, lists and quotations. **Style** offers normal
text, all six heading levels and callouts, with the current style checked. **Bold**, **Italic**,
**Underline** and **Remove format** are available directly; **Text**, **Paragraph** and **Insert**
submenus contain the other commands. Right-clicking inside a selection preserves it; clicking
outside targets the clicked text. Selections inside links and cells also retain their specific
commands. **Copy**, **Cut** and **Paste** preserve formatting when the browser allows clipboard
access; if access is denied, use the indicated keyboard shortcuts.
In read-only or viewing mode, right-click is disabled, including on text, and no contextual
toolbar appears. Left-click opens links and objects directly; a card's background also opens
its target. Keyboard selection and copying remain available.
While editing, images and noneditable HTML regions select as a single object with a yellow
outline. Right-clicking displays their commands; **Open** in an image's menu opens its preview.
In read-only mode, clicking opens the fullscreen preview directly, without selection or
editing menus. An HTML block's preview uses a static isolated copy of its current rendering,
without rerunning its scripts or Dataset writes.
Independent HTML objects leave intervening prose editable. Regions sharing CSS, JavaScript
or SVG references stay grouped to preserve their behavior.
Heading and font size selectors display their current value as text. Their dropdown lists
preview headings and font sizes at their respective sizes.
In documents, the first **Style** menu combines normal text, all six heading levels and
card styles, each with its visual preview.
On mobile, common commands remain visible; **More tools** provides additional commands,
including Full width and exports. Source remains limited to non-document rich-text fields.

The context menu for cards, block images, tables, code blocks and embedded applications
offers **Insert paragraph before block** and **Insert paragraph after block**. These commands
move the cursor into the new paragraph. Right-clicking inside an application’s form also opens its menu, preserving input. Tooltips describe each icon's action. These controls stay
out of saved content and are hidden in read-only and Source views.

## Document formatting shortcuts

Place the cursor in the document or select text. On Mac, replace **Ctrl** with **Cmd**.
Help displays **Cmd** only when Safari is detected, and **Ctrl** elsewhere.
Numbers use the top row, including on AZERTY keyboards. The **Keyboard help** button
in **Reading**, shown as a GNOME keyboard icon visible on desktop, or **Alt+0** inside
the editor, shows the list of formatting, editing and navigation shortcuts.
Press **Escape** to close the help.
In read-only mode, help lists only reading and navigation commands; help and print
shortcuts remain available without changing the document.

Available commands follow [LibreOffice Writer shortcuts](https://help.libreoffice.org/latest/fr/text/swriter/04/01020000.html).
Heading level 6 and Galaris-specific commands extend this baseline.

| Action | Shortcut |
|---|---|
| Headings 1–6 | Ctrl+Alt+1–6 |
| Normal text | Ctrl+0 |
| Numbered / bulleted list | F12 / Shift+F12 |
| Remove the list | Ctrl+Shift+F12 |
| Insert table / current table properties | Ctrl+F12 |
| Block quote | Ctrl+Shift+9 |
| Bold / italic / underline | Ctrl+B / Ctrl+I / Ctrl+U |
| Strikethrough (Galaris) | Ctrl+Alt+S |
| Left / center / right / justified | Ctrl+L / Ctrl+E / Ctrl+R / Ctrl+J |
| Superscript / subscript | Ctrl+Shift+P / Ctrl+Shift+B |
| Clear direct formatting, keep headings and links | Ctrl+M |
| Inline code / code block (Galaris) | Ctrl+Alt+E / Ctrl+Alt+C |
| Increase / decrease indent (Galaris) | Ctrl+] / Ctrl+[ |
| Nest / unnest a list item | Tab / Shift+Tab |
| Insert or edit a link | Ctrl+K |
| Find and replace | Ctrl+H; on Mac: Cmd+Alt+F (Ctrl/Cmd+F also available) |
| Undo / redo | Ctrl+Z / Ctrl+Y; on Mac: Cmd+Z / Cmd+Shift+Z |
| Nonbreaking space / soft hyphen / nonbreaking hyphen | Ctrl+Shift+Space / Ctrl+Minus / Ctrl+Shift+Minus |
| Document start / end, add Shift to extend selection | Ctrl+Home / Ctrl+End; on Mac: Cmd+Up / Cmd+Down |
| Editor fullscreen | Ctrl+Shift+J |
| Print the document | Ctrl+P |
| Keyboard help / toolbar / context menu | F1 / F10 / Shift+F10 |

In tables, **Tab** and **Shift+Tab** move between cells. In code blocks, they adjust
indentation. At the start of a heading, they demote or promote its level.
**Alt+Enter**, at the start of the first cell or the end of the last cell, inserts a paragraph
before or after the table; it also works at code block edges and after a selected object.
On a link away from these boundaries, Alt+Enter still opens its target.
Elsewhere, Tab retains keyboard navigation; use toolbar indentation commands or Ctrl+] and Ctrl+[.
Commands respect editing permissions and do not apply to **Source** fields or JSON Datasets.

Features absent from the editor (pagination, fields, macros, Writer Navigator, etc.) have no
equivalent shortcut. Browser or system combinations, including Ctrl+Tab, F5 and F11, cannot
be reliably reproduced. Some function keys may require Fn; commands remain available in the toolbars.

At the start of a paragraph, type `#` through `######` then a space for a heading, `-` or
`*` then a space for bullets, `1.` then a space for a numbered list, or `>` then a space for
a quote. **Backspace** immediately after conversion restores the typed characters. The
document is still saved as rich HTML.

## Folder colors

Document folder colors indicate their role: **blue** for custom folders specific to one
agent, **red** when they contain at least one document shared between agents, and **green**
for goal folders regardless of sharing. The tooltip explains both role and sharing. Actual
document access determines sharing; matching folder names across agents do not imply sharing.
“Goals” and “Objectifs” represent the same category. Colors stay consistent in the tree and
folder picker, including when a search hides some documents.

## Links

The **Insert a link or file** menu groups **Link**, **Add an internal attachment** and
uploads. In Documents and simpler editorial fields, including the reduced toolbar,
the internal action opens the same file_share tree with compact files,
search within the location and multiple selection. The dialog opens directly in this
browser, without tabs. Check files or directories to insert them; click a directory to
browse it. Galaris objects are available in `galaris://` and document folders in
`document://folders/`. The **Preview** icon, to the left of the checkbox, opens supported formats fullscreen without changing
the selection. Checked items remain visible in the dialog footer, where they can be removed.
It inserts citations in the text without
adding attachments or copying existing files. An existing file opens at its source in Files,
with the reader's access rights. The attachment list below the document contains uploaded
files only; use **Upload** or drag and drop to add them.
The former link search dialog with a resource kind filter has been removed.
Selected text and its formatting are preserved when inserting a single link.
Clicking the backdrop closes the dialog.
Use **Link** to enter a URL or Galaris reference. The label belongs to your text; renaming the target does not break its reference. A link
does not share the target: access is checked when it opens. In reading mode, click to open.
Document links and cards replace the document in the current context: the Documents page,
the Chat pane or the open dialog. In Chat, you stay in the conversation; back/forward arrows
appear to the right of the title, before the pane positioning buttons. Each context has its own
history. The browser's **Back** and **Forward** buttons also retrace these visits in Documents,
Chat and dialogs. In Chat or a dialog, the conversation or underlying page stays open while
the document changes. Chat history resets when the pane closes or the conversation changes;
dialog history resets when the dialog reopens. The arrows have rounded blue borders and tooltips.
Document URLs copied from this installation use the same navigation. Agents, tasks, goals,
processes, runs, Datasets and memories open in their modal without leaving the document.
Paste a `data://` address or a Dataset URL from this installation to retrieve its title,
then choose **Show card** to create a clickable reference opening the Dataset modal.
External links open in a new tab. In documents, a single click on a link or card opens its
target, including while editing: titles, backgrounds, portraits and diagrams are clickable.
The hand cursor indicates this action. Copy and zoom buttons and embedded players keep their
own actions. Right-click offers editing commands for the object or link. In other editorial fields,
Ctrl/Cmd-click opens the target; Alt+Enter remains available from the keyboard.
For documents, **Open in a dialog** opens a separate window from Documents,
Chat or another dialog, preserving the current document and its history.
For an agent, **Show card** displays its avatar, name and job title in the
text. Click the card or its avatar to open the complete agent details, including while editing.
**Show URL** restores the
link with its label.

On the **Documents** page, **Previous document** and **Next document** retrace documents
opened during your visit, including links to this page. On mobile, the arrows also appear
in the document dialog. Opening another document after going back replaces the forward
history. Changes are saved before switching documents; if saving fails, the current document
stays open. Document arrows reset when you leave or reload the page; browser URL history
remains available.

To reference another document, drag it from the folder tree or the list to the desired
position in the text. The link displays its title and the document stays in its library
location. Pasting a `document://…` reference or a document URL from this installation also
retrieves its title when you can read it. **Show card** turns the link into a clickable card;
**Show URL** restores the link while keeping the title. The card displays the document thumbnail
and its UUID in small text below the title. Click the UUID to copy it. A single click on the
title or a text link opens the document, including while editing.
The thumbnail also opens the document in the current context. Existing saved cards also get this preview;
thumbnail access follows the reader's rights.
The inserted title is saved in your
text: renaming the target later does not replace it.

### Cite business objects

**Galaris link → Galaris objects** searches Tasks, Goals, Topics, discussions, text rounds,
calls and voice turns. Their details and menus offer **Copy reference**. Paste it into a
Document with **Ctrl+V** or the **Paste** menu to insert a titled link, then choose **Show card** from its context
menu while editing. **Show URL** restores the link.

Task and exchange cards retain essential information from insertion time without copying
execution content. The link or title opens current details in a modal under the viewer's
permissions. While editing, **Open** or **Alt+Enter** also opens the target. In read-only
mode, use left-click; right-click menus and contextual toolbars are disabled. Sharing the
Document does not share cited objects.

## Callouts and attachments

The document toolbar shows real-time connection and saving status as icons. Hover over them
or focus them with the keyboard to read their tooltips. The shield icon and application
permission dialog have been removed. Server checks for Dataset access remain active;
additional consent cannot be granted here.

Attached photos remain visible when a CSS note places them in the same isolated region
as a form or calculator. Their access remains checked, and document code receives no
additional network access.

In documents, the **Style** menu includes Information, Warning, Question, Error, Stop, Forbidden and
Investigate. Each choice previews the final card, including its icon, colors and border,
adapted to the light or dark theme. Select one or more paragraphs and choose a style to wrap them in a card with
an icon and theme-aware background. Choose another style to change the card, or select the
active style again to remove it.

To insert new files directly in the text, drop them at the desired location or place the cursor
and paste copied files. Multiple files keep their chosen order and insertion position while
uploading. Upload progress
includes cancellation; images also retain the editor’s upload controls.

The document body supports rich text and isolated interactive HTML with custom CSS and JavaScript.
Three.js is available locally in that rendering as `THREE`. Uploaded HTML pages, 3D files, videos and other
files are attachments opened with their resource viewer. HTML files use the same attachment
and thumbnail mechanisms as other files and also open from Chat without creating another copy.
Import keeps the supplied file; images, styles and other resources referenced by URLs inside
it are neither downloaded nor added as attachments. **Insert attachment** in the toolbar's **Insert** group
opens a file picker and inserts uploaded files at the cursor. The attachment area below the content
remains available even when empty: drop files there or use **Upload**, then **Insert into document**
in the attachment’s context menu to insert them into the text. You can also drag an uploaded
attachment to the desired position in the text. Insertion remains available to show the same
file several times without uploading it again. Images appear in the text; audio, video and PDF files have inline
players. Other files become clickable cards opening their viewer.
All attachments remain listed below the text, including files referenced by images or links
in the content, with actions to open, download and remove them. Removing an insertion from
the text preserves its file.
Each upload shows progress and can be cancelled. Pasting a complete HTML page into the text
imports editable rich content with owned images, without executing its scripts.
Custom HTML with CSS and JavaScript stays preserved in existing documents or content supplied
by tools and agents; its interactive rendering remains isolated. The document editor does not display source code.

Paste a URL on its own into the document: it becomes a clickable link without a modal.
Right-click the link and choose **Show card** in the editor’s context menu to insert its title,
available description and thumbnail, including for YouTube. **Show URL** in the card’s context menu
converts it back to a link. The card is fetched only after you choose it. You can repeat these appearance
changes: a card with a thumbnail reuses its cached preview during editing without creating
an attachment. If a site refuses automated previews, the card retains its address without
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
Previews require public HTTPS URLs; plain links remain available. Thumbnails are cached technical
previews, not attached content: they create no files in the document's attachments. If the cache
is cleared, the preview can be regenerated; if the source is unavailable, the card retains its
text and link. Old cards remain readable. Clicking an attachment link opens its viewer, including while editing.
From Memory, the preview button also waits for its reader to become available. Changing
the memory or agent while waiting cancels the previous opening. An error shows a message
and makes the button available for another attempt.
Right-click an attachment, or press **Shift+F10** while it has focus, to open, download,
rename, copy its reference, insert or remove it according to the available permissions.
Thumbnails retain download and remove icons; clicking the thumbnail opens its preview.

Previews have two shared presentations: **in-page blocks**, within the content with a player when
appropriate, and horizontal **below-page blocks**, with the thumbnail on the left, information
on the right, and icon actions. Attachments below documents and
conversation previews use the same component.
When present, the URL appears on its own line below the other information.
Thumbnails preserve the file’s proportions and transparency, using lossless WebP within 320 × 320 pixels
without added white bars. They fill the available height or width according to their shape
while keeping the entire image visible.

Office attachments (DOC, DOCX, ODT, RTF, ODG, ODP, PPT and PPTX) display a thumbnail
of their first page. XLS, XLSX and ODS spreadsheets show their first printed page,
according to the workbook’s page layout. The preview appears after generation; if
conversion fails, the file remains downloadable. Clicking these cards downloads the
original file, which remains intact. The same rule applies to indexed files and chat
previews: Office documents, spreadsheets and other formats without a viewer only offer
downloads, with no fullscreen action.

On desktop, the editor’s **Print** button opens the browser print dialog with the current content,
including unsaved changes. Printing retains images, tables and callouts on a light background,
without editor controls. Embedded objects use a static copy of their current rendering,
without rerunning their scripts.
In mobile mode (below 1024 px wide), **Share** replaces **Print**: the current content is
prepared as a PDF and offered to the device’s share menu. If the browser cannot share files,
it offers to save the PDF instead.

In the **Editing** group, **Export as PDF** downloads the current content directly using the
document title and a `.pdf` extension. Text remains selectable; images, tables and callouts
are retained on light A4 pages. As with printing, only static content is exported. Exporting
requires read access and does not create a document revision.
Process cards include their full diagram fitted to the page width; agent cards retain their
portrait and text. Images and embedded objects are not clickable in the PDF. Ordinary text
links remain usable.

Bootstrap Icons’ filled compressed-file icon, with the **Export document and attachments (ZIP)** tooltip, downloads `document.html` and an `attachments/`
directory. Extract the entire archive to keep file links working. The limit is 64 MiB,
including up to 12 MiB of text and embedded images. External dependencies of attached files
remain external.

Documents open in **Fixed width**: an A4 page with 10 mm margins, suitable for printing.
A single icon button toggles **Full width** to use all available space when working on wide
tables; it is active in full width mode. It also works in fullscreen and leaves the saved
content unchanged. On mobile, the page fits the screen width.

## Source code files

You can attach JavaScript, TypeScript, Python, shell and other source files to a document
or chat. Click the file to open its preview: the internal CodeEditor displays read-only
code with syntax highlighting. You can select and copy the text, then download the
original file. Neither the preview nor thumbnail generation executes the source, even
when it contains HTML tags or a shebang. Downloading does not launch the file.

HTML and SVG files keep their usual isolated previews.

## Document images

Ordinary working documents accept local images through the editor’s selection, paste or
drop controls. The context menu provides alternative text, captions and width settings.
Uploads show progress. Images remain document attachments and appear in the content when embedded.

Images are unavailable in other memories, agent profiles, tasks and Goal descriptions/tracking,
including the tracking Document in the library. Remote image URLs and SVG are unsupported.

An agent can also generate an image, copy its URI to the document's attachment collection,
then embed it in the text. The filename follows the model's native output format: a PNG uses
`.png`, even when the requested destination ended in `.jpg`. Its bytes and dimensions are
preserved; reuse the URI returned by the tool.
Requested dimensions are preferences. If OpenRouter explicitly rejects the selected resolution,
Galaris retries once with the provider's default resolution, preserving the model, requested
aspect ratio and reference images. The result reports the actual dimensions.

Two attachments can share a source filename. To distinguish them, the agent uses their
complete URIs and `entry_name` navigation keys, which are unique within their parent.
A copy preserves the source filename and does not overwrite an existing file without an explicit request.

Removing an image from the text preserves its attachment. Explicit deletion hides the attachment
from the list but keeps historical versions restorable under current access rights. Forgetting
the document permanently removes these resources, subject to business protections.

## Saving and history

Edit the title in the outlined field in the document header, next to its icon. Long titles wrap
across multiple lines and the field adjusts its height. It saves automatically
like the content; read-only documents keep a non-editable title. Owner and Sharing sit on the same row.

The **Owner** field shared by Documents, Datasets and internal processes lists **Me** first,
then other users and finally agents, according to your permissions. Search for a name in
the menu. Each type with more than 50 results has independent pagination; shorter lists
have none. Pages default to 50 results, with 10, 20, 50, 100 or 500 results available.
Avatars accompany names, including **Me** and the selected owner. The list stays in memory
for five minutes within your session; opening the field after that period refreshes it.

Documents save automatically. Wait for the saved status before closing the browser. A draft is
also retained within the tab so interrupted editing can be recovered. If two people change the
same content, a message preserves your draft and offers a choice between your version and the
latest remote version. No automatic choice overwrites a concurrent edit.

In Documents, saving updates the title in the list and tree before their refresh completes.
After you confirm deletion, the row disappears while the server processes the request; a refusal
restores the row and preserves the open content. Reconnecting refreshes documents and available
filters without closing expanded folders.

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
Embedded HTML follows the same theme: text remains readable even when its CSS fixes a dark
color. No additional background is added around its text. Forms retain their input and
scripts continue without restarting.

Select an image to show the native resize handles: drag a corner to change its width while
preserving its aspect ratio, or use the size menu. Move images by dragging and dropping them.
The context menu also controls wrapping, captions and alternative text. Changes can be undone.
To align a block image to the left, center or right, select it and use the alignment buttons
in the main toolbar. Alignment is preserved when editing its caption or alternative text and
after reopening the document.

Inside a table, the context menu exposes rows, columns, headers, merge/split and deletion.
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

## Sharing a document

New documents are **Private**. Their optional Memory synthesis inherits current document rights.
Standalone memories remain private to their Agent and have no sharing control. From the synthesis,
use **Open document**, then click the document editor’s **Sharing** field to open the choices:

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
