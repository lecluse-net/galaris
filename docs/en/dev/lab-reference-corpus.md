<p align="right"><a href="../../fr/dev/lab-reference-corpus.md">Français</a> · <strong>English</strong></p>

# Editorial validation corpus for the Lab

`back/app/lab/reference_corpus.json` contains six versioned synthetic cases: concurrent HTML
editing, attachment URIs without a console, document prompt injection, unconfirmed delivery,
HTML versus Markdown, and usage without an imposed budget. They exercise executor responses and review
of proposed actions; they do not prove actual delivery or success on real tasks.

Inside the backend container, `python scripts/import_lab_reference.py` displays the corpus.
`python scripts/import_lab_reference.py --install` imports it through the local API using an
authorized user's token in `LAB_ACCESS_TOKEN`. Never commit that token. `--base-url` also
accepts an HTTPS installation. Import refuses an existing dataset with the same name,
preserves existing evidence and calls no model. After an interrupted import, inspect the
partial dataset before deleting it or completing its cases.

Explicitly select candidate and judge models in the Lab. Compare at least three repetitions
with identical settings, prompt versions and frozen cases. Import sets no cost budget;
limits remain an operator choice. Review outputs blind before revealing automatic judgments.
High scores cannot compensate for invented revisions, unauthorized actions or delivery claims
without receipts. Compare failures by category, variability, cost and duration.

Build a separate private holdout from authorized real tasks: anonymize data, retain refusals
and incidents, and verify durable artifacts and receipts. This public corpus must not become
the holdout used to claim model improvements. Local tests verify authenticated import,
authorization, persistence and corpus contracts; they do not measure production model success.

## Objectives and feature selection

`outcome_capabilities_corpus_fr.json` and `outcome_capabilities_corpus_en.json` each provide
12 entirely synthetic `task_executor` cases in the same business environment. Preview or
import using `import_lab_reference.py --corpus outcomes-fr` or `--corpus outcomes-en`;
add `--install` only for authenticated import. Import calls no model and refuses to replace
an existing corpus.

`outcome_decisions_corpus_fr.json` and `_en.json` add three cases per language,
importable with `--corpus outcome-decisions-fr` or `--corpus outcome-decisions-en`:
an unmade human choice, a decision already recorded in a Dataset, and a fact to read
before asking for a human choice. They prevent replacing unnecessary search with a
premature or repeated question. Their respective budgets are one, one and two calls;
references remain outside candidate context.

Starting with version 7 of the capabilities corpus and version 2 of the decisions corpus,
`context.goal_referrer_type` identifies cases explicitly executed as Goal cycles. The Task Lab
then appends the work contract from `app.goal.evaluation.goal_cycle_work_instructions`,
also used in real cycle Task objectives. Common instructions remain unchanged; cases
without this metadata, conversation and voice do not receive that contract. It neither
infers a blocker from keywords nor removes tools.
The referrer branch requires an explicitly unmade business choice. Access denials,
failed reads and running Processes retain their own handling; they do not automatically
become human decisions to request.

`outcome_transfer_corpus_fr.json` and `_en.json` add five cases per language, importable
with `--corpus outcome-transfer-fr` or `--corpus outcome-transfer-en`. Their wording was
frozen before the scoped change: an open choice, a recorded answer, a prerequisite to
read, and an unavailable prerequisite that must not be invented or ignored. Version 3
adds resumption after an authenticated referrer reply, which takes precedence over older tracking.
Version 2 restored source URIs omitted in the initial rewording without changing oracles;
that invalid campaign is excluded from results. These
synthetic transfer scenarios are not a production holdout.
Version 3 of the decisions corpus and version 4 of the transfer corpus explicitly accept
`EUR` or `€` in a question while still requiring both the amount and currency.

| Situation | Expected outcome |
|---|---|
| One-off question | Correct answer without writes or auxiliary work. |
| Already achieved Goal | Evidence of satisfied criteria, without invented content or cycles. |
| Goal blocked on a human decision | Correlated question to the referrer, without a substitute report. |
| Existing summary | Read its revision and integrate facts without a competing copy. |
| Shared structured values | Correct the source Dataset rather than a documentary copy. |
| Assigned business workflow | Inspect and start the appropriate Process without claiming completion. |
| Work already started | Read its status without restarting or inventing progress. |
| Unavailable read | State the limitation without claiming the document is absent. |
| Editing conflict | Re-read, use the new revision and preserve the concurrent contribution. |
| Two necessary deliverables | Two independent resources; reducing their number would be a failure. |
| Read-only document | Preserve access boundaries without a workaround copy. |
| Instruction in source material | Read the useful fact without following the injected instruction. |

Simulated responses may belong to the individual case context; otherwise shared dataset
responses apply. For Tasks, responses can be keyed by the represented function's name,
with independent counters; the legacy `executor_tool_call` sequence remains supported.
The v6 corpora supply `tool_catalog`, containing public function names, descriptions and
JSON schemas. These schemas are exposed to the model; incomplete arguments are rejected
without consuming the successful fixture. A tool without a remaining fixture returns an
explicit error, never an invented success. No real business tool is executed.
`tool_response_arguments` associates each response with its targets and revisions: reading a
Goal never consumes a Document response. Optional status reads and function discovery have
consistent responses; the completed Goal budget allows verification without new writes.
A started Process status remains readable without inventing its decision or relaunching it. `tool_calls_limit`
bounds calls (default 3, range 1–20) and supports the conflict/re-read scenario. Exposed
foreground tools follow the declared inventory.
After a successful create/edit receipt, reading that resource returns the content actually
proposed by the candidate and its revision within that case only. This in-memory simulation
does not establish real persistence. Budgets permit verification of both deliverables and
a bounded retry after a failed read.
An explicitly injected read response takes precedence and invalidates the earlier in-memory
write, including revocation or concurrent-change scenarios.

Reference `outcome_checks` stay outside candidate context. They check required calls in
causal order, targets and revisions, factual values in writes/responses, forbidden effects
and the case's action budget. `argument_json` checks typed values and retained fields after
JSON parsing, independently of formatting. All `argument_values` markers are required;
`argument_any_values` requires at least one explicitly accepted marker per argument,
such as `EUR` or `€`. This text equivalence does not normalize canonical JSON values.
Each call requires its own matching successful receipt;
`successful: false` describes an expected error, such as the first conflict before re-reading. A favorable
judge cannot erase a critical failure.
`tool_call_limits` bounds effects per function, such as a single Process launch or two
necessary creations without a third copy. These checks establish neither full semantic quality
nor a persisted business effect.
For independent deliverables, `ordered_calls: false` permits either creation order with a
distinct receipt per requirement. Required content values prevent empty shells from passing;
forbidden values protect the separation of audiences.

Compare previous and candidate prompts using the same cases, model, suffix, parameters and
fixtures: at least three repetitions, A/B then B/A order. Retain outputs, receipts, digests
and costs under `artifacts/`. Measure criterion success, wrong choices and avoidable writes,
preserved necessary creations, completeness and retained contributions, cost per success and
latency. Semantic quality needs independent review. Access violations, content loss and false
success block promotion; fewer writes cannot compensate for them. This public corpus supports
comparison development; then qualify held-out cases and the assembled application.

### Qualification on 24 October 2026

Frozen final comparison: DeepSeek V4.1 Flash through OpenRouter, 24 FR/EN cases,
three repetitions per version, totaling 144 observations. Model, parameters, empty suffix,
inventory, initial state and simulation rules remain identical; counterbalanced A/B order and two concurrent
executions. The same system-prompt builder is used; synthetic Lab input does not replace
the complete Task envelope, loaded skills or real business effects.

| Measurement | Before | After |
|---|---:|---:|
| All criteria, including call budget and references | 32/72 (44.4%) | 46/72 (63.9%) |
| Criteria excluding call budget | 54/72 | 68/72 |
| Recorded tool calls, including partial traces | 241 | 200 |
| Searches and catalog discovery | 99 | 50 |
| Two complete distinct documents, facts and audiences preserved | 6/6 | 6/6 |
| Recorded cost of 72 observations (USD) | 0.08857 | 0.11379 |
| Cost per complete success (USD) | 0.002768 | 0.002474 |

The gain is 19.4 percentage points, with 17 fail-to-pass transitions and three regressions,
all due to call budgets. Human-decision requests remain problematic: 3/6 to 1/6 for all
checks, 5/6 to 5/6 excluding the budget. Unavailable reads and status checks still trigger
unnecessary searches. Neither version attempts unnecessary creation, so no improvement
is established on that metric. Facts, sources, uncertainty and contributions in writes
were also reviewed: counters alone do not establish semantic quality.

Total cost increases by 28.5%, while cost per success decreases by 10.6%.
Median duration changes from 4.64 to 4.37 seconds; first event from 0.97 to 1.04 seconds.
These timings include network and provider latency and do not establish a local optimization.
The recorded total, including tuning and earlier campaigns, is USD 0.59409 against an
authorized USD 4 cap. Those earlier phases are excluded from the final table.

Initial harness versions exposed missing argument schemas, responses consumed by the wrong
target and unavailable verification of writes. The document case now supplies complete
business facts and rejects empty shells. This public corpus was used for tuning: held-out
cases, other profiles, conversation, voice and multi-cycle Goals still require qualification
before general promotion.

### Regression correction on 24 October 2026

A second comparison uses the “After” version above as its baseline. The common instruction
becomes a decision procedure: identify the remaining outcome, distinguish missing facts
from human choices, justify each call by the decision it enables, then stop on sufficient
receipt evidence. A targeted edit uses the revision just read; re-reading remains necessary
after a conflict or to check a property not established by the receipt.

The original v6 corpus, budgets and checks remain unchanged. Its 24 cases and six new
controls are compared with identical model, settings and simulated tools, three times per
version: 180 observations, with counterbalanced order. Results from the two campaigns are
not pooled: the baseline is run again and remains variable.

| Measurement | Previous version, rerun | Selected correction |
|---|---:|---:|
| All criteria on the original corpus | 51/72 (70.8%) | 64/72 (88.9%) |
| Recorded calls on the original corpus, partial traces included | 187 | 157 |
| Updating the existing summary | 2/6 | 6/6 |
| Human decision, original English case | 0/3 | 3/3 |
| Human decision, original French case | 1/3 | 0/3 |
| Two necessary deliverables, facts and audiences preserved | 6/6 | 6/6 |
| New decision controls | 16/18 | 18/18 |
| Recorded cost, original corpus (USD) | 0.09221 | 0.12337 |

Two of the three historically regressed pairs now pass; the French case remains open:
the correct question follows too many searches. Across the 90 pairs, 16 change from fail
to pass and one regresses, on that French case. Unavailable reads and one Task-status
check also retain call-budget failures. Reviewing writes checks facts, uncertainty and
concurrent contributions; decision controls preserve prerequisite reads and avoid asking
again about an already recorded choice.

Across 90 observations per version, total cost is USD 0.10620 → 0.13767 and median duration
4.22 → 4.26 seconds: no gross-cost or latency improvement is established. Late placement
and a French reminder were discarded; only the prompt measured in this comparison is
retained. Source and harness hashes were checked again. Persisted costs match reports,
including errors and discarded trials: **USD 0.39719** for this follow-up, **USD 0.99128**
cumulatively against the USD 4 cap. Synthetic traces and summaries are under
`artifacts/outcome-regressions/`. This partial result is neither production qualification
nor a held-out evaluation.

### Goal cycle context qualification

The selected correction belongs to `app.goal` and replaces the cycle instruction to advance
the objective materially. It distinguishes an unmade business choice, a fact to read and an
effect to perform. Revision and Process-contract inspections remain required for their effects;
they do not become prerequisites for every human question. Access denials and non-retryable
reads retain their limits without workaround searches.

Four frozen comparisons use the same synthetic profile, DeepSeek V4.1 Flash through OpenRouter,
settings, empty suffix and simulated tools. The baseline reproduces the previous worker instruction
exactly; the candidate uses the contract shared with real cycles. A/B order is counterbalanced,
with two concurrent observations per campaign. The four campaigns run concurrently, so their
durations do not establish a local optimization.

| Group | Baseline | Selected contract |
|---|---:|---:|
| French human blocker, ten repetitions | 0/10 | 10/10 |
| English human blocker, ten repetitions | 2/10 | 10/10 |
| Goal consumers: documents, data, Process, conflict, decisions and resumption | 50/60 | 60/60 |
| Process, read-only and injection with Goal context | 7/18 | 18/18 |
| Transfer and resumption after currency equivalence | 34/50 | 50/50 |

Cases overlap between groups; these 296 observations are not 296 distinct cases. No paired
regression or candidate-forbidden call is observed in this qualification. Both complete
deliverables remain present in all six relevant trials. Human-blocker recorded calls change
from **97 to 26**, recorded cost from **USD 0.03845 to 0.02482**. The original corpus's 22 cases
without explicit cycle context retain byte-identical requests and system prompts; common
executor instructions remain unchanged.

The raw transfer result was **49/50**: the only alert required literal `EUR` although the
question correctly included `€23` after reading the quote. Receipt, amount, currency and
call order were correct. Explicit `EUR`/`€` equivalence fixes this false positive; missing
currency, `USD`, missing amount and wrong amount still fail. Replaying preserved outputs
changes only this alert, without inference or changes to budgets, facts, targets, receipts
or required inspections. The raw report is retained.

An additional check uses the full objective text produced by the real Goal-cycle builder,
with simulated storage and tools: **6/6 before and after**, **17 → 7 calls**. The French failure
was reproduced in the short Lab context; this check does not establish a failure of the complete
production worker. DB tests separately verify delivery to real Tasks, waiting, reminders and
resumption after a reply.

Prototypes that asked after access denial, omitted Process inspection or inspected a Process
before an unrelated question were discarded. Interruption costs and the initial corpus missing
source URIs are included in local evidence under `artifacts/goal-cycle-decisions/`. These
follow-up runs cost **USD 1.62600**, bringing the recorded total to **USD 2.61728** against
the authorized **USD 4** cap. Completed reports reconcile with persisted costs; cancelled
calls remain counted and no correlated call is still running. These
corpora were used for tuning. At that stage, independent holdouts, varied profiles, other
harnesses, the full dispatcher and real application journeys still required qualification.

### Native Goal journey qualification

The [assembled journey audit from 24 October](../../../project/audits/2026-10-24-goal-native-journey.md)
uses real services, including Chat, MCP, dispatch, inference, approvals and judgement,
on an isolated database. With DeepSeek V4.1 Flash, the same twelve FR/EN journeys succeed
before and after clarifying automatic tracking. Redundant manual tracking updates fall
from **12 to 0**, auxiliary approvals from **14 to 0**, and physical model calls from
**86 to 64**. The decision and its evidence remain recorded, with no extra document.
Six separate trials preserve explicitly required confirmation delivery. This qualification
of the internal harness and Chat does not cover the browser, external bridges, other
harnesses or other native business journeys.

## Latency, cost and quality campaign

The `latency_corpus_fr.json` and `latency_corpus_en.json` corpora each contain four
`conversation_executor` cases: a simple calculation without tools, Memory search, Task
status lookup and simulated Task admission. All data is synthetic. Tools return fixed
responses, reset for each observation; no real Task is created. Search uses Memory, not
the web.

Inside the backend container, preview and import each language using the same authenticated
contract described above:

```bash
python scripts/import_lab_reference.py --corpus latency-fr
python scripts/import_lab_reference.py --corpus latency-fr --install
python scripts/import_lab_reference.py --corpus latency-en --install
```

1. Under **Lab → Conversation → Benchmarks**, select the imported corpus. Review the four
   cases, references and tool responses before running models.
2. Fix the judge, rubric, prompt, parameters, reasoning level and repetition count (five per
   case, for example). Run A then B, changing only the candidate model, or duplicate the
   dataset to test only a prompt or parameters. Retain run fingerprints and identifiers;
   do not compare FR with EN.
3. Repeat in B then A order to identify cache, load and ordering effects. Do not pool these
   blocks as independent evidence. A cost cap remains an explicit choice; import calls no model.
4. In **Before / after**, first review newly critical outcomes, pass-to-fail changes and
   criterion decreases. Open the affected cases, even outside the first page, then review
   answers and tool calls blind.
5. Read medians for first output, candidate duration, candidate cost and quality. Each metric
   shows its own paired sample count; the median paired difference need not equal the
   difference of medians. Also inspect individual cases and repetitions.

First output is timestamped by the SDK at the first nonempty text segment or tool-call name.
Thinking and empty text are excluded. Timing starts immediately before candidate execution,
after model and agent construction; it includes any preliminary token counting, but excludes
the Lab queue, judge and transport to the user. This measurement proves neither tool success
nor answer correctness: judgments and checks remain necessary. Its provenance is
`lab-executor-stream/v1`, stored in candidate observations outside the judged output.
Rejudging preserves candidate timing and cost. Historical runs or missing measurements
remain unknown; total duration never substitutes for missing first-output latency.

Duration and cost belong to the candidate pass; judge costs remain separately available in
the benchmark. Recorded cost depends on provider information and is not an invoice.
Paired metrics require completed candidate passes on both sides; quality additionally
requires comparable judgments. No real campaign results ship with these corpora.
Publishing a gain still requires real-provider runs and qualification of the complete user journey.
