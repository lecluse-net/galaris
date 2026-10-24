<p align="right"><a href="../../fr/user/internal-processes.md">Français</a> · <strong>English</strong></p>

# Internal business processes

In run details, files offer **Rename** when you have Process control rights. This changes
their display and download name without changing their content, URI, variables or run state.

Processes are managed exclusively in **Processes**. They own their BPMN definitions and
history and never appear in the **Documents** library, which contains HTML. Their JSON
run variables and attachment links belong directly to Process.

The **Processes** page brings internal and external processes, including n8n, into a single list.
Click a process row to open its editor page for both internal and external processes.
The arrow area on the left loads and expands its runs; click again to collapse the sublist.
The edit icon on the right also opens its editor page.
Adding an external process also uses a dedicated page.
In each editor, **Back to list** is below the title, at the top left.
Search applies to the combined list; the agent filter applies to external processes.
**Engine** selects Galaris or external processes. **Archive** defaults to unarchived
processes; archived definitions remain available through this filter. The server paginates
the list, with 50 processes per page by default. Each row also shows its description,
latest run, active run count and runs awaiting a human reply. These summaries follow
the reader's permissions and update without opening runs. A search with no matches
offers **Clear filters**.
Returning from the editor preserves search, the agent filter, sorting, pagination and
expanded processes during the current session. Sublists also retain their page when
collapsed and reopened. Signing out, switching users or fully reloading the application
resets these preferences. Open sublists update on run events, reconnection and returning
to the browser tab without changing their page. If deletion removes the final page,
the last available page is loaded. Collapsed lists load only catalogue summaries, without
run lists or detailed views.
Internal and external runs show their start date and time, duration, identifier, status,
then the result before the actions. **Refresh** at the top of the page also reloads open
sublists. Internal process creation is on the following row in development. Duration excludes time spent waiting to start,
updates during execution and stops at completion. A missing start time leaves duration
unavailable. External runs have no additional filter.
**Integrations**, available to Process administrators, opens a dialog with n8n API health
and operational counters. It groups **Add an external process** and **Sync n8n** and can
close while synchronization is running. On the page,
an error banner appears only when connection to a configured n8n instance fails;
an unconfigured integration does not display this banner.
Each internal process has a human or agent owner and read or write access granted to users, agents and groups;
it can also be shared publicly. Users also see managed agents' processes.
Definitions without an active owner are restricted to human PROCESS_ADMIN administrators.

Creating an internal process through the interface is temporarily available only in
development mode (`APP_ENV=dev`). Other environments retain viewing, authorized editing
and monitoring of existing processes. This UI restriction does not replace API or MCP permissions.

## Build and save

Create a process and enter its title in the compact toolbar. The **Description** field
accepts optional plain text, which can be edited and saved with **Save**.
The description remains visible with read-only access. **Owner** stays visible during
creation and after reopening. It lists **Me**, then other eligible users, then managed agents.
Search covers each list; above 50 results of one type, that type has its own pagination,
defaulting to 50 results. The owner or a Process administrator can transfer ownership;
the former owner keeps write access, while the diagram and editing drafts remain available.
A version conflict refuses the transfer and requires reloading. **Sharing** is available from creation
to grant **Read** or **Write** access to users, agents and groups, or choose public access.
Saving applies these choices to the new process; sharing changes to an existing process
are saved directly. If sharing fails after creation, retry preserves the process and
selected permissions without creating a duplicate. The first lane's agent
selector defaults to **Agent launching the process**, without imposing a specific agent.
Choosing an execution agent there assigns tasks without a specific actor assignment to
that agent; selecting **Agent launching the process** restores the default. Its code
is unique and immutable. The diagram begins with a connected **Start** and **End**.
Click an input or output
handle to continue, insert an activity into a flow, add a branch or connect an existing
activity. Edit a flow's source, destination and condition from its handle menu or label.
Add another **End** to close a branch. To connect existing activities, drag an output
handle to the other activity's input handle: a line follows the gesture and is created
on release. Dragging in the opposite direction also works. Escape cancels the connection;
duplicates, self-links and cycles are refused. The last End and the Start cannot be removed.
Arrow keys move a selected activity; Delete removes
it when allowed. **Arrange** aligns the graph; zoom and scrolling support larger diagrams.
The navigation capsule's **Full screen** button expands the diagram and preserves its
editing menus. The exit button or Escape returns to the page.

Define **named actors**, such as executor and reviewer. Each actor has a fixed agent or
human type and an assignment. Agent tasks can only use agent actors; human tasks can
only use human actors. Tasks appear on their actor's lane. An assigned agent actually
replaces the launch agent for these tasks, within the launcher's management scope.
Unassigned agent actors use the execution agent. Human actors require an active assigned
user before launch. Actors in use cannot be removed.
Edit names and assignments directly in each lane header. **New actor**, in the hatched
strip below the diagram, creates an agent or human lane. The name uses an outlined input.
The header's trash button directly removes an unused lane; it is disabled when activities
use that actor. There is no separate Actors panel. Drag a header's handle to reorder lanes together
with their tasks, preserving assignments. Release to apply the move; Escape cancels it.
The up and down arrow keys on that handle also move the lane. Saving preserves the order.

To change actors, **drag the task onto the intended actor's lane**. Assignment changes on
release and the task aligns to its new lane, retaining its instructions and flows.
In the typed profile, a task or IF adopts human processing on a human lane and AI/code
on an agent lane. Historical definitions still refuse incompatible type changes.
Escape or an interrupted gesture
cancels the move. Save retains the new assignment.
Dropping a task outside the table creates a new lane and an actor of the same type, then
assigns the task to it. The 40 px hatched strip below the diagram also accepts this drop
and contains the **New actor** button. Rename the new actor
and choose its agent or human in the lane header; human actors need an assignment before
launch. Cancelling the gesture creates no lane.

Click an activity to open its contextual form below the block; click a flow label to
open its settings in the same way. The form adapts to the available space and remains
accessible on mobile and in full screen. Click outside, press Escape or use the close
button to dismiss it. Changes and JSON drafts, including invalid drafts, survive
reopening until saving or reloading.
The **Save** button is in the diagram toolbar, next to **Validate**, and remains
available in full screen.

Each task has **Input variables** and **Output variables**: name, type, nullable/notnull
and an optional default. Start and End configure process-level variables. Names must be
unique and defaults are checked when saving. Types are int, float, string, bool, Agent,
File, User, Document, array and object. Containers may be nested; every type can be nullable.
Omission uses the default, else null if nullable; a notnull variable without a default must
be supplied. Explicit null never uses the default. False and zero remain values.
Contract errors identify the task and variable. FOR/WHILE use the same editor and breadcrumbs.
Old definitions retain their shared pool; **Configure typed inputs and outputs** starts
an explicit conversion to complete before saving. Existing runs retain their original profile.
For an IF using **AI** processing, **AI mode** distinguishes **Agentic (Task)** from
**Simple LLM call**. Agentic delegates work to the agent through a Task, with its tools
and interactions. Simple LLM call evaluates only the instructions and process data:
explicitly choose a text or decision **LLM model**, such as Jev. It creates no Task and
uses no tools. A model failure ends the process in error; it never selects the False
branch. Existing IFs remain agentic. Saving preserves both the mode and selected model.

An IF has two output handles, **True** and **False**. On an AI actor's lane, choose **AI**
and enter instructions, or **Code** and enter a Python program. On a human lane, human mode
is automatic: the assignee receives the question in messaging and chooses True or False.
The run waits and follows exactly one branch. Historical IFs without a mode keep their
existing conditions. Tasks retain agentic AI, Code or Human processing according to their actor.
Code receives run data variables directly: `return variable_2 != "pas mon projet"` for
an IF, or `return {"variable_1": variable_1 + 1}` to update a declared task output. The editor
starts with a commented example; only valid outputs are integrated.
Connecting a task's output to several tasks launches them in parallel. From its output handle,
**Add a branch** keeps the existing connection and adds another task;
**Connect to an activity** lets you select an existing task.
To bring the branches together, connect them directly to the next task: it waits for the
activated branches to succeed and then starts once. An unselected IF branch does not block
this wait. No dedicated parallel block needs to be added. The harness determines how many
Tasks can actually execute concurrently.
An execution error stops the process and its active branches. The observer returns the
error code and message; the run data and files are preserved. There are no recovery
activities or automatic retries to configure.

Validate checks the executable profile. Save creates a saved process revision. Invalid JSON
drafts remain visible and prevent saving. The diagram opens directly, without tabs or
an XML editor. History lists dates of earlier states on the left. Clicking a date
opens its diagram on the right, or below the list on mobile. The current state
remains visible in the editor above. The **Return to this state** icon on each row
asks for confirmation before replacing the current process diagram and configuration.
The dialog explains that unsaved changes will be lost while history and existing runs
will be preserved. Launches never select an old version.
The **Delete this saved state** trash icon asks for confirmation, then permanently deletes
the selected snapshot. The current state is excluded from this list and cannot be deleted.
Deleting a snapshot preserves the draft and existing runs. Cancelling a confirmation or
encountering an error preserves the draft.
The numeric selector in the list footer controls how many saved
revisions appear. The footer shows the displayed range, total and page navigation arrows.

## Launch and observe

Ask the agent to launch the process from Chat. The agent gathers the required information
and files, prepares the declared inputs and launches the latest saved version.
The process page provides editing and observation without a manual launch form.
Calls forward their local inputs and
integrate validated outputs. Children own independent data and have no fixed business depth.

Each run retains its admitted graph and stores business variables in its `data` field.
A run file table holds attachment links. No Dataset is created. Data and files inherit
the parent Process's read/edit rights, including immediate revocation for existing runs.
Tracking exposes **Run data** and **Attachments**, with downloads for managed files.
The engine integrates validated outputs and keeps technical receipts separate from variables.
Invalid output is never integrated. Disjoint changes
are preserved and conflicting variable updates are reported. File references travel without
automatic downloads or copies; operations on contents enforce resource access.
Run output follows the variables declared on End. Sharing a Process also shares its runs. Different runs own independent data. Only historical profiles retain
direct shared-pool editing and copy initial files into their attachments.

Opening a run from Chat's **Processes** panel, a process's execution list or process tracking in Tasks shows
a dialog centred on the diagram saved at launch.
In Chat, runs appear from oldest to newest at the bottom. Scrolling up loads older runs
while preserving the reading position. A new run scrolls the list to the bottom; a status
update preserves the position. Diagram code is prepared in the background when an internal
run is present, and other resource screens load only when opened.
Active activities are highlighted, including parallel branches. Clicking a node opens its read-only execution details:
output data, task or operation result, input data, attempts, executed instructions and
available errors. Its execution selector reaches an activity's executions, with pagination
when needed. Activities that have not run show an explicit message. Closing the
dialog stops its refresh loop.
The diagram and open activity details follow run events in real time while preserving
the selection. Reconnecting catches up on missed changes; a check every two seconds
remains active while the run is in progress.
The graph and activity details remain usable while costs and statistics load and
refresh independently.
Chat, the catalogue, tracking in Tasks and run links open the same dialog.
Its title groups the status, the last
activity, then elapsed time and the total cost of the process and its child processes.
The clickable UUID with a transparent background sits to the left of the inspection hint
in the diagram toolbar. Clicking the UUID copies the internal
`galaris://processes/runs/<uuid>` reference. The diagram replaces occurrence counters and lists of
occurrences or child processes; the calling activity's details open its child process.
Agents can read the reference through `file_info`, `file_read` or
`processus_get`, according to the parent Process rights
or with dedicated Process administration access.

The observer shows the graph, occurrences, actual prompts, errors, run data, children
and available metrics. Loop bodies and children open on demand. Pause suspends new
admissions while observing accepted effects. Step admits one occurrence and lets its
composite descendants progress until completion. Pause and breakpoints survive restarts.
Cancellation remains pending until required stops have been confirmed.

**Run progress** shows completed, active, ready and failed occurrences, the last activity
and precise waits: a messaging reply, authorization, task or child process. **Resume**
continues the same run. **Stop run** asks for confirmation, closes human requests and
interrupts active tasks and children. A stopped run cannot be resumed. An uncertain
operation requires reconciliation before resuming; elapsed time alone does not prove
that a run is blocked.

Agents use `processus_get` for this view. The Process's read policy authorizes its
runs, data and files; its edit policy authorizes controls. Existing dedicated
`process_admin` access remains available. Sharing a Process also shares its existing runs.

A reply to an activity's question belongs to the existing run; it does not request a new
launch. The agent replies briefly by default; ask for any details you need.
In Chat, new launches are bounded to the received request: a technical retry reuses the same
run. A different workflow or changed parameters require a request that includes them.

All human interactions take place through messaging: internal Chat or an external messenger
channel. An AI activity may also ask a question while working: it waits for your reply in
the conversation, then resumes with the supplied information without creating an extra
Task just to wait. The recorded reply is retained when work resumes, even if the agent
rephrases the same request. An activity with no output
variables may simply produce a result message.

An activity assigned to a human uses a messaging channel
linked to the assignee's account. A human activity sends its instructions to the conversation
and waits durably for a reply without starting an AI task just to wait.
Reply naturally or attach the requested file, even without text. The agent retrieves pending
requests and their expected data, and asks for clarification when a reply is incomplete or
could match several activities. Unrelated messages leave the process waiting. Files keep
their reference in their original messenger.
Only the assignee can answer; outputs are validated before execution resumes. Identical
replies do not complete an activity twice, and replies after cancellation cannot restart it.
Assignment grants no access to other runs' data. Process tracking stays in Processes; the
“My human activities” inbox is replaced by these messaging exchanges.

Durations and costs are observation metrics without a blocking Process budget in v1.
Unavailable or partial costs are never displayed as zero. Inclusive totals add accessible
children and retain estimated-cost information. Recovery reattaches admitted Tasks/Runs;
Tool effects without certain receipts are never blindly replayed.
Billed cost and inference value are separate, including subscription calls. The table
details these measurements for each occurrence, including loops and retries. Archiving
a definition preserves its BPMN, history and run links.

## Audit and test

Authorized agents inspect complete definitions, prompts, actors and history
through MCP, then propose or apply changes according to their rights. Tool capabilities
never replace access to the corresponding Process and its data.

**Lab → Processes** prepares invented cases, optionally generated by the Lab model,
and launches real campaigns. Cases retain actual runs, measurements and optional exact
output checks. Actual authorized Tools are used; mocks remain a second phase.

Secrets remain in Connections. Tool nodes call declared MCP operations. REST activities use
their execution agent's connection and paths relative to the configured API; HTTP errors
stop the activity. Code and optional preparation/integration scripts use an isolated Python
subset with no filesystem, network or third-party package access, bounded by time and memory.
Documentary programs require their separately qualified
executor; its absence is reported. See the [native BPMN profile](../dev/native-processes.md).

Each Document, Dataset and process definition retains independent sharing. Changing access to one resource does not change access to another linked resource. Upgrades preserve existing permissions, including team access. See the [sharing mechanism](../dev/sharing.md).

## Cite a Process in a Document

In the Document toolbar, **Insert a link or file** then **Add an internal attachment**
opens the file_share resource picker. Its tree, compact files and search within the
current location support multiple selections, including internal definitions and runs.
Use the checkboxes or Shift to select multiple files; double-click to open a folder.
The toolbar's **Insert a link or file** command groups web links, internal resources
and uploads. Selected resources are cited in the text without becoming attachments.
Below the document, **Upload** adds files only; existing references are not listed there.
The picker thumbnail represents the Process; a play badge
distinguishes executions. Opening a definition displays its read-only modal, while
opening a run displays its tracking modal.

In the editor, the link appearance action switches between a title link and a diagram. Hover over the
diagram frame, or move keyboard focus into it, to show zoom and fullscreen controls
at the top right. These controls remain available on touch screens. A run diagram
uses the definition frozen at launch.

Citing a resource grants no Process access. Each reader needs access independently
of the Document. Removing its citation from the text leaves the Process and run intact.
