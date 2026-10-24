<p align="right"><a href="../../fr/admin/privileges.md">Français</a> · <strong>English</strong></p>

# Delegate privileges by function

Under **Administer → Roles & permissions** (`/authorize`), select a role and grant the
privileges it needs. A user/role assignment determines the active role; categories only
organize privileges and grant no access. Check the role shown in the account menu when
investigating an access denial.

## Separate reading, editing and management scope

The following domains can be delegated independently. Where a route accepts its read
**or** edit privilege, an operator can read what they edit without implicitly receiving
another privilege. Resource permissions and managed-agent scope still apply;
`AGENT_MANAGE_ALL` is a separate delegation.

| Function | Read | Edit or control |
|---|---|---|
| Agents | `AGENT_ACCESS` | `AGENT_EDIT` |
| Contacts | `CONTACT_ACCESS` | `CONTACT_EDIT` |
| Personal memories | `MEMORY_ACCESS` | `MEMORY_EDIT`, administration `MEMORY_ADMIN` |
| Documents | `DOCUMENT_ACCESS` | `DOCUMENT_EDIT`, administration `DOCUMENT_ADMIN` |
| Datasets | `DATASET_READ` | `DATASET_EDIT`, administration `DATASET_ADMIN` |
| Files | `FILE_ACCESS` | `FILE_EDIT` |
| File indexing | `FILE_INDEX_ACCESS` | `FILE_INDEX_RUN` |
| Dashboard | `DASHBOARD_ACCESS` | — |
| Dream supervision | `DREAM_ACCESS` | Separate settings below |
| Permissions | `PERMISSION_ACCESS` | `PERMISSION_DECIDE`, `PERMISSION_REVOKE` |
| AI providers | `LLM_PROVIDER_ACCESS` | `LLM_PROVIDER_EDIT` |
| Configured models | `LLM_MODEL_ACCESS` | `LLM_MODEL_EDIT` |
| LLM profiles | `LLM_PROFILE_ACCESS` | `LLM_PROFILE_EDIT` |
| LLM calls | `LLM_CALL_ACCESS` | `LLM_CALL_CONTROL`, purge `LLM_CALL_PURGE` |
| Tasks | `TASK_ACCESS` | `TASK_EDIT`, purge `TASK_PURGE` |
| Text history | `CONVERSATION_ACCESS` | `CONVERSATION_CONTROL` |
| Voice history | `VOICE_HISTORY_ACCESS` | `VOICE_HISTORY_CONTROL` |
| Shared harness configuration | `HARNESS_CONFIG_ACCESS` | `HARNESS_CONFIG_EDIT` |
| Processes | `PROCESS_READ` | `PROCESS_EDIT`, launch `PROCESS_LAUNCH`, administration `PROCESS_ADMIN` |
| Tool catalogue | `TOOL_ACCESS` | `TOOL_EDIT` |
| Connections | `CONNECTION_ACCESS` | `CONNECTION_EDIT` |
| Mail journal | `MAIL_ACCESS` | `MAIL_EDIT`; send decisions also require `PERMISSION_DECIDE` |
| Calendars | `CALENDAR_ACCESS` | `CALENDAR_EDIT` |
| Skills | `SKILL_ACCESS` | `SKILL_EDIT`, assignments `SKILL_ASSIGN` |

Forgetting a contact and its linked memories requires **both** `CONTACT_EDIT` and
`MEMORY_EDIT`. Dream supervision also requires global agent management; configuring Dream
does not open its receipts. Per-agent runtime actions use Agent privileges and scope;
some global harness operations also require global management. Commands that unblock a
Task retain their Task privileges.

Providers, Available models and Models in use follow provider, model and profile privileges
respectively. Selection catalogues expose only the metadata needed: seeing a provider name
from a model does not allow editing its credentials. Installing or deleting a model on the
provider's server remains an `LLM_PROVIDER_*` operation.

Under **Monitor → Permissions**, deciding a request, enabling a function or restoring its
inheritance requires `PERMISSION_DECIDE`. Blocking, requiring approval or revoking uses
`PERMISSION_REVOKE`. Approver identity and the web session are still checked. Editing a
connection's parameters does not replace these rights.

The Mail journal still checks the designated approver. Approving or rejecting a send requires
a web session and both `MAIL_EDIT` and `PERMISSION_DECIDE`. View and configure calendars under
**Monitor → Calendars** (`/connection/calendars`) for connections within management scope;
creating the connection remains a Connection operation.

## Delegate a Preferences section

The parameter API applies a policy per key. `PARAMS_ACCESS` and `PARAMS_EDIT` cover system
parameters; they do not provide general access to every setting. Each edit privilege below
also permits reading its family's values.

| Settings family | Read | Edit |
|---|---|---|
| System: registration, HTTP rate limit | `PARAMS_ACCESS` | `PARAMS_EDIT` |
| Language and localization | `LANGUAGE_CONFIG_ACCESS` | `LANGUAGE_CONFIG_EDIT` |
| Messaging | `MESSAGING_CONFIG_ACCESS` | `MESSAGING_CONFIG_EDIT` |
| Memory and sessions | `MEMORY_CONFIG_ACCESS` | `MEMORY_CONFIG_EDIT` |
| Dream and classification/extraction prompts | `DREAM_CONFIG_ACCESS` | `DREAM_EDIT` |
| Voice | `VOICE_CONFIG_ACCESS` | `VOICE_CONFIG_EDIT` |
| Audio | `AUDIO_CONFIG_ACCESS` | `AUDIO_CONFIG_EDIT` |
| Processes | `PROCESS_CONFIG_ACCESS` | `PROCESS_CONFIG_EDIT` |
| Tasks, planner and LLM call timeout | `TASK_CONFIG_ACCESS` | `TASK_CONFIG_EDIT` |
| Harnesses, manager and binary inputs | `HARNESS_CONFIG_ACCESS` | `HARNESS_CONFIG_EDIT` |
| Web search | `SEARCH_CONFIG_ACCESS` | `SEARCH_CONFIG_EDIT` |
| Janus | `JANUS_CONFIG_ACCESS` | `JANUS_CONFIG_EDIT` |
| Executor instructions | `INSTRUCTION_CONFIG_ACCESS` | `INSTRUCTION_CONFIG_EDIT` |
| Logging, retention and Logfire token | `LOG_CONFIG_ACCESS` | `LOG_CONFIG_EDIT` |
| Browser | `BROWSER_CONFIG_ACCESS` | `BROWSER_CONFIG_EDIT` |
| Goal settings | `GOAL_CONFIG_ACCESS` | `GOAL_CONFIG_EDIT` |
| Default LLM profile | `LLM_PROFILE_ACCESS` | `LLM_PROFILE_EDIT` |

Secrets remain masked and encrypted. Internal signing and Web Push keys are not exposed
through this API. The executable reference is
[`core.params.access`](../../../back/core/params/access.py); the frontend derives each
field's rights from it. A specialized route's denial cannot be bypassed by writing through
the generic parameter API.

## Other functions and exceptions

Goals and Topics have `GOAL_ACCESS`/`GOAL_EDIT` and `TOPIC_ACCESS`/`TOPIC_EDIT` pairs.
Teams distinguish reading, editing and membership composition (`TEAM_ACCESS`, `TEAM_EDIT`,
`TEAM_MEMBERS_EDIT`); editing also retains the read requirement. Each Lab section has its
own independent read/write pair. Incident review uses `INCIDENT_ACCESS`/`INCIDENT_EDIT`,
with a distinct `INCIDENT_PURGE` capability.

Chat separates reading, sending, management, calling and impersonation. User management
retains its four CRUD rights; roles, privileges and assignments each have a read/manage
pair. The IDE (`CODE_ACCESS`) and API access grants are execution capabilities, rather
than a promise of a read-only code interface. Personal account functions remain reserved
to their authenticated owner.

Mail (`MAIL_ACCESS`/`MAIL_EDIT`) and Calendar (`CALENDAR_ACCESS`/`CALENDAR_EDIT`) are independent
of Connections. Topic content additionally requires each Task, history, Memory, Document
or Dataset source domain's rights. Global taxonomy operations move classification links
without opening or editing their source content.

## Distinguish file access from source access

The file browser is shared transport: it checks the requested URI's source domain and
provider permissions. `FILE_ACCESS` opens neither Documents nor Datasets. Reading an
authorized Document attachment does not require global Files access. Media links recheck
session, role, agent and source on every read, including range reads. Sharing a link never
supplies missing permissions.

MCP function permissions and local `tools.management_scope` are further independent checks.
See [Tool administration](tool-administration.md) and [resource sharing](../dev/sharing.md).

## Organize categories and update roles

Initial category labels follow the interface language until renamed. A renamed label is
literal text. With `MANAGE_PRIVILEGE`, moving a privilege or deleting a category changes
organization without removing role grants. Later synchronizations preserve renames, moves,
unassignments and deleted categories: initialization is recorded once per category.

The split from former broad privileges includes a one-time preservation step for existing
roles, described in [decision 0233](../../../project/decisions/0233-functional-domain-privileges.md)
and implemented in
[`domain_projection.py`](../../../back/core/authorize/domain_projection.py).
It is not a permanent equivalence between old and new privileges. New roles require
explicit grants; later synchronization does not restore a revoked domain grant. Check
additional settings privileges in every custom role. Administrators retain all declared
privileges; no additional global scope is inferred for other roles.

The settings, Mail and Calendar continuation is described in
[decision 0235](../../../project/decisions/0235-functional-settings-and-source-authorization.md).
A former read-only Mail approver needs explicit `MAIL_EDIT` and `PERMISSION_DECIDE` grants
for journal reviews. Global Goal changes retain `AGENT_MANAGE_ALL`; the generic parameter
API cannot bypass that scope.

In development, `make sync-db` synchronizes declarations. For deployment, use `make update`.
After updating, check a reader and an operator role through the actual delegated journeys.
The [generated map](../architecture/generated/project-map.md) lists the current catalogue
without freezing its count in guides.
