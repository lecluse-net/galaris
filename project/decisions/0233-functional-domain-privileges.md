# 0233 — Independently delegable functional privileges

Date: 2026-10-24
Status: accepted

## Decision

The catalogue has 109 privileges after removing the two retired Hermes privileges and
adding 24 functional privileges. Contacts, Files, indexing, the Dashboard, Dream supervision,
permission decisions, model configuration, LLM profiles, call inspection, text history,
voice history and shared harness configuration no longer inherit unrelated administrative
powers from Memory, Task, Connection or general settings privileges.

| Domain | Read | Mutation or control |
|---|---|---|
| Contacts | `CONTACT_ACCESS` | `CONTACT_EDIT` |
| Files | `FILE_ACCESS` | `FILE_EDIT` |
| File indexing | `FILE_INDEX_ACCESS` | `FILE_INDEX_RUN` |
| Dashboard | `DASHBOARD_ACCESS` | — |
| Dream | `DREAM_ACCESS` | `DREAM_EDIT` (settings) |
| Permissions | `PERMISSION_ACCESS` | `PERMISSION_DECIDE`, `PERMISSION_REVOKE` |
| Configured models | `LLM_MODEL_ACCESS` | `LLM_MODEL_EDIT` |
| LLM profiles | `LLM_PROFILE_ACCESS` | `LLM_PROFILE_EDIT` |
| LLM calls | `LLM_CALL_ACCESS` | `LLM_CALL_CONTROL` |
| Text history | `CONVERSATION_ACCESS` | `CONVERSATION_CONTROL` |
| Voice history | `VOICE_HISTORY_ACCESS` | `VOICE_HISTORY_CONTROL` |
| Harness configuration | `HARNESS_CONFIG_ACCESS` | `HARNESS_CONFIG_EDIT` |

Each domain explicitly permits its operators to read the resources they can modify.
Forgetting a Contact also deletes linked memories, so this compound operation requires
both `CONTACT_EDIT` and `MEMORY_EDIT`. Contact editing alone cannot erase memory contents;
Memory links and the forgetting action are exposed only with the corresponding rights.
This is an OR policy on the relevant API and navigation, not an implicit privilege hierarchy.
Dream supervision remains a separate read capability requiring `DREAM_ACCESS` and global
Agent management scope. Editing Dream settings does not confer supervision. Existing
global settings readers retain read-only Dream configuration visibility without accessing
receipts. Global harness mutations retain their existing global management requirement;
per-agent runtime operations still use Agent privileges and scope.

Provider configuration, OAuth and server-side model installation/deletion retain
`LLM_PROVIDER_*`. Model editors can discover providers and their resource metadata without
editing provider credentials. Profiles and call displays can read the configured model
catalogue for selection and labels. Assignment managers have minimal user/role lookups;
permission editors have scoped connection/Tool metadata without connection parameters.
Task settings can read pipeline eligibility metadata without full harness configuration.
These bounded reads never confer the neighbouring domain's mutation privileges.

Permission decisions and revocations are distinct. Enabling a capability or restoring
inheritance requires `PERMISSION_DECIDE`; `PERMISSION_REVOKE` can block it or require
approval. Existing approver identities, web-session requirements, agent scopes and
resource ACLs remain authoritative.

The file browser is shared transport. It authorizes each canonical source domain,
including verified legacy Dataset aliases, and retains provider ACLs. A Document attachment
does not require global Files access; Files access does not authorize Documents or Datasets.
The assertion reads Query identities from the same source as its handlers, preventing an
ignored JSON body from authorizing another URI. Media grants carry canonical URIs and
recheck session, role, agent and source authorization for every range read.

General parameter administration applies per-key read/write rules: Dream keys use
`DREAM_*`, `llm_profile_id` uses `LLM_PROFILE_*`, and manager, harness enablement and defaults
use `HARNESS_CONFIG_*`. Other keys retain `PARAMS_*`. The generic API cannot bypass the
specialized write policy. Secret masking, encryption and software-owned internal keys remain.
Topic assignment provenance follows the displayed subject's domain or explicit Topic access,
with the existing management scope/resource ACL. Opening a Dream receipt requires Dream
supervision rights. Shared Agent selectors use the scoped selection catalogue; optional
administrative hydration only runs with Agent catalogue privileges.
Chat/Mail availability and Chat notifications start only after the current role's grants
have loaded. Revocation invalidates pending reads and stops background inbox work.

## Dependency review

File indexing UI and its service now belong to File Share. The existing Dream indexing
tab consumes the public `app/file_share/interface` panel rather than owning another copy.
This introduces one intentional frontend edge, `app/dream -> app/file_share`, preserves
the existing Dream journey and adds no reverse edge or dependency cycle. Its access and
run gates remain `FILE_INDEX_*`. The frontend baseline records this reviewed public edge;
eight retired private imports are removed. No new private import is accepted.

## One-time preservation of existing roles

The explicitly approved mapping is owned by `core.authorize.domain_projection`:

| Existing grant | Initial additional grants |
|---|---|
| `MEMORY_ACCESS` | `CONTACT_ACCESS`, `FILE_ACCESS`, `FILE_INDEX_ACCESS` |
| `MEMORY_EDIT` | `CONTACT_EDIT`, `FILE_EDIT`, `FILE_INDEX_RUN` |
| `MEMORY_ADMIN` | `CONTACT_ACCESS` |
| `TASK_ACCESS` | `CONVERSATION_ACCESS`, `VOICE_HISTORY_ACCESS`, `LLM_CALL_ACCESS`, `DASHBOARD_ACCESS`, `DREAM_ACCESS` |
| `TASK_EDIT` | `CONVERSATION_CONTROL`, `VOICE_HISTORY_CONTROL`, `LLM_CALL_CONTROL`, `DASHBOARD_ACCESS` |
| `CONNECTION_ACCESS` | `PERMISSION_ACCESS` |
| `CONNECTION_EDIT` | `PERMISSION_ACCESS`, `PERMISSION_DECIDE`, `PERMISSION_REVOKE` |
| `LLM_PROVIDER_ACCESS` | `LLM_MODEL_ACCESS` |
| `LLM_PROVIDER_EDIT` | `LLM_MODEL_EDIT` |
| `PARAMS_ACCESS` | `LLM_PROFILE_ACCESS`, `HARNESS_CONFIG_ACCESS` |
| `PARAMS_EDIT` | `LLM_PROFILE_EDIT`, `HARNESS_CONFIG_EDIT`, `DREAM_EDIT` |

The administrator keeps every declared privilege under its existing invariant. Roles,
assignments, custom privilege lists and existing placements are retained. No new role or
Agent management scope is inferred.

`roles.domain_privileges_initialized_at` distinguishes existing roles from new roles.
The nullable column has a Python default for new inserts and no server backfill default:
existing rows remain NULL until projected. A DbAdmin `AFTER_DATASET` action is triggered by
the table/column delta. It writes grants and the initialization marker in one transaction;
its postcondition verifies that no pending role remains. Inserts are conflict-safe and
bounded. DbAdmin's existing obligation journal handles interruption before completion.
New roles use explicit grants immediately. Later synchronizations do not restore a revoked
domain grant; the action does not become a continuously enforced dataset or a global
numbered migration history. Privilege deletion retains FK cascade of grants only.

## Verification

HTTP tests exercise readers, operators, neighbouring and former broad rights, scope
denials, parameter writes, source URI substitution, permission revocation and minimal
catalogues. PostgreSQL tests cover the exact projection, rollback, new roles and persistent
revocation. Browser scenarios use the real pages and stores to verify tab selection,
role changes, saving/retry and independent indexing on desktop and mobile.
