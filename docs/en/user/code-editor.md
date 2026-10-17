<p align="right"><a href="../../fr/user/code-editor.md">Français</a> · <strong>English</strong></p>

# Follow and edit a Git repository in a conversation

When an agent presents its repository with `repository_show`, the work pane displays
code-server, based on VS Code OSS. The pane alternates between a Document and a repository,
while the conversation stays usable. **Source code** lists previously presented
repositories so that you can reopen them after reconnecting. It sits directly below
**Documents** in the right sidebar.

Open this section to also discover repositories in the agent’s SSH home without asking the
agent to present them. Paths are relative to that home, such as `work/galaris`, without the
`console://` prefix. Click a path to link the repository to the discussion and open it in
VS Code. **Refresh repositories** runs discovery again. Discovery requires an active Console
owned by your account; previously authorized repositories remain accessible if discovery
fails or you do not own the Console.

Discovery recognizes both `.git` directories and worktree `.git` files. It skips hidden
directories, `node_modules`, `__pycache__` and symbolic links. The scan is limited to eight
subdirectory levels, 10,000 entries, 100 repositories and 20 seconds; a message reports partial
results or inaccessible folders. The checkout and permissions are rechecked when clicked.
An external Console needs the editor runtime configured before it can open a repository.

Clicking a `console://…/` folder card also opens the agent’s repository editor,
provided you have editor and repository access. The folder must belong
to a Git checkout. An unavailable editor or incompatible folder displays an error in
the conversation without opening an empty preview. Folders from other providers remain
references without a fullscreen preview.

The editor stays on the same address as Galaris; no other site or separate sign-in is needed.

Set the theme and preferences directly in VS Code, using its native profile.
Synchronization with Galaris is deferred to a later iteration. Changing the Galaris
theme preserves the editor window and drafts.

The editor opens the checkout used by the agent’s SSH Console, including uncommitted
changes. Opening it does not clone a repository. A `galaris://code/<uuid>` reference opens
the current checkout, rather than a historical snapshot.

With write access, save files, inspect changes and use the usual Git operations:
branches, staging, commit, fetch, pull, push and rebase. The integrated terminal provides
Git in an isolated environment. It reuses the agent’s Git configuration and SSH forge keys
accessible within its home; commits use that identity. The terminal does not reproduce
every service and tool of the SSH Console. VS Code’s native workspace trust remains enabled;
trust the folder in the editor to activate executable features.

Manage the file explorer, diffs and Git operations directly in VS Code. The Galaris pane
keeps the title, layout controls and **Hide editor**. Opening or reopening a repository
preserves the editor’s native view. An explicit agent presentation can select a file or
diff. VS Code may request workspace trust for Git operations; Galaris never grants it for you.

With read access only, repository files and Git metadata are mounted read only. Terminals and
extensions cannot write to the checkout. This session receives neither forge keys nor
network access. The agent retains its independent write access.

You and the agent share the same files and Git index. External changes and save conflicts
follow native VS Code behavior. Unsaved buffers and cursors are not shared. Inspect current
changes and coordinate in the conversation before switching branches, rebasing or committing.

**Hide editor**, opening a Document and changing conversations retain the iframe and its
tabs in the browser session. The browser may ask before
leaving while an editable session is open. Galaris does not promise to save IDE buffers
automatically.

Connection or access loss displays an error and retains the window. The server interrupts
revoked access; saves may then fail. Retained profiles allow native recovery after an
authorized reopening, within VS Code’s recovery limits. Sessions last at most 24 hours,
before explicit recovery, with a 10-minute idle lease. After expiry, **Retry** renews
access to the same profile, checking grants and repository identity again. If the IDE
process stopped, a recovery window opens in the pane. **Show previous window** keeps its
old drafts accessible: copy needed changes into the recovered editor, then save them.
After another restart, replacing only the recovery window requires confirmation;
save or copy its contents first. The original window remains retained.
The runtime accepts eight active IDEs
and retains up to 64 profiles. Stopped profiles do not consume active IDE slots.
Administrator maintenance can archive obsolete profiles and restore them when needed.

Source editing is supported in Chromium, Firefox and WebKit. Use Chromium or WebKit for
the native Markdown preview: Firefox preview is an accepted limitation of this first delivery.

The pane provides no sharing or session deletion controls. The Console owner and agent
receive repository access when it is registered; existing grants remain enforced. Humans
also need the Git repository access privilege. A link, conversation membership or agent
management alone does not grant repository access.

Messages sent while a loaded repository is displayed carry its URI and server-observed
branch/HEAD as context. File and selection are not transmitted because no reliable bridge
confirms them. Viewing a diff does not approve a commit or push.

Availability depends on [administrator configuration](../admin/code-editor.md), including
for external Consoles.
If opening reports that the editor is not configured for this external Console, a connection
manager can click **Deploy code editor** directly in the agent’s Console connection and save
that connection. Deployment checks SSH automatically. The conversation remains usable, and you can reopen the
repository after configuration.

If `repository_show` reports a permission refusal, also check that the agent’s Console
connection is active. Testing or deploying the editor preserves its saved activation state.

After initial deployment, managed editors on active SSH connections are checked and upgraded
when necessary during every Galaris update. No update button is needed. Save files and end
sessions before an upgrade: an open session, including a hidden one, blocks editor replacement.
