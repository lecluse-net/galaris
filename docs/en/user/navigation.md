<p align="right"><a href="../../fr/user/navigation.md">Français</a> · <strong>English</strong></p>

# Finding your way around Galaris: menus, screens and workflows

The **Dashboard** uses `DASHBOARD_ACCESS`. **Contacts** uses `CONTACT_ACCESS` or `CONTACT_EDIT`,
independently of memories. **Roles & authorizations** tabs follow their own privileges:
privileges, roles and assignments can be viewed or administered separately. An unauthorized
tab does not load its catalogues.

Providers, Available models and Models in use have their own rights. Preferences settings
can also be delegated by function. The [privilege guide](../admin/privileges.md) lists rights
and scopes; changing roles can therefore change the available tabs and actions.

**Knowledge → Documents** contains Text and Data documents. The type filter finds JSON documents. See the [Data journey](datasets.md).

Use this guide to locate a feature in the application. The
[menu map generated from the frontend](../architecture/generated/navigation.md)
provides exact labels, routes, descriptions and access conditions for the shipped version.
Paths below are relative to your Galaris instance.

For milestones, plans, questions and recovery, see the [Task guide](tasks.md).

## Find work and take action

Home groups unread conversations, usage indicators and **Recent activity**. It does not add
a second list of Tasks and results to open. Tasks, waits, failures and recovery commands remain
under **Monitor → Activity → Tasks**; approvals remain under **Monitor → Permissions**.

Search within the relevant screens: Documents, Discussion, Activity, Goals, Files and Memory.
Welcome (`/welcome`) offers **Complete your first mission** after setup, to prepare a request
and follow its document. See the [discovery guide](README.md).

During Dream acquisition, complementary information may enrich an editable personal memory
while preserving its content, keywords and sources. A contradiction remains a separate memory
linked to the previous one; it does not erase the old information. A concurrent edit blocks
enrichment against a stale revision. Documents and managed projections cannot be enriched by
this operation. Examine content, sources and relations in Memory and correct them under your rights.

A loading indicator may briefly appear when opening a tab or editor for the first time.
The rest of the page stays usable. If loading fails, **Retry** attempts to open the view
again without reloading the page or discarding current input. A persistent error leaves
that view unavailable; other actions remain accessible.

## Opening the menus

The **About** page (`/about`) shows the version, features and a **Technologies and
acknowledgements** section with logos, roles and links to the main projects used,
including LibreOffice and VS Code through code-server. The **License** button opens
Galaris licensing information and available third-party notices.

Once signed in, use the left sidebar. If only icons are visible, expand it with the menu
button. Below 1024 CSS pixels in viewport width, the top toolbar's menu button opens the
navigation drawer. The sections stay the same; visibility depends on the active role and
available features. The sidebar logo leads to the home page `/`.

Open the account menu by clicking your name or avatar at the top right. It contains your
profile, personal API tokens, language, theme, assignments for switching roles, and sign out.
The role displayed below your name identifies the current context. Personal language and
theme preferences are separate from the instance's administrative **Preferences**.

## The main sections

Documents, files, attachments, goals, tasks and topics also offer actions through right-click.
With the keyboard, focus the item or one of its controls and press **Shift+F10**. Available
commands follow your permissions and the resource state; confirmations still apply.
Chat messages and conversation list items keep the browser menu.
The Chat task menu also expands or collapses a task without opening its details.
Contextual submenus open on hover and stay open while the pointer moves toward their commands.
Click, touch and keyboard access remain available; opening a sibling submenu closes the previous one.
Clicking or tapping outside a menu immediately closes its entire submenu chain, including
inside the original source area or embedded content. The clicked control remains usable.

In development mode only (`APP_ENV=dev`), **Developers** appears directly after **Administer**
as a section at the same level. **Developers → Visual reference** opens
`/graphic-reference`. This page brings together the Solaire palette, form controls,
buttons, an embedded mini dialog and its openable version, open/closed folders at their
display sizes, navigation, resizable splitters, states, content and editors. Interactions
use synthetic data and save nothing. Theme changes are temporary, and Reset restores the
examples. The searchable glyph table includes bundled artwork and document icon catalogues;
the component inventory lists consumer files. Personal user icons are not loaded.
The route is excluded from builds for other environments.

| Section | Contents |
|---|---|
| **Configure** | Providers & models, Agents, Tools & connections, Skills |
| **Act** | Chat, Goals, Processes |
| **Knowledge** | Documents, Files, Memory, Contacts, Thematic dossiers |
| **Monitor** | Dashboard, Activity, Dream, Permissions, Mail journal, Calendars, Failure journal |
| **Administer** | Preferences, Laboratory, Console, Users, Teams, Roles & permissions |
| **Developers** (dev mode only) | Visual reference |

Technical documentation may refer to “Tasks”, “Conversations” or “AI Lab”. Tasks and
conversation histories are tabs inside **Activity**; the AI Lab is **Laboratory**.
They are not additional sidebar menus. Use the generated map for labels in each language.

## Calendars and Mail journal

**Monitor → Calendars** (`/connection/calendars`) selects a Calendar connection and displays
its feeds with `CALENDAR_ACCESS` or `CALENDAR_EDIT`. Editing requires `CALENDAR_EDIT`;
connection creation remains under Tools & connections. The Mail journal separately uses
`MAIL_ACCESS` or `MAIL_EDIT`; send decisions also require `PERMISSION_DECIDE` and the
designated approver identity.

## Providers, models and agents

**Configure → Providers & models** (`/llm`) offers:

| Tab | Purpose | Direct link |
|---|---|---|
| Providers | Configure model services and browse their catalogs | `/llm?tab=providers` |
| Available models | Manage models exposed to Galaris | `/llm?tab=models` |
| Models in use | Choose models for usages and profiles | `/llm?tab=usage` |

Configured model input, output and cache-read prices refresh nightly around 3 a.m.
in the installation timezone. In a model's edit dialog, disable **Update prices
every night** to retain manual or negotiated prices. The dialog shows the source
and date of each imported rate. Provider API prices take precedence, supplemented
by models.dev for the same provider and exact model identifier. Missing fields
remain unchanged; an explicit zero remains zero. Failed checks preserve previous
prices and dates and retry after 30 minutes. Missed checks are caught up after a
restart. Historical costs are never recalculated. Freshness depends on the
information published by the sources.

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

Each tab uses its own privileges: `LLM_PROVIDER_ACCESS`/`LLM_PROVIDER_EDIT` for **Providers**,
`LLM_MODEL_ACCESS`/`LLM_MODEL_EDIT` for **Available models**, and
`LLM_PROFILE_ACCESS`/`LLM_PROFILE_EDIT` for **Models in use**. The page selects an authorized
tab, including after a role change. Read-only selection catalogues do not permit editing
provider configuration.

### Create an agent

The **Galaris** assistant proposed at installation uses a dedicated avatar: a blue and green G
over a starry network background.
Its [product knowledge guide](../admin/product-knowledge.md) loads automatically for text
and turn-based voice replies and internal Tasks, subject to existing access rights.
You can customize or remove its avatar; updates preserve your choice.
Renaming or deleting this assistant never causes an update to recreate it.

**Configure → Agents** (`/agent`) contains **Agents**, **Teams** and **Titles**, according
to permissions. To create an agent, open **Agents**, then **New Agent**. Open an existing
agent's record from the list to edit it. Tabs in that record differ from page tabs:
they include general settings, models and MCP according to permissions. Choose the Task
engine in the agent's record. The form appears as soon as it opens; selectors load afterward.
In **General**, the Harness selection follows the identity fields.
Profiles and voices refresh when **Models** opens. Administer harnesses under
**Administer → Preferences → Harnesses** (`/params/harnesses`). Harness entries depend
on the server catalog: use the displayed link without inventing an identifier.

If a managed Harness rejects its technical identity (`Invalid runtime principal`), use
**Restart** in its supervision view to recreate the runtime with its credentials, wait
until it is ready, then retry the Task. **Refresh** only requests Skill projection.
Recreating the runtime does not retry any business action.

Under **Models**, choose the **Primary profile** and, if needed, a
**Secondary profile (fallback)**, then save the record. An empty primary selection follows
the current profile; **No fallback profile** disables failover. Configure the same usages
in both profiles: an empty secondary usage provides no fallback.
The internal Harness uses the secondary when the provider is overloaded, unavailable or
fails access, preserving the results of tools already executed. The call details under
**Monitor → Activity → LLM activity** show the reason for failover. An external Harness using the
Galaris gateway benefits before its response is published; an already published stream
keeps its provider. Models explicitly selected through the profile API and native voice
follow their own contracts.

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
avatar; any Agent update during generation prevents its replacement, including an avatar
replaced and then restored.

## Tools, connections and skills

**Configure → Tools & connections** (`/tools`) separates three needs:

| Tab | Purpose | Direct link |
|---|---|---|
| Tools | Browse Tools and their functions | `/tools?tab=tools` |
| Connections | Configure connections associated with agents | `/tools?tab=connections` |
| Authorizations | Administer access rules for tools and functions | `/tools?tab=authorizations` |

In **Connections**, connections belonging to historized agents are hidden. Parameters
refresh after saving and whenever you return to the tab. Filters apply to the loaded
list; if loading fails, use **Retry**.

Under **Tools**, **Galaris built-in tools** groups integrated definitions protected by the
software. Created or imported Tools remain under **Custom tools**, including those
using a dedicated bridge such as Nextcloud or AFFiNE. A bridge name does not determine
Tool origin. n8n is not created as a standard Tool; an existing n8n entry is preserved
as a custom Tool with its process references.

In **Authorizations**, only connections belonging to non-historized agents are offered.
Each function has **Global (all)** and **This connection** columns offering Enabled,
Disabled and Ask. The selected column identifies the applicable rule. Choosing a global mode
returns this agent's connection to inheritance without removing other agents' exceptions.
Saving follows successive choices and reports errors.

The Grav bridge has been removed. It is no longer offered in file-sharing configuration;
existing Grav configurations are rejected as an unknown service.

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

New authorization requests show the action and its parameters as readable fields.
For an email, review the recipients, Cc and Bcc, subject, message and attachments of the
prepared email. In **Permissions**, **Technical details** reveals the JSON parameters.
HTML content remains inert source text. Shortened notifications are marked: open the
request to read its complete content.

A configurable MCP function request, such as `topic_create`, offers **Allow this action**,
**Deny this action**, **Always allow this function** and **Always deny this function**. Permanent choices save the decision for
that function on this agent's connection, with any arguments in future calls. Other functions
keep their policies. Set the function back to **Ask** in the connection's permissions to
require confirmation again. Requests use the manager's language (French, English, or Chinese),
falling back to the instance's default language when their profile has none.
In internal Chat, the “Answer to…” sentence for button responses follows the interface
language, including after reopening or changing languages. The request title and selected
option label retain the wording of the original request.

For a local action of any managed external Harness (Hermes, DeepSeek Harness, Codex,
Claude Agent or a configured OpenAI Messages Harness), choose
**Always allow this action type** or **Always deny this action type**. The decision applies to this agent, Harness and exact action
name, with any arguments, including future tasks. For example, allowing `write_file` does not
allow command execution. Other pending requests still require a decision; a permanent denial also
blocks already approved actions that have not started.
In **Permissions**, **Harness action type decisions** lets you remove either decision.
A change of Harness, configuration or manager requires new consent. Revocation prevents
future dispatches; an action that has already started may finish.
The internal Harness is excluded from this Harness action-type consent mechanism.

For browser access, open the agent's **Browser** connection. **Public sites allowed** is the
initial choice for new installations: public HTTP methods and WebSocket pass without per-site
consent, subject to filters and explicit denials. Existing instances keep their policy; a previously
absent parameter becomes **Per-site approval**. Local networking is blocked by default; enable
`allow_local_network` to allow a separate permission request. Public mode permits no local access.
A configuration block creates no permission request: no approval button awaits your answer
while that setting blocks access. Attached files can be read through their source URI without
opening their page in the browser. Destination filters stay
authoritative. Answer through messaging or the internal-chat buttons: both approvals and denials
are remembered per agent, access type and origin (domain, protocol, port). Public GET requests
need no question with the default settings. **Always allow all sites**
saves consent for all domains, protocols, ports and paths, with configured HTTP methods and
WebSocket, for this agent. New web destinations no longer require site permission requests.
Filters, explicit denials and separate local-network permissions still apply.
**Always deny all sites** saves a denial with the same scope: configured methods and WebSocket
are blocked without further questions, including in public access mode. Methods that need no
permission, such as GET by default, keep their current policy.
**Allow and remember** and **Deny and remember** remain limited to the requested access type.
In **Per-site approval** mode, delete the all-sites agreement to require a choice again for those
accesses. Returning to that mode creates no implicit grant. Existing
single-site agreements keep their original scope.
**Monitor → Permissions** (`/permissions`) opens an agent dashboard without tabs. Select the agent,
then search and filter all sections: pending approvals, Tools and functions, Harness action types,
contacts and network access. The list has two levels: each agent Tool, then its functions and prompts.
Inactive connections remain available for reactivation; unconnected Tools are excluded.
This page offers activation and authorization controls without technical configuration or a connect
button. Skills and resource access remain on their dedicated pages.
Review unanswered requests, then allow the action, deny it or choose **Always allow** or
**Always deny** when available. A permanent decision applies to this connection's function or
this agent's Harness action type, with any arguments and in future tasks. Changing the Harness,
configuration or manager makes the Harness decision stale.
Pending network requests can also be answered here. The Agent filter applies to the
whole page. Answered requests leave the list; expired action requests are excluded.
A one-time approval creates no permanent permission.

The sections show approvals, denials, defaults and inherited policies. Connections display the effective
`tools.management_scope` rule and a toggle with that Tool’s supported choices. A global manager with
connection editing privileges can change the scope or reset its default. This setting stays local
to the connection. **Tool functions and prompts** lists functions from every connected Tool,
including denied and on-request functions. Select a Tool from the list on the left to
view its functions and permissions on the right. Scope and activation controls appear
at the top of that panel. On mobile, the list precedes the selected Tool's details.
The left list displays every matching Tool, without pagination or internal scrolling.
The **Allowed**, **Denied**, **On request** and **Pending** counters filter the whole page;
click the active counter again to restore all states. They replace the decision selector and
combine with search. Functions on the right remain paginated, defaulting to 50 items.
**Custom settings** shows agent-level function rules on active Tools, local scopes whose values
differ from inherited rules, and remembered Harness, contact and network decisions. Global rules
are excluded. A disabled Tool counts once at connection level; its functions are neither listed
nor counted in this filter. Pending requests
are hidden in this view. **Reset filters** clears search, the state filter and the custom settings
filter without changing the selected agent.
The custom settings count follows the current search across all pages and remains available
when this filter is turned off.
Every decision uses a multi-state toggle with its current position selected.
Buttons use icons like skill authorizations: green for allow, red for deny, orange for ask
or pending, gray for inherit. A tooltip describes each choice; double check and block
symbols distinguish permanent decisions. For functions, choose
**Allow**, **Deny**, **On request** or **Inherit**. Selection reflects the local rule; the separately
displayed effective state also accounts for Tool activation. A failed save keeps the stored selection.
**On request** requires approval even if the global policy is active; **Inherit** restores the global
or software rule. Remembered Harness, contact and network decisions can also be changed or withdrawn.
An unavailable external catalog shows a warning and keeps known policies visible; unseen Harness
action types remain on request. Future requests
follow the current policy. Removing a denial creates no approval and replays no blocked action.
Technical execution records remain available internally
to prevent duplicate execution and support task recovery; this page does not present them as grants.
For browser access, a blocked action requires a new attempt after your reply; forms are not
resubmitted automatically.

To give an agent product knowledge, start in **Connections**, find its **Galaris Admin**
connection, then follow the [product knowledge guide](../admin/product-knowledge.md).
A skill provides instructions; actual function access also depends on authorized Tools and connections.

**Configure → Skills** (`/skill`) contains **Skills** (`?tab=skills`), **Personal skills**
(`?tab=personal`), including packages learned by Dream, and **Authorizations** (`?tab=authorizations`)
with `SKILL_ASSIGN`. Skill assignments do not replace Tool permissions or human account roles.

The personal tab supports reading/editing managed agents' packages, activation, deletion,
owner changes and, with global management, conversion between personal and generic.
The [Skills guide](skills.md) explains revisions, quotas and local `skills` Tool delegation.
Administration does not grant usage of another agent's personal package.

New Skills connections default to **Use skills and manage own personal skills** (`personal`),
allowing agents to create and maintain their own packages without changing or reassigning
administered general skills. Existing deactivations and explicit scopes remain authoritative;
change them in **Tools & connections → Connections** when needed.

Its **Global (all)**, **Category** and **This agent** columns offer Active/Blocked and highlight
the applicable rule. Category rules concern the selected agent. Agent skill exceptions take
precedence over that agent's category rules, then global settings.
Changing a global or category rule preserves more specific exceptions.
In the **Skills** catalogue, **Disable for everyone** suspends a generic package despite
those exceptions, including a system package. This requires skill editing and global agent
management; files, assignments and administrative MCP management remain available.

The bundled **Galaris**, **Galaris Lab**, and **Connaissance de Galaris** skills belong to
the **Galaris** category by default. Synchronization also groups existing uncategorized
skills while preserving your custom classifications.

## Chatting, tracking work and finding results

Use **Act → Chat** (`/chat`) to talk with an agent, **Act → Goals** (`/goal`) for a durable
objective, and **Act → Processes** (`/process`) for predefined workflows. Attachment and
large-report analyses remain available through the request made to the agent and do
not create entries in this workflow catalogue. The
[user guide](README.md) explains when to choose a conversation, Task or Goal.

A Goal description is a simple HTML field. Its tracking is an unclassified Document,
visible in the Documents list but outside the tree until you classify it. No Goal folder
is imposed. Existing folders retain their names and behave as ordinary editable folders,
without translation or automatic renaming.

The **Processes** page displays its lists without waiting for the external engine check or
agent catalogue. Execution details and their diagram load only when you open an execution;
you can close its dialog during loading and reopen it.

**Processes** use the engine selected by their assigned definition.
**Preferences → Processes** currently configures n8n; other software requires an
installed bridge. The [external engine guide](../dev/process-engines.md)
explains that preparation for administrators and developers.

In conversation composers, **Add an internal attachment** sits inside the file drop area,
outside the text field. Local files and selected internal resources appear together in
that area, remain draft attachments and can be removed
before sending, including messages without text. Their cards and thumbnails appear below
the published message. Files retain their source URI (`file://`, `console://` or the service's
scheme), without copying or replacing it with a Galaris page URL. Source permissions and
the receiving agent's access still apply. A compatible model receives the image, PDF,
audio or video directly. Otherwise, configured specialists supply a textual description
or transcription; unavailable analysis and incomplete coverage are reported explicitly.

The Chat home screen shows all conversations, like the chat window's **Conversations** section,
then agents. Older and empty conversations are included, with the same filters and usual pagination.

During a response, **Pause response** gives you time to compose a supplement.
Sending it automatically continues with both your original request and the supplement.
**Resume response** continues without a new message; **Stop response** abandons the current
reply. An already running tool finishes before the pause or stop takes effect.

On phones and tablets, **Return** inserts a newline. Use the send button to post the message
while keeping the input focused and the keyboard open. On computers, **Enter** sends and
**Shift+Enter** inserts a newline, including in a narrow window.

When opening a conversation, messages appear without waiting for the command catalogue
or call status. Link previews and document thumbnails load progressively near the visible
area; you can read and compose while they load, and open a document before its thumbnail
is ready.
Attachment previews, including Markdown, also load as they approach the screen.
Recent previews are reused while browsing history, within a bounded memory budget;
an older preview may reload when revisited. Visible, opened and playing media remains
available. Switching conversations cancels pending transfers. If a preview fails,
use its reload action; the original file remains
available for download.
In long conversations, the reading position is preserved when earlier messages load
and when resizing. After focusing the history, use **Home**, **End** and **Page Up/Down**
to navigate loaded messages. **Ctrl+F** (or **Cmd+F**) makes these messages available
to the browser's search. Playing media stays active while scrolling.
Link cards and their thumbnails are briefly reused when revisiting a message.
Received document updates and deletions refresh them, including while the message
is offscreen.
Messages from the same agent share its avatar load; initials remain visible while the
image is unavailable.
Avatars are also briefly reused across other screens. Replacing or deleting one in the app
invalidates its cache; signing out clears it.

In chat, deleting a document immediately removes it from the **Documents** section and closes
its pane or dialog, preserving the message draft. The **Source code** section groups
repositories linked to the discussion and discovers those in the agent’s SSH home when opened,
provided you own its active Console. Full paths from the home, such as `work/galaris`, distinguish
repositories with the same name. Click to open the internal VS Code editor; **Refresh repositories**
runs discovery again. The section collapses like the other sidebar sections.

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

For a plan that must produce and deliver a file, the agent's reported result is checked
against recorded production and delivery. A different file already delivered cannot
validate the plan; a stale file or unconfirmed send may leave the work in error. Check
the cause in task details. If the final file is preserved and no send to the requested
destination has been attempted, recovery can be limited to delivery. A send with an
uncertain outcome must be checked before repeating it.

When you request a saved report even if work fails, the plan can retain that closing action.
The task remains in error with its cause and report; failed work waits for your retry decision.
A manual retry also updates the report.

In **LLM activity** and task details, **Stop this LLM call** interrupts a running
inference with `LLM_CALL_CONTROL`, within your managed agents. Confirm the request, then wait
for its terminal state: acceptance does not yet confirm that the provider has stopped.
The trace and costs are retained; these inferences do not offer a delete button.
The waiting task or conversation may report an interruption. To suspend work while
keeping it resumable, use the task’s pause action instead.

Under **Preferences → Tasks**, **Maximum LLM call duration (minutes)** defaults to 30.
A call without a terminal result is interrupted and marked as an error at that deadline,
even if the model keeps reasoning or producing a partial answer. Calls are timed separately:
a task with multiple calls may run for hours. Changes apply to new calls.

## Documents and knowledge

The [document library guide](documents.md) covers creation, folders, sub-documents,
lists, bulk actions and keyboard shortcuts.

**Knowledge → Documents** (`/documents`) holds and creates Text (HTML) and Data (JSON) documents.
The editor toolbar's **Conversation** icon opens an existing conversation or starts one with an agent
on the same page. The document remains the focus of the work; **Chat** continues to
focus on conversations and activity monitoring.
The **Create document** button and context menus offer both types.
Legacy `/dataset` links redirect to this library filtered to Data.
**Knowledge → Memory** (`/memory`) offers **List** and **Graph**: open the
page and select the tab without assuming a URL parameter. Contacts are at
`/memory/contacts`; thematic groupings are under **Knowledge → Thematic dossiers** (`/topic`).
Sharing a link does not grant access to its content.

Legacy `/memory/documents` links redirect to `/documents`, preserving the selected document
and attachment. Legacy HTML forms remain accessible in the library.

Click a dossier row, or its mobile card, to open its content. Within a dossier, task,
text round, voice round, space, document and memory rows open their target in a dialog
without leaving the dossier. Keyboard activation is also available. Close the dialog
with its close button or by clicking outside it. The **Back** button below the dossier
title returns to the list.

A discussion opened in a dialog starts at the latest messages. Scroll to the top to load
earlier messages automatically while keeping your reading position. Scroll back to the bottom
to refresh the latest messages, or use the downward arrow.

Deleted documents disappear from the chat document list. Their old references in messages
display **Document deleted**, without allowing access to their content.

Both tabs place the agent and search on the first row, followed by the thematic dossier
and interlocutor below. In **List**, the target date and its apply button complete the
filters. The fields rearrange on smaller screens.

In **Graph**, memories load without a time range filter or a global node cap.
All known directories load when opening the graph, in pages. Zooming reveals their files;
you no longer need to discover subdirectories one at a time.
In overview, dense maps spatially group directories within each share. Approaching or
opening a group reveals the already loaded directories.
Below the graph header, the legend groups node kinds, relationships, then age markers
and zoom and fullscreen controls.
Node size and opacity follow a linear scale of last activity relative to the oldest and
most recent nodes in the loaded graph. The legend shows both dates; hiding a node kind
does not change this scale. Older nodes remain visible and their labels retain their contrast.
Items hidden by a filter, folding or framing contribute to the size of their visible
representatives, up to four times their normal diameter. Their weight is shared between the
nearest linked representatives and follows hidden parents; known children that have not loaded
yet also contribute. The hidden-item count remains visible even if some have no representative.
Their reappearance removes that weight without moving nodes.
The graph is exclusively 3D. Captions of representatives with hidden items always remain
visible, even when distant or overlapping. If WebGL is unavailable, a message offers a retry.
Auto refresh applies additions, updates and deletions in the background every five minutes
while the tab is visible. It preserves the camera, positions, filters and open branches,
including after reconnection. Previously loaded directories are also refreshed. A temporary
failure leaves the graph usable; session or access changes still remove protected data.
When zoomed out, titles prioritize structural nodes and those with the most connections.
Symbols have two base display sizes: distant and near. Beyond the near zoom threshold,
further zoom spreads their positions without enlarging them. Other titles remain filtered to
avoid overlaps, including at maximum zoom; hovering or selecting reveals them.
Memories with exactly the same relationships to topics, contacts or other structural
anchors are grouped with a count. Only visible nodes are drawn. Minimum zoom fits the entire
graph to the window and always centers it after panning; zoom can reach one million times
this framing. Previews grow later, depending on neighbor spacing, up to their actual pixel
dimensions. Hiding a kind reorganizes and frames the remaining items; showing all kinds
restores the saved positions.
Root directories keep their titles visible even when zoomed out. Memory stores the Tool's
label as their title, falling back to its scheme, such as `nextcloud://`, when no label exists.
Synchronization repairs old “.” and “/” titles while preserving valid custom titles.
The graph uses this stored title.

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
Standalone memories are private to their agent, with no title input or sharing control.
Dream automatically merges compatible duplicates during idle time when they reach the
configured similarity threshold, initially **92%**. Set this threshold in
**Preferences > Memory**; merging no longer has a mode selector. Updates remove the
old modes while preserving custom thresholds. Disabling Dream suspends this treatment
along with its other maintenance work.
Dream can also retain a durable fact from a transcribed audio message or an attachment already
analysed in a Task linked to the conversation. It preserves evidence and coverage limits;
an unanalysed attachment cannot establish a fact. Late evidence can add memories.
For new memories produced by this treatment, removing the source, correcting the transcript
or revoking the connection removes the fact from recall unless another independent valid
source supports it.
For a document, this content is an optional synthesis:
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
Invalid or incompatible saved state is automatically discarded: positions are rebuilt and
saved without changing Memory data. Network failures offer a retry without closing or
moving the graph; subsequent interactions also resume saving.
The **Reset node positions** button to the left of **Auto refresh** discards saved positions for
the current context, rebuilds the automatic layout and fits the view. Node kind filters
remain active; the new layout is saved for subsequent visits.
Zooming, unfolding and closing node details preserve positions. Zooming out also simplifies links and titles.
Large maps place items near their anchors before settling and load all pages matching the filters.
Spatial loading and subgroups remain the next steps
in the [multi-level memory graph plan](../../../project/plans/graphe-memoire-multiechelle.md) (in French), with `partial` status.

## Preferences, monitoring and account

**Administer → Preferences** (`/params`) presents a section grid and submenus for System,
Language, Messaging, Memory, Dream, Voice, Audio, Processes, Tasks and execution,
Harnesses, Search, Browser, Janus, Instructions and Logs. The
[generated map](../architecture/generated/navigation.md) provides each route.

In **Preferences → Messaging** and a Tool’s **Messaging** tab, network notices help prepare
[bridge tests from a local instance](../bridges/telegram-whatsapp.md).
Telegram, Matrix and Nextcloud Talk do not require a public Galaris URL for messages.
WhatsApp requires a public HTTPS webhook; its warning appears for a local or private address
or one without HTTPS. OneBot needs an address reachable from the adapter, including through
a local network or VPN. These warnings use the browser address and do not block saving.

The **OneBot 11** and **WhatsApp** preference tabs display an **Experimental messaging**
notice. If you encounter a problem, use **Report a problem on GitHub** to provide feedback
in the [project issues](https://github.com/lecluse-net/galaris/issues).

Under **Tasks and execution → Planner**, planning is bounded by maximum depth and maximum leaves.
There is no separate limit on the total number of steps.

Agents execute simple actions directly. For long or complex work, durable tracking retains
milestones and the next action while keeping one coherent deliverable together. If the scope
or expected depth is ambiguous, the agent asks in the conversation and waits before starting.
An unanswered question fails at its deadline; silence does not select a course of action.
Tracking is available through `task_get`.

Useful distinctions:

- **Monitor → Dream** (`/dream`) shows activity; **Preferences → Dream** (`/params/dream`)
  configures its behavior.
  Dream opens **Tracking** by default, showing indicators and action progress.
  **History** groups operations and their filters.
  **Preferences → Files** (`/params/files`) lets you select an agent, inspect traversals,
  start or cancel indexing, and retry repairs.
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
When conversation replaces durable work, its successor waits for confirmed termination
of associated tasks and processes. Uncertain remote stop remains pending and never
starts a duplicate. An active Goal requires its own coordination. Independent work and
your manual holds remain preserved. If a destination differs from the request, the agent
may ask for clarification on the same work before sending or changing a resource.
