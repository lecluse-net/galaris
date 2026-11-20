# 0304 — Runtime LLM calls are attributed to one task execution

An external runtime uses its agent principal and the server-issued execution grant
for model calls as well as MCP. The LLM gateway resolves the task, run and task
attempt before admitting the inference. A task or run header, when present, must
agree with the grant. The persisted inference keeps the admitted attempt even if
the scheduler advances the task before a physical call is recorded.

Parallel execution is enabled for a provisioned runtime whose adapter and control
endpoint both support run-scoped model calls. Codex, Claude Agent and DeepSeek Harness
implement the contract. Their concurrency follows scheduler capacity and the optional
operator cap per harness. Runtime instances without the verified capability
use the existing serial contract. A missing or invalid execution grant on a
qualified instance causes rejection at the gateway.

The grant is forwarded by each managed SDK execution through its own configuration.
The gateway derives conversation and Process lineage from the task. Task admission
and its transactional per-agent concurrency check remain owned by the scheduler.
Concurrent task attribution establishes no filesystem isolation for a shared
checkout. Separate code worktrees retain independent writable files.

Qualification exercises five actual SDK calls in parallel against a synthetic provider.
Gateway coverage checks admission, a conflicting identity and revocation scoped to one run.
