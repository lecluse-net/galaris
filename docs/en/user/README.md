<p align="right"><a href="../../fr/user/README.md">Français</a> · <strong>English</strong></p>

# User and Discovery Guide

This guide introduces Galaris without requiring knowledge of models, APIs or Docker.
Visible screens depend on your account's permissions. For an overview, start with the
[feature tour](../features.md).

| Your need | Guide |
|---|---|
| Find a menu or screen | [Navigation and workflows](navigation.md), [generated map](../architecture/generated/navigation.md) |
| Assign and track work | [Tasks, milestones and recovery](tasks.md) |
| Organize authored content | [Document library](documents.md) |
| Write, link, share and export | [Rich content](rich-content.md) |
| Manage JSON data | [Datasets](datasets.md) |
| Explore an agent's locations | [Files](files.md) |
| Edit a repository with an agent | [Conversational Git editor](code-editor.md) |
| Build and observe a workflow | [Internal business processes](internal-processes.md) |
| Organize agent access | [Teams and dialogue permissions](teams.md) |

Detail, form and Lab benchmark windows scroll their content while keeping the title
and close control accessible.

## Galaris, Simply

A Galaris Agent is a software collaborator with:

- a required first name, an optional last name, a role, and behavioral instructions;
- a language model for understanding and drafting;
- authorized tools for searching, reading, creating, sending, or running a Process;
- governed memory, Working Set documents, and an activity history;
- an execution driver, that is, the concrete way its work is executed.

Galaris is the orchestrator around these Agents. It receives a request, chooses an Agent, retains the Task, supervises its execution, and returns the result. A model can make mistakes: the interface therefore shows the steps, tools used, and failures instead of pretending that every response is necessarily a successful action.

## First Login and Orientation

Open the address provided by your administrator, then log in with your email address and password. If open registration is displayed, you can create an account; this does not automatically grant you access to Agents or Tools.

On an instance with no accounts, the first signup creates the administrator. Registration
then closes by default. **Preferences → System → Allow users to create their own accounts**
reopens it immediately; new accounts have no permissions until a role is assigned.
Disabling this setting closes the signup form and API while existing accounts can still log in.

After login, Home displays Welcome when the instance default language, a usable LLM, or an agent
is missing, even if your profile already has a language. Without configuration permissions, the
journey explains the required access. Saving the language restores the normal home page when
the other required items are configured; `/welcome` remains accessible.

The LLM step opens **Providers & models**. It is complete only when a conversational model
belongs to an active provider with its required credentials configured. OpenRouter is enabled
by default, but its API key must be entered. A local provider that does not require a key can
complete the step without one; an OAuth provider must be connected. This check uses the saved
configuration; test the connection to verify that the credentials are valid.

The welcome journey presents seven steps in a timeline that wraps to fit the available width,
without horizontal scrolling. Select a step to display its content
below, or use **Previous step** and **Next step**. The first step, **Default language**, uses the
same presentation: if the language is unset, users with parameter management permissions can
choose it directly; otherwise, the saved language is displayed. The choice saves automatically;
the profile language still takes precedence. In the other steps, the configuration button opens
the corresponding screen according to your permissions.

The sidebar shows only the screens authorized by your role:

| Screen | What it is for |
|---|---|
| Home | view available Agents, recent Tasks, and missing configuration steps |
| Agents | learn the role, personality, and capabilities of each Agent |
| Execution Tracking | separately track text conversations, calls, Tasks, Processes, and LLM calls in real time |
| Goals | track long-running missions, their cycles, evidence, and results |
| Topics | find global topics and related knowledge across multiple channels |
| Memory | search, read and correct an Agent’s private memories and authorised document syntheses; forget only standalone memories |
| [Files](files.md) | choose an Agent, browse their locations and directories, and open files or their domain views; loading on scroll |
| Dream | track background work, inspect its history, and manage file indexing per agent |
| AI Lab | analyze a Task and measure AI mechanisms on reproducible case sets |
| Processes | build and track an internal BPMN workflow, or launch an external workflow such as n8n |
| Tools | view MCP and REST API capabilities and agent connections; primarily intended for administrators |

To configure a REST integration, an administrator enables **API** on the Tool, then
enters its address and credentials in global parameters or the agent's connection.
API permissions come from the token at the third-party service. See
[Tool administration](../admin/tool-administration.md).

To connect an account to an MCP server, open the agent connection and click
**Connect account**. The provider asks for consent directly; Galaris retrieves the token
without technical fields to fill in. OAuth belongs only to the connection, never the Tool.
Each connection owns its authorization and its disconnect button. Tokens refresh
automatically when supported by the provider. See the
[Tool guide](../admin/tool-administration.md).

In **Providers**, an administrator can adjust concurrent LLM calls for each connection.
Voice conversations take priority, followed by text conversations and background work;
with a single place, the current call must still finish before the next one starts.

The LLM, settings, users, and permissions sections are administrative. Their absence from your menu is normal. In **Profile**, choose Français, English or 简体中文; this choice translates the interface and also becomes the reference language for your new Tasks. Your account menu lets you change your assignment if you have been assigned multiple roles. The permissions displayed change immediately with the active role.

The profile also lets you enable two-factor authentication with a TOTP application. Keep the recovery codes displayed during activation in a separate, secure location: they will not be displayed again, and each one works only once. After several incorrect passwords or codes, Galaris temporarily slows down new login attempts.

## Choosing an agent fallback profile

Agent managers can choose a **Primary profile** and an optional **Secondary profile (fallback)**
in **Agents → Edit → Models**. The secondary is used when the primary provider is overloaded
or unavailable. The conversation or Task retains completed work; LLM call logs expose the
failover details. An empty secondary selection does not replace a missing usage.

## Installing Galaris on Android or iPhone


Galaris is a Progressive Web App (PWA): it can be added to the home screen and launched from its own icon, like an application installed from a store. After an initial login from this icon, the session is automatically restored for 30 days of inactivity by default.

- on Android, installation is done from the Chrome menu;
- on iPhone, it is done in Safari using **Share**, then **Add to Home Screen**.

The address must be provided over HTTPS by the administrator. The PWA caches its interface, but conversations, Tasks, and other data remain online: Galaris is not an offline business application.

The [detailed PWA guide](pwa.md) describes installation step by step, updates, session security, and solutions to common problems.

## Creating Your First Task in the Interface

1. Open **Execution Tracking → Tasks**, then **New Task**.
2. Give it a short label, such as “June invoice summary.”
3. Choose the Agent whose area of expertise matches the need.
4. Put the complete instruction in **Objective**: expected result, inputs, constraints, and desired verification.
5. Leave **Mode** and **Effort** set to **Auto** for a first attempt.
6. Click **Create & run**. **Create** alone saves a paused Task, which is useful for preparing or having the request reviewed before launch.

The auto-approval option authorizes certain actions in advance that would normally require approval. Enable it only if you understand the possible effects on files, messages, or external services. Approval given to one Agent does not automatically authorize the Agents to which it delegates.

From the list, click a Task to open its details. There you will find the current phase, subtasks, Tool calls, related Processes, known LLM costs, and final response. The pause and resume buttons act on the work tree. **Force finish** is an administrative recovery action for a genuinely blocked execution: it marks the Task as failed and releases its lease; it is not an ordinary cancellation of the external work.

A temporary provider error in DeepSeek triggers automatic continuation in the same session,
retaining recorded work. Task retry limits apply; an action whose outcome remains unknown
requires reconciliation before continuing. Partial text after an error does not complete a Task.

New executions and model messages wake their observers as soon as they are saved. For an
internal inference, pause and stop remain responsive even when the provider stops producing
text. Reopening monitoring reads the saved events without restarting generation; closing
a monitoring view alone does not stop it.

Executions without an explicit response budget automatically request the model's published
output capacity when known. Existing configured models need no extra setting. This avoids
small provider defaults; their physical limit still applies, and a cut-off response does
not complete the Task successfully.

If you ask to replace a running Hermes task, the new work waits for confirmation that its
predecessor has stopped. A network outage or Galaris restart does not automatically launch
the replacement: verification resumes from the saved information. A pause you requested
still applies after confirmation. If an older Hermes instance remains waiting, ask your
administrator to check its update status.

With the internal harness, three identical errors or three repeated calls without progress
prompt the agent to change approach, reread relevant skills, or check arguments. Tools remain
available so the agent can continue; if it cannot proceed, it explains the repeated errors
and what remains blocked. Overall execution limits still apply.

With this harness, a tool error may remain visible while the agent continues working: it can verify the
state, correct the call, or choose another method. A failed external response does not
prove that a write had no effect; the agent must verify it before repeating it. Very
long results may reach the model as explicitly partial previews, with available
pagination information. Such a preview proves neither missing source data nor task success.

If the Agent invents a top-level parameter for a tool whose schema strictly lists its
accepted parameters, Galaris ignores it and tells the Agent which parameters are available
in the result. Nested objects and composed schemas retain their validation. A missing required parameter or an
invalid value still rejects the call; the Agent must correct it. Tools that accept
free-form parameters retain them.

For a Hermès Agent configured with its own LLM provider, the Task and its result remain visible, but Galaris cannot display intermediate LLM calls or their detailed cost. This does not mean the Task was lost: these calls take place directly within Hermès.

When an agent delegates work, it checks the recipient's access to cited documents.
Missing access prevents task creation and identifies the recipient and required right.
The parent waits for child results before resuming consolidation; tasks with matching
labels remain distinguishable by their references. An authorization answered from the
permissions page also displays its decision in Chat.

## The Three Forms of Request

### Discuss

Ask a question as you would ask a colleague. A short request with no external action is normally handled immediately in `standard` mode.

Example: “Explain the difference between a quote and an invoice.”

### Perform an Action

Specify the expected result, target, and useful constraints. If a Tool is required, the Agent must actually call it; a simple statement such as “done” with no Tool trace does not validate the action.

Example: “Send the `reunion.md` meeting report to the Alpha Project room.”

### Delegate a Long-Running Goal

Describe the final deliverable rather than a step-by-step conversation. When the driver allows it and the work contains several distinct units, the dispatcher may ask the planner to create a durable plan.

Example: “Compare these three offers, produce a reasoned table, verify the totals, and share the file in the Purchasing room.”

A planned Task remains finite work: it ends after the requested delivery. A **durable Goal** is different: Galaris launches successive cycles, evaluates progress after each cycle, and continues until success or explicit termination.

When an Agentic HR Agent has the corresponding management capabilities, you can ask it, for example:

> Give the Sales Agent the durable Goal “Structure prospect tracking,” with the Management Agent as the referent, then tell me how it is progressing.

The HR Agent can then create the Goal with a distinct owner and referent, list or search an Agent’s Goals, view their tracking and cycles, modify them, pause them, resume them, trigger a cycle immediately, close them, or delete them when no cycle is in progress. Sensitive changes use the Goal’s current revision so as not to overwrite a concurrent change.

The single **Skills** Tool has four server-owned scopes: `usage` to use authorized generic
packages and active personal packages; `personal` to manage the agent's own packages; and
`team` to also manage packages and generic permissions for agents in any of its teams;
`all` to administer the entire catalogue and all permissions. Writes require an active Skills
connection. Agents cannot increase their own scope. `skill_read` reads the central `SKILL.md`;
references and other files use File Sharing. A personal package uses
`galaris://skill/personnal/<agent_id>/<code>/` and stays private: even an administrator cannot
assign it to another agent. Explicit ownership release requires a revision and operation ID,
turns it into a generic package and enables it for nobody. Replaying the operation preserves
permissions configured since conversion. Loading changes apply to the next execution;
instructions already loaded remain in the current context.

In **Skills → Personal skills**, inspect private packages owned by agents within your
management scope, even when Dream is disabled. The list shows the owner, activation,
validity, files and last modification. Filter by agent or search by name/code, then use
**View** to read `SKILL.md` and its references. Configure the scope in **Tools → Connections →
edit the Skills connection → Management scope**, choosing `usage`, `personal`, `team` or `all`.
This parameter belongs to the connection and has no global inheritance; editing it requires
connection editing and global agent management. An agent in three teams can administer agents
included in at least one of those teams. Files are read-only
in this tab; agent editing, activation and deletion use MCP. These packages remain separate
from the generic library and cannot be shared.

### Using a Messaging System

In the default installation, `galaris-lab` and `galaris-knowledge` are globally disabled
and individually enabled only for the **Galaris** Agent created during setup.
Permissions remain configurable, and updates preserve previously saved choices.

The **Messenger** entry opens Galaris’s native messaging system when it is enabled and your role has the necessary permissions. You can create separate direct conversations with an Agent, search rooms, track unread messages, reply, attach a file, record a voice note, and start a browser call. The **Activity** panel shows publishable steps and Tools from the round. Archiving a conversation removes it from the current list without deleting its history; you can find it again in the archives. Internal messaging does not offer group creation or participant management.

Switching conversations updates the browser address. **Back** and **Forward** return to
visited conversations; going back before the first opening returns to the Chat home.
Selecting the current conversation again does not add a visit. Any open document is saved
before switching; if saving fails, the conversation and document draft stay open.

Text and selected attachments remain in the composer until sending is confirmed. After an
error, you can retry without entering them again; an unchanged retry keeps the message identity
to avoid a second admission if the first send was already received. Once confirmed, a slow or
unavailable conversation refresh does not block the next send or attachment selection. These
drafts remain in page memory: save any unsent content before reloading the page.

In native Chat, the small buttons beside “Thinking” control that response: **Pause** saves
progress, **Resume** continues from it, and **Stop** removes the Agent’s response from the
round, including its provisional text. Your message remains visible. **Reply now** requests an answer using available
information, without new tools. An already running tool finishes before stopping; completed
actions are preserved. Resuming uncertain previous effects is refused. Paused responses
remain visible after reopening; stopped responses remain absent, and you can send a new
request. Background Tasks and Processes have their own controls.

After your message is admitted, “Thinking” appears as soon as the interface
receives the queued round, before its first fragments. A response already in
progress remains visible if you send another request.

Before you select a conversation, the Chat home screen first shows **Conversations**,
with the same list as the chat window's **Conversations** section, including older and empty
ones, with the usual pagination. Agents appear below, under **Who would you like to talk to?**.
Click an agent to open a new conversation with that agent preselected, then confirm its name
and preferences. The suggested name accounts for your existing conversations with that agent,
including archived ones: if the name is already taken, Galaris adds **(2)**, **(3)**, and so on.
You can edit the name; availability is checked again on creation and a suffix is added if needed.
**Conversations** appear as cards with the agent, unread messages and
the date of the last message. Previews respect your privacy preference. On this home screen,
search and filters remain visible: external conversations, archives and, with the appropriate
permissions, an agent’s view. Cards adapt to the available width and use one column on phones.
Agents and conversations load in pages of 50. Each list shows pagination only above
50 results, with a choice of 10, 20, 50, 100 or 500 items per page. Changing a filter returns
conversations to the first page.

The panel sections appear in this order: **Conversations, Documents, Tasks, Processes**.
They open automatically when they contain items and collapse when empty. You can collapse them
manually; an ordinary refresh does not reopen them.
The search button in the **Documents** header finds accessible documents.
The conversation bell opens a menu to enable or disable notifications on this device
and mute or restore notifications for the conversation.
The **+** button in the same header creates a document even when the section
is collapsed, provided you have edit permission.

On desktop, when a document is open alongside the conversation, each message also gives the
Agent the last text selection in that document, the last cursor position, and an excerpt of
the area visible when you send. Select a passage, then write “rephrase this passage”; moving
to the message field preserves that reference. This works in read-only documents, HTML content,
and Source. Datasets have their own editor. Long excerpts are truncated and include the document revision.
Switching documents or replacing content invalidates previous positions; closing the pane stops
sending this context. The internals of embedded applications are not inspected. The Agent’s
document permissions remain unchanged.

In the **Conversations** header, the filter button to the left of **+** shows or hides
the **Me / agents** selector, search field, and external and archived conversation checkboxes.
This area is hidden by default; hiding it preserves the filters. **+** creates a conversation
subject to your permissions.
The **Tasks** section retains Tasks linked to the displayed messages and their subtasks.
It also shows the Agent’s ongoing Tasks and Tasks awaiting a reply, including work created
elsewhere or before the visible messages, even in an empty conversation. Queued Tasks and
automatic waits remain visible; completed or manually paused work from elsewhere is not
added. The list updates live, and clicking a Task opens its details, subject to your read permissions.

Requesting work again does not systematically retry an older failed Task. The Agent must inspect
the error and partial results: it can retry the same Task when you explicitly request it or the
failure's cause has been corrected. If the approach or instructions must change, it prefers a new
Task taking the failure and your corrections into account, through a channel that allows Tasks.
Manual retry also remains available from the Task detail view.

A native conversation never opens a Task, even if the message explicitly requests it. It can, however, launch a configured Process. To delegate durable work to a Task, use the Tasks page or another channel whose admission policy allows it.

If your organization connects Nextcloud Talk, Matrix, OneBot, Telegram, or WhatsApp Business, send your request to the Agent’s account in the designated room. Configured platforms can operate simultaneously, and the response returns through the original connection and conversation. Avoid resending a slow request multiple times: instead, open the created Task or Process, or ask for its status.

Goal-cycle messages use the messaging connection selected for the Goal's referrer. Keeping
Nextcloud Talk active therefore does not redirect messages from a Goal assigned to internal Chat.
For an outgoing message without a fixed channel, Galaris uses the recipient's latest inbound
exchange, then internal Chat by default. The Agent may explicitly request another channel.

In **Tools → Connections → edit the messaging connection**, a global manager can set
**Inter-agent communication** (`tools.management_scope`): **None** (`none`),
**Agents in its teams** (`team`) or **All agents** (`all`). The default `team` preserves
communication between agents sharing at least one team. This setting applies to sending and
receiving on that connection; human contact rights remain independent. Internal requests
check both agents' connections before creating a Task.

When a Task asks another Agent for help over the internal channel, it creates a tracked request
and waits for its result, without requiring a conversation with a human. Follow the request
through its Task link. Acceptance confirms neither the colleague's reply nor completion of the
requested action; contact and sharing permissions still apply.

Attachments remain files. Specify their name and the expected action: “read,” “modify,” “compare,” “return,” or “share.” For a large file, the Agent may transfer it without loading all its content into the model.

In a writable internal discussion, **Rename** changes an attachment’s name before or
after sending it. Documents offer the same action on their attachments when you can
edit them. Enter the complete name including the extension; file links and content
are preserved. Closing the form without confirming discards the draft.

To exchange files with agents from your PC, use a Nextcloud folder accessible to the agent's
connected account, synchronized or mounted on your computer. Specify the folder and file.
Names containing accents, spaces, `#`, `?`, and `%` are preserved. If you change a file while
the agent is editing it, the concurrent edit is rejected: the agent must read your version
before continuing. Search may continue across several pages; content search reports files it
could not examine. Generic deletion only removes individual files, never an entire folder.
An active connection with incomplete configuration remains unusable.

Samba and Windows shares are also available through the **Samba / SMB 2–3** bridge.
See the [Samba setup and usage journey](samba.md) to connect a share and manipulate
its files through the same File sharing functions.

The Agent interprets a resend request and selects the file and destination before sending.
A document open beside the chat provides context; its words never trigger automatic redelivery.
Attaching an image to a document and sending it back in the chat are separate requests.

### Understanding Short Conversations and Background Work

During an update or restart, an ongoing conversation automatically continues from its saved
state. You do not need to resend the message. Confirmed actions are retained and interruptions
do not consume attempts reserved for errors. If an external action or delivery remains
uncertain, execution tracking reports it for verification before repeating it.

An Agent can consult the agent directory during a conversation to identify a colleague and
their role, without creating a Task. Asking for a colleague's contribution follows the usual
action policy and contact permissions; reading a profile does not itself contact that Agent.

On initialization, **Console SSH**, **Image**, **Mail**, and **Multimedia** are unavailable
in conversation mode by default. An administrator can enable each Tool for conversations
in the Tool catalog. This setting does not change access in Tasks; updates preserve
previously saved choices.

A received message is no longer systematically turned into a Task. The conversational controller aggregates messages arriving in bursts, reconstructs the useful history, and prepares a short response. When a Tool must produce a lasting effect or work will take time, it creates a background Task or Process and gives you its reference.

In **Execution Tracking → Text conversations**, you can see processed or pending messages, rounds, their attempts, LLM calls, delivery, and any errors. A response between two Agents is admitted only when a fresh request is waiting for it; this safeguard prevents automatic loops of polite exchanges.

Execution details show time to the first observed text or tool call, split into time within
and between LLM calls. For Tasks, preparation, admission and waiting before the first claim
remain separate. “Not measured” means the required evidence is missing; these server timings
do not prove delivery.

### Talking to an Agent in Real Time

When Matrix or Nextcloud Talk and a voice capability are configured, an Agent can participate in a call. Depending on the voice selected on its profile, Galaris uses either the transcription → Agent → synthesis pipeline or a low-latency native audio session. The second mode may retain no intermediate transcription: the absence of text in a native turn therefore does not indicate a lost call.

The **Phone Calls** tab shows active or completed calls, their turns, interruptions, responses, LLM calls, and errors. A voice turn can also create a background Task; it then appears in the **Tasks** tab and continues after the call ends.


In a turn's detail in **Phone Calls**, agent managers with Task edit permission can
**Force hangup** audio processing. Confirmation retains history; pending teardown
remains explicit. Deleting a turn retains its content until audio cleanup completes.
Reopening follows the persisted request through temporary service interruptions.

### Summarizing Audio, Video, or a YouTube Video

If the Agent has the Audio Tool, attach the recording and then directly request the expected deliverable, for example:

> Transcribe `reunion-projet.mp4`, then summarize the topics discussed, decisions, owners, and actions with their deadlines. Also retain the complete transcription.

The same Tool accepts a public YouTube URL directly. You therefore only need to ask, for example:

> Summarize this video in French, identify its main ideas, and retain the useful timestamps:
> `https://www.youtube.com/watch?v=…`

Galaris processes the media as a large resource: it retains the original Tool URI without copying its bytes into the conversation, temporarily materializes it, extracts its first audio track, ignores the video, and normalizes the sound to mono 32 kHz MP3 at 96 kbit/s. The transcription model receives this normalized audio file, and Galaris writes its result to a `.txt` file.

Beyond approximately 10 minutes, Galaris warns you that processing will take longer, splits the audio into segments, transcribes and summarizes each segment, then merges these summaries into an overall `.summary.md` summary. The Agent reads this short summary to respond to you; the complete verbatim remains available without being loaded in full into its context. If the meeting is extremely long, several levels of reduction are applied automatically.

For a YouTube URL, Galaris does not download the video and does not use the transcription model. It retrieves an already available subtitle track, preferring manual subtitles in the requested language and then accepting automatic subtitles or another language. The `youtube-<identifier>.txt` file indicates the language, whether the track is manual or automatic, the source, and the timestamps. A long video also produces `youtube-<identifier>.summary.md`, which the Agent uses to respond without loading the entire text.

HTTPS URLs for `youtube.com/watch`, `youtu.be`, `shorts`, `live`, and `embed` are recognized. The video must be public and provide accessible subtitles. A private, restricted, or subtitle-free video produces an explicit error; Galaris does not automatically download its audio track as a fallback.

The main audio and video formats recognized by PyAV are accepted; a corrupted, unreadable file or a file without an audio track produces an explicit error. You can specify the language of the recording, but automatic detection remains available.

Normalization greatly reduces the size of a video, WAV, or high-bitrate media. It does not necessarily reduce the transcription provider’s charge when the provider bills based on recording duration rather than transmitted volume.

### Analysing a large document source

Attach the file or supply an accessible URI and ask a precise question with the expected references:

> Analyse this report in batches, identify decisions and figures in its last pages,
> cite source pages and state which parts could not be read.

The agent can start a durable document analysis, read progress and coverage and request cancellation.
Completed batches are retained; interrupted billable inference is never automatically replayed.
The analysis belongs to the model service and does not appear as a business Process. Source access
and version remain checked; moving or modifying the file can invalidate results. Coverage describes
units supplied to the model without certifying answer accuracy. See
[reading formats and limits](../dev/document-qualification.md).

### Launching a Business Process

The **Processes** page combines internal BPMN workflows and external workflows, including n8n.
Ask the agent to launch a Process with the required information and files. Internal Process
pages are for editing and monitoring; launch takes place through Chat without a manual launch
form. Human activities ask through messaging, and an answer continues the existing run.

The [internal Process guide](internal-processes.md) explains actors, variables, branches,
run data and controls. Administrators integrating external software use the
[engine guide](../dev/process-engines.md).

Technical tool catalogue refresh does not appear on this screen. If the Agent reports a
partially refreshed catalogue, ask it to retry refresh for the indicated agents without
repeating the configuration change that was already saved.

A local cancellation does not always guarantee that the external engine will stop immediately. When the interface indicates that the remote execution may continue, check the target service before relaunching the Process.

## Memory, Documents, and Topics

Files uploaded to Documents and Chat use shared internal storage. Existing links and access
rights remain valid after migration. An agent can also create an independent private file
with `file_create`, `path="file://"` and a readable name. External references such as Nextcloud
retain their provider and are never imported by migration. See
[storage and backups](../dev/file-storage.md).

To personalise a document icon, click its icon in the editor header.
In the list and tree, clicking the icon simply opens the document.
For a folder, open its icon picker. Use the **+** button to
upload an SVG. The size limit is the same as for files (100 MB by default); scripts
and external content remain prohibited.

Agent selectors follow alphabetical order by first name, then last name. The last selected
agent is kept in frontend memory and offered when moving to another page, including between
**Memory** and **Contacts**, provided it remains available and authorized. An empty choice
or **All agents** does not replace the remembered agent. An explicit selection, including
one in a link, takes precedence. A full reload or logout clears this choice.

Memory search preserves the current contact context in text conversations, voice calls and their
associated Tasks. Memory commands and agent searches use the same context.

Recent conversation memory is reconstructed automatically. For durable context, Galaris can inject a bounded reminder of relevant memories before execution. If semantic search is unavailable, the interface indicates the fallback to lexical search.

A memory's details include **Temporality (optional)**. Enter only meaningful components:
day, month, year, weekday, hour and minute. Empty fields are unrestricted: day 27 and month 9
mean every September 27; adding a year restricts the match to that year. A date without a time
matches the whole day. Hour 9 without a minute matches 9:00–9:59. The timezone is configured globally for Galaris (`TZ`);
it cannot be changed in this form. An interpretation appears below the fields;
**Remove temporality** preserves the memory and its content.

Current and upcoming matches enrich agent context under the same access rules. Configure the
lookahead in **Preferences → Memory** (24 hours by default). Context remains bounded; agents
can inspect additional matches with `memory_upcoming`. This creates no notification and does
not expire the memory. Agents and Dream reserve anchors for intended reminders (appointments,
birthdays or habits). A historical date stays in the prose and does not itself justify an anchor.
Adding an anchor excludes the memory from automatic recall outside its period and gives it priority
when it matches. Undated memories continue through ordinary relevance search.

In **Memory → List**, the temporal filter always applies, starting with the first search. A single
date and time field is prefilled with the current instant in Galaris's global timezone. Edit it and click **Apply**
to check that exact instant, with no lookahead or timezone to enter. The list unites two independent
selections: **undated memories** matching text, topic and interlocutor filters, and **dated memories**
matching the target time regardless of those other filters. Dated memories outside their period are excluded.
The target date appears in the filter; dated results display their matching time in Galaris's global timezone, independently of the browser.
The field is required and the filter cannot be disabled. The simulation
uses current memories, validity and access rights; it does not reconstruct historical state.

Search is integrated into **List**; the two tabs are **List** and **Graph**.
A text query uses lexical and semantic recall under the selected filters. Relevant results
are bounded to 500 undated memories. Calendar matches are added independently of that limit.
The combined results can be paginated and sorted without duplicates; calendar matches appear first by default. A message asks you
to refine the search when this selection is truncated and indicates fallback to matching words
when semantic search is unavailable. With no text, the list browses all undated memories matching
the filters, plus calendar matches.

At a close zoom, visible files, attachments and HTML documents show their thumbnail instead of
the turquoise square, at a larger size. Ready previews load first; missing previews are
generated progressively. Image counts adapt to client capabilities;
distant images are hidden and cached for reuse when returning nearby. Unavailable previews
keep the square. A preview obtained in the details also appears in the graph.
Thumbnails retain their proportions within 320 × 320 pixels; the graph displays these
images directly without recompressing them. Loading thumbnails preserves node positions.
Audio files display a musical note inside their turquoise square. Datasets keep their
document symbol.

Clicking a node opens its modal directly, showing its kind, visibility, access count and
last activity. Graph links open neighboring nodes; folders and conversations have a modal
for their metadata and relationships. Closing with the button or backdrop returns to the
graph with its viewport preserved.

The **Graph** tab displays the 3D map exclusively.
3D displays pages as they arrive, starting with File Share roots, topics and contacts,
then folders/directories, documents and details. All known directories load on opening.
Approach a directory to load its known files, in pages of at most 500;
visited branches return when reopening. Their depth follows
local distances rather than distant fixed levels. A link disappears when either node
passes behind the camera. The map uses folder SVGs, file and media glyphs, borders,
relation colors, curves and relative widths. Links are thicker for visibility, and long links use
more segments to preserve their curve. Labels have no background.
Distant nodes are roughly half the size of nearby nodes.
In 3D, a left click without movement opens the node. Hold the left button and drag to
orbit the pointed node without centering it on screen. If the press starts on the background,
dragging pans the graph until release without rotating. Panning follows mouse movement near
nodes even after zoom, with a stable speed throughout the drag. Releasing after moving never opens a modal, even when returning
to the starting point. Right-drag pans. The wheel moves the camera toward the pointer:
the aimed point stays under the cursor while approaching or backing away, without rotation.
Pinch and zoom buttons move along the central viewing axis. You can pass a node and keep travelling through the graph. Moving
back to the overview shows the entire graph centered. 3D framing fills the available
space according to width, height and depth, with a margin to keep glyphs fully visible.
Arrow keys select a visible node, **Enter** opens its details, and **Home** centers the
whole graph. The camera is saved for reopening. If 3D rendering is unavailable,
a message offers to check WebGL support and retry.
Dense areas can also show a **Group of N items**, even without a shared Topic.
Click its marker to approach and reveal the members; moving back groups them again.
These display groups do not change memories or their relationships.

Items hidden by a filter, folding or framing enlarge their visible representatives, up to
**four times their normal diameter**, with diminishing growth. Their weight follows confirmed
links and hidden parents; it is shared between the nearest representatives when there are
several. Known directory children that have not loaded yet also contribute. Captions of
representatives with hidden items always remain visible, including distant and dense views.
As items reappear,
their contribution disappears without changing their coordinates. The **hidden items** count
also reports items without a visible representative; hover captions indicate the hidden items
linked to a node. Inaccessible resources do not contribute to the calculation.

In **Graph**, branches with at least eight items exclusively linked to the same anchor are
represented by a larger anchor and a count. Zoom in or click the group to see its items;
the **Zoom in** and **Zoom out** buttons are keyboard accessible.
**Reset node positions**, to the left of **Auto refresh**, replaces saved positions for the
current context with an automatic layout and fits the view. Node kind filters are kept;
the new positions are saved for reopening. Zooming out and **Fit graph to viewport**
fold the branches. Zooming, unfolding and closing node details preserve positions.
A worker prepares placement; orbiting and zooming start no simulation. Clicking a group
frames its anchor. Zooming out hides detailed links and some ordinary titles; zoom back
in to restore them.
Memories sharing exactly the same relationships to structural anchors are also grouped;
each group retains connections to every anchor. Symbols have two base display sizes,
distant and near: further zoom beyond the near threshold spreads their positions without
enlarging them. Previews grow later, depending on the space between neighbors, up to the
thumbnail's actual pixel dimensions, never beyond them. Ordinary titles remain limited to avoid overlaps and remain available on hover or
selection; representatives of hidden items always retain their captions. All pages matching the filters load without a global node cap;
exclusive branches are folded on opening. Large maps place items near their anchors before
settling. The minimum zoom always fits and centers the entire graph, including after panning.
Zoom can then reach one million times this framing. Only nodes in the visible region are
drawn. Hiding a kind reorganizes and frames the remaining items; showing all kinds restores
the saved positions. All pages still load; network loading by visible region remains planned.

A document used with the same Agent remains a recall candidate after many ordinary exchanges.
The Agent recovers its reference, current title and revision, subject to current access rights.
Deleted or newly private documents are excluded. Recall remains bounded: provide an exact URI
if an older document cannot be found.

Each standalone memory remains private to its Agent and displays keywords, provenance and a
label derived from its content. A document retains its title, full content and access rights; its Memory
details hold an optional synthesis with independent history. **Open document** lets you edit
full content and sharing. The synthesis inherits current document permissions.
The list can be filtered by text, Topic, interlocutor and date; the graph shows memories
alongside documents, files, folders, contacts and Topics.

In **Memory**, authorized accounts can:

- search an Agent’s memories directly in List;
- view content, revisions, provenance, relationships, and uses;
- correct or archive an ordinary memory;
- share a document for reading or editing from its editor;
- create HTML working documents that evolve across multiple Tasks;
- explore the graph over a given period;
- permanently forget an item, an irreversible action reserved for the appropriate permissions.

Agents are encouraged to consider a Dataset when structured data can serve several
documents, calculations or Tasks. For example, a company record can hold its share capital
and currency for reuse in a presentation or budget. Agents prefer an existing Dataset,
preserve sources and uncertainty, and read current data when drafting. The choice remains
suited to the need: an isolated fact or short answer does not systematically require a
Dataset. Prose drafted from this data does not automatically update when the Dataset changes.

Agent profiles, Goals, and cycles are read-only projections: modify their source rather than their memory copy. Contacts from messaging systems contain only the minimum identity required and remain private to the owning Agent.

In **Knowledge → Contacts**, select an agent and click a contact or its pencil action to edit
its display name. One display name applies to the entire contact. The dialog offers neither
direct account attachment nor account deletion: to group accounts, select two contacts with
the checkboxes and use **Merge two contacts**.
To separate an account, use **Split** in the contact dialog, then save. Each selected account
gets a separate contact with the same initial name and is preserved. Keep at least one account
on the original contact. Memories and history remain on that original contact; future messages
from the separated account resolve to its new contact. Cancel discards staged splitting.
A concurrent edit requires reopening the contact before retrying.

**Add email contact** accepts a name and a valid email address. This address book remains private
to the selected agent: the correspondent does not need to be a user or an agent. Creation sends
no email, creates no account, and grants no access. An address already in this agent’s address
book is rejected regardless of case. These actions require `MEMORY_EDIT` and management access to that agent.

For internal Chat, the **Galaris user** identity is sufficient: no second internal messaging
identity is created. DbAdmin synchronization removes existing redundant internal aliases
without deleting the contact or its memories.

Manually created and split contacts retain their names and accounts across future messages.
Split contacts can be reunited by merging. If saving fails, the draft remains available for retry.
Cancel closes the dialog without saving the draft.

File entries remain empty until they have notes or a useful description.
Their technical metadata (URI, size, type, date, fingerprint) does not fill the description.

**Topics** group knowledge around a global subject, even if it comes from different rooms, Tasks, or calls. Dream performs this classification in the background; authorized accounts can also correct an item’s assignment. Dream can consolidate memories and separately analyze Task results to strengthen Skills specific to the Agent. A self-learned Skill is added to future executions only after reaching the configured evidence and score thresholds; the **Skills → Self-learned** page lets you view its evidence and suspend it.

Dream also associates documents and Datasets with topics. A topic's **Linked content** tab appears
first and opens by default, letting you open associated conversations, documents and Datasets you can read.
Tasks have their own tab, and the **Memories** tab gathers linked memories with their previews and details.
Counters cover conversations, tasks, memories, documents and Datasets; text and voice rounds are no longer shown separately.
Merging topics preserves these associations; deleting a topic preserves its resources. Topic creation follows the existing
Dream setting; in proposal mode, these resources only reuse existing topics.

Document and Dataset editor headers show the UUID followed by the same topic badge as Chat.
Click the badge (or **No topic**) to inspect the assignment and change it with resource editing
and Topic editing rights. The open draft is preserved; concurrent changes require a refresh
before retrying. The document reference button still copies the complete address.

## Organizing and following work

Galaris distinguishes effort level, work method and coordination. A simple action can run
directly; a long mission keeps milestones within one Task; several independent results
can form a plan. Ambiguous scope requires clarification before execution.

The [Task guide](tasks.md) explains Chat directives, milestones, progress, questions,
authorizations and recovery after failure.

## Measuring Quality with the AI Lab

Authorized accounts have access to an **AI Lab** that separates two uses: full analysis of a real Task and reproducible benchmarks for the Dispatcher, Planner, and Task/Conversation/Voice executors, as well as Dream/Goal mechanisms.

The [complete AI Lab guide](lab-ai.md) explains how to import a real case, build a reference, run a candidate model, assess relevance, and calibrate the automatic judge. A percentage in the Lab is never sufficient proof on its own: it must be interpreted together with the dimensions, coverage, errors, and dataset.

## Connect an external Codex or Claude Code client

To select usages such as `profile1/text/high` from a shared catalog of all profiles,
see the [profile API guide](profile-api.md).

These guides provide configuration examples, user API token authentication, and
verification commands:

- [Codex CLI](codex.md): `~/.codex/config.toml`, Responses provider at `/api/profile/openai`.
- [Claude Code](claude-code.md): `.claude/settings.json`, four tier aliases and catalog at `/api/profile/anthropic`.

All profiles share the URLs; the `model` field carries the complete selector.

Claude Agent can also be selected directly as the **Task Engine** on an Agent’s profile. Galaris then provisions an isolated Claude Agent SDK container, provides it with the resolved internal model, the Agent’s Skills and MCP, and displays the text, Tool calls, LLM calls, and terminal result live. No direct Anthropic account or token is required.

- [Writing and linking rich content](rich-content.md): editor, links, document images and history.
