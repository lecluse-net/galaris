<p align="right"><a href="../../fr/user/datasets.md">Français</a> · <strong>English</strong></p>

# Datasets

## Open the library and editor

**Knowledge → Datasets** contains independent `data://` JSON resources. Each has its own
title, owner, sharing and history. They do not appear in the Documents library, which holds
HTML content. Legacy Document links to migrated Datasets open the same Dataset editor
under current permissions.

Click a Dataset to open its editor in the page. On desktop, the tree and list stay on the left
and a draggable separator adjusts the two panes, as in Documents. The separator also supports
the left/right arrow keys. Tree items show only their fixed icon and name on one line.
On mobile, the editor fills the page. Return to the list through browser history or the
**Datasets** menu entry; search and pagination are preserved. Unsaved drafts require confirmation before switching Datasets or
leaving the editor. Chat Dataset cards continue to open a modal with full JSON, history and
authorized actions.

The browser's **Back** and **Forward** buttons return to visited Datasets and the list,
preserving its filters and pagination. This navigation also asks for confirmation when you
have an unsaved draft, including invalid JSON. **Cancel** keeps the current Dataset and
your input; **Discard changes** continues navigation.

The personal folder tree appears above the list, with an adjustable separator. These folders
are independent of Documents folders and belong to your account. Context menus create child
or sibling folders, rename and change icons, sort by name, expand/collapse branches and delete
them. **Show as a list** opens a folder's contents. Drag folders and Datasets to move them,
or use a Dataset's **Move to a folder** action. Deleting a branch preserves its Datasets and
returns them to your unclassified list.
The root contains only Datasets you explicitly place there. Use **Create a Dataset at the root**,
drop a Dataset beside the creation buttons, or select **Root** in **Move to a folder**.
This personal choice survives reloads. Other Datasets without a folder remain unclassified,
outside the tree. To remove a root placement, drop the Dataset into the list area or select
**Unclassified** in **Move to a folder**. General creation also leaves Datasets unclassified.

The list shows **Unclassified** Datasets by default. **Filters** can disable this restriction,
select a user or agent owner, a keyword, creation/modification dates and manual, title or date
sorting in either direction. Search covers titles and JSON. Pagination defaults to 50 items,
with 10, 20, 50, 100 or 500 available.

## Create and edit JSON

An agent can rename a Dataset with `file_rename`, after reading `file_info` and its
`lock_version`. Only the title changes: the `data://` URI, JSON, content history,
attachments and permissions remain unchanged. A concurrent rename requires rereading
metadata. Write access is required; a read-only Dataset cannot be renamed.

The editor has three tabs: **Content**, **History** and **Usages**.
In **Content**, the JSON editor fills the available height to the bottom of the view.
Switching tabs preserves your draft, including invalid JSON.

Create a Dataset from this library. Content can be an object, array or scalar without an
associated schema. Use a root array `[]` to collect successive additions. An agent uses
`file_create(path="data://", name="Responses", content="[]")` and retains the returned URI.
Complete JSON is required; replacing its scheme with `document://` does not create a valid reference.

JSON is indented on opening and in history without changing exact values or saving an edit.
Invalid JSON or a revision conflict preserves your draft; retain the edits you need before
reloading. Agent reads provide line coordinates, the revision and partial-line boundaries
before `file_edit`. Reading and restoring old revisions still checks permissions and
revisions; a restore does not reinstate historical sharing.

## Ownership and sharing

**Owner** and **Sharing** sit on the same row. The owner or an authorized administrator can
transfer the Dataset to a managed agent or themselves; a Dataset administrator may also choose
another active user. Transfer is immediate, preserves the draft and history, and keeps the
former owner as an editor. Read-only Datasets cannot be transferred.

Sharing follows Document rules: private, teams or public for authenticated users, with agent,
user or team recipients and read or write access. Only the owner or an authorized administrator
may reshare; write access alone is insufficient. Teams follow current membership. Read-only
resources cannot be reshared. Documents, Datasets and Processes retain independent permissions;
see the [sharing mechanism](../dev/sharing.md).

## Cite and use data

In a Document, **Insert a link or file → Add an internal attachment** opens the resource picker.
Choose `data://`, then the Datasets: these become citations without copied JSON or additional
attachments. Pasting a `data://` URI or this installation's `/dataset/…` link also lets you
choose **Show card**. Its title opens the Dataset modal without leaving the Document.
Removing a citation does not delete data; sharing the page does not share cited Datasets.

HTML/JavaScript applications can read and update Datasets through the Dataset bridge, using
the viewer's permissions and personal consent for the page's current revision. Share page and
data separately. See [document applications](../dev/document-apps.md). Referencing data does
not automatically update previously authored prose.

## Inspect usages and delete

**Usages** lists Documents referencing the Dataset, Process definitions and runs mentioning
it, and agents whose retained tool traces contain its URI. Each category respects your rights
on source objects. Dynamically constructed URIs and purged history may be missing; a mention
does not prove successful access.

**Delete** asks for confirmation and removes access. History remains retained.
Memory projections of migrated Datasets are erased with their content and indexes.
Memory items linked only to this Dataset or its attachments are also deleted. Existing
references may become unavailable. Old Datasets created for Processes follow the same
permissions. Current Processes keep data and files in their own runs rather than creating
a Dataset for execution state. Before a workflow launch, the agent collects missing inputs
and prepares the required variables; Process validates them and preserves authorized file URIs.
