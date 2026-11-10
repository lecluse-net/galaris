# 0277 — Configurable operating knowledge shared by executors

Date: 2026-11-10
Status: Accepted

## Decision

The administrable prompt `ai.galaris-operating-prompt` describes how agents use and combine
Galaris resources: native Goal management, Tasks, Processes, Documents, Data documents,
personal Memory, files, media and collaboration. Its canonical English default is packaged
under `core/params/prompt_defaults`; no new operating guidance is embedded in runtime code.
An explicit empty value disables this optional guide; null follows the packaged default.

`app.agent.executor_instructions` composes that value before the existing executor-specific
instructions. Internal Tasks, Hermes Tasks, text, STT/TTS voice and realtime consume this
same composition. Other Task drivers consume the generic facade's prepared system prompt.
Existing customized executor additions remain intact and last. The current rights-filtered
inventory, mounted schemas and server authorization remain authoritative.

The Lab freezes the complete composed suffix when initializing a dataset or resolving its
run configuration. Explicit experimental suffixes replace the entire composed value,
allowing a baseline without the operating guide. Later administrative edits cannot change
frozen dataset or run prompts.

## Qualification

The development-only operating-knowledge benchmark reuses Lab recording tools with real
model inference and synthetic, versioned scenarios. It changes only the composed suffix
between paired arms. It freezes inputs, tool schemas, fixtures, prompts, model and reasoning
effort; uses repeated, alternated pairs; retains raw outputs and deterministic checks; and
reports cost, duration, calls, case-cluster uncertainty and regressions. Unknown costs or
infrastructure errors stop new admissions. In-flight work may exceed the recorded-cost
threshold. Simulated receipts establish model behaviour, not successful business effects.

References are checked against real function signatures and must detect omitted required
effects. The corpus includes Goal lifecycle management, revisions, access denials, Memory,
documents, Task status, Process handling and self-contained answers. Public cases are
validation material, not a private production holdout. Rescoring preserves original evidence
and records any oracle correction made after observing outputs.
