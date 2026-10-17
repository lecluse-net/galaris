<p align="right"><a href="../../fr/user/datasets.md">Français</a> · <strong>English</strong></p>

# Datasets

Open **Knowledge → Datasets** to create JSON data. Datasets belong to this dedicated
library and no longer appear in the Documents library or its creation dialog.
An old Document link to a Dataset now opens its dedicated editor. An HTML Document can
read its values for display or computation with the viewer's permissions and consent.
**Attach a Dataset** in a Document adds a live attachment. The Dataset retains its own
URI, history and sharing. **Detach** removes the link without deleting data; sharing the
Document does not share its Datasets. Unavailable attachments no longer reveal their title.
Each Dataset has its own `data://`
address, sharing and revision history. Content can be an object, array or scalar value,
without an associated schema. Invalid JSON and conflicts preserve your local draft;
keep any edits you need before reloading.

Create new Datasets here, separately from HTML Documents. An agent uses
`file_create(path="data://", name="Responses", content="[]")` and retains the returned URI.
Complete JSON content is required; replacing the returned URI's scheme with `document://`
does not create a valid reference.

On desktop, select a Dataset in the flat list on the left to open its editor on the right.
Search and the current page remain in place when switching Datasets. On small screens,
use **Back to list** to leave the editor. Unsaved changes require confirmation before
switching Datasets.

The editor's **Sharing** uses the same rules as Documents: private, groups or public for
authenticated users, with read or write grants for agents, users and groups. Only the
owner or an authorized administrator can change sharing; write access does not grant
resharing rights. Groups follow current membership. Read-only Datasets cannot be reshared.

**Usages** lists documents containing the reference, process definitions and runs that
reference it, and agents whose retained tool traces mention its URI. Each category respects
your permissions on its sources. Dynamically constructed URIs and purged history may be
missing; a mention in a trace does not establish successful access.

**Delete** requires confirmation and removes access to the Dataset. Historical content is
retained; existing references may become unavailable. Engine-managed process Datasets
follow their own lifecycle.

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
