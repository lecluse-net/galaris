# 0177 — Remembered consent per Harness action type

Accepted on 2026-10-12. Extends [0153](0153-common-action-authorizations.md).

All managed external runtimes expose **Always allow this action type** alongside the one-action
choices. `app.tools` owns the durable consent, scoped to the agent, runtime provider
and exact local tool name. Arguments, sessions and Task identities are excluded
from this reusable scope; file writes and command execution remain distinct types.
The human request names that scope explicitly, including its application to future
tasks. The internal Harness is excluded from this runtime consent mechanism.
MCP connection policies and domain-specific approvals retain their contracts.

Consent binds the current manager, authorization policy version, configured Harness
assignment and revision, and runtime execution configuration (including Hermes's
governed terminal signature). A stale question cannot grant reusable authority.
Historical requests without a remembered-configuration fingerprint remain single-use.
An unconfigured or unavailable Harness cannot acquire consent.

Every runtime operation still creates and consumes its own one-use authorization
with exact arguments, context and run authority. Automatic decisions reference the
specific consent record and are audited as `runtime_policy`. Existing pending
questions and denials are never answered retroactively by another consent.
Revocation and claims serialize on the agent policy lock. Revocation invalidates
unconsumed authorizations referencing that consent, without rewriting executing or
terminal operations. Changed configuration or authority also blocks unconsumed claims.

The human Permissions page lists these consents, distinguishes ineffective records,
and permits their manager or original approver to revoke them. Runtime credentials
cannot list or revoke human consents. No SDK session allowlist is enabled, and the
existing lifecycle, isolation, resource preconditions and provider guards still apply.

Coverage extends the same real-DB authorization scenarios to every registered external
provider (Hermes, DeepSeek Harness, Codex, Claude Agent and configured OpenAI Messages),
and explicitly verifies the internal Harness exclusion, alongside
the runtime HTTP authentication checks, and component browser journeys for permanent
choices, failure/retry, reopening and revocation.
