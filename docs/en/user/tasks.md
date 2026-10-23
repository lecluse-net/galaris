<p align="right"><a href="../../fr/user/tasks.md">Français</a> · <strong>English</strong></p>

# Assigning and following a Task

A Task keeps durable work, its state and its result. This guide explains methods,
milestones, plans, questions and recovery. To create your first request, follow the
[user guide](README.md); to find commands, see the [menus and workflows](navigation.md).

Conversation context includes the agent's active Tasks and Processes, including work started
in another discussion: queued, running or waiting, with the known question or dependency.
Old waits remain visible until resolved. Finished work, cancellation requests and manual holds
are excluded. Replying to a question or sending the requested file gives the agent context
to recognize that contribution. If several waits match, it must ask for clarification; replies
remain subject to the permissions and validation of the relevant resumption mechanism.

The same projection is available for monitoring through
`GET /api/conversations/agents/{agent_id}/active-work?page=1&page_size=50`.
It combines Tasks and internal and external process runs with their operational states,
waits and references. The response contains `items`, `total`, `page`, `page_size` and
`observed_at`; `kind` distinguishes `task` from `process`, and `engine_code` identifies
the process engine. Access requires `TASK_ACCESS`, `PROCESS_READ` and management scope
over the agent; process read permissions still apply. Pagination accepts up to 500 items.

## Standard and High

The effort level does not refer to two different architectures. The same driver executes the
Task, but Galaris can select a more powerful model. Work method and coordination across Tasks
are separate decisions from effort level.

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

In native Chat, placing `@task` anywhere in the message immediately creates a durable Task with the remaining text as its objective, without calling the conversational LLM. For the internal Galaris harness, `@plan` is also sufficient to create the Task and force its planning, without adding `@task`. These directives can be combined, in any order, with `@standard` and `@high`. `@approve` grants no agreement. Sensitive actions use [authorization requests](../admin/tool-administration.md). Chat retains the round and immediately publishes a deterministic confirmation in the room; the Task result will be published there when it terminates. The composer’s `@` button displays only the directives compatible with the selected Agent’s driver.

The result automatically returns to the discussion even if a tool or attachment failed. If the
Agent already sent that exact result to this discussion, Galaris does not send it again. An
unavailable attachment does not prevent the text from being published.

After human approval of a managed Harness action, the same Task resumes the same call
once its executor has regained ownership. Agreement remains recorded during this wait;
do not create another Task to bypass a resumption refusal or repeat the action.
A manual pause still takes precedence.

## What Happens After Submission

A request continuing existing work can reuse its tracking document without repeating
its URI in the latest message. Galaris resolves that reference from context and retains
the evidence supporting its update. This does not authorize updates to other documents
mentioned in the discussion; their access controls still apply.

1. The request created on this screen becomes a durable Task.
2. The Dispatcher selects the route, effort and work organization.
3. Missing clarification can suspend the request; the planner prepares decomposable work.
4. The driver executes the Agent with its authorized Tools.
5. Galaris records the trace and result, then resumes any parent Tasks.

Text and voice conversations follow their own configured controller and executor. They do not go through the Task Dispatcher; when they need durable work, they explicitly create a linked Task.

In native voice mode, you can speak again during a slow lookup. The agent interrupts its
response and does not automatically resume the old sentence when the result arrives.
Actions already performed remain recorded.

If the agent's profile configures a Decision model, the text conversation dispatcher helps
match your message to pending or active work and select a new business process to launch.
The agent then performs the action through the usual checks. Without this model, or when
analysis cannot conclude, the agent must identify the pending request and select and launch
the appropriate process itself when needed. A progress request does not answer a pending question.

## Force-terminating a Task

**Force terminate** makes the Task terminal with an error and revokes its execution lease,
even if its revision changed after opening the details. An active attempt is cancelled
without waiting for the harness to cooperate. A late worker can no longer save its result.
Edit permissions and management scope over the agent remain required.

The stop commits before Goal cycle cleanup and notifications. These followups have bounded
waits: failures are logged and cannot undo the stop. Repeating the command preserves the
terminal state and retries cleanup of any cycle still open. Effects already sent to an
external system are not undone retroactively.

## A method suited to the work

A bounded action, such as renaming a precisely identified file, runs directly.
A long or complex mission can keep milestones within the same Task: preparation,
acceptance criteria, observed results, resources and the next action. This tracking helps
resume work without losing context or repeating effects already completed. It does not
create child Tasks for each phase of one deliverable.

Task details show activity, tools and results; `task_get` exposes saved milestone tracking.
The executor can update it with
`task_work_update` on its active Task, with revision checks. Up to twenty milestones are
retained; declaring one complete does not replace evidence of the result or its delivery.
Tracking has its own revision, so execution checkpoints do not block progress updates.

In reasoning steps, expanding a tool call shows its name, arguments and returned content,
with its success or failure state. These details remain available during live monitoring and
after reconnection. Large previews are explicitly truncated and secret keys are redacted;
older activity records that did not contain these details remain incomplete.

During long reasoning, intermediate saves are spaced out so execution can keep moving.
Tool results, errors and block completions are still saved immediately; reopening the
Task restores its latest saved activity.

When scope or expected depth substantially changes the work, Galaris can ask a question
before starting. Reply in the conversation linked to the request. A technical unknown
that the agent can resolve through authorized inspection belongs to its preparation.

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

When the internal agent repeats its reasoning without progress, Galaris interrupts that
generation and asks it to change approach, preserving completed tool results. Recovery is
bounded: a persistent loop leaves the Task unfinished with a diagnostic. Retrying a failed
plan resumes its first unfinished step, including nested groups, without replaying successful
items. A document still requiring checks or tracking updates remains in the work inventory.

In Task details and the conversation task panel, a warning appears after two minutes without
received activity: reasoning, text, generated tool arguments or tool results. It clears when
activity resumes and cancels neither the call nor the Task. Long reasoning remains allowed.
Declared pauses and waits do not trigger it; an unavailable connection is reported separately.

For a Task using the internal harness, users allowed to edit the Task can select
**Interrupt call and resume** to request guided recovery. The runtime closes the current
generation call and continues the same Task, preserving tool results and the original budget.
It refuses interruption while a tool is running or its effect is uncertain. The activity view
shows whether recovery is requested, accepted or refused; late responses after changing Task
or attempt do not affect the current view.

If you requested a saved report even after failure, an independent closing action can
produce it after the failed work. Other dependent steps are skipped. A successful report
preserves the plan's error; a manual retry resumes unfinished work and refreshes the
report while preserving other successful results.

For managed network harnesses, **Retry** starts a new inference with the same Task
parameters. The Task and its previous attempts remain available; no new-Task dialog is
required, including when the previous runtime has no resumable state. Galaris retires the
previous operation and issues a new runtime identity and authority. Previous tool receipts
remain available to check effects already performed. Automatic recovery after an interruption
still observes the existing operation.

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

In **MCP function authorizations**, **Global (all)** offers **Enabled**, **Ask**
or **Disabled** as joined buttons: a green check, a yellow question mark, and a red cross.
The selected button has a solid background; each button describes its effect in a tooltip.
Without a saved global rule, this column displays the software policy when the connection inherits it.
Selecting a **This connection** button creates an override: the global buttons in that row
appear unselected and remain clickable. Clicking a **Global (all)** button saves that rule
and returns this connection to inheritance; its local buttons all become unselected.
Other connections keep their overrides.
Selections change immediately and buttons remain clickable while saving.
Successive choices for the same capability are saved in order. If saving fails,
a message alerts you and Galaris reloads the stored rules.

For web browsing, **Public sites allowed** is the initial choice in the Browser parameters for new installations,
globally or for one agent: new public sites then stop triggering per-site network requests.
Existing instances keep their behaviour; **Per-site approval** remains available. Localhost and private networks remain blocked by
default; filters and explicit denials stay active. See [Browser administration](../admin/tool-administration.md).

If a Mail connection requires human approval, its designated approver receives a private Chat
request for each prepared email. Review the recipients, subject, content preview, and attachment
list, then allow or deny the action. The **Mail journal** shows the complete content and delivery
result and also lets you answer the same authorization. A decision in either place applies to
both. Approval covers only this email and lets the task resume its prepared call: a recorded
approval does not yet mean the email was sent. Without a response it stays unsent; an expired
authorization requires a new request. Historical pending Mail approvals remain accessible
from the journal.

After SMTP accepts the email, Galaris stores a copy in the Sent mailbox configured or
advertised by your server. If archiving fails, the receipt reports it without undoing
the actual send. A replay with the same key and content repairs the copy without
sending a second email.

The **Mail journal** has **Sending** and **Reception** tabs. Reception keeps headers, sender,
receiving agent, consent/read/Task admission timestamps, denials, blocks and errors. Bodies and
attachments are not downloaded before consent. After reading, the journal retains a content
page of up to 50,000 characters and attachment metadata, with an explicit truncation notice.
The complete email remains available in pages from its source mailbox.

By default, an exact email identity in this agent’s **Contacts** allows processing directly.
A display name, another address or another agent’s directory cannot grant this permission.
Unknown senders require the agent manager’s common authorization, available in private Chat,
**Permissions**, and the Reception detail. Denial or expiration causes neither reading nor Task
creation. Consent resumes reception automatically without creating duplicate Tasks. Messenger
projects contacts after admission.

The **mail_process** function uses the same global and local policies as other functions:
**Enabled** processes every sender; **Ask** requires consent for every email, including contacts;
**Blocked** prevents processing. Without an explicit policy, contacts are accepted and unknown
senders require consent. **Always process emails** enables the function only on this agent’s
connection; revoke it in Permissions. Sending permissions remain independent of reading and
processing permission. Only inbox (`INBOX`) messages and their attachments can be processed,
read or admitted as Tasks. Searches in Sent, Trash, Archive or subfolders may return headers,
but create no reception entry or processing request. Historical entries outside INBOX cannot
resume processing. The journal covers newly observed incoming mail and INBOX mail discovered by
tools; startup preserves the existing cursor and does not replay old mailbox contents.

Essential information may be missing: recipient, file, period, authorization, or an irreversible choice. The Agent must then ask a short question and wait rather than guess. A question is a valid result of the current turn; reply in the same conversation to continue.

Two waits have different outcomes. When choosing the organization of an ambiguous mission,
a question that cannot be delivered or expires unanswered ends the Task in error without
starting work. An explicit retry goes through routing again. When clarifying an already
selected plan, the Planner may ask one series of questions and resume at expiry with
explicit assumptions. Expiration never grants approval for a sensitive action.

If a step reports that a document is outside its admitted scope, changing tools or retrying
does not grant permission to modify it. To authorize the change, include the document's exact
URI in an amendment to the root Task. The Agent receives a diagnostic distinct from invalid
arguments; this refusal does not automatically create an approval request or a waiting state.

## Reading a Task’s Status

Chat text continues to appear during generation. LLM call supervision refreshes at most
four times per second and automatically recovers a missed update. The final response and
persisted costs remain complete.

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

Pausing preserves work; resuming follows the available evidence. Explicit replacement waits
for confirmed stops of the previous Task, its descendants and associated processes.
Acknowledged stop requests, network errors and logical completion do not always prove a
remote stop. Goals and unsupported waits remain refused by this path; independent work
is preserved.

## Writing a Reliable Request

A good request contains four elements:

1. the final result: “produce a CSV,” “reply to Paul,” “correct the document”;
2. the exact inputs: period, files, URLs, identifiers, and recipients;
3. the constraints: language, format, limits, and elements not to modify;
4. the expected check: verified totals, shared file, confirmed response.

Prefer:

> Analyze the June invoices in `nextcloud://compta/2026-06/`, create `synthese.csv` with the columns
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
