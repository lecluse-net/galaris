<p align="right"><a href="../../fr/dev/document-apps.md">Français</a> · <strong>English</strong></p>

# Forms and JavaScript in documents

Printing, PDF export, mobile PDF sharing and HTML archives preserve the current rendering:
field values, calculated results, styles, SVG and canvas images. They capture the open page
without rerunning its code or performing another Dataset write. The copy is static and
sanitized before export; an unavailable capture reports an error instead of replacing the
content with a launch instruction. Layout is recalculated at the printable width, using the
document's responsive CSS rules, independently of the editor panel width. This preparation
uses a copy without scripts and does not resize the open document. A capture is cancelled
when its document changes.

HTML documents accept ordinary forms, CSS and JavaScript directly. Agents write HTML;
no application manifest is required. The existing CKEditor toolbar stays visible and
surrounding prose remains editable. There is no additional read/edit mode, start button
or form builder. The existing **Source** button is the code editor.

Forms appear in place and their controls work normally. Script-driven areas are not edited
through WYSIWYG. Saved code runs when the document opens. Entering Source, changing the
document or leaving it stops the runtime; rendering resumes after a valid save.
Existing `language-galaris-app` manifests remain compatible without showing their JSON.
Use ordinary HTML for new documents.

## Shared Dataset example

Create a Dataset containing `[]` with `file_create(path="document://", name="Responses",
document_type="dataset", content="[]")`, then use its actual URI:

```html
<p>Prose editable through the usual toolbar.</p>
<form id="entry" data-dataset="document://11111111-1111-4111-8111-111111111111">
  <label>Answer <input name="answer" required></label>
  <button>Save</button>
  <output id="status"></output>
</form>
<style>form { display: flex; gap: 1rem; flex-wrap: wrap; }</style>
<script>
document.getElementById('entry').onsubmit = async event => {
  event.preventDefault();
  const button = event.target.querySelector('button');
  button.disabled = true;
  try {
    const current = await galaris.datasets.read('entries');
    await galaris.datasets.append('entries', {
      answer: new FormData(event.target).get('answer')
    }, current.revision);
    document.getElementById('status').textContent = 'Saved';
    event.target.reset();
  } catch (error) {
    document.getElementById('status').textContent = error.message;
  } finally { button.disabled = false; }
};
</script>
```

`data-dataset` declares a resource. `data-dataset-alias` selects its alias (default `entries`).
`data-dataset-access` defaults to `write` for forms and `read` for other elements; an explicit
value takes precedence. Up to ten bindings with different aliases are supported; conflicting
declarations are rejected.

`file_create`, `file_write`, `file_edit` and `file_append` accept this HTML. Read before
editing and provide the expected revision. Share the document and each Dataset separately
using `memory_sharing` and `document_share`; a link grants no access. Document types remain
immutable. Other editorial fields (Memory, Goal, Agent) keep their static profile and reject
scripts.

## SDK and guarantees

`galaris.datasets.read(alias)` returns `{data, revision}`. `append(alias, value, revision)`
adds one JSON value to a root array; `replace(alias, value, revision)` replaces its content.
Both mutations return the new snapshot and preserve normal Dataset history. Multiple pages
can use the same Dataset. Execution uses the current viewer's permissions, never the author's.
A binding grants no privilege.

A stale revision yields `error.code === 'conflict'`. Preserve input and reread before another
submission. Writes are never automatically retried. Other errors use `permission_required`, `denied`, `failed` or
`limit`. The server checks persisted bindings, current page and Dataset access, and locks rows
before mutations. Closing a page discards pending requests and late responses; committed writes
remain durable. Direct HTML uses the technical identifier `document-html` on the existing
`/memory/documents/{id}/apps/{app}/datasets/{alias}` route.

## Isolation and limits

Two opaque iframes isolate code from the parent DOM, cookies, Galaris storage, popups and parent
navigation. This is internal: no visual frame, application heading or extra button is added.
Editorial prose stays in CKEditor; its model preserves interactive content opaquely and restores
ordinary HTML in Source and saved content. Interactive regions sharing scripts run in the same
isolated context.

CSP blocks ordinary network loads, native form submissions, workers and nested frames. Bundle
dependencies and use JavaScript for forms. No session token reaches the document code; a bounded
bridge exposes only declared Dataset operations. Generic previews, history and exports remain
inert and hide executable source, which remains available for editing and restoration.

Opening a document executes its code: share trusted code only, especially when it accesses
sensitive data. CSP is not a universal firewall for browser APIs. WebRTC constructors are made
unavailable before application code, without allowing redefinition in that context. The
sandbox does not bound CPU use. Documents and Datasets are each limited to 2,000,000 bytes.
See [decision 0125](../../../project/decisions/0125-document-applications.md).

Blob URLs created by code are limited to passive MIME types: `image/png`, `image/jpeg`,
`image/gif`, `image/webp`, `audio/mpeg`, `audio/ogg`, `audio/wav`, `audio/webm`, `video/mp4`,
`video/webm` and `video/ogg`. HTML, SVG and untyped blobs are rejected: navigating to executable
Blob content could otherwise create a fresh realm before the parent stops it.

## Personal consent and server quotas

Dataset access is denied by default, including existing documents. Each reader approves
application–Dataset bindings through the document toolbar's **Application permissions** icon.
Consent is stored in the database, outside generated HTML, for that user, app, alias, Dataset
and exact document revision. It does not transfer to another reader or document. Any content
edit or restore requires new consent; title-only changes do not change the content revision.
Current page and Dataset ACLs are still checked on every call. Revocation blocks future calls;
committed writes remain durable and data already read cannot be taken back from the code.

Human routes `GET /memory/documents/{id}/app-permissions` and
`PUT /memory/documents/{id}/app-permissions/{app}/{alias}` manage consent using
`{document_revision, access: null | "read" | "write"}`. Neither the SDK nor MCP exposes these
routes. Write consent also requires the human edit privilege. Code still displays automatically;
only Dataset operations require consent. Missing consent produces `permission_required`.
`write` still allows **append and full replacement**, including at page opening: review allowed
sources and destinations together, because code can transfer data between approved Datasets.

Application writes validate incoming JSON and the complete result: finite numbers, maximum
depth 32, at most 20,000 JSON nodes and 2,000,000 serialized UTF-8 bytes. These are structural
bounds, not a business validation schema. A persistent transactional budget limits each
user–Dataset pair to 30 writes and 4,000,000 resulting content bytes per 60-second window.
Documents, tabs and workers share it; reloads and renewed consent do not reset it. No-op writes
also consume quota. HTTP 429 includes `Retry-After: 60` and becomes `error.code === 'limit'`.
Wait and reread before submitting again. Invalid data and conflicts alter neither the Dataset
nor its successful write budget.

Captured export HTML remains untrusted. Sanitization and URL removal operate on DOMPurify's
inert tree before loading the script-free layout frame. Adversarial tests cover external
resources, injected code, WebRTC, bridge saturation, unapproved cross-Dataset copies, revocation
and quotas across workers. They do not guarantee protection from every browser flaw or
CPU/memory exhaustion attack.
