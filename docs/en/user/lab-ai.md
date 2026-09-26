<p align="right"><a href="../../fr/user/lab-ai.md">Français</a> · <strong>English</strong></p>

# Using the AI Lab

Every lab identifies its treatment, **one business variable**, and the result to
evaluate. Shared settings belong to the test dataset. Each item contains the tested value,
its context and expected output, with a name and optional provenance.

| Lab | Item variable | Evaluated result |
|---|---|---|
| Dispatcher | Request | Route, effort, action, language and rationale |
| Briefing | Objective | Briefing and selected resources |
| Planner | Objective | Plan or clarification |
| Topic detection | Ordered exchange | Topic for each message |
| Memory extraction | Exchange or Task report | CREATE, LINK or IGNORE |
| Learning | Execution outcome | Supported lessons |
| Goal tracking | Cycle result | Decision and durable tracking |
| Task executor | Request | Response and tool calls |
| Conversation executor | Current request | Response and actions |
| Voice executor | Transcribed request | Spoken response and actions |
| Task analysis | Execution dossier | Structured diagnosis |

A Topic sequence is one item. History and catalogs do not add tests. The voice lab
evaluates transcribed text, not speech recognition or audio synthesis.

## Assign the Labs to an agent

Enable the agent's **Lab Galaris** connection and assign the **Galaris Lab** system skill
(`galaris-lab`) in its skill authorizations. The **Galaris** agent created during installation
already has this skill enabled. Other agents inherit its disabled default; the Lab connection
still requires explicit activation in every case. Fifty tools
cover all eleven labs: discover contracts, create and clone datasets, edit experimental
prompts, start, monitor, cancel, resume, rejudge and compare benchmarks, and submit
attributed agent assessments.

Capturing real Tasks, messages, conversations, voice turns or LLM calls also requires
**Galaris Admin** with its execution-inspection functions. Documentation-only access
does not grant this permission. Real Task diagnoses require the same additional access.

The agent operates the same datasets and results as the Workbench. Synthetic datasets
remain drafts to review. Long operations return durable references whose results can
be retrieved without repeating the operation. Agent assessments display their author
and campaign separately from human reviews and automatic judgments.

Provide an experimental question, a budget and a stopping condition. Changes affect
the experiments; they do not update production prompts or models. Revoking a connection
or function prevents new work, although an inference already sent may still be billed.

## Create the dataset

Select **New dataset**, edit shared parameters and instructions under **Dataset settings**,
then save. The algorithm contract describes fixed inference settings, output schema
and scoring rubric. Items and benchmarks use saved settings.

Parameters are grouped by topic. Search finds a parameter by its label; **Expand all** and
**Collapse all** control the sections. Lists and objects show a summary: open their row to
edit them. The **Save** bar stays accessible at the bottom of the form and indicates unsaved
changes.

Fields follow the treatment: Topic catalog and context window, memory corpus and ranking,
Briefing resources, Planner limits, or executor context and simulated tool responses.

## Generate a synthetic dataset

Each of the eleven labs offers **Generate a synthetic dataset**. Choose a new name, generator
model, language, 1–20 cases and coverage categories. Describe the domain, scenarios and
constraints; the dialog explains the lab's specific focus. Request at least one case per category.

The model proposes shared parameters, inputs, contexts and reference outputs using the lab's
contracts and rubric. With a dataset selected, **Use the context of dataset** is enabled by
default: the new dataset preserves its parameters, corpora, tools, algorithm configuration and
instructions, without copying its cases. Save edits first; stale revisions are rejected.
Disable this option to create a separate fictional environment. Provenance records the source
context and its revision.

Scenarios follow each lab's workload: natural topic continuity and returns, durable facts and
memory corpora, planning dependencies and deliverables, outcome evidence, cycles against one
goal, conversational history and delegation, or voice transcripts and interruptions. Reference
outputs must respect available tools and configured response fixtures.

Generation does not import real conversations or Tasks. Executor tool calls are
simulated. Contract and reference consistency checks precede atomic publication: a failure
creates no partial dataset, and existing datasets remain intact.

All cases start as **drafts**. Review shared settings, then open, correct and save each case to
make it usable. Generated references remain suggestions. Provenance records the generator,
instructions and cost. You can close and reopen the dialog while generation is pending;
switching labs never inserts its result into the new lab. If generation times out, request
fewer cases or select another model.

## Prepare items

Create an item or capture a real source. The editor separates the named variable,
item context, expected output and source provenance. Shared settings are edited in the dataset.
Complex values use JSON editors.

Previous history belongs to each item, including clarifications, earlier media and message
metadata when used by the treatment. Previous goal tracking also belongs to its item.
These values accompany the variable in previews, suggested references, execution and judgment.

**Preview inputs** displays resolved inputs and instructions. Complete required values
before saving. Draft items are excluded from benchmarks.

**Propose a reference for review** calls the Lab model. Review that output yourself:
the candidate never receives it, and the judge treats it as a non-normative example.
A different valid answer may receive a good score.

A capture retains the original evidence. If a text prompt cannot reliably be separated
into objective and context, it remains a draft to complete. Its entire text is not
relabeled as the tested variable. Voice captures without a transcript also remain drafts.

When source parameters differ from the selected dataset, a confirmation displays the
differences before adding an item. Cancelling adds nothing. Confirming uses the dataset
parameters and creates a draft for reference review. Source parameters remain provenance
only; they cannot override the dataset.
Source history is preserved in the item context. Different histories within a dataset do
not require confirmation.

## Execute and judge

Select the candidate and judge independently. Starting a benchmark freezes ready items
and their resolved settings.

1. The first pass executes all items and persists candidate outputs and objective checks.
2. The second pass judges those saved outputs against their inputs, constraints and rubric.

The detail shows two progress indicators, separate costs, inputs, references, outputs,
checks and verdicts. Markdown analysis summarizes persisted results without changing scores.

A technically **completed** benchmark may contain quality failures. Coverage shows how
many items actually received a judgment. Judge failures leave the score absent; structural
similarity never replaces it. A critical objective violation prevents a passing verdict.

Cancellation preserves published work. **Resume remaining items** continues a cancelled
benchmark with its frozen settings. **Rejudge saved outputs** creates an independent
campaign without calling the candidate. Previous campaigns remain available. Starting
again from the dataset creates a new execution.

## Tasks

Interactive Task analysis remains available: select a Task, optionally supply human
context, and request a diagnosis. It reads canonical evidence without replaying the Task.

**Test and judge diagnoses** on the same page opens dataset-based diagnosis evaluation.
The Task capture menu also offers diagnosis capture.

## Interpret results

Compare identical items, context and rubrics with adequate judgment coverage. Snapshots
retain separate corpus, context and model fingerprints. Calibrate the automatic judge
against reviewed examples. Simulated tool calls do not prove real production effects.

See the [architecture contract](../architecture/ai-lab-evaluation.md).

## Read, repeat and review

Item lists display text without HTML tags, including nested messages. Original inputs
remain unchanged in the editor and in benchmark execution.

Each result shows its coherence percentage without expanding its details. Average
benchmark coherence is the arithmetic mean of available scores across all repetitions,
with the number of scored evaluations out of the planned total. A score of 0% counts;
an unjudged result is excluded. Filtering does not change the mean. Criteria remain
specific to each lab.

Result details display readable output, criterion scores, assessments and objective
checks. Filter failures, critical failures or unjudged results. Inputs, references and
raw data remain expandable.

Choose 1–20 repetitions per item. Stability shows passes out of planned repetitions,
available judgments, mean, range and standard deviation of available scores. A missing
judgment is never scored zero. These statistics describe repeated items, not generalization.

An optional USD budget covers candidates and all judgment campaigns. No new evaluation
starts once recorded costs reach the budget. An ongoing evaluation may exceed it;
costs not reported by a provider cannot be measured. Saved results remain available.
Create a new benchmark to use another budget. Optional Markdown analysis is billed separately.

From the benchmark list, **Human review** hides model identities and automatic scores.
Score and explain each criterion, then **Save and reveal judgment** displays dimension
differences and verdict disagreements. Your independent assessment is immutable after
disclosure and does not alter the judge. Each user and judgment campaign has a separate
review. This mode cannot undo prior exposure to results viewed elsewhere.

## Organize coverage

Choose the dataset role: **Work** for tuning, **Validation** for release checks, or
**Holdout** for independent evaluation. Roles do not restrict access or editing.
Assign item categories: nominal, ambiguity, incomplete context, multilingual, robustness,
security, real incident or valid alternative. Counts include ready and enabled items;
category filtering also finds drafts. Categories are frozen in benchmark snapshots.
