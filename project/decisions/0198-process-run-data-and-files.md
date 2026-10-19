# ADR 0198 — Run data and files belong to Process

Date: 2026-10-17

Status: accepted

## Decision

`process_runs.data` stores the run's current business variables as JSONB.
`data_revision` protects direct writes against lost updates. `process_run_files`
links a run to managed files through `file_id` (FK to `files.id`) or an exact
external provider URI. Managed bytes remain in `core.storage`. There is no
Dataset, Document, independent resource sharing policy or new privilege for run data.

The parent Process's existing read/edit policy governs its runs, data and
attachments. Sharing or revoking access to the Process takes effect immediately,
including existing runs, children and inclusive metrics. The existing dedicated
`process_admin` capability remains available. Execution participant snapshots
describe assignments; they do not grant an independent run ACL.

Process locks the run and commits variable changes, file links and execution
receipts together. Disjoint changes merge; overlapping changes conflict.
Duplicate integration commands reuse their receipt; a different result conflicts.
Cancellation and terminal states prevent new writes. Typed activities publish
validated outputs through the engine. Historical v1 activities can edit run JSON
with an expected revision. Each child owns its own data and file links.

`galaris://processes/runs/<uuid>` remains the read-only execution projection.
`galaris://processes/runs/<uuid>/data` addresses business JSON and
`galaris://processes/runs/<uuid>/attachments/` lists its files. Their provider delegates
authorization to Process. External file links retain their provider's access checks.
Deleting a run retires its managed attachment references.

Runs use the existing `galaris` scheme under `processes/runs/`; no separate
Process URI scheme is advertised or accepted.

## Scope

This supersedes Dataset ownership in ADR 0174 and ADR 0196, and the independent
run participation policy in ADR 0193. Internal processes have never been deployed;
the target schema changes directly, without a historical run-Dataset adapter or
data transfer action. Dataset remains available for independent JSON resources
and the shared typed value codec.

The retired run-Dataset runtime policy is removed from Dataset and its Memory adapters.
Historical engine metadata is inert: former run Datasets use ordinary Dataset permissions
for content, files, ownership and logical deletion. Their metadata and revision history
are preserved; no automatic deletion or transfer into runs is introduced.

## Verification

The existing Process integration scenarios cover execution, child forwarding,
conflicts, cancellation and recovery. `test_run_execution_state.py` verifies
transaction rollback, file receipts, terminal immutability, the absence of Dataset
or Document creation, and inherited/revoked Process access to JSON and managed bytes.
