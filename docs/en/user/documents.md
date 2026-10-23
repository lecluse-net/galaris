<p align="right"><a href="../../fr/user/documents.md">Français</a> · <strong>English</strong></p>

# Organize the document library

Open **Knowledge → Documents** (`/documents`) to create and organize accessible HTML
content. [JSON Datasets](datasets.md) and [Processes](internal-processes.md) have their own
libraries. Classification is personal and does not change other readers' organization.
A folder can automatically grant additional access to your documents without sharing your tree.


## Create and find Documents

In the **Documents** library, every folder offers a **New document** icon among its
actions. Enter the title and owner: the document is automatically placed in that folder,
which expands, and opens in the editor. The general creation button keeps new documents
in the unclassified list.

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
document, even with edit access, never authorizes resharing it. Your tree stays personal.

Removing a folder grant, moving a document or deleting a folder removes only that source's
contribution. Own grants and other sources remain. A permission inherited from an ancestor
returns when removed directly on the document while the ancestor still grants it.
Every `make update` idempotently reapplies all these rules.
