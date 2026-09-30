# 0148 — AgentAdmin delegation and deferred avatars

Status: accepted. Date: 2026-09-30.

AgentAdmin is an optional built-in Tool, inactive by default. Every operation requires
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

Avatars use a dedicated integrated Process engine. Admission freezes the caller's
image model and provider configuration, target descriptive fingerprint, manager and
avatar revision. A durable submission claim prevents a second provider request after
an uncertain interruption. The avatar and final engine receipt commit together. Before
publication, current delegation and target preconditions are checked again. Late images
produce a conflict and preserve the current avatar. A monotonic avatar revision also
detects replacing an image and restoring its previous bytes.

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
