# 0235 — Functional settings and source authorization

Date: 2026-10-24
Status: accepted

## Decision

Continue decision 0233 with independent read/write capabilities for Mail, Calendar,
Browser configuration, Goal configuration and each family of preferences. The executable
parameter policy is `core.params.access`: every declared key has an explicit owner;
unknown keys fail closed. DbAdmin verifies this policy before merging parameter data.
The frontend field policy is generated alongside privilege accessors. `PARAMS_*` now
controls registration and HTTP rate limits only; it is not an administrative bypass.
Internal signing keys remain inaccessible. Composite Goal settings are written through
the Goal API, preserving validation, global scope and the event contract.

Dream supervision remains `DREAM_ACCESS` with global Agent management. Its configuration
uses `DREAM_CONFIG_ACCESS` and the existing `DREAM_EDIT`; configuring Dream does not grant
supervision or Memory administration. Operational Goal status is a bounded projection
for Goal readers/operators; full settings and their WebSocket events use `GOAL_CONFIG_*`.

Native Process payloads require Process rights on all eight previously Memory-readable
surfaces. Topic content additionally requires the source domain's read/operator rights,
with unchanged source ACL and Agent scope. Compact Topic labels are available to the
source histories without granting Topic analytics. Topic taxonomy operations may move
classification links globally; they do not grant source content access or edit its body.

Mail history uses `MAIL_ACCESS`/`MAIL_EDIT`. A journal review additionally requires
`PERMISSION_DECIDE`, the designated approver, a web session and the managed Agent scope.
The generic Permissions queue can approve its single bound request with
`PERMISSION_DECIDE`; this explicit consent capability does not open the Mail journal.
Decision rights are revalidated in business services and in registered choice policies
before buttons, typed replies and interrupted delivery can consume an answer. Revocation
leaves an unanswered choice pending; it never schedules the old answer to execute after
rights are restored. HTTP checks use the active role; background recipients use their
current assignments, independently of the sender's context.

Calendar feed management has its own page and rights. Selecting a Calendar connection
or trigger Process returns scoped metadata, never connection parameters or Process
payloads. Domain Agent selectors use public, scoped display metadata; Connection editors
receive public connection schemas without Tool transport credentials or global values.
These projections do not grant the neighbouring domain's administration rights.

## Existing roles and exceptions

`roles.functional_isolation_initialized_at` follows the same nullable-column, Python
default and transactional one-time projection pattern as decision 0233. The new action
first completes that earlier projection when an upgrade crosses both versions, then
projects the explicit capabilities in `core.authorize.functional_projection`:

- Former `PARAMS_ACCESS`/`PARAMS_EDIT` receive the corresponding settings capabilities.
- Former `DREAM_ACCESS` receives configuration read access only.
- Former `CONNECTION_ACCESS`/`CONNECTION_EDIT` receive Mail and Calendar read/write rights.
- Former `GOAL_ACCESS`/`GOAL_EDIT` receive Goal configuration read/write rights.

New roles are explicit. Projection and marker roll back together; later runs preserve
revocations. The second projection adds only the newly introduced capabilities: existing
Harness/Profile rights and the Dream writer remain governed by the first marker, including
revocations made between the two upgrades. Existing role identities, assignments, category placement and resource ACL
remain authoritative. Administrators retain all declared privileges. Read-only Mail
approvers need explicit decision and Mail write grants for journal reviews after upgrade.

A pair is the default, with documented exceptions: observation-only dashboards and
Dream supervision; separate purge, launch, administration, assignment, call and
impersonation powers; User CRUD and Team membership composition; API execution grants;
and `CODE_ACCESS`, which opens an interactive IDE with execution rather than promising
an unenforceable read-only editor. Personal account functions remain authenticated and
owner-scoped. MCP function modes and resource ACL remain independent controls.

## Verification

The executable settings matrix covers every declared key, every domain reader/writer,
foreign domains, internal keys and the generated frontend contract. Persisted HTTP
regressions cover the five audit findings and positive source/scope cases. Transactional
projection tests cover direct upgrades, rollback, explicit new roles and revocation.
Real browser journeys open each delegated function with a separate role and reject
unexpected API denials; interaction tests cover saving/retry and role changes.
See the functional isolation audit for actual results and qualification limits.
