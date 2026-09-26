<p align="right"><a href="../../fr/user/navigation.md">Français</a> · <strong>English</strong></p>

# Finding your way around Galaris: menus, screens and workflows

Use this guide to locate a feature in the application. The
[menu map generated from the frontend](../architecture/generated/navigation.md)
provides exact labels, routes, descriptions and access conditions for the shipped version.
Paths below are relative to your Galaris instance.

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

## Tools, connections and skills

**Configure → Tools & connections** (`/tools`) separates three needs:

| Tab | Purpose | Direct link |
|---|---|---|
| Tools | Browse Tools and their functions | `/tools?tab=tools` |
| Connections | Configure connections associated with agents | `/tools?tab=connections` |
| Authorizations | Administer access rules for tools and functions | `/tools?tab=authorizations` |

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
objective, and **Act → Processes** (`/process`) for predefined workflows. The
[user guide](README.md) explains when to choose a conversation, Task or Goal.

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

## Documents and knowledge

**Knowledge → Documents** (`/memory/documents`) holds authored content and Datasets.
**Knowledge → Memory** (`/memory`) offers **Search**, **List** and **Graph**: open the
page and select the tab without assuming a URL parameter. Contacts are at
`/memory/contacts`; thematic groupings are under **Knowledge → Thematic dossiers** (`/topic`).
Sharing a link does not grant access to its content.

## Preferences, monitoring and account

**Administer → Preferences** (`/params`) presents a section grid and submenus for System,
Language, Messaging, Memory, Dream, Voice, Audio, Processes, Tasks and execution,
Harnesses, Search, Browser, Janus, Instructions and Logs. The
[generated map](../architecture/generated/navigation.md) provides each route.

Useful distinctions:

- **Monitor → Dream** (`/dream`) shows activity; **Preferences → Dream** (`/params/dream`)
  configures its behavior.
- **Monitor → Failure journal** (`/incident`) supports diagnosis; **Preferences → Logs**
  (`/params/logs`) configures retention and purges.
- **Administer → Laboratory** (`/lab`) groups task analysis and mechanism evaluations,
  filtered by permissions. See the [Lab guide](lab-ai.md).
- The account menu opens your profile (`/authorize/profile`) and **My API Tokens**
  (`/user/tokens`). It also changes language, theme and active role.
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
