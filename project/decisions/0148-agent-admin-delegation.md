# 0148 — AgentAdmin delegation and direct avatars

Status: accepted. Date: 2026-09-30.

AgentAdmin is an optional built-in Tool, inactive by default for ordinary agents. The
bundled Galaris assistant receives an active connection when first created; subsequent
synchronization preserves manual deactivation and previously initialized agents.
Every operation requires
the caller's current active connection and effective function permission. Its scope is
the caller's active human manager's current Agent management scope; no HTTP identity is
required or trusted. The manager's assignments are evaluated without a selected HTTP
role. `AGENT_MANAGE_ALL` extends scope but never substitutes for domain privileges.

Agent operations require `AGENT_EDIT`. Connection operations additionally require
`CONNECTION_EDIT`; team membership requires `TEAM_ACCESS` and `TEAM_MEMBERS_EDIT`;
shared group mutations require `TEAM_ACCESS`, `TEAM_EDIT` and global Agent management.
Title mutations require global Agent management. Reads require the corresponding
domain access or edit privilege. Changing a manager requires global management and
cannot change the caller's own manager. AgentAdmin connections and permissions are
human-administered only, including revocation; MCP cannot grant or extend delegation.

Correction on 2026-10-01: avatar generation is an ordinary function call, not a Process.
It reads the target's personality, title gender, first and last name, invokes the same
image service as `image_generate`, converts the result to JPEG within 500 × 500 pixels
and registers it before returning success. Current delegation and target preconditions
are checked again before registration. Late images produce a conflict and preserve the
current avatar. A monotonic revision detects replacement followed by restoration.
The obsolete avatar engine and deferred receipt are removed. DbAdmin hard-purges its
exact generated definitions and runs, including archived records; jobs and events cascade.
Waiting Tasks and approval receipts are settled before removal. Business processes and
stored avatars are preserved. Automatic provider resubmission is not introduced.

Native discovery uses the same live projection as execution, including conditional
image generation. AgentAdmin supplies no skill management, global Tool permissions,
LLM provisioning or task termination commands.

The Agent domain gains two public dependencies: `app.file_share` for bounded authorized
URI materialization and `app.image` for specialist image generation. Harness MCP entries
use the public `app.tools` decorators. These explicit dependencies extend the declared
fan-out limits; they do not authorize new private imports or increased coupling baselines.
`agents.avatar_revision` is a non-null integer with a zero server default, converged by
DbAdmin. It adds no handwritten migration or dependency. HTTP avatar reads revalidate
their browser cache and UI readers key their bounded cache by the revision.
