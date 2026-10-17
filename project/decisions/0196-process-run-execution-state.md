# ADR 0196 — Process execution state belongs to its run

Date: 2026-10-17

Status: accepted

Updated by [ADR 0198](0198-process-run-data-and-files.md): business data and file
links also belong to the run; Dataset is no longer involved.

## Decision

Technical execution state is owned by the corresponding `ProcessRun` and stored in
`process_runs`. Integration and input-file preparation receipts use its private
JSONB `execution_state` column. They are neither
Dataset contents nor Dataset metadata, and are not exposed through business data reads.

Process performs workflow-specific merging. It locks the run before its Dataset,
validates conflicts against the activity baseline, and commits functional changes and
the run receipt in one transaction. Duplicate commands with the same result reuse
the receipt; a changed result is rejected. New writes after cancellation or a terminal
result are rejected. Completed receipts remain readable for idempotent recovery.

Input-file publication and its run receipt share the same database transaction. Stable
file identities bound retries after rollback; a reused receipt avoids downloading or
publishing the same input again. Independent runs and child runs own independent receipts.

Dataset continues to own functional JSON, resource revisions, attachments and access
policies. Existing engine ownership and write-protection policies remain resource
metadata; they are not execution checkpoints. Whether Dataset should continue to hold
process business data remains an open product decision.

## Deployment scope

Internal processes have never been deployed. The target schema directly stores
execution receipts on the run: there is no Dataset integration table, receipt transfer
action, historical checkpoint adapter or staged compatibility mechanism.
