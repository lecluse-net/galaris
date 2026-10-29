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

## Choose a document type

Each **New document** icon opens the type menu below the clicked icon before creating any record. Choose **Text** or
**Data**, then the title and owner. Document and folder context menus also offer both
creation actions in the current classification. Closing the menu or creation dialog
creates no document.

The **Document type** filter selects all types, Text or Data. It combines with search
and the other filters before pagination. Each type has a distinct icon, editor and
preview. Title, owner, sharing, Topic, keywords, summary and history follow common rules.
The Data editor preserves invalid JSON drafts without saving them or leaving the document.


## Current description and keywords

The small **View summary** icon beside the editor title and Topic opens the current summary
and keywords for reading. Content is refreshed each time it opens. Close with its button,
Escape or a backdrop click. The dialog also reports missing summaries and offers retry
after a loading error.

Each Document has one current shared description and current keywords, without separate history.
Only its content keeps restorable versions; restoring content preserves the current description
and keywords. Its documentary entry in Memory always shows the current description and no longer
offers description history.

During idle time, Dream can generate a short explanation of what the Document is and when it is
useful, with search terms. The default threshold is **more than 1,000 useful text characters**.
An automatic description is refreshed only after **more than 25%** of the content has changed
since its last generation; small edits accumulate. HTML presentation changes alone do not count.
Manual descriptions are preserved. Both thresholds are configurable in Dream settings and also
apply to Datasets.

## Write with an agent

The **Conversation** icon in the editor toolbar's **Reading** group opens a panel to the
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
or press **Enter** on the selection to open its editor. Right-click or **Shift+F10** opens
its menu: edit, cut, copy, delete and write before or after. The last two actions place the
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

On mobile (below 1024 px), an icon row appears below the toolbar of editable documents.
Its commands follow the cursor or selection: table and cell, image, link or code block.
Icon menus provide text and paragraph options; common styles remain in the main toolbar.
Swipe the icon row horizontally to reach all its commands.
Long press retains native text selection and copy/paste commands. On desktop, contextual
commands remain available through right-click.

## Create and find Documents

To change a title through an agent, ask it to rename the document. It uses `file_info`,
then `file_rename` with the metadata version. The library title changes while the
`document://` URI, body, content history, attachments and sharing remain unchanged.
Editing a heading in the body or a link label is a separate action. Titles of
Goal-controlled documents remain controlled by that Goal.

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

A document can also contain **sub-documents**. Use its **New sub-document** icon,
or drag an existing document onto the middle of its row. The arrow expands its children
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
(a sub-document on document rows). **Delete** opens confirmation for the targeted row;
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
