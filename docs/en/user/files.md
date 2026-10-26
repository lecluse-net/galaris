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
their virtual filesystem: SSH console, documents, datasets, Galaris resources and
connected providers. It respects the agents you can manage and each resource’s own
access rules.

When no location is selected, the central grid displays available schemes as folders.
Click one to open its root, then a directory in the tree or the central grid. Use the breadcrumbs
or parent directory button to go back up. Files have a thumbnail when their format
can be rendered and an icon otherwise. Click a file to preview it, or a Document,
Task, Dataset or conversation to open its existing domain view. Formats without an
integrated viewer are downloaded.

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
