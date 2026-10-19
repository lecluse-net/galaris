<p align="right"><a href="../../fr/user/datasets.md">Français</a> · <strong>English</strong></p>

# Datasets

Open **Knowledge → Datasets** to create JSON data. Datasets belong to this dedicated
library and no longer appear in the Documents library or its creation dialog.
An old Document link to a Dataset now opens its dedicated editor. An HTML Document can
read its values for display or computation with the viewer's permissions and consent.
In the toolbar, **Insert a link or file** then **Add an internal attachment** opens the
file_share picker: choose `data://` and select the Datasets. Citations are inserted in the
text without adding attachments. Each Dataset retains its own URI, history and sharing.
Removing a citation does not delete data; sharing the Document does not share its Datasets.
Click a Dataset to open its editor in a modal on desktop or mobile. Close it with the cross,
Escape or the backdrop to return to the list with its search and page preserved. Unsaved
changes require confirmation before closing. Dataset cards in chat open the same dedicated
modal with complete JSON content, history and available permissions.
In a document, paste a `data://` address or this installation’s `/dataset/…` URL, then choose
**Show card** in the link’s context menu. Clicking the card title opens the Dataset modal
without leaving the document. The JSON stays in the Dataset; the document stores its reference.
Each Dataset has its own `data://`
address, sharing and revision history. Content can be an object, array or scalar value,
without an associated schema. Invalid JSON and conflicts preserve your local draft;
keep any edits you need before reloading.
JSON is indented when opened and in revision history. This display preserves exact values
and does not save a change by itself.

**Owner** and **Sharing** appear on the same row. The owner or an authorized administrator
can transfer the Dataset to an agent they manage or to themselves; Dataset administrators
can also select another active user. Transfers take effect immediately, preserve the draft
and history, and keep the former owner as an editor. Read-only Datasets cannot be transferred.

Create new Datasets here, separately from HTML Documents. An agent uses
`file_create(path="data://", name="Responses", content="[]")` and retains the returned URI.
Complete JSON content is required; replacing the returned URI's scheme with `document://`
does not create a valid reference.

When an agent updates part of the JSON, reads provide line coordinates for editing,
the required revision and flags identifying partial lines to complete before replacement.

On desktop, select a Dataset in the flat list on the left to open its editor on the right.
Search and the current page remain in place when switching Datasets. On small screens,
use **Back to list** to leave the editor. Unsaved changes require confirmation before
switching Datasets.
The **Owner agent** filter limits the list to Datasets owned by a managed agent.
**All agents** restores all accessible Datasets, including user-owned ones. Search and
pagination apply to the filtered results.

The editor's **Sharing** uses the same rules as Documents: private, groups or public for
authenticated users, with read or write grants for agents, users and groups. Only the
owner or an authorized administrator can change sharing; write access does not grant
resharing rights. Groups follow current membership. Read-only Datasets cannot be reshared.

**Usages** lists documents containing the reference, process definitions and runs that
reference it, and agents whose retained tool traces mention its URI. Each category respects
your permissions on its sources. Dynamically constructed URIs and purged history may be
missing; a mention in a trace does not establish successful access.

**Delete** requires confirmation and removes access to the Dataset. Historical content is
retained; existing references may become unavailable. Former process Datasets follow the
same deletion permissions. Current run data and files are stored in Process runs and remain independent.

Old document links for migrated Datasets continue to address the same data. Changes and
sharing revocations apply through both addresses.

HTML/JavaScript applications in Documents can read and populate these resources through
the Dataset bridge, using your permissions and personal consent for the current Document
revision. Share the page and its Datasets separately. See
[document applications](../dev/document-apps.md).

For a business process, the agent gathers missing information and prepares the variables
in the format expected by that process. The engine validates them before execution.
Attachments retain their authorized file URIs.

Each Document, Dataset and process definition retains independent sharing. Changing access to one resource does not change access to another linked resource. Upgrades preserve existing permissions, including team access. See the [sharing mechanism](../dev/sharing.md).
