# 0213 — Galaris ownership of managed Hermes API runs

Accepted on 2026-10-21. Extends [0153](0153-common-action-authorizations.md).

Hermes 0.22.4 routes ordinary gateway API runs through its native session authority.
That queue does not propagate the Galaris run context used by local tool authorization,
MCP continuations, and worker-exit evidence. Updating the image without adapting this
boundary would change the execution owner and lose those guarantees.

The pinned image keeps runs carrying `galaris_run_context` on the direct Hermes API
worker. Galaris continues to own admission, serialization, retries, and reconciliation
for its dedicated sessions. The retained run record identifies this ownership so stop,
steer, and approval commands reach the same worker. API authentication and exact-request
idempotency remain enforced by Hermes. The worker validates the issued Galaris context
before executing tools; the marker alone grants no action authority.

Native Hermes runs continue to use their session authority. Galaris sessions are not
native Bot Chat sessions and are not delegated to another conversation owner. Any future
integration with the native queue must carry the same context and prove the end of the
actual execution before replacing a run; a logical cancellation alone is insufficient.

The image patch checks each upstream boundary at build time. Qualification starts the
real gateway in an isolated container and exercises authentication, exact-request replay,
allowed and denied writes, stop while waiting for authorization, worker exit, and native
session execution. The existing SDK scenarios retain coverage of local actions and MCP
continuations. Existing managed instances receive the change through an explicit image
rebuild, never during an active Task.
