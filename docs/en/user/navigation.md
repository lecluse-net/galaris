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

The **Galaris** assistant proposed at installation uses a dedicated avatar: a blue and green G
over a starry network background.
Its [product knowledge guide](../admin/product-knowledge.md) loads automatically for text
and turn-based voice replies and internal Tasks, subject to existing access rights.
You can customize or remove its avatar; updates preserve your choice.

**Configure → Agents** (`/agent`) contains **Agents**, **Teams** and **Titles**, according
to permissions. To create an agent, open **Agents**, then **New Agent**. Open an existing
agent's record from the list to edit it. Tabs in that record differ from page tabs:
they include general settings, models and MCP according to permissions. Choose the Task
engine in the agent's record. The form appears as soon as it opens; selectors load afterward.
In **General**, the Harness selection and **YOLO mode** follow the identity fields.
Profiles and voices refresh when **Models** opens. Administer harnesses under
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

In a saved agent's record, **General → Generate avatar** creates an avatar from its names,
the gender specified by its title, personality and job description. Its form and artistic
style are unrestricted, with a visually identifiable AI nature. The canvas remains square,
without a circular mask or crop. The button appears only
when the **default LLM profile** has an active, configured image model. Save profile changes
before generation. The existing image service requests 1024 × 1024 and adapts the dimensions
to the model, then saves the result like any other avatar. An error preserves the previous
avatar; profile or avatar changes during generation prevent its replacement.

## Tools, connections and skills

**Configure → Tools & connections** (`/tools`) separates three needs:

| Tab | Purpose | Direct link |
|---|---|---|
| Tools | Browse Tools and their functions | `/tools?tab=tools` |
| Connections | Configure connections associated with agents | `/tools?tab=connections` |
| Authorizations | Administer access rules for tools and functions | `/tools?tab=authorizations` |

In **Authorizations**, each function has **Global (all)** and **This connection** columns offering Enabled,
Disabled and Ask. The selected column identifies the applicable rule. Choosing a global mode
returns this agent's connection to inheritance without removing other agents' exceptions.
Saving follows successive choices and reports errors.

For compatible file providers and the SSH Console, **File indexing** defaults to
**Only files already known**. Files and directories returned by `file_share` listings and
searches become private Memory entries; Dream can later enrich supported files.
**Discovery and indexing** also delegates traversal to Dream: one directory per work item,
without an LLM, while Galaris is idle. **Preferences > Dream > File rescanning** controls
periodic refresh, every Monday at midnight by default.
Existing settings, including explicit disabling, are preserved. See the
[indexing journey](../admin/tool-administration.md).

Dream groups identical file copies **per agent**, using SHA-256 over their complete bytes.
The shared entry retains its locations and one common summary. Its primary preview URL
stays stable when a copy is discovered and follows a moved or deleted source.
In an entry or the graph's
file inspector, **File locations** provides thumbnails and original downloads, plus fullscreen
previews for formats with a viewer. Each source's permissions still apply; changing one copy does not replace the others.

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

For browser access, open the agent's **Browser** connection. **Public sites allowed** is the
initial choice for new installations: public HTTP methods and WebSocket pass without per-site
consent, subject to filters and explicit denials. Existing instances keep their policy; a previously
absent parameter becomes **Per-site approval**. Local networking is blocked by default; enable
`allow_local_network` to allow a separate permission request. Public mode permits no local access. Destination filters stay
authoritative. Answer through messaging or the internal-chat buttons: both approvals and denials
are remembered per agent, access type and origin (domain, protocol, port). Public GET requests
need no question with the default settings. The third choice, **Always allow all sites**,
saves consent for all domains, protocols, ports and paths, with configured HTTP methods and
WebSocket, for this agent. New web destinations no longer require site permission requests.
Filters, explicit denials and separate local-network permissions still apply.
**Allow and remember** and **Deny and remember** remain limited to the requested access type.
In **Per-site approval** mode, delete the all-sites agreement to require a choice again for those
accesses. Returning to that mode creates no implicit grant. Existing
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

Its **Global (all)**, **Category** and **This agent** columns offer Active/Blocked and highlight
the applicable rule. Category rules concern the selected agent. Agent skill exceptions take
precedence over that agent's category rules, then global settings.
Changing a global or category rule preserves more specific exceptions.

The bundled **Galaris**, **Galaris Lab**, and **Connaissance de Galaris** skills belong to
the **Galaris** category by default. Synchronization also groups existing uncategorized
skills while preserving your custom classifications.

## Chatting, tracking work and finding results

Use **Act → Chat** (`/chat`) to talk with an agent, **Act → Goals** (`/goal`) for a durable
objective, and **Act → Processes** (`/process`) for predefined workflows. Attachment and
large-report analyses remain available through the request made to the agent and do
not create entries in this workflow catalogue. The
[user guide](README.md) explains when to choose a conversation, Task or Goal.

The Chat home screen shows conversations with a message in the last 7 days first, then agents.
The **+** button opens the full paginated history; **−** returns to recent conversations.

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
**Knowledge → Memory** (`/memory`) offers **List** and **Graph**: open the
page and select the tab without assuming a URL parameter. Contacts are at
`/memory/contacts`; thematic groupings are under **Knowledge → Thematic dossiers** (`/topic`).
Sharing a link does not grant access to its content.

To develop a document with an agent, ask for updates to the relevant passages. The agent
preserves useful information and can add distinct material; prior versions remain in the
revisions. Specify when you need a chronological journal or meeting minutes: that chronology
then remains relevant in the document.

Both tabs place the agent and search on the first row, followed by the thematic dossier
and interlocutor below. In **List**, the target date and its apply button complete the
filters. The fields rearrange on smaller screens.

In **Graph**, memories load without a time range filter or a global node cap.
Below the graph header, the legend groups node kinds, relationships, then age markers
and zoom and fullscreen controls.
Node size and opacity follow a linear scale of last activity relative to the oldest and
most recent nodes in the loaded graph. The legend shows both dates; hiding a node kind
does not change this scale. Older nodes remain visible and their labels retain their contrast.
When zoomed out, titles prioritize structural nodes and those with the most connections.
Symbols have two fixed display sizes: distant and near. Beyond the near zoom threshold,
further zoom spreads their positions without enlarging them. Titles remain filtered to
avoid overlaps, including at maximum zoom; hovering or selecting reveals them.
Memories with exactly the same relationships to topics, contacts or other structural
anchors are grouped with a count. Only visible nodes are drawn. Minimum zoom fits the entire
graph to the window and always centers it after panning; zoom can reach one million times
this framing. Previews grow later, depending on neighbor spacing, up to their actual pixel
dimensions. Hiding a kind reorganizes and frames the remaining items; showing all kinds
restores the saved positions.
Root directories keep their titles visible even when zoomed out. A title of “.” is
replaced in the graph by the URI with its scheme, such as `nextcloud://`;
custom titles are preserved.

In **List**, documents, attachments and indexed files display their thumbnail when
available. Click the row or card to open its details; write permissions determine
whether its content can be edited.

In **List**, edit **Target date and time**, then apply the filter to find memories matching
that date. Input and matches use Galaris's configured global timezone (`TZ`), even when
your browser uses another timezone. A memory's calendar fields have no timezone selector.

Item details separate **Memory**, **Links and relations** and **History**.
In **Memory**, previews of associated content appear before keywords and content, followed
by compact calendar fields. The title displays the memory kind, last activity, access count
and revision. Protected deletion appears as a warning badge with an explanatory tooltip.
Standalone memories are private to their agent, with no
title input or sharing control. For a document, this content is an optional synthesis:
**Open document** opens a second modal to edit its title, full content and sharing while
preserving the memory details and draft. This memory cannot be forgotten separately:
deleting the document from its editor also deletes its synthesis and history. Revoking
sharing removes it from the affected agent's memories while preserving it for the owner
and other authorized readers. Attachments and indexed files open in fullscreen
when a viewer supports their format; audio files have a player directly in their preview.
Office documents, spreadsheets and other formats without a viewer retain their thumbnail
when available and only offer original downloads, with no fullscreen action. A notice indicates
when the document has changed since the synthesis. Search always uses both full
content and synthesis and returns one result. A locked resource displays **Read-only**
as a status, without a lock control.
The document and its Memory details share the same keywords. You can edit them from
either view with document write access. Changes refresh the other open view without
losing its content draft or creating a synthesis version. If the same keywords changed
elsewhere during editing, saving reports a conflict and preserves your draft.
Older versions retain their historical keywords.
Dream actions and the other footer buttons share a row aligned to the right. Each button
keeps its content on one line; the row can wrap according to the available width.
Close the details with the cross
or backdrop; there is no longer a Cancel button.
**Links and relations** groups provenance, graph neighbors and explicit relations. You can add a relation according to
your permissions. Switching tabs preserves the draft; **Save** remains available in
the first two tabs.

Clicking a node opens its modal directly. It retains graph metadata (kind,
last activity and access count) and navigation to neighbors, including folders and
conversations. The close button or backdrop returns to the graph.

The modal offers buttons for Dream treatments compatible with the node: generate its
description, **Regenerate thumbnail** for a file, attachment or HTML document, analyze PDF
or Office content with the document model, check
memories, or **Synchronize graph links**. For a document, this last action updates its
attachments, references and folder links. For a folder, it updates folders and their
parent-child links across your entire folder tree. These buttons require Memory editing rights and
resource ownership. They run immediately, even when automatic Dream is disabled or waiting.
A new analysis replaces the generated description; personal catalogue file notes and
revision history remain preserved. Save your edits before running an action. Failures can
be retried, and concurrent edits take precedence over the analysis. Regenerating a thumbnail
reruns rendering even when an image is already cached; failures preserve the previous image.

The graph folds branches with at least eight exclusive leaves into an anchor and a count.
Zoom in or click the group to see its items, then zoom out to fold
them. Shared nodes remain visible. Up to 600 loaded items, the first placement is animated.
Positions are then saved in the background, including hidden and folded nodes. Reopening
restores known nodes to their places and positions newcomers around existing anchors.
Each user keeps their own positions, hidden kinds, open branches and camera for each
agent and search/Topic/contact context. New nodes of a hidden kind stay hidden.
A restore or save failure offers a retry without closing the graph.
Zooming, unfolding and closing node details preserve positions. Zooming out also simplifies links and titles.
Large maps place items near their anchors before settling and load all pages matching the filters.
Spatial loading and subgroups remain the next steps
in the [multi-level memory graph plan](../../../project/plans/graphe-memoire-multiechelle.md) (in French), with `partial` status.

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
  Dream opens **Tracking** by default, showing indicators and action progress.
  **History** groups operations and their filters; **Indexing** lets you select an agent,
  inspect traversals, start or cancel indexing, and retry repairs.
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
