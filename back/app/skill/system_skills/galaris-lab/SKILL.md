---
name: galaris-lab
description: Operate Galaris AI Labs through the dedicated lab MCP tools. Use for constructing synthetic or captured benchmarks, testing experimental prompts and models, diagnosing Tasks, comparing runs, reviewing outputs and iterating on measured regressions.
---

# Galaris Lab

Use the exact tool names exposed by your runtime. `lab_*` requires the optional Lab connection;
this skill grants no access. Real source discovery, capture and Task diagnosis additionally
require the execution-inspection functions of `galaris_admin`. Explain a missing capability
without trying to bypass it with SQL, a console, another identity or a direct provider call.

## Discover the experiment

Call `lab_list`, then `lab_get(mechanism)` and `lab_models(mechanism)`. Eleven mechanisms share
the same tools: dispatcher, briefing, planner, topic_classification, memory_extraction,
outcome_reflection, goal_tracking, task_executor, conversation_executor, voice_executor,
task_analysis. Read the actual schemas, rubric and compatible models rather than guessing fields.
`lab_prompt_defaults` returns effective defaults without creating anything.

State the question being tested, the baseline and the one intended change. Choose a spending
budget and stopping condition consistent with the user's mandate. If an essential budget is
missing for an open-ended campaign, ask before launching repeated paid experiments; ordinary
bounded work already authorized does not require repeated permission.

## Build the corpus

The dataset tools are `lab_dataset_list`, `lab_dataset_get`, `lab_dataset_create`,
`lab_dataset_update`, `lab_dataset_clone` and `lab_dataset_delete`. Case tools are
`lab_case_list`, `lab_case_get`, `lab_case_create`, `lab_case_update`, `lab_case_duplicate`
and `lab_case_delete`. Discover Topic sources with `lab_topic_agent_list` and
`lab_topic_person_list`; preview with `lab_topic_messages_preview`, then capture with
`lab_topic_messages_import`.

Use `lab_dataset_list/get/create/update/clone/delete` and `lab_case_list/get/create/update/duplicate/delete`.
Datasets here are Lab experiments, not JSON documents in the document library. Each holds
shared parameters, algorithm configuration and a work/validation/holdout purpose. Each case
holds `input_data.variable_value`, its item-specific `input_data.context`, and `expected_output`.
An item's context cannot override shared parameters. Keep text, JSON and editorial HTML in
the format required by the mechanism; do not convert every input to Markdown or HTML.

Read before editing and pass the returned revision in `data.revision`. Patches preserve omitted
fields. On conflict, reload and reconcile; never guess a newer revision. Dataset cloning copies
the cases and provenance, allowing a prompt or parameter experiment without overwriting the baseline.
Case edits validate their input and reference before becoming ready. Use `readiness="draft"`
for a case needing review and `enabled=false` to exclude it from future runs. Existing snapshots
are unaffected by later edits. Dataset deletion requires finished/cancelled runs.

Two ways to acquire cases:

- `lab_dataset_generate` creates a synthetic draft experiment from a name, instructions, language,
  count (1–20) and categories. Optionally pin a source dataset and its revision to keep its shared
  experimental configuration. Poll the returned operation; inspect every generated reference before
  making its cases ready. A generated reference is a proposal, not independent ground truth.
- `lab_source_list` and `lab_case_import` capture typed real sources. Topic ranges use
  `lab_topic_agent_list`, `lab_topic_person_list`, `lab_topic_messages_preview/import`. Supply
  timezone-aware dates; shorten a truncated range rather than treating it as complete.

When capture reports `dataset_parameters_mismatch`, inspect the differences. Either adapt the
experiment or explicitly resubmit the returned `confirmation_token` if retaining the dataset's
parameters matches the user's experiment. The token is bound to the exact captured state; stale
confirmation fails. The captured case remains a draft for review. `lab_case_restore_source`
restores its captured evidence using the same conflict protocol.

`lab_expected_generate` proposes a reference asynchronously without accepting it. Use
`lab_input_preview` to inspect the resolved input and prompts before spending on a benchmark.
Cover relevant ambiguity, incomplete context, multilingual inputs, security and failure cases,
not just nominal examples. Do not revise references simply to improve a candidate's score.

## Run, inspect and recover

`lab_run_start` takes the dataset's current revision, a candidate `llm_id`, optional
`judge_llm_id`, repetitions (1–20) and optional `max_cost` in USD. It returns a durable run
immediately. Candidate execution completes before the independent judgment pass.

Every command with `invocation_key` needs a new stable key for a new intention. Reuse the exact
key and arguments after a lost response; changing arguments with that key is a conflict.
Record returned dataset/case/run/campaign/operation references. Never create a replacement
solely because a request was slow or its response was lost.

Read `lab_run_get` for progress, cost and errors; use `lab_run_results` for paginated evidence
and `lab_campaign_list/get` for independent judgment history. Lists take
`pagination={"limit":50,"offset":0}`; follow `next_offset` until null. Supported page sizes are
10, 20, 50, 100 and 500. For oversized case/result/run JSON use `lab_content_read`, checking that
the fingerprint remains identical across character pages. `pagination.summary_only=true` discovers
IDs when complete list items exceed the response budget. The content reader also supports
dataset, campaign, judgment and agent review records.

`lab_run_list` finds existing runs. `lab_campaign_list` lists their campaigns and
`lab_campaign_get` reads one campaign's judgments. `lab_run_delete` removes a terminal
run at its observed status; preserve useful evidence before deleting it.

- `lab_run_cancel` requests cancellation; an in-flight model call may still be billed.
- `lab_run_resume` resumes a cancelled benchmark's missing publications, preserving saved output.
- `lab_run_rejudge` creates a new judgment campaign over saved outputs. Use it after a judge
  failure or to evaluate another judge; it does not rerun the candidate.
- `lab_run_analyze` starts an asynchronous analysis of a terminal run. `lab_operation_get`
  exposes its status and complete JSON result, with character continuation for large results.
- `lab_operation_cancel` cancels a queued job or requests a stop before publication. An
  interrupted inference may leave an `unknown` operation; inspect it before explicitly retrying.

Poll with reasonable pauses; avoid a tight loop. A revoked connection/function stops new work.
The budget is checked between evaluations using recorded candidate and judge costs; it is not
a strict financial reservation. In-flight work can exceed it, missing provider costs remain
unknown, and generation/analysis costs are separate. A budget-exhausted run retains its results.

## Compare and judge honestly

Use `lab_run_compare(left_run_id, right_run_id, axis, pagination)` with axis model, prompt or
parameters. Inspect blockers, configuration differences, missing outputs, critical checks,
scores by case/dimension, costs and durations. Repeat with reversed runs for unmatched cases.
A changed corpus, judge or unrelated configuration can invalidate a claimed improvement.
Results are descriptive observations: repetitions of one case are not independent new cases.

`lab_review_get` provides the frozen rubric and candidate evidence without its automatic judgment
until this agent submits. `lab_review_submit` records an immutable **agent** assessment for that
campaign/result; `lab_review_list` labels agent and human assessments separately. Do not present
an agent assessment as human validation. Seeing an answer elsewhere means the review is no
longer meaningfully blind even if this endpoint hides it. Failed critical checks remain failures.

A missing judge score is missing evidence, never a pass. The executors simulate tools and do
not execute real side effects. Voice Lab tests transcribed turns, not recognition or synthesis.
Briefing remains evaluable even when disabled in normal runtime. Decision models are only
eligible for Dispatcher, Topics and memory extraction; hybrid runs pin their text model.

## Diagnose and iterate

For a real Task, use `lab_task_candidates/list`, `lab_task_add`, `lab_task_analyze` and
`lab_task_diagnoses`. Cite its complete `galaris://task/<uuid>` URI when reporting findings.
`lab_task_remove` removes only its Lab reference. Add an authorized captured or synthetic
regression case to a suitable experiment and test the proposed change against the baseline.
`lab_task_candidates` discovers Tasks outside the Lab; `lab_task_list` lists registered Tasks.

Useful recipes:

1. **Two models:** prepare and review one corpus; run each model with the same judge and budget;
   compare on axis model, inspect regressions and costs, and stop at the agreed evidence threshold.
2. **Prompt change:** clone the baseline, edit only its experimental prompt, preview an input,
   run the same model/judge and compare on axis prompt. Explain any comparability blocker.
3. **Judge outage:** inspect saved candidate output and errors; rejudge when the judge is usable,
   keeping both campaigns and avoiding a second candidate run.

Conclude with evidence, coverage and remaining uncertainty. If durable authored reporting is
requested, update the relevant Galaris document or create one through File Sharing, with links
and identifiers for the canonical experiment records. The report does not replace those records.
Experimental edits never authorize promotion to production settings. Use separately authorized
administration for any production change, and preserve the agreed stopping condition.
