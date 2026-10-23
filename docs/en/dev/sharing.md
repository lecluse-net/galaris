<p align="right"><a href="../../fr/dev/sharing.md">Français</a> · <strong>English</strong></p>

# Resource sharing

`app.share` owns `share_configs`, `share_grants` and the public sharing contracts.
Documents, Dataset and Process authorize the business object before calling its
facade. Ownership, read-only restrictions, source policies and administrative
privileges remain domain-owned. Write access does not allow resharing.

Each logical object has an exclusive `share_id`. Unique, typed references prevent
policy reuse by another object. A Document and its Memory summary share the same
logical identity, enforced by a composite foreign key, and must therefore retain
the same policy. Ordinary memories remain private; attachments continue to follow
their parent's access.

The Agent domain supplies the principal directory and team memberships. Lists
filter permissions in SQL before counting and pagination. Cached decisions never
replace current membership and revocation checks.

The `app/share` frontend also owns `SharingPanel`, its recipient selector and
presentation types, moved from `core.util`. It exposes `ResourceSharingPanel`,
`SharingState` and `SharingUpdate`. Its controller receives domain reader and writer functions and
knows no document endpoints. The remaining Memory component is a compatibility
adapter around its own services.

## Upgrading existing installations

The required `app.share.resource_acls` DbAdmin action copies existing permissions
and backfills references, including soft-deleted resources. It preserves users,
agents, teams, global access and historical live owner-team access. Each copy is
verified before attaching its resource. Replays preserve subsequent changes,
including revocations.

Legacy grant tables and access columns remain as migration sources without
business writes. Their removal belongs to a later release after migration review.
Use `make sync-db` in development; production continues to use `make update`.

See [decision 0200](../../../project/decisions/0200-exclusive-resource-sharing.md).

## Migration and concurrency checks

DbAdmin tests reconstruct a historical schema populated with 484 logical objects
and 1,089 synthetic grants, covering three principal kinds, global and owner-group
access, and tombstones. They verify every right and unchanged source data, then
replay the upgrade. An interruption after DDL proves transfer rollback and recovery
from the durable action journal.

Concurrency tests use separate PostgreSQL connections and wait for an actual lock:
one replacement wins, stale versions cannot restore revoked access, and independent
resources remain editable. Document and Process E2E journeys use an owner and a
recipient without administrator privileges. They cover reading, editing, denial
of resharing, reloading, reopening and revocation.

These fixtures are entirely synthetic; they are neither a production copy nor a
migration duration estimate for a real installation.

## Document inheritance across personal classifications

Memory stores authoritative own ACLs in `document_sharing_intents`. Common configurations
and grants remain the effective projection used by SQL admission, agents, lists and exports.
Existing ACLs become own intent on first reconciliation; inherited results never become
sources during replay.

Edges from `document_tags`, `document_tag_assignments` and `document_nesting` add every
ancestor's permissions. Only the human owner's classification, or that of the owning agent's
manager, can transmit permissions to a document whose sharing they can manage. Filing a
received document, even with edit access, cannot reshare it. Trees stay private even when
folder policies grant public access. Dataset and Process policies remain independent.

The additive closure starts exclusively from own rights and takes the maximum read/edit
permission. It also terminates on legacy cyclic graphs. Sharing and placement changes rebuild
the projection in the business transaction under a common advisory lock. Deletions and
ownership transfers recalculate contributions that no longer apply. The required
`app.memory.sharing_inheritance` reconciler runs after document structure, repairing the
complete projection on every DbAdmin synchronization and `make update`. A replay without
drift changes neither rights nor versions. The F4 form reuses the common sharing component;
saving unchanged effective rights does not turn them into own grants.

See [decision 0218](../../../project/decisions/0218-personal-tree-sharing-inheritance.md).
