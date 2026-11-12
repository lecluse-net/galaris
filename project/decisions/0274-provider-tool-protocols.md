# 0274 — Provider protocols and multiple Mail accounts

Status: accepted, implemented for Mail. Calendar extensions are delivered independently.

A Tool represents a provider such as Ionos. Its explicit capability selections identify one
technical protocol per capability. The shared catalogue drives standard settings and connection
parameter editors. Mail uses `imap_smtp.mail` and `mail_config`: fixed transport settings belong
to `settings`, while `param_map` references ordinary encrypted connection parameters. IMAP and
SMTP form one entry with two sections and may share or separate their login and password.
Parameters are created only on an explicit user action. Existing empty configurations retain
legacy global and local values. Unknown external capability identifiers survive edits and exports.

One agent may have several connections to the same Mail provider. Database uniqueness uses
`(tool_id, agent_id, singleton_key)`: the internal key defaults to zero for ordinary connections
and is NULL for new Mail accounts. Existing identities and values are preserved. Tool locks
serialize writers. Removing Mail while an agent has additional connections is rejected;
remaining singleton connections recover the zero key when Mail is removed.

All `mail_*` MCP functions select the exact active account by `connection_id`; authorization
and execution use that same connection. Ambiguous or foreign selections fail before transport.
The `tools_list` catalogue exposes each account's address, connection ID and permitted functions,
never passwords. The Galaris skill, agent advertisement and MCP parameter descriptions explain
selection and preserving message references with the original account.

Mail resources carry `account/<connection_id>/` in their provider URI locator, after `mail/`
when ordinary file sharing coexists. Multiple active accounts appear as separate directories.
Legacy URIs remain usable when account resolution is unambiguous. Every operation rechecks the
agent, provider and connection activation. Allowed folders constrain browsing, reading and
mutations; administrative folder discovery can enumerate excluded folders without reading mail.
Mail polling and another messaging capability use separate connection cursors.

The editor places the Protocols title and Add protocol button above its tabs. A filled red
Delete protocol action below the configuration asks for confirmation. Export as YAML uses the
list's existing export function and exports saved settings without secrets. Capability badges
use dark orange text and borders on a transparent background.

DbAdmin introduces the schema and converts legacy Mail definitions without moving connections,
re-enabling disabled accounts, or replacing secrets, policies and delivery receipts. New
installations do not seed a Mail Tool. Shared additive protocol metadata preserves the
published Calendar Tool and editor; this commit does not enable its new provider workflow.

Persistence/API tests cover distinct accounts, permissions, ambiguous selection, atomic saves,
MCP discovery, migration and removal. Mail tests retain real persistence and MIME handling
with synthetic external transport boundaries. Browser component scenarios cover desktop/mobile
creation, folder choices, failures, late responses, protocol editing and reopening.
