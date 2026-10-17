<p align="right"><a href="../../fr/user/internal-processes.md">Français</a> · <strong>English</strong></p>

# Internal business processes

The **Processes** page brings internal and external processes, including n8n, into a single list.
Click a process row to open its editor page for both internal and external processes.
The arrow area on the left loads and expands its runs; click again to collapse the sublist.
The edit icon on the right also opens its editor page.
Adding an external process also uses a dedicated page.
In each editor, **Back to list** is below the title, at the top left.
Search applies to the combined list; the agent filter applies to external processes.
Internal and external runs show their start date and time, duration, identifier, status,
then the result before the actions. **Refresh** at the top of the page also reloads open
sublists. The add buttons are grouped on the following row. Duration excludes time spent waiting to start,
updates during execution and stops at completion. A missing start time leaves duration
unavailable. External runs have no additional filter.
**Sync n8n** opens a dialog with API health and operational counters. On the page,
an error banner appears only when connection to a configured n8n instance fails;
an unconfigured integration does not display this banner.
Each internal process has a human or agent owner and read or write access granted to users, agents and groups;
it can also be shared publicly. Users also see managed agents' processes.
Definitions without an active owner are restricted to human PROCESS_ADMIN administrators.

## Build and save

Create a process and enter its title in the compact toolbar. The **Description** field
accepts optional plain text, which can be edited and saved with **Save**.
The description remains visible with read-only access. Choose its owner when
creating it. The **Sharing** field is available from creation
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
An IF has two output handles, **True** and **False**. On an AI actor's lane, choose **AI**
and enter instructions, or **Code** and enter a Python program. On a human lane, human mode
is automatic: the assignee receives the question in messaging and chooses True or False.
The run waits and follows exactly one branch. Historical IFs without a mode keep their
existing conditions. Tasks offer the same processing modes according to their actor.
Code receives run Dataset variables directly: `return variable_2 != "pas mon projet"` for
an IF, or `return {"variable_1": variable_1 + 1}` to update a declared task output. The editor
starts with a commented example; only valid outputs are integrated.
Splits create
branches; an activity waits for all its ordinary predecessors and starts once without
requiring an extra gateway.
The harness determines how many Tasks can actually execute concurrently.
An execution error stops the process and its active branches. The observer returns the
error code and message; the Dataset and files are preserved. There are no recovery
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
integrate validated outputs. Children own independent Datasets and have no fixed business depth.

Each run retains its starting graph and owns a private Dataset independent of the
definition. The engine manages global data and the file manifest; activities work on local
inputs and return validated outputs. Invalid output is never integrated. Disjoint changes
are preserved and conflicting variable updates are reported. File references travel without
automatic downloads or copies; operations on contents enforce resource access.
Run output follows the variables declared on End. Sharing a definition never publishes
its run Datasets. Different runs own independent data. Only historical profiles retain
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
In the dialog opened from the process catalogue, the title groups the status, the last
activity, then elapsed time and the total cost of the process and its child processes.
The clickable UUID with a transparent background sits to the left of the inspection hint
in the diagram toolbar. Clicking the UUID copies the internal
`processus://run/<uuid>` reference. The diagram replaces occurrence counters and lists of
occurrences or child processes; the calling activity's details open its child process.
In other views, the **Run URL** field and its copy button share the same reference for
debugging, including from Chat. Agents can read it through `file_info`, `file_read` or
`processus_get`, within their participation scope
or with dedicated Process administration access.

The observer shows the graph, occurrences, actual prompts, errors, Dataset, children
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

Agents use `processus_get` for this view. They see only runs they participate in through
the frozen launch graph, unless they have active dedicated `process_admin` access.
Definition or Dataset sharing does not extend this scope. Participants may inspect;
the launcher and Process administrators may control the run.

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
a definition preserves its Documents and run links.

## Audit and test

Authorized agents inspect complete definitions, prompts, actors and history
through MCP, then propose or apply changes according to their rights. Tool capabilities
never replace access to the corresponding Document or Dataset.

**Lab → Processes** prepares invented cases, optionally generated by the Lab model,
and launches real campaigns. Cases retain actual runs, measurements and optional exact
output checks. Actual authorized Tools are used; mocks remain a second phase.

Secrets remain in Connections. Tool nodes call declared MCP operations. REST activities use
their execution agent's connection and paths relative to the configured API; HTTP errors
stop the activity. Code and optional preparation/integration scripts use an isolated Python
subset with no filesystem, network or third-party package access, bounded by time and memory.
Documentary programs require their separately qualified
executor; its absence is reported. See the [native BPMN profile](../dev/native-processes.md).
