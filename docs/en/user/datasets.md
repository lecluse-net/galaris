<p align="right"><a href="../../fr/user/datasets.md">Français</a> · <strong>English</strong></p>

# Data documents

## Create and find data

Open **Knowledge → Documents**. Click a **New document** icon to open the choice below it between **Text**
and **Data**. Choose Data, enter a title and owner, then edit your JSON. Document and
folder context menus offer the same creation in the selected classification. Closing
the choice creates no document.

The **Document type → Data** filter finds JSON documents in the common library. Folders,
personal classification and pagination are shared with Documents. The Data icon identifies
the type; an adapted preview may replace its fallback image. Existing `data://` and
`/dataset/:id` links open the same content under current permissions.

## Edit and share

The JSON editor accepts objects, arrays and scalar values without an imposed schema.
Valid JSON saves automatically. Invalid drafts remain visible and never replace saved
content; navigation checks whether the draft has saved. Concurrent edits require a
fresh read and preserve the draft.

If you use browser **Back** from the document dialog with invalid JSON, choose
**Cancel** to stay and correct it, or **Discard** to restore the last saved content
and leave. Cancel receives initial focus; dismissing confirmation preserves the draft.

Title, owner, Topic, sharing, keywords, summary and history use the common commands.
Sharing can target people, agents or teams; permission to edit JSON does not confer
permission to reshare it. A reference from Text grants no access to its Data target.
A shared folder can grant additional rights to documents you classify there.

## History and summary

Each content edit creates a version. History lets you inspect an old JSON version and
restore it as a new version. Current title, rights, owner, summary and keywords survive
restoration. Saved JSON retains its exact content, including numbers and line endings.

The **View summary** icon refreshes the current summary without showing keywords.
With edit rights, you can edit, save or regenerate it after confirmation, as for a
[Text document](documents.md). Errors and conflicts preserve
your draft. Existing descriptions are retained. Dream can fill a missing description
above 1,000 normalized JSON characters and refresh an automatic description after at least
100 changed characters since the last generation. History groups saves after five minutes
without content edits; Dream also waits for this stabilization. Both thresholds are configurable;
manual descriptions are preserved.

## Use data with an agent or a page

An agent can find a Data document, filter and sort rows, and calculate totals on the
server without copying the complete JSON into the conversation. Results identify the
version read and distinguish missing, null and incompatible values. Units must be explicit;
a change between pages requires a new read. Semantic discovery depends on the vector
model and Dream indexing.

An HTML application inside a Text document retains personal consent to access Data.
That consent depends on the page revision, does not replace sharing and can be revoked.
Writes use the shared server-side quota: at most 2,000,000 UTF-8 bytes per resulting
JSON content, then 30 writes and 4,000,000 resulting bytes per minute per user–Data pair,
across documents and tabs. A successful write lets the form continue working; access
changes and revocation still apply to subsequent calls. Business process definitions
remain in Process; they are not Data documents.
