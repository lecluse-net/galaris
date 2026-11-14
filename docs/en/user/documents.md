<p align="right"><a href="../../fr/user/documents.md">Français</a> · <strong>English</strong></p>

# Organize the document library

Open **Knowledge → Documents** (`/documents`) to create and organize **Text** documents
(rich HTML) and **Data** documents ([JSON](datasets.md)). [Processes](internal-processes.md)
retain their business library. Classification is personal and does not change other readers' organization.
A folder can automatically grant additional access to your documents and expose its collection to authorized recipients.

Documents and their shared summaries are independent of agents' personal memories.
Sharing a document does not share any memory; deleting a reference in the memory
graph does not delete the document. Memories about a document remain private to
the agent that acquired them.

A document body uses the same full editor in the library, Chat, preview dialogs and
Goal tracking, including its mobile layout. Rich text fields — memories, Agent profiles,
Goal descriptions and summaries — use a simple toolbar with common formatting,
headings, lists, alignment, inline and block code, checklists, tables, separators and Galaris links.
Each group has one row and wraps when space is limited, without horizontal scrolling.
Fullscreen, attachments and equation insertion remain in full mode;
previously saved content is preserved.

## Import a file

Drag one or more files from your computer onto a folder in the tree, onto a document
to create sub-documents, or onto the root creation area. The **Import documents** dialog
opens with an upload area for adding more files. Its table shows each format, whether
it is importable, and its processing status. **Import** processes files one
at a time and identifies the current file. Each file becomes a personal document named
after the file and placed at the drop location. You can close and reopen the dialog
while processing; each successful import disappears from the list, while pending,
unsupported or failed files remain visible. Adding the same file repeatedly adds only
one row to the list. Closing it after completion
opens the last created document. A placement failure is reported; the created document
remains accessible and can be moved later.

In the **New document** menu, choose **New document from…**, then select a file in
the import dialog. Add files there and click **Import**. **Galaris files** also adds
sources from the file spaces accessible to agents.
**Local files from the client computer** opens your computer's file chooser.
**Clear list** removes all remaining files before another import.
**New document from…** is also available in the **…** and right-click menus of every
folder and document in the tree. The imported document is created in the selected
folder or as a sub-document of the selected document.
JSON files become **Data** documents; HTML pages (`.html`, `.htm`), Markdown files
(`.md`, `.markdown`) and plain text (`.txt`) become **Text** documents.
These text formats must use UTF-8. HTML files are cleaned before validation: scripts,
event handlers and active embeds are removed while compatible text, structure and styles
are retained. PDF, Word, Excel, PowerPoint, OpenDocument, RTF, EPUB
and supported image files also become **Text** documents. Word/OpenDocument and compatible
formats are converted to cleaned HTML with images and tables. PDFs and other conversions
include editable text and cropped illustrations, without adding a full-page image repeating
the same text. Scans use available OCR to separate text from detected illustrations.
Segmentation can be incomplete for complex layouts; the attached original remains the
reference. No original-file link, page heading or explanatory text is added to the content.
Technical spreadsheet extraction records are not inserted into the body.
Import has no separate 2 MB cap; the application's configured
resource quota applies as it does to other files.

You can also select an existing **Text** or **Data** document in the same picker,
including a personal document. The new document retains its type and a copy of
its content. Text document images and attachments are copied with new identities;
the original permissions and history are not copied.

Import creates an independent copy. Converted files retain the original file as an
attachment and images owned by the new document. Images displayed in the body remain
stored for rendering without also appearing in the attachment list. Editing or deleting the source does
not affect the imported document.
A non-convertible format is marked “Attachment only” in the table. **Import** creates
an empty **Text** document with the original file attached. Invalid content in a supported
format or denied access prevents document creation and remains visible as a failure.

For ZIP files, **ZIP import mode** offers **Import as file**, **Into the current folder**
or **Into a dedicated subfolder**. The subfolder named after the archive is selected by
default. Both extraction modes recreate subfolders including empty ones, then import each
file as content or an attachment according to its format. From a document, the current
folder means its known containing folder, or the root otherwise. **Import as file** keeps
the ZIP attached to an empty document. Progress identifies the
current file's path. After an error, successful files are not imported again and previously
created folders are reused. Nested ZIP files are not automatically decompressed. The resource
quota also applies to expanded bytes; an archive accepts at most 2,000 entries and 32 folder levels.

## Choose a document type

Each **New document** icon opens the type menu below the clicked icon before creating any record. Choose **Text** or
**Data**, then the title and owner. Document and folder context menus also offer both
creation actions in the current classification. Closing the menu or creation dialog
creates no document.

The **Document type** filter selects all types, Text or Data. It combines with search
and the other filters before pagination. Each type has a distinct icon, editor and
preview. Title, owner, sharing, Topic, keywords, summary and history follow common rules.
The Data editor preserves invalid JSON drafts without saving them or leaving the document.
Using the browser Back action to close its window asks whether to keep or discard the draft.
Discarding restores the last saved content.


## Current description and keywords

The small **View summary** icon beside the editor title and Topic displays the current summary
in place of the editing area, like history. This view hides keywords. Content is refreshed each
time it opens, with retry after loading errors. With editing rights, edit the summary and click
**Save summary**. **Back to document** also saves changes before returning to the content.
Errors and conflicts preserve your draft in the summary view.
**Regenerate summary** asks for confirmation, then replaces the summary, including manual edits, using the saved
document and configured Dream model, even for short documents. It preserves the document body,
content versions and keywords. Readers without editing rights see a read-only summary.

Each Document has one current shared description and current keywords, without separate history.
Only its content keeps restorable versions; restoring content preserves the current description
and keywords. Its documentary entry in Memory always shows the current description and no longer
offers description history.

Work is still saved immediately. After a content edit, a new version enters history after
**five minutes without another content edit**. Nearby saves are grouped and the delay survives
restarts. The initial state is retained; reverting to the latest checkpoint creates no duplicate.
The technical version token still protects every concurrent save, so history version numbers
may have gaps.

During idle time, Dream can generate a short explanation of what the Document is and when it is
useful, with search terms. The default threshold is **more than 1,000 useful text characters**.
A Dream entry to refresh an automatic description is created only after **five minutes
without content edits** and **at least 100 characters have changed**
since its last generation; small edits accumulate. HTML presentation changes alone do not count.
Manual descriptions are preserved. Both thresholds are configurable in Dream settings and also
apply to Datasets.

## Insert a Contact card

To insert a Contact card into the content, use **Galaris link**, then **Galaris resources →
Contacts** in the browser. Select the contact and confirm. The card displays coordinates
according to each reader's rights and opens its dialog when clicked. An existing Contact link
can become a card using **Show card** in its contextual toolbar; **Show URL** restores the link.
Sharing the document grants no additional access to the agent's address book. See [Files](files.md).

## Write with an agent

The **Conversation** icon in the library header, beside the library visibility button, opens a panel to the
right of the document on desktop. Drag the handle between the document and chat to adjust
their widths, just as between the library and document. Focus the handle and use the
left/right arrow keys to resize with the keyboard. Search
for an existing conversation or select **New conversation with an agent**. Both pickers only
offer agents who can read or edit the document through personal, team or global permissions.
Creation also retains the usual dialogue permissions. Selecting an agent does not grant new
document access. The picker shows
each agent's avatar and paginates long lists: 50 conversations by default, with a choice of
10, 20, 50, 100 or 500 per page. Paging or searching preserves the open conversation and its
draft. The last conversation selected or created is saved per document and per user.
The panel always stays closed when loading or switching documents: no conversation is
loaded until you click the **Conversation** icon. Clicking restores the last saved
conversation for that document if you still have access and its agent can still read the document;
otherwise, the panel opens empty.
You can hide it with its close button. This preference changes neither document content nor permissions.
These are the
same conversations available in **Chat**. Documents focuses on writing around the open
content; Chat focuses on exchanges and activity monitoring.

The document is saved before sending a message. The open document is identified to the
agent without changing its access rights. A failed save keeps the message in the composer.
Hiding the desktop panel preserves the conversation and its draft. On mobile, the button
opens a conversation dialog from the same icon. Access, creation and sending use the same privileges as Chat.
A displayed conversation produces no sound, toast or system notification for its new
messages. Messages actually visible on screen are marked as read. Hiding the panel or tab
restores notifications for new messages that have not been viewed.

Select a passage with the mouse or keyboard, then write your request in the chat.
The selection is remembered before focus leaves the editor, even if its highlight disappears.
Each send includes the selected text, its start and end offsets and the last cursor position,
with the document UUID and saved revision. This works both in Documents and in the document
opened in Chat. Offsets refer to displayed text, not HTML. Long excerpts are truncated;
switching documents or replacing content invalidates old positions. This context stays in
message metadata: it creates no document revision and changes no access rights.

In the editor, **Document outline** opens an indented list of headings on the left.
All headings remain visible, and the panel uses the document's background and border. Select a
heading to navigate to its section. The outline follows heading edits and can be hidden.
The library icon also hides the desktop folder pane to make more room.

In the toolbar, **Text** includes **Special characters** and the inline equation.
**Quote** is at the end of the first row of **Paragraph**; its second row includes
**Code block** and the block equation.
**Insert table** is on the second row of **Insert**.

**Inline equation** inserts a formula within the text; **Block equation** displays it
on a separate line. Both buttons open the MathLive visual editor, with its symbol
keyboard and a synchronized **LaTeX source** field. A click selects a formula; double-click
or press **Enter** on the selection to open its editor. Its contextual toolbar offers
cut, copy, delete and write before or after. The last two actions place the
cursor beside an inline formula or create a paragraph beside a block. On mobile, the actions
appear in the contextual toolbar after selecting a formula. **Ctrl/Cmd+Z** undoes deletion.
**Apply** saves the formula; **Cancel**, **Escape**
or clicking the backdrop preserves the previous content. Equations remain editable
after reopening and render in read-only views, printing and PDF/HTML exports.
The editor and its fonts are hosted locally.

**Checklist** turns the selected paragraph or list into a checklist. Checking a line saves
its state in the document, including autosave and revisions. **Enter** adds a line;
**Tab** and **Shift+Tab** nest or unnest lines. States survive reopening and remain visible
in read-only views and exports. These lists require no Dataset.

On desktop and mobile, a contextual toolbar appears below the main toolbar in editable documents.
Its commands follow the cursor or selection: table and cell, image, link or code block.
Icon menus provide properties specific to the selection. Text, paragraph and insertion
commands stay in the main toolbar, with **More tools** for its additional commands.
Swipe the icon row horizontally to reach all its commands.
This toolbar stays below the main toolbar while scrolling and appears only when the selection offers actions, without leaving a gap
when it disappears. Right-click, **Shift+F10** and long press remain native: spelling,
dictionary and clipboard commands depend on the browser's capabilities.
While editing, a left click selects a link or card without opening it. Use **Open** in the
contextual toolbar, or **Ctrl/Cmd+click**, to follow its target. Read-only views keep direct left-click navigation.
Common commands are not repeated. To edit a link or equation, select it
and use the corresponding toolbar button.

## Organize by folders, topics or agents

Use **Folders**, **Topics** and **Agents** to switch library views immediately. Your last
selected tab is saved to your account and restored when reopening, including in another
browser. Without a saved preference, **Folders** remains the default and preserves your
manual organization.

**Topics** groups accessible documents by topic, then by tag (the document’s keyword).
**Agents** groups them by their owning agent, then by tag. A tag appears once within each
group and can appear under several groups. **All documents** opens the complete group;
**Without a tag** groups its documents without keywords. These navigation entries use
different colored markers from the tags.

The lower list keeps unassigned documents available: without manual placement in Folders,
without a topic in Topics, or without an owning agent in Agents. Human-owned documents
therefore remain accessible in that last list. Search and filters remain available there.

In **Topics**, drag a document from one tag branch to another to change its topic and
replace the source tag with the destination tag. Other tags, content, permissions and
manual folders are preserved. Dropping onto the topic itself changes only the topic;
dropping into the lower list removes the topic while preserving tags. Changes require
permission to edit topics and the document. If the document has changed in the meantime,
the move is refused and only its classification is reread. Dropping on **Without a tag**
removes all its tags.

In **Agents**, the same move transfers ownership to the destination agent and replaces
the source tag with the destination tag. Other tags are preserved; dropping on an agent
preserves every tag. Dropping into the lower list places documents under your personal
ownership. Your editing rights are preserved.

Use Ctrl/Cmd or Shift to select several documents, topics or tags. Dragging
moves the entire selection; hovering over a tab during a drag switches trees. Context
menus (right-click, the **…** button or Shift+F10) move the selection and open document
bulk operations. Topics can be created, edited, deleted or merged; tags can be renamed,
deleted or merged. Dropping a topic or tag on a compatible entry prepares a merge for
confirmation. Deleting a topic or tag preserves documents. Topic actions apply throughout
the application; renaming, removing or merging a tag affects all accessible documents
carrying it. Confirmations explain this scope. A refused operation keeps the entries and
allows a retry.

Above 100 entries, a branch is split into virtual folders labeled with the names of its
first and last documents, identified by a cyan zipped-folder icon. The names follow each
other when space allows; otherwise, each is truncated with a balanced share of the available
width. Hovering shows both complete names. Opening a range loads only its own 100 documents
at most. Very large collections add range levels, with at most 100 folders per level.
This grouping does not move documents or change their classification.

When merging tags, choose the destination from the selected tags; the first is selected
by default.

Selection moves and bulk ownership changes are submitted to the server as one operation,
up to 5,000 documents. You can then navigate to another application page while processing
continues. Moves report their result in a notification. An access denial or version
conflict rolls back the whole batch; if the outcome could not be confirmed, refresh the
library before retrying.

A change updates only the affected entries: other rows, expanded branches and loaded
documents stay in place. Switching tabs preserves each tree. Reconnection and access
changes reconcile data without emptying the tree; changing accounts removes the previous
account’s data.

## Create and find Documents

To change a title through an agent, ask it to rename the document. It uses `file_info`,
then `file_rename` with the metadata version. The library title changes while the
`document://` URI, body, content history, attachments and sharing remain unchanged.
Editing a heading in the body or a link label is a separate action. Titles of
Goal descriptions are Goal-owned HTML fields. Tracking remains a Document created unclassified:
it appears in the list, outside the tree including its root. Each user can freely classify it.
No Goal folder is imposed.

In the **Documents** library, every folder offers a **New document** icon among its
actions. Enter the title and owner: the document is automatically placed in that folder,
which expands, and opens in the editor. The general creation button keeps new documents
in the unclassified list, outside the tree. The root contains only documents you explicitly
place there. Use **Create a document at the root** below the tree, or drop a document there
from the list or a folder. Drop it back into the unclassified list area to remove that
placement. This personal choice survives reloads and is independent of list filters;
other documents without a folder remain unclassified.

Library filters use a single **Owner** field to choose a person or agent. It lists **Me**,
then users and agents, with search and independent pagination for each large list.
Clearing the field restores all owners while retaining the other filters.

## Organize folders and sub-documents

Right-click a folder to open its menu with icons and
labels for all its actions: show as a list, create a document or folder, edit, sort, expand,
collapse, and delete. **New document**, **New subfolder**, **Edit**, and **Delete** remain
available directly on the row, including on mobile. Press **Shift + F10** on the folder
from the keyboard; **Escape** closes the menu.
The **…** button on folders and documents opens the same menu without right-clicking,
including on mobile. **Copy folder URL** and **Copy document URL** place
`document://folders/<uuid>/` and `document://<uuid>` respectively on the clipboard without
changing classification or selection. Copying remains available for read-only documents.
While a context menu is open, its folder or document stays highlighted even when the
pointer leaves the row.

A document can also contain **sub-documents**. Use its **New sub-document** icon,
or drag an existing document onto the middle of its row. Sub-document creation is available
only for documents in the tree, through neither the list below it nor the list with checkboxes.
The arrow expands its children
across multiple levels; clicking the title still opens the document. To move a child out of
its parent, drag it into the unclassified documents area or a folder.
This hierarchy is personal, like folders: each document retains its own sharing rights,
with permissions from its folders and parent documents added to them.
Deleting a parent preserves its children; readable children reappear in the unclassified
list, including when access to their parent is revoked.

Once the server confirms an operation, a moved document appears in its new location and a
deleted document disappears immediately. Lists refresh in the background without blocking
the next move. If the server rejects a move, the existing placement stays unchanged and you
can retry.

## View lists and act on a selection

In **Documents**, **Show folder as a list** opens a paginated view with titles, thumbnails,
owners and keywords. Enable **Include subfolders and sub-documents** to include descendants.
**Show unclassified documents as a list**, beside the search field, opens documents without
personal classification. Pages default to 50 documents and offer 10, 20, 50, 100 or 500.

In the library tree and list, **Ctrl+click** (**Cmd+click** on Mac) adds or removes an
individual document without opening it. **Shift+click** selects the range from the last
individual click, excluding collapsed descendants. **Ctrl/Cmd+Shift+click** adds that range
to the existing selection. A plain click replaces the selection and opens the document.
The counter lets you clear multiple selections. Changing search, filters or pages resets selection.

To move several documents, drag any selected document onto a folder, inside another document,
or into the unclassified documents area. The gesture carries the entire selection in its
displayed order; dropping before or after a row places the group at that position.
A descendant selected together with its parent follows that parent without being detached.
You can also drag from the paginated list with checkboxes into the tree.
Moves are saved document by document. If some fail, a summary appears and failed documents
remain selected for retry.

In the list with checkboxes, these shortcuts also work on titles and checkboxes.
Clicking a row's background selects it; a plain click on its title opens the document.
Documents protected against bulk operations cannot be selected.

Select individual documents or **Select this page**, then open **Selection actions** to
delete after confirmation, change ownership, add or remove keywords, or add, change or remove
a share. Selection covers the displayed page and resets when changing pages or search.
Each command preserves the other keywords and shares specific to each document. Read or
write access is set for the chosen recipient across the selection; removing an explicit
share preserves access inherited through teams or public sharing. Owners retain access
through ownership. Results list successes and failures; accessible failed documents stay
selected for another attempt. Concurrent changes are rejected instead of overwriting newer settings.

## Use keyboard shortcuts

Hover a folder or document row, or focus it with the keyboard, to use its shortcuts.
**F2** renames, **F3** creates a document in the folder or a sub-document under the document,
**F4** opens the folder as a list or opens the document, and **F7** creates a subfolder
(a sub-document on document rows). **F3** and **F7** are available only in the tree;
document lists do not use them. **Delete** opens confirmation for the targeted row;
it does not delete the bulk selection. Shortcuts are suspended while typing, in menus and
dialogs, and respect each document's permissions and protections. Folder context menus
also show the available keys.

## Follow changes

In **Documents**, ordinary refreshes update affected rows without clearing the tree or list.
Expanded folders and filters stay in place, including after reconnection. A failed refresh
can be retried while displayed documents remain available; access revocation removes them immediately.

## Write and share

In every document editor, **Ctrl+F** (or **Cmd+F**) and the **Find** tool open a bar below
the icons, with search and replacement fields. Clicking **Find** again hides the bar and
keeps the query for reopening. Matches are highlighted as you type without changing the
document. The content remains accessible. **Enter** in the search field or **Next**
selects the next match; options support case-sensitive and whole-word
search. **Escape** or the close button hides the bar and returns focus to the document.
The same bar is available on desktop and mobile, in Documents, documents opened from
other pages and fullscreen, including rich-text content. Read-only documents keep search
available with replacement disabled. Find no longer opens a modal.

To develop a document with an agent, ask for updates to the relevant passages. The agent
preserves useful information and can add distinct material; prior versions remain in the
revisions. Specify when you need a chronological journal or meeting minutes: that chronology
then remains relevant in the document.

The [rich content guide](rich-content.md) covers editing, links and cards, attachments,
sharing, revisions and exports. To work alongside an agent, open a document from the
discussion's Documents section.

## Automatic folder sharing

Open a folder as a list (**F4**) and use **Automatic folder sharing** at the top.
Grant read or edit access to users, agents and teams, or public access for authenticated
users. These rights apply recursively to subfolders, documents and sub-documents,
including later additions. A document combines permissions from every folder containing
it and every parent document; the most permissive permission wins. Filing somebody else's
document, even with edit access, never authorizes resharing it. Editing classifications stays
personal. Readers can discover folders containing a document they can read, together with their
ancestors, even without explicitly sharing the folder. This grants no access to other documents
classified in the same location.

Every folder has a stable URL `/documents/folders/<uuid>` and reference
`document://folders/<uuid>/`. In its list (**F4**), the link icon copies the reference and
**Open folder** opens its dedicated page. Renaming, changing the icon or updating contents
preserves the link. The page lists subfolders and readable documents throughout the branch,
including nested documents, with search and pagination.

To attach a folder, use **Add an internal attachment** in Chat or **Galaris link** in a Document,
browse `document://folders/`, check the folder, then click **Select**. Its card retains a live reference and uses the folder icon as its
thumbnail. It copies no documents and grants no access: the agent must already be able to read
the relevant documents. Sharing the folder can grant access to documents you own.
Agents discover their collections with `file_list("document://folders/")`,
then read a folder with `file_read("document://folders/<uuid>/")`. The response contains its
JSON hierarchy of readable subfolders and nested Documents, in pages of at most 200 items.
Pass the returned `next_offset` as `offset` on the next read, then read the desired document
URIs. Every request checks current
permissions; revocation prevents subsequent reads.

Removing a folder grant, moving a document or deleting a folder removes only that source's
contribution. Own grants and other sources remain. A permission inherited from an ancestor
returns when removed directly on the document while the ancestor still grants it.
Every `make update` idempotently reapplies all these rules.
