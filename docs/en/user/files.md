<p align="right"><a href="../../fr/user/files.md">Français</a> · <strong>English</strong></p>

# Browse an agent’s files

In **Knowledge → Files**, click an agent card to open their browser. Use the selector
to change agents without clearing the current selection. The counter to its right shows
the items loaded in the current directory. The tree presents the known schemes of
their virtual filesystem: SSH console, documents, datasets, Galaris resources and
connected providers. It respects the agents you can manage and each resource’s own
access rules.

Open a root and then a directory in the tree or the central grid. Use the breadcrumbs
or parent directory button to go back up. Files have a thumbnail when their format
can be rendered and an icon otherwise. Click a file to preview it, or a Document,
Task, Dataset or conversation to open its existing domain view. Formats without an
integrated viewer are downloaded.

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
whose names start with a dot are omitted. All known schemes are displayed, including
HTTPS. A message explains when a scheme supports URI access without a root listing.

On mobile, **Show locations**, next to the breadcrumbs, reveals the tree.
Navigate using locations, directories and breadcrumbs. Providers without a root
listing or a continuation cursor report that limitation; open an available
subdirectory to continue.

The `file://` root contains independent internal files owned by the selected agent
and attachments they can access. Each file appears once, even when it has several
references. Attachments retain their owning domain’s permissions; revoked access
takes effect on the next load. The console appears only when the agent
has an active SSH connection and stays inside its home directory. This page adds
no permissions and creates no persistent file copies.
