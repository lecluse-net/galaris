<p align="right"><a href="../../fr/user/tasks.md">Français</a> · <strong>English</strong></p>

# Assigning and following a Task

A Task keeps durable work, its state and its result. This guide explains methods,
milestones, plans, questions and recovery. To create your first request, follow the
[user guide](README.md); to find commands, see the [menus and workflows](navigation.md).

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

In native Chat, placing `@task` anywhere in the message immediately creates a durable Task with the remaining text as its objective, without calling the conversational LLM. For the internal Galaris harness, `@plan` is also sufficient to create the Task and force its planning, without adding `@task`. These directives can be combined, in any order, with `@standard` and `@high`. `@approve` grants no agreement. Sensitive actions use [authorization requests and YOLO](../admin/tool-administration.md). Chat retains the round and immediately publishes a deterministic confirmation in the room; the Task result will be published there when it terminates. The composer’s `@` button displays only the directives compatible with the selected Agent’s driver.

The result automatically returns to the discussion even if a tool or attachment failed. If the
Agent already sent that exact result to this discussion, Galaris does not send it again. An
unavailable attachment does not prevent the text from being published.

## What Happens After Submission

1. The request created on this screen becomes a durable Task.
2. The Dispatcher selects the route, effort and work organization.
3. Missing clarification can suspend the request; the planner prepares decomposable work.
4. The driver executes the Agent with its authorized Tools.
5. Galaris records the trace and result, then resumes any parent Tasks.

Text and voice conversations follow their own configured controller and executor. They do not go through the Task Dispatcher; when they need durable work, they explicitly create a linked Task.

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

If you requested a saved report even after failure, an independent closing action can
produce it after the failed work. Other dependent steps are skipped. A successful report
preserves the plan's error; a manual retry resumes unfinished work and refreshes the
report while preserving other successful results.

For remote harnesses, **Retry** preserves the execution identity and its receipts;
it checks the existing execution before continuing. If its authority is missing,
revoked or expired, recovery remains refused with the corresponding reason.
Creating a new Task starts another execution rather than recovering the checkpoint.

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
list, then choose **Allow sending** or **Reject**. The **Mail journal** shows the complete content
and delivery result and also lets you decide. Approval applies only to this email. Without a
response, it stays unsent; after seven days, use the journal because the Chat request has expired.

Essential information may be missing: recipient, file, period, authorization, or an irreversible choice. The Agent must then ask a short question and wait rather than guess. A question is a valid result of the current turn; reply in the same conversation to continue.

Two waits have different outcomes. When choosing the organization of an ambiguous mission,
a question that cannot be delivered or expires unanswered ends the Task in error without
starting work. An explicit retry goes through routing again. When clarifying an already
selected plan, the Planner may ask one series of questions and resume at expiry with
explicit assumptions. Expiration never grants approval for a sensitive action.

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
