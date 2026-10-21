# 0212 — Direct Topic associations for Documents and Datasets

Date: 2026-10-21

## Context

Topic graph links can expose related Documents, but Documents and native JSON Datasets
also need a single optional thematic classification independent of graph projections.

## Decision

Add an indexed nullable UUID foreign key to `topics.id` in `documents` and `datasets`.
Memory and Dataset own their association queries and writes behind public facades. Dream
registers separate document and Dataset mechanisms using the existing Topic classifier,
candidate validation, creation policy, checkpoints and retries. Resources without a
conversation reuse existing Topics in `propose`/`forbid` mode; `auto` may create a Topic.

Receipts include the resource version. Application compares that version and requires an
unassigned, active resource, preserving concurrent edits and content revisions. A successful
no-op does not rescan an unchanged resource. Topic retirement serializes with assignments;
merging moves references and deleting clears them, including references on deleted resources.

Topic summaries and details combine direct Documents with existing graph Documents, without
duplicates, and list native Datasets separately. HTTP projections apply current resource ACLs.
These narrowly scoped integrations add `app.dataset` as a dependency of Topic and Dream;
they introduce no private import or new coupling-debt baseline entry.

The resource editors reuse the Chat Topic badge and its assignment modal next to the UUID.
Topic owns the HTTP composition endpoint and validates the target; Memory and Dataset retain
resource ACL checks and mutation logic behind their facades. Changes compare both the current
Topic and metadata lock version, preserve content revisions and record a protected manual
assignment marker so an older Dream receipt cannot override its provenance. The editors merge
only the returned Topic and lock version, preserving unsaved HTML or invalid JSON drafts.
As with resource detail dialogs, an application composition provider loads the shared Topic
badge and command outside domain dependency graphs. Core only exposes the loading port;
the editors acquire no direct dependency on Topic and the coupling baseline stays unchanged.

## Verification

`app/dream/tests/test_resource_topics.py` exercises persisted checkpoint replay, content
preservation, creation modes, changed/deleted/already assigned sources, access filtering,
merging and deletion. `front/browser-tests/topic-detail.spec.mjs` opens both resource kinds
from Topic details on desktop and mobile while preserving the Topic route.
