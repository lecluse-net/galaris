# Native Process campaigns

Use this procedure to benchmark a native business Process through `lab_process_*`. A campaign
creates real runs. Synthetic inputs do not simulate email, API calls, file writes or any other
declared workflow operation. Lab access alone does not grant Process or source-file access.

## Prepare a bounded experiment

Read the exact definition with `process_definition_read(process_code=...)`. Check its input
declarations, actors, external operations and expected outputs. Use the canonical definition
reference returned by Galaris; do not invent a Process code or turn a standalone tool into a
Process to benchmark it. The campaign agent needs Process launch rights and the `process_start`
capability; each case rechecks admission rights.

Choose a small case set and stopping condition consistent with the user's requested experiment.
Do not assume these tools offer `lab_run_start`'s model, repetitions or `max_cost` arguments.
If real external effects fall outside the mandate, prepare the cases and explain the missing
authorization before launch. Existing authorization for the experiment need not be requested again.

## Create the input Dataset

- `lab_process_dataset_create(title, cases, invocation_key)` saves an independent private JSON
  Dataset. Each case contains `input`, optional `expected` exact outputs and optional `files`.
- `lab_process_dataset_generate(code, title, invocation_key, instructions="", count=8)` generates
  1–20 cases from the current Process contract using the agent's configured Lab model. Read the
  returned Dataset with `file_read` and review every case before launching.

Use entirely invented data; do not copy live conversations or business records into fixtures.
The Dataset contains `synthetic: true` and `cases`, and returns `dataset_id`, `dataset_uri` and
`revision`. Keep these exact references. A generic mechanism dataset ID is not this Dataset ID.

For a typed v2 Process, construct inputs using its declared `{type, value}` envelopes, including
nested values, defaults and nullability. Historical v1 uses its own ordinary JSON contract.
File inputs carry exact authorized resource URIs with optional descriptions; never fabricate
identities or embed bytes. Expected outputs are optional exact checks, not independent ground
truth. Omitting `expected` is valid when only execution evidence is being measured.

## Launch and inspect

1. Call `lab_process_campaign_start(code=CODE, title=TITLE, dataset_id=DATASET_ID,
   invocation_key=KEY)`. Keep the returned campaign `id`. The Dataset's current cases are
   captured; each subsequent case admission resolves the latest saved Process definition.
2. Inspect `lab_process_campaign_get(campaign_id=ID, page=1, page_size=50)` with reasonable
   pauses. Page sizes are 10, 20, 50, 100 and 500; use `total`, `page` and `page_size` to read
   all cases. This family does not use the generic `pagination` / `next_offset` contract.
3. Inspect each case's status, `run_id` and `evidence`: actual data, checks, duration and cost.
   Follow a returned run through the normal Process readers if more context is needed.
   A created campaign or admitted case is not a completed run or a passed exact check.

Reuse the same invocation key and unchanged arguments after a lost creation or start response.
A new experiment needs a new key. Do not create a replacement campaign merely because it is
slow. If the source Dataset changed before retry, reconcile the saved campaign instead of
guessing that the previous launch failed.

## Stop and compare

`lab_process_campaign_cancel(campaign_id=ID, invocation_key=KEY)` requests cancellation of
the campaign and its admitted runs. Follow the same campaign until termination is confirmed.
Already completed effects and incurred costs remain; cancellation is not rollback. Do not
relaunch a campaign to resume or rejudge it: this family has no generic benchmark resume or
rejudge contract.

Compare saved case evidence only after checking inputs, actual admitted definitions, actors
and operations. Do not claim a single frozen definition when edits occurred between case
admissions. Unknown or partial costs are not zero, and passing exact output checks does not
prove every external effect was correct. Report unfinished cases, failed checks and the scope
of observation. Do not promote experiment settings or change the Process without the relevant
mandate and edit rights.
