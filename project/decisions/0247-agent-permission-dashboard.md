# 0247 — Agent permission dashboard

Status: accepted. Date: 2026-10-29.

`/permissions` is the canonical per-agent permission dashboard. The legacy
`/connection/permissions` route redirects while preserving the query and hash, including
pending-request deep links. There are no tabs: pending action reviews, existing connections,
function and prompt policies, observed Harness action types, contacts and network decisions
are visible together with search and state filters. Skills assignments, resource ACLs and
MCP resource enumeration remain outside this page. Unconnected Tools are omitted; existing
inactive connections remain visible for reactivation. Tools are parent groups containing their
function/prompt lists. All matching Tools are listed directly without pagination or internal
scrolling; the selected Tool's functions retain 50-item pagination. Clickable summary counters
replace the decision selector and toggle one state filter across every section. The dashboard has
no connection-creation or technical-configuration action.

An optional custom settings filter retains local function/scope values that differ from inherited
defaults and remembered decisions. Pending approvals are not custom settings.
Global function rules never qualify. A disabled optional Tool counts once at connection level;
its functions are excluded from the custom settings list and count, even when local rules are
stored for a future reactivation. Inherited parameter descriptions are hidden in that view.
Contact decisions are filtered before server pagination. The counter covers every matching custom setting before
pagination and state filtering, even while the custom settings filter is off.
Reset clears search, state and the custom settings filter without
changing the selected agent or retaining a queued debounced search update.

The inventory exposes blocked, on-request, inherited and default policies without exposing
secrets. External discovery failure retains stored rules and reports an incomplete catalog.
Unknown Harness action types require approval; the dashboard does not enumerate or pre-approve
arbitrary runtime names. Pagination follows the shared 50-item default and fixed options.

Declared `tools.management_scope` values are displayed using the connection-local resolver,
never global parameter inheritance. Inline toggles use each Tool’s declared choices and
allow resetting the software default. Delegation requires a web session, connection editing
privilege and global human management scope. A narrow scope-only operation also supports
protected services without unlocking their definition, activation or other parameters.

Every permission control is a multi-state toggle with the persisted rule selected, including
read-only views. Local function overrides and inheritance are distinct from the effective
state, which also accounts for inactive connections and runtime support. Rendering never
writes; save failures retain the selected stored state. Action reviews expose whether their
decision was remembered so the selected choice survives reopening.

Function decisions reuse the existing ordered policy writes. Settled contact/network changes
create a new decision and retain historical interaction resolutions. Runtime policy changes
retain manager/configuration binding and invalidate obsolete pending approvals without
replaying effects. Agent, session and privilege changes clear stale dashboard state.

Verification covers server denials and persistence, catalog failure and secret exclusion,
search beyond the first page, responsive real-component interactions, delegation and retry,
and existing one-time approval workflows.
