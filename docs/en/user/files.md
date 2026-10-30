<p align="right"><a href="../../fr/user/files.md">Français</a> · <strong>English</strong></p>

# Browse an agent’s files

**Files** requires `FILE_ACCESS` or `FILE_EDIT`; the latter also permits file mutations.
Documents, Datasets and memories retain their own privileges: Files access does not open
them, and reading an attachment through its domain does not require global Files access.
Agent scopes and resource ACLs still apply. **Preferences → Files** (`/params/files`)
groups file indexing: select an agent to inspect traversals, start or cancel indexing,
and retry repairs. This page separately requires `FILE_INDEX_ACCESS` or `FILE_INDEX_RUN`;
the latter allows actions. Neither file browsing nor Dream access is required.

When deletion is confirmed, or indexing detects that an external file has disappeared,
its linked Memory item is deleted with its content and indexes if no other resource
URI remains. An outage or access denial does not trigger erasure. An item shared
between multiple locations is retained until its last location disappears.

In **Knowledge → Files**, click an agent card to open their browser. Use the selector
to change agents without clearing the current selection. The counter to its right shows
the items loaded in the current directory. The tree presents the known schemes of
their virtual filesystem: SSH console, documents, Galaris resources and
connected providers. It respects the agents you can manage and each resource’s own
access rules.

In **Mail**, IMAP folders follow the connected agent’s mailbox hierarchy, including parent folders
without messages. Open a folder to see its subfolders and messages, newest first. The list loads
50 entries at a time as you scroll and shows the subject, sender, date and read/unread state.
Click a message to read its headers and text; **Read more** loads the next page of long messages.
Attachments can be previewed or downloaded from the reader, and the message menu downloads
the original `.eml`.

Browsing requires `MAIL_ACCESS` or `MAIL_EDIT` in addition to Files access and respects the
managed-agent scope. It does not mark messages as read, create a Task or authorize agent
processing. Users can browse Sent, Archive and Trash folders. HTML emails appear as text,
without executing their content or loading remote images. Mail search and IMAP mutations
are not offered in this browser.

In **Documents** (`document://`), folders appear directly at the root alongside files that
are not classified in any accessible folder. Opening a folder shows its subfolders and
files, without mixing in files from deeper folders. A file classified in several folders
appears in each of them with the same URL. Breadcrumbs follow folder names, including
when opening a direct link. Folders become visible as soon as their branch contains a readable
document, even without explicitly sharing the folder. All users' classifications are included;
other files retain their own access rules.

Text and Data documents share this location. Text documents display a thumbnail and Data
documents their dedicated icon. Files no longer shows a separate `data://` location;
existing `data://…` URIs remain usable.

Under **Galaris → Goals**, click a Goal to open its dialog directly. Cycles are not
displayed in Files listings or search; view them from the Goal. Goals without cycles
remain accessible.

Under **Galaris → Contacts**, browse the selected agent's private address book.
Each entry uses the contact's name. Clicking opens its usual dialog: `CONTACT_EDIT` lets you
edit the name, phone numbers and postal addresses; `CONTACT_ACCESS` displays the same fields
read-only. Search matches names and coordinates.
This requires `CONTACT_ACCESS` or `CONTACT_EDIT` in addition to Files access.
In a Text document, **Galaris link** lets you select this contact from the same browser and
insert its dedicated card. An existing Contact link can also become a card through **Show card**
in its context menu. Clicking the card opens the same dialog. The document stores the name and
URI; coordinates are loaded with the reader's rights rather than copied into its content.
Sharing the document does not share the address book.
Agents discover their contacts with `file_list` or `file_search` under `galaris://contact/`.
The `galaris://contact/<uuid>` URIs support reading, exporting and editing through the owning
agent's File Sharing tools. After `file_read` or `file_info`, pass the returned `etag` as
`expected_etag` to `file_write` or `file_edit`. The JSON can change `display_name` and
`coordinates` (phone numbers and postal addresses). Omitted fields and lists are preserved;
supplied lists replace the existing lists, and empty lists clear them. A stale version is rejected:
read the contact again before retrying. Identities, metadata and other agents' directories
remain protected.

Under **Galaris → Code repositories**, click a repository path to open the code editor.
This requires `CODE_ACCESS` and the repository's own access rights. Closing the dialog
hides the editor; reopening it preserves unsaved files.

When no location is selected, the central grid displays available schemes as folders.
Click one to open its root, then a directory in the tree or the central grid. Use the breadcrumbs
or parent directory button to go back up. Files have a thumbnail when their format
can be rendered and an icon otherwise. Click a file to preview it, or a Document,
Task, Dataset or conversation to open its existing domain view. Formats without an
integrated viewer are downloaded.

Under **Galaris → Skills**, click a generic or personal skill to open its reading dialog,
with `SKILL.md` displayed first. Its files remain available inside the dialog. Generic
skills are grouped into virtual folders named after their category; **Uncategorized**
contains skills without a category. Only categories containing accessible skills appear.
Grouping moves no files and preserves skill links after renaming or reclassification.
**Personal skills** retains owner folders showing each agent's first and last name.
The attachment picker still lets you browse the skill's files.

Your browser's **Back** and **Forward** buttons restore previously visited Agents,
locations and directories. Breadcrumbs and the parent-directory button use the same
history. The URL retains the current Agent and location, so copying it or reloading
the page restores them subject to your access rights. Navigation inside the attachment
picker remains local to its dialog.
If an open Dataset contains an unsaved draft, browser traversal asks for confirmation
before closing it; cancelling preserves both the draft and the current location.

Right-click a file or directory to open its context menu, or use **Shift+F10** while
the item has focus. On mobile, a long press opens this menu; icons are smaller and
the **⋮** button is hidden. On desktop, this button provides the same actions in the grid.
**Rename** and **Delete** appear according to your edit access and the
provider's capabilities. SSH console, Nextcloud and Samba directories support both
actions; their roots remain protected.

For a Git repository under `console://`, the context menu also offers **Open in the code editor**
with the `CODE_ACCESS` privilege. Checkouts and worktrees are detected when the menu opens.
Use the folder's menu or right-click the file area inside an open repository.
Clicking rechecks repository access and opens the editor without creating a conversation.
Closing and reopening the editor preserves unsaved buffers in the browser.

To rename an item, enter its complete name, including the extension for a file, then
confirm. Content is preserved and existing items are never overwritten. Internal files
and attachments retain their URI; external files and directories change their path.
An error preserves your draft for retry. Internal filenames are shared across domain
views, previews and downloads.

Deletion requires confirmation and includes all contents when deleting a directory.
Only the Agent's independent internal files can be deleted from `file://`; attachments
owned by a domain retain that domain's deletion rules. Business snapshots and read-only
sources do not offer mutations. The grid and tree refresh after an action. Deleting the
open directory returns to its parent. If deletion fails partway through, refresh to
inspect the remaining entries before retrying.

Videos from Samba, Nextcloud/WebDAV, AFFiNE, the SSH console and internal files play
progressively, without waiting for a complete download. The player can request a
different portion when seeking; the 512 MiB downloaded-preview limit does not apply
to this path. Your browser must support the format and codecs. Public HTTPS links
also use this playback when their size is known; if the remote server ignores byte
ranges, seeking may require rereading preceding bytes. Other providers keep their
usual preview.

The list loads as you scroll, without pagination controls. The tree displays only
the subdirectories received as loading progresses, without messages or pagination
controls; if there are none, nothing appears below. After an error, **Retry** continues loading while preserving
the files already displayed. **Refresh** rereads the current directory. Changing
agents closes previews and immediately removes the previous agent’s files.

Schemes open as accordion sections without arrows. The tree contains only visible
directories. Status messages and errors appear in the central file area; errors
and their **Retry** button are highlighted in red. Hidden files and directories
whose names start with a dot are omitted. Only schemes that can list files at their
root are displayed. Other schemes remain accessible through their URIs.

On mobile, **Show locations**, next to the breadcrumbs, reveals the tree.
Navigate using locations, directories and breadcrumbs. Providers without a
continuation cursor report that limitation; open an available
subdirectory to continue.

The `file://` root contains independent internal files owned by the selected agent
and attachments they can access. Each file appears once, even when it has several
references. Attachments retain their owning domain’s permissions; revoked access
takes effect on the next load. The console appears only when the agent
has an active SSH connection and stays inside its home directory. This page adds
no permissions and creates no persistent file copies.
