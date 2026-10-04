<p align="right"><a href="../../fr/user/README.md">Français</a> · <strong>English</strong></p>

# User and Discovery Guide

In detail windows, forms and Lab benchmarks, only the content scrolls: the title and its
close button remain visible even with long content.

To find a screen, see the [menu and workflow guide](navigation.md) and the
[generated navigation map](../architecture/generated/navigation.md).

This guide is intended for anyone who wants to use Galaris without knowing about language models, APIs, or Docker. The screens available depend on the permissions assigned to your account.

For an overview, see the
[complete feature tour](../features.md).

To organize access to agents, see [Teams and dialogue permissions](teams.md).

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
| Memory | search, read, correct, share, or forget an Agent’s authorized memories |
| Dream | view the filing, extraction, and learning operations executed in the background |
| AI Lab | analyze a Task and measure AI mechanisms on reproducible case sets |
| Processes | launch and track an external workflow, such as n8n |
| Tools | view authorized capabilities and connections; primarily intended for administrators |

The LLM, settings, users, and permissions sections are administrative. Their absence from your menu is normal. In **Profile**, choose Français or English; this choice translates the interface and also becomes the reference language for your new Tasks. Your account menu lets you change your assignment if you have been assigned multiple roles. The permissions displayed change immediately with the active role.

The profile also lets you enable two-factor authentication with a TOTP application. Keep the recovery codes displayed during activation in a separate, secure location: they will not be displayed again, and each one works only once. After several incorrect passwords or codes, Galaris temporarily slows down new login attempts.

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

For a Hermès Agent configured with its own LLM provider, the Task and its result remain visible, but Galaris cannot display intermediate LLM calls or their detailed cost. This does not mean the Task was lost: these calls take place directly within Hermès.

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

The same HR Agent can audit the Skills available to an Agent and read a Skill’s central `SKILL.md`. It does not receive the package’s scripts, references, or other files through this Tool. These specialized capabilities are not granted to any Agent by default.

### Using a Messaging System

In the default installation, `galaris-lab` and `galaris-knowledge` are globally disabled
and individually enabled only for the **Galaris** Agent created during setup.
Permissions remain configurable, and updates preserve previously saved choices.

The **Messenger** entry opens Galaris’s native messaging system when it is enabled and your role has the necessary permissions. You can create a direct conversation with an Agent, or a group containing that Agent and colleagues, search rooms, track unread messages, reply, attach a file, record a voice note, and start a browser call. The **Activity** panel shows publishable steps and the round’s Tools, never the Agent’s private reasoning. Leaving a conversation removes your access without deleting its history for the other members.

Before you select a conversation, the Chat home screen first shows **Recent conversations**
with a new message within the **last 7 days**, from newest to oldest. The **+** button shows
all conversations, including older and empty ones, with the usual pagination. The **−** button
returns to recent conversations. Agents appear below, under **Who would you like to talk to?**.
Click an agent to open a new conversation with that agent preselected, then confirm its name
and preferences. The suggested name accounts for your existing conversations with that agent,
including archived ones: if the name is already taken, Galaris adds **(2)**, **(3)**, and so on.
You can edit the name; availability is checked again on creation and a suffix is added if needed.
**Recent conversations** appear as cards with the agent, unread messages and
the date of the last message. Previews respect your privacy preference. On this home screen,
search and filters remain visible: external conversations, archives and, with the appropriate
permissions, an agent’s view. Cards adapt to the available width and use one column on phones.
Agents and recent conversations load in pages of 50. Each list shows pagination only above
50 results, with a choice of 10, 20, 50, 100 or 500 items per page. Changing a filter returns
conversations to the first page.

The panel sections appear in this order: **Conversations, Documents, Tasks, Processes**.
They open automatically when they contain items and collapse when empty. You can collapse them
manually; an ordinary refresh does not reopen them.
The **+** button in the **Working documents** header creates a document even when the section
is collapsed, provided you have edit permission.

On desktop, when a document is open alongside the conversation, each message also gives the
Agent the last text selection in that document, the last cursor position, and an excerpt of
the area visible when you send. Select a passage, then write “rephrase this passage”; moving
to the message field preserves that reference. This works in read-only documents, HTML content,
Source, and JSON Datasets. Long excerpts are truncated and include the document revision.
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

Attachments remain files. Specify their name and the expected action: “read,” “modify,” “compare,” “return,” or “share.” For a large file, the Agent may transfer it without loading all its content into the model.

To exchange files with agents from your PC, use a Nextcloud folder accessible to the agent's
connected account, synchronized or mounted on your computer. Specify the folder and file.
Names containing accents, spaces, `#`, `?`, and `%` are preserved. If you change a file while
the agent is editing it, the concurrent edit is rejected: the agent must read your version
before continuing. Search may continue across several pages; content search reports files it
could not examine. Generic deletion only removes individual files, never an entire folder.
An active connection with incomplete configuration remains unusable.

The Agent interprets a resend request and selects the file and destination before sending.
A document open beside the chat provides context; its words never trigger automatic redelivery.
Attaching an image to a document and sending it back in the chat are separate requests.

### Understanding Short Conversations and Background Work

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

### Launching a Business Process

The **Processes** screen exposes the workflows that the administrator has associated with an Agent. Open a definition, enter its JSON input, and then launch an execution. Its status, output, events, and related Tasks remain available in the same screen.

Technical tool catalogue refresh does not appear on this screen. If the Agent reports a
partially refreshed catalogue, ask it to retry refresh for the indicated agents without
repeating the configuration change that was already saved.

A local cancellation does not always guarantee that the external engine will stop immediately. When the interface indicates that the remote execution may continue, check the target service before relaunching the Process.

## Memory, Documents, and Topics

Recent conversation memory is reconstructed automatically. For durable context, Galaris can inject a bounded reminder of relevant memories before execution. If semantic search is unavailable, the interface indicates the fallback to lexical search.

A memory's details include **Temporality (optional)**. Enter only meaningful components:
day, month, year, weekday, hour and minute. Empty fields are unrestricted: day 27 and month 9
mean every September 27; adding a year restricts the match to that year. A date without a time
matches the whole day. Hour 9 without a minute matches 9:00–9:59. The proposed timezone comes
from the application and can be changed. An interpretation appears below the fields;
**Remove temporality** preserves the memory and its content.

Current and upcoming matches enrich agent context under the same access rules. Configure the
lookahead in **Preferences → Memory** (24 hours by default). Context remains bounded; agents
can inspect additional matches with `memory_upcoming`. This creates no notification and does
not expire the memory. Agents and Dream reserve anchors for intended reminders (appointments,
birthdays or habits). A historical date stays in the prose and does not itself justify an anchor.
Adding an anchor excludes the memory from automatic recall outside its period and gives it priority
when it matches. Undated memories continue through ordinary relevance search.

In **Memory → List**, the temporal filter always applies, starting with the first search. A single
date and time field is prefilled with the browser's current local time. Edit it and click **Apply**
to check that exact instant, with no lookahead or timezone to enter. The list unites two independent
selections: **undated memories** matching text, type, topic and interlocutor filters, and **dated memories**
matching the target time regardless of those other filters. Dated memories outside their period are excluded.
The target date appears in the filter; dated results display their matching time in browser local time.
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
Loading thumbnails preserves node positions.
Audio files display a musical note inside their turquoise square. Datasets keep their
document symbol.

In **Graph**, branches with at least eight items exclusively linked to the same anchor are
represented by a larger anchor and a count. Zoom in or click the group to see its items;
**Branch details** also provides keyboard access. Zooming out and **Fit graph to viewport**
fold the branches. Up to 600 loaded items, the initial placement settles naturally,
with gentle rebalancing for at most 0.7 seconds after the graph changes. Zooming, unfolding and closing node details
preserve positions; larger windows retain fixed positions to bound computation.
New nodes fade into their existing positions; dense views and reduced-motion preferences
disable this effect.
Clicking a group frames its anchor. Zooming out hides detailed links and some titles; zoom
back in to restore them.
Shared nodes remain visible. Titles are limited to avoid overlaps and remain available on
hover or selection. The window is still limited to 3,000 nodes; refine filters to explore
other items. Loading by visible region remains planned.

A document used with the same Agent remains a recall candidate after many ordinary exchanges.
The Agent recovers its reference, current title and revision, subject to current access rights.
Deleted or newly private documents are excluded. Recall remains bounded: provide an exact URI
if an older document cannot be found.

In **Memory**, authorized accounts can:

- search an Agent’s memories directly in List;
- view content, revisions, provenance, relationships, and uses;
- correct or archive an ordinary memory;
- share an item directly for reading or editing;
- create Markdown Working Set documents that evolve across multiple Tasks;
- explore the graph over a given period;
- permanently forget an item, an irreversible action reserved for the appropriate permissions.

Agent profiles, Goals, and cycles are read-only projections: modify their source rather than their memory copy. Contacts from messaging systems contain only the minimum identity required and remain private to the owning Agent.

**Topics** group knowledge around a global subject, even if it comes from different rooms, Tasks, or calls. Dream performs this classification in the background; authorized accounts can also correct an item’s assignment. Dream can consolidate memories and separately analyze Task results to strengthen Skills specific to the Agent. A self-learned Skill is added to future executions only after reaching the configured evidence and score thresholds; the **Skills → Self-learned** page lets you view its evidence and suspend it.

## Standard and High

The effort level does not refer to two different architectures. The same driver executes the Task, but Galaris can select a more powerful model and apply additional preparation.

| Level | Best for | Expected effect |
|---|---|---|
| `standard` | conversation, simple research, bounded and deterministic operations, including an explicitly authorized destructive action | fast and economical response; ordinary safeguards unchanged |
| `high` | genuine ambiguity, substantial context to reconstruct, complex diagnosis or recovery, highly coupled decisions, demanding technical or creative creation | more robust execution model |

Operational risk alone does not determine effort: deleting a precisely identified file or resetting an exact repository after explicit authorization can remain `standard`. Scope controls, confirmations, and protections against destructive effects remain applicable regardless of the level.

You can let Galaris choose. The `@standard` and `@high` directives force the level when they are available in your channel. `@exec` and `@plan` force the route, but a driver that prohibits the planner cannot be forced to use it.

For a single document, research, chapters, and reviews stay within one execution to preserve
consistency. Separate deliverables that can be accepted and resumed individually may use `PLAN`,
even when they must run sequentially and share a progress log. A small mechanical batch does not
by itself require a plan.

In native Chat, placing `@task` anywhere in the message immediately creates a durable Task with the remaining text as its objective, without calling the conversational LLM. For the internal Galaris harness, `@plan` is also sufficient to create the Task and force its planning, without adding `@task`. These directives can be combined, in any order, with `@standard` and `@high`. `@approve` grants no agreement. Sensitive actions use [authorization requests and YOLO](../admin/tool-administration.md). Chat retains the round and immediately publishes a deterministic confirmation in the room; the Task result will be published there when it terminates. The composer’s `@` button displays only the directives compatible with the selected Agent’s driver.

## What Happens After Submission

1. The request created on this screen becomes a durable Task.
2. The Dispatcher chooses direct execution or a plan, then sets the effort.
3. The planner prepares decomposable work.
4. The driver executes the Agent with its authorized Tools.
5. Galaris records the trace and result, then resumes any parent Tasks.

Text and voice conversations follow their own configured controller and executor. They do not go through the Task Dispatcher; when they need durable work, they explicitly create a linked Task.

## Planner: Decomposing Coordinated Work

The planner breaks down only an objective that requires several coordinated blocks of work. Each leaf of the plan is a real Task. A step is not intended to “think” or “write the final response”: it must produce a verifiable part of the result.

The preferred decomposition repeats the same complete treatment across independent items:
one file to process means one task that reads, transforms, verifies and records its result.
A unique task stays whole even when complex: its research, construction and validation phases
do not become subtasks. This also applies to `@plan`, which selects orchestration without
replacing the requested work with writing a plan.

For repeated work on many documents or records, the planner can create a collection: Galaris
identifies its items from the inventory, then creates one Task per item in bounded waves.
“One workspace after another” preserves that order while keeping documents separate. The
progress total becomes more precise as each collection is discovered. After a failure,
**Retry** on the plan resumes failed work and preserves successful items. Existing saved
plans are not automatically decomposed again.

A small mechanical batch of up to five known items can remain one Task, such as renaming
three documents to supplied names. Reading, transforming and verifying each document remains
per-document work, even for a small batch. Multiple targets alone do not trigger the planner.


These aids are enabled per driver. In the current configuration:

| Driver | Planner |
|---|---:|
| Internal (Pydantic AI) | yes |
| Hermès | no |

Hermès therefore retains its own capabilities without being confined to a second harness.

## When Galaris Asks a Question

If a Mail connection requires human approval, its designated approver receives a private Chat
request for each prepared email. Review the recipients, subject, content preview, and attachment
list, then choose **Allow sending** or **Reject**. The **Mail journal** shows the complete content
and delivery result and also lets you decide. Approval applies only to this email. Without a
response, it stays unsent; after seven days, use the journal because the Chat request has expired.

Essential information may be missing: recipient, file, period, authorization, or an irreversible choice. The Agent must then ask a short question and wait rather than guess. A question is a valid result of the current turn; reply in the same conversation to continue.

A planner may also request a single series of clarifications before creating its plan. Without a response before expiration, it resumes with explicit assumptions.

## Reading a Task’s Status

| Displayed status | Practical meaning |
|---|---|
| Creation / dispatch | the request is being routed |
| Execution | the Agent is working or calling Tools |
| Plan | Galaris is creating or advancing through the steps |
| Paused | the Task is waiting for a response, a child step, or a resume |
| Success | the workflow ended without a declared error |
| Error | the attempt failed or was interrupted after the authorized retries |

The **Text conversations** and **Phone Calls** tabs use their own statuses. “Up to date” means that all known messages have been processed; “Waiting” means that a new round can be claimed; “In progress” means that a controller is currently responding.

Technical success does not guarantee that the content is perfect. For an important action, verify the deliverable, destination, and Tools called.

## Writing a Reliable Request

A good request contains four elements:

1. the final result: “produce a CSV,” “reply to Paul,” “correct the document”;
2. the exact inputs: period, files, URLs, identifiers, and recipients;
3. the constraints: language, format, limits, and elements not to modify;
4. the expected check: verified totals, shared file, confirmed response.

Prefer:

> Analyze the invoices in `/compta/2026-06`, create `synthese.csv` with the columns
> supplier, net, VAT, and gross, verify that net + VAT = gross, then share the file in the
> Accounting room. Do not modify the source files.

To:

> Take care of the invoices.

## If the Result Is Unexpected

- Verify that the correct Agent and room were used.
- Open the Task details and check the Tools actually called.
- Rephrase the exact target rather than adding “be careful.”
- If the action may have side effects, request verification before repeating it.
- Give the administrator the Task identifier visible in the interface; it allows the traces to be found without sharing your secrets.

Never copy an API key or password into a conversation. Secrets are configured in the administration interface or in the environment intended for that purpose.

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
