# ADR 0187 — Dataset domain and typed JSON contracts

- Status: Accepted
- Date: 2026-10-15
- Supersedes the ownership of structured data in ADR 0124/0125; preserves their HTML consent guarantees.

`app.dataset` owns typed values, Dataset content, revisions and permissions.
`app.process` consumes its codec through a compatibility
surface. Process v1/v2 keep their frozen profiles; the explicit `Dataset` reference
belongs to the shared codec and is not silently admitted to Process v2.

A Dataset has an independent UUID and `data://<uuid>` URI. Its source remains exact
UTF-8 JSON, including scalar and array roots. Datasets have no associated schema,
schema library or structural constraint on writes and restores. Process variables carry
`{type, value}`, recursively for arrays and objects. Missing nullable variables
normalize to typed null; a declared default takes precedence. Explicit null never
invokes a default and is rejected for a non-nullable variable.

The codec supports int, float, string, bool, Agent, User, File, Document, Dataset,
array and object. File values remain authorized File Sharing URIs. Dataset never
introduces another binary store: native attachments use `core.storage` and external
attachments retain their provider URI. Type validation grants no resource access.

Legacy Dataset documents are transferred additively by a resumable DbAdmin action.
UUIDs, exact content, revisions, ACLs, attachments, personal classification, consents
and budgets are retained. Original rows and files remain as migration evidence;
legacy entry points delegate to Dataset and metadata/ACL projections keep historical
Process consumers working. Only a verified alias may resolve a `document://` URI
to `data://`. No blanket replacement occurs inside business JSON or HTML.

HTML applications retain personal consent bound to the exact document revision and
binding. Old and new Dataset URIs share the Dataset authority and the same persistent
user/Dataset write budget. These applications collect structured input through the
existing Dataset bridge. For business processes, agents gather missing information and
prepare the expected typed variables; Process validates them at its execution boundary.

The additive compatibility phase retains Process's legacy document foreign key.
Removing those projections remains a separate compatibility step.

Dataset sharing uses the Document level/grant contract, the same recipient directory and
the shared frontend permission picker. Its owning domain applies atomic replacement,
version checks and live ACLs. Editors cannot reshare; read-only resources retain that guard.
Dataset administrators use the corresponding administration privilege.

Usage discovery is composed through registered public domain queries. Memory owns current
Document references, Process owns run references, and LLM owns retained agent tool-trace
observations. Source ACLs and module privileges filter both records and counts. Dynamic
references and purged history are outside this evidence; a trace mention does not prove a
successful access. Dataset gains no reverse dependency on its Process or LLM consumers.
Deletion is logical and preserves revisions, while engine-managed data retains its owner.

The compatibility writer consumes the explicit `DatasetDocumentProjection` contract owned
by Memory. Dataset builds this metadata/grant snapshot directly from its records rather
than serializing its HTTP response. Native Datasets create no Memory projection; only verified
legacy aliases participate. A retirement signal removes the historical item from current
readers without deleting migration evidence. Its state is read asynchronously, including
soft-deleted records, rather than loading an expired ORM timestamp implicitly.

The retirement criteria are maintained in `docs/fr/dev/datasets.md` and its English peer:
migrated consumers, contracted Process foreign keys, and canonical content/history/ACL,
attachment, consent and budget journeys. Verified old-reference aliases have a separate
compatibility lifetime and must not be removed together with metadata projections by default.

## Architecture review

The reviewed static graph adds Dataset to the existing application component that
already contains Agent, Process, Memory, Tools and File Sharing. Process imports the
lightweight public value codec; loading that surface does not load Dataset services
or models. Dataset consumes the public Agent, Memory and File Sharing surfaces.
Memory and File Sharing delegate through registered ports and do not import Dataset.
This review admits that bounded component expansion during additive compatibility;
it does not admit private imports or additional domain dependencies. The frontend
adds only Dataset's Core dependencies and Process's public Dataset contract import.
