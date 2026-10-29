# 0251 — Dream learns through personal skill packages

- Date: 2026-10-29
- Status: accepted and implemented
- Supersedes the separate procedure storage and injection in ADR 0047 and the learned/personal separation in ADR 0222.

## Decision

A procedure learned by Dream is a normal personal `Skill` owned by its agent. Its canonical
content lives in the personal package's `SKILL.md`; Dream, the human editor, MCP and every
Harness consume the same package identity, revision, files and ownership policy. There is
no separate learned catalogue, Markdown column, runtime capability builder or `.learned`
projection. The former learned-tab link opens personal skills.

Learning augments `skills` with provenance and scoring fields. `skill_learning_evidences`
contains auditable positive and negative observations linked to the package; it does not
own procedure content. The existing mode, evidence threshold, score threshold and active cap
remain. Candidates are visible and editable in the personal catalogue before becoming usable.
Normal manually authored packages retain their explicit activation policy. Reinforcement
never reactivates a disabled package. Automatic edits require the revision observed before
inference, so late decisions preserve concurrent human edits. The personal management scope,
package quotas and normal file/DB rollback handling also apply to Dream writes.

A Task contributes at most one positive confirmation to a procedure. Late evidence can still
revise or weaken it; replaying an identical evidence fingerprint has no additional effect.
Dream may consult and improve an existing manually authored personal package without changing
its explicit activation policy. A deleted, transferred or published target is not recreated by
a late targeted decision.

## Upgrade and recovery

A required DbAdmin `AFTER_EXPAND` action transfers historical procedures and evidence into
personal packages before Atlas can remove the legacy tables. The original UUID is retained
as `learning_key`, including for already checkpointed reinforcement/weakening decisions.
An old checkpointed revision without an observed package revision is skipped safely.
The transfer preserves scores, evidence, revisions, audit metadata, deleted state and suspension
(as personal deactivation). Same-owner code collisions allocate a deterministic distinct code;
existing package bytes are never overwritten. Interrupted file installations can be replayed
only when the existing bytes match the source.

The postcondition checks canonical file bytes, owner, scoring metadata, activation and every
evidence field. Failure retains the source tables and prevents contraction. No production
intervention is part of this change.

## Verification

DB integration covers personal creation, owner isolation, candidate gating, one runtime path,
manual edits, deactivation, idempotency, distinct Task confirmations and injected commit failures.
Upgrade integration covers collisions, suspended procedures and file-storage failures; a disposable
PostgreSQL clone exercises real DbAdmin/Atlas contraction and retry. Existing skill, HTTP, MCP,
Harness and browser journeys retain their guarantees. The old tests asserting a third runtime
collection or DB-owned learned Markdown are replaced by personal package coverage.

The upgrade fixture retains the historical named constraints and starts without the destination
table or columns. This catches schema-global index-name collisions during expansion; new evidence
constraints use distinct names while both source and destination coexist. A fixture lacking those
constraints initially missed this failure, which local development synchronization exposed.
