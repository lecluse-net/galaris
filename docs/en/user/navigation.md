<p align="right"><a href="../../fr/user/navigation.md">Français</a> · <strong>English</strong></p>

# Finding your way around Galaris: menus, screens and workflows

Use this guide to locate a feature in the application. The
[menu map generated from the frontend](../architecture/generated/navigation.md)
provides exact labels, routes, descriptions and access conditions for the shipped version.
Paths below are relative to your Galaris instance.

A loading indicator may briefly appear when opening a tab or editor for the first time.
The rest of the page stays usable. If loading fails, **Retry** attempts to open the view
again without reloading the page or discarding current input. A persistent error leaves
that view unavailable; other actions remain accessible.

## Opening the menus

Once signed in, use the left sidebar. If only icons are visible, expand it with the menu
button. Below 1024 CSS pixels in viewport width, the top toolbar's menu button opens the
navigation drawer. The sections stay the same; visibility depends on the active role and
available features. The sidebar logo leads to the home page `/`.

Open the account menu by clicking your name or avatar at the top right. It contains your
profile, personal API tokens, language, theme, assignments for switching roles, and sign out.
The role displayed below your name identifies the current context. Personal language and
theme preferences are separate from the instance's administrative **Preferences**.

## The five main sections

| Section | Contents |
|---|---|
| **Configure** | Providers & models, Agents, Tools & connections, Skills |
| **Act** | Chat, Goals, Processes |
| **Knowledge** | Documents, Memory, Contacts, Thematic dossiers |
| **Monitor** | Dashboard, Activity, Dream, Mail journal, Failure journal |
| **Administer** | Preferences, Laboratory, Console, Users, Teams, Roles & permissions |

Technical documentation may refer to “Tasks”, “Conversations” or “AI Lab”. Tasks and
conversation histories are tabs inside **Activity**; the AI Lab is **Laboratory**.
They are not additional sidebar menus. Use the generated map for labels in each language.

## Providers, models and agents

**Configure → Providers & models** (`/llm`) offers:

| Tab | Purpose | Direct link |
|---|---|---|
| Providers | Configure model services and browse their catalogs | `/llm?tab=providers` |
| Available models | Manage models exposed to Galaris | `/llm?tab=models` |
| Models in use | Choose models for usages and profiles | `/llm?tab=usage` |

Provider configuration is saved automatically after a successful connection test, on each
change while the provider is active and required fields are complete, and when disabling
the provider, even with incomplete fields. Changes to an already inactive provider remain
a draft until a successful test or a manual save. If saving fails, your input is preserved;
use **Save** to retry.

API key fields stay masked while typing and have no eye icon. Stored keys are encrypted
and never displayed again: an empty field shows the fixed `**********` indicator.
The label stays visible in small text inside the field.
Leave it empty to retain a key, or enter a new key to replace it. The small remove button
inside the field asks for confirmation, then deletes the stored key. Removing a required
key deactivates the provider; removing an optional key preserves its active state. This
behavior applies to both model keys and OpenRouter’s optional management key.

For supported providers, **Usage and credits** in provider settings displays service-reported
limits: ChatGPT windows and additional credits, ElevenLabs credits, Mammouth AI and OpenRouter key spending,
DeepSeek balances and SunoAPI.org credits. These figures refresh automatically every five
minutes while the panel is open. **Refresh limits** reads the service without
generation. The panel identifies account-wide or API-key scope, including use outside
Galaris. A gauge appears only when a reported ceiling permits a percentage. Amounts retain
their units, zero values and overages; failed reads can be retried. Mammouth application
quotas are separate from API credits. OpenRouter displays only the remaining amount, without
a gauge or percentage based on cumulative purchases. Without a management key, this amount
is the available API-key budget; the account balance requires a management key.
**Management key (optional)** stores this second key encrypted
in the database without replacing the model API key. **Create a management key on OpenRouter**
opens the provider’s dedicated page. This key grants administrative permissions; Galaris uses
it only to read account credits and usage. Saved keys stay hidden; entering a new value replaces
the key, and **Remove management key** restores the remaining amount for the API key.
The ElevenLabs key needs **User → Read** permission to
read subscription usage. Missing values remain unknown.
For ChatGPT, the additional credit balance appears in credits, without a gauge, alongside
subscription windows. A zero balance remains visible; a missing amount or unlimited
entitlement is not shown as zero. These credits are separate from OpenAI API credits.

Fireworks AI settings display no balance or usage panel because the prepaid balance
cannot be read with the API key.
The [provider availability survey](../dev/provider-quotas.md) distinguishes integrated readers
from APIs requiring additional integration or permissions.

Under **Providers → Available resources**, the **Resource type** dropdown keeps the icons
and filters the provider catalog. **Documents / PDF** lists chat models declaring file
input and text output. Add a model, then assign it to **Document analysis model** under
**Models in use**. Incomplete provider metadata may leave a compatible model out of this list.

**Models in use** requires `PARAMS_ACCESS` or `PARAMS_EDIT`, in addition to access to
the screen. It is the default tab for authorized accounts; other accounts start on **Providers**.

### Create an agent

**Configure → Agents** (`/agent`) contains **Agents**, **Teams** and **Titles**, according
to permissions. To create an agent, open **Agents**, then **New Agent**. Open an existing
agent's record from the list to edit it. Tabs in that record differ from page tabs:
they include general settings, models and MCP according to permissions. Choose the Task
engine in the agent's record; administer harnesses under
**Administer → Preferences → Harnesses** (`/params/harnesses`). Harness entries depend
on the server catalog: use the displayed link without inventing an identifier.

To delegate this administration to an agent, enable its optional **AgentAdmin** connection
under **Tools & connections**. It starts active when the **Galaris** assistant is created;
later deactivation is preserved. Its 34 functions remain limited to its human manager’s rights
and scope. Generated portraits use the caller’s image model; wait for registration
to be confirmed, then reopen the target’s record. See the
[AgentAdmin contract](../dev/agent-admin.md) for connections, teams and Harnesses.
When an agent avatar is saved, the image is converted to JPEG and reduced to at most
500 × 500 pixels, preserving its proportions without enlarging small images.

## Tools, connections and skills

**Configure → Tools & connections** (`/tools`) separates three needs:

| Tab | Purpose | Direct link |
|---|---|---|
| Tools | Browse Tools and their functions | `/tools?tab=tools` |
| Connections | Configure connections associated with agents | `/tools?tab=connections` |
| Authorizations | Administer access rules for tools and functions | `/tools?tab=authorizations` |

In a custom Tool definition, each connection parameter can have a label, description and
default value. For text or integers, **Add a fixed choice** defines allowed values and their
display labels: the form then shows a dropdown. The technical code stays visible below the
label. Agent connections, global parameters and MCP tests share these controls. Parameters
without choices remain free text; passwords stay masked. YAML export and import preserve
choices and labels.

To delegate catalogue and connection management, explicitly enable **ToolAdmin** and follow
the [delegated administration journey](../admin/tool-administration.md).
The Galaris assistant receives this active connection when first created; later deactivation
is preserved. Prepare an MCP
candidate under **Tools → New Tool → Test connection**; send only its temporary reference
to the agent, keeping secrets server-side.

A configurable MCP function request, such as `topic_create`, offers **Allow this action**,
**Deny this action**, and **Always allow this function**. The last choice saves consent for
that function on this agent's connection, with any arguments in future calls. Other functions
keep their policies. Set the function back to **Ask** in the connection's permissions to
require confirmation again. Requests use the manager's language (French, English, or Chinese),
falling back to the instance's default language when their profile has none.
In internal Chat, the “Answer to…” sentence for button responses follows the interface
language, including after reopening or changing languages. The request title and selected
option label retain the wording of the original request.

For browser access, open the agent's **Browser** connection. Local networking is blocked by
default; enable `allow_local_network` to allow a permission request. Destination filters stay
authoritative. Answer through messaging or the internal-chat buttons: both approvals and denials
are remembered per agent, access type and origin (domain, protocol, port). Public GET requests
need no question with the default settings. The third choice, **Always allow all sites**,
saves consent for all domains, protocols, ports and paths, with configured HTTP methods and
WebSocket, for this agent. New web destinations no longer require site permission requests.
Filters, explicit denials and separate local-network permissions still apply.
**Allow and remember** and **Deny and remember** remain limited to the requested access type.
Delete the all-sites agreement to require a choice again for those accesses. Existing
single-site agreements keep their original scope.
**Monitor → Remembered permissions**
(`/connection/permissions`) shows the original question and answer, filters by agent or decision,
and lets you delete a choice. The agent asks again on its next attempt allowed by configuration.
A blocked action requires a new attempt after your reply; forms are not resubmitted automatically.

To give an agent product knowledge, start in **Connections**, find its **Galaris Admin**
connection, then follow the [product knowledge guide](../admin/product-knowledge.md).
A skill provides instructions; actual function access also depends on authorized Tools and connections.

**Configure → Skills** (`/skill`) contains **Skills** (`?tab=skills`), **Self-learning**
(`?tab=learned`) when learning is enabled, and **Authorizations** (`?tab=authorizations`)
with `SKILL_ASSIGN`. Skill assignments do not replace Tool permissions or human account roles.

The bundled **Galaris**, **Galaris Lab**, and **Connaissance de Galaris** skills belong to
the **Galaris** category by default. Synchronization also groups existing uncategorized
skills while preserving your custom classifications.

## Chatting, tracking work and finding results

Use **Act → Chat** (`/chat`) to talk with an agent, **Act → Goals** (`/goal`) for a durable
objective, and **Act → Processes** (`/process`) for predefined workflows. Attachment and
large-report analyses remain available through the request made to the agent and do
not create entries in this workflow catalogue. The
[user guide](README.md) explains when to choose a conversation, Task or Goal.

When opening a conversation, messages appear without waiting for the command catalogue
or call status. Link previews and document thumbnails load progressively near the visible
area; you can read and compose while they load, and open a document before its thumbnail
is ready.
Messages from the same agent share its avatar load; initials remain visible while the
image is unavailable.
Avatars are also briefly reused across other screens. Replacing or deleting one in the app
invalidates its cache; signing out clears it.

Agent lists are reused for one minute; titles, groups and parameters for five minutes.
Saving these resources invalidates the corresponding cache. To immediately see a change
made from another session, reload the page with **F5**: all these memory caches start empty.

Monitor work in **Monitor → Activity** (`/task`):

| Tab | Contents | Direct link |
|---|---|---|
| Text conversations | Short exchanges and rounds | `/task?tab=conversations` |
| Phone calls | Voice history | `/task?tab=voice` |
| Tasks | Durable work, status and execution details | `/task?tab=tasks` |
| LLM activity | Model calls | `/task?tab=llm` |
| Processes | Workflow runs, with `PROCESS_READ` | `/task?tab=processes` |

There is no separate sidebar menu for Tasks or conversation histories: these are tabs
inside **Activity**. **Chat** is for interaction; **Activity** is for monitoring executions.
Access to the screen does not grant access to every conversation or agent.

In **LLM activity** and task details, **Stop this LLM call** interrupts a running
inference with `TASK_EDIT`, within your managed agents. Confirm the request, then wait
for its terminal state: acceptance does not yet confirm that the provider has stopped.
The trace and costs are retained; these inferences do not offer a delete button.
The waiting task or conversation may report an interruption. To suspend work while
keeping it resumable, use the task’s pause action instead.

Under **Preferences → Tasks**, **Maximum LLM call duration (minutes)** defaults to 30.
A call without a terminal result is interrupted and marked as an error at that deadline,
even if the model keeps reasoning or producing a partial answer. Calls are timed separately:
a task with multiple calls may run for hours. Changes apply to new calls.

## Documents and knowledge

**Knowledge → Documents** (`/memory/documents`) holds authored content and Datasets.
**Knowledge → Memory** (`/memory`) offers **Search**, **List** and **Graph**: open the
page and select the tab without assuming a URL parameter. Contacts are at
`/memory/contacts`; thematic groupings are under **Knowledge → Thematic dossiers** (`/topic`).
Sharing a link does not grant access to its content.

In **Documents**, ordinary refreshes update affected rows without clearing the tree or list.
Expanded folders and filters stay in place, including after reconnection. A failed refresh
can be retried while displayed documents remain available; access revocation removes them immediately.

## Preferences, monitoring and account

**Administer → Preferences** (`/params`) presents a section grid and submenus for System,
Language, Messaging, Memory, Dream, Voice, Audio, Processes, Tasks and execution,
Harnesses, Search, Browser, Janus, Instructions and Logs. The
[generated map](../architecture/generated/navigation.md) provides each route.

Under **Tasks and execution → Planner**, planning is bounded by maximum depth and maximum leaves.
There is no separate limit on the total number of steps.

Useful distinctions:

- **Monitor → Dream** (`/dream`) shows activity; **Preferences → Dream** (`/params/dream`)
  configures its behavior.
- **Monitor → Failure journal** (`/incident`) supports diagnosis; **Preferences → Logs**
  (`/params/logs`) configures retention and purges.
- **Administer → Laboratory** (`/lab`) groups task analysis and mechanism evaluations,
  filtered by permissions. See the [Lab guide](lab-ai.md).
- The account menu opens your profile (`/authorize/profile`) and **My API Tokens**
  (`/user/tokens`). It also changes language, theme and active role.
  Managing personal tokens and agents' MCP tokens requires an authenticated web
  session. An API token cannot list, create, update or delete them, or obtain a web
  JWT through renewal or role switching, even when its owner is an administrator.
  Passwords, profiles, avatars, MFA, dismissed help, the default role and personal
  LLM/voice preferences are also managed through a web session. API tokens cannot
  create, update or delete accounts through administrative routes. The usual
  privileges are still required in the web application.
- **Administer → Roles & permissions** (`/authorize`) manages user permissions;
  agent dialogue permissions also involve [teams](teams.md), accessible at `/team`.

## A menu or button is missing

First check the active role in the account menu. The generated map lists visibility
privileges: one privilege within a group is sufficient; ancestor requirements also apply.
Creation, editing, sharing and deletion may require additional privileges enforced by the API.

Some entries have availability conditions: **Chat** can be disabled globally; the
**Mail journal** needs an available mail service; the **Console** depends on the embedded
executor; **Preferences → Browser** depends on browser availability. Harness submenus come
from the server catalog. A section with no visible entries disappears. A direct link bypasses no permissions.

An agent guiding you should give **section → screen → tab → action**, using labels in
your language and explaining relevant prerequisites. If it does not know your role or
configuration, it should ask for the displayed label or message instead of concluding a
feature does not exist. Documentation describes the software's possibilities; it is not
an observation of your session.
