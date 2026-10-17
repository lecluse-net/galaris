# 0200 — Exclusive resource sharing configurations

Status: accepted

## Decision

`app.share` owns resource-independent sharing contracts, `share_configs`,
`share_grants`, principal selection, atomic grant replacement and SQL permission
evaluation. Its frontend owns the asynchronous sharing controller and public types.
Domains authorize their resource, supply its owner and retain business restrictions,
administrative recovery, notifications and transaction boundaries.

Each logical object has an exclusive `share_id`. Unique resource references and
composite foreign keys to `(share_configs.id, resource_kind)` prevent reuse within
and across resource types. A Document and its one-to-one Memory summary are the
same logical object: a composite identity FK requires their policy references to
agree. Independent documents, datasets and process definitions never share policies.

Owners remain on resources. Editing content does not confer sharing management.
Authenticated global access, explicit user/agent/team grants and historical live
owner-group access retain their existing meanings. Team membership is evaluated
at access time. Resource restrictions and source-derived Memory visibility remain
domain-owned; ordinary private memories do not become shareable through this change.

The Agent domain supplies principal identities and memberships through public
contracts. Share does not import a consumer domain, avoiding a dependency cycle.
HTTP and MCP operations remain resource-scoped; no endpoint accepts an arbitrary
policy identifier as authorization to inspect or mutate it.

## Upgrade and rollback evidence

The required DbAdmin action `app.share.resource_acls` backfills resource references,
including tombstones, and copies every principal and write flag. Configurations
receive deterministic upgrade identities. Each copied grant set is checked before
the resource points to it; the original ACL fingerprint is retained on the policy.
Missing references prevent the postcondition and final NOT NULL convergence.
Existing document and BPMN transfers initialize sharing in their own transaction
before consuming the new representation.

Legacy grant tables and global/group columns are retained as upgrade sources for
this additive release. Runtime sharing reads and writes use the common storage.
They must not be removed until migration and deployment evidence has been reviewed
in a later change. Replaying the transfer skips bound resources, preserving later
revocations and edits instead of restoring the historical grant snapshot.

Tests exercise exclusive references, read/write versus sharing management,
historical grants, replay, live membership and the existing domain journeys.
