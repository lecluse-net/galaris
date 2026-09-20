<p align="right"><a href="../../fr/architecture/ai-lab-evaluation.md">Français</a> · <strong>English</strong></p>

# AI Lab Evaluation Architecture and Theory

The Lab exposes eleven evaluable treatments through one contract: **one business variable per
case**, its own context, shared parameters, and one output to assess.
See the [operator guide](../user/lab-ai.md) and [ADR 0078](../../../project/decisions/0078-lab-variable-and-judgment-campaigns.md).
Repository contracts and tests remain authoritative.

## 1. Treatment contracts

The complete typed inventory lives in `back/app/lab/contracts.py`. Descriptors expose the
treatment, variable schema, result and editable parameters. The registry adds the algorithm
configuration schema, inference limits, output schema and rubric.

| Treatment | Single variable | Evaluated result |
|---|---|---|
| Dispatcher | Request | Routing decision |
| Briefing | Objective | Preparation and resource choices |
| Planner | Objective | Plan or clarification |
| Topic classification | Exchange texts | Topic assignments |
| Memory extraction | Source content | Ranking and memory operations |
| Learning | Execution outcome and observations | Supported lessons |
| Goal tracking | Cycle result | Progress assessment and continuation |
| Task executor | Request | Response and recorded tool calls |
| Conversation executor | Current turn | Response and proposed actions |
| Voice executor | Turn transcript | Response and proposed actions |
| Task analysis | Evidence dossier | Structured diagnosis |

A variable may be structured: a dossier or execution outcome is one business object.
The original mission in learning remains a parameter. Topic message contents belong to the
variable; metadata belongs to context. Expected output is never a candidate input.

## 2. Datasets, cases and provenance

A dataset owns all parameters, algorithm configuration and, for executors, its instruction
suffix. A case input contains `{variable_value, context}`, with a separate expected output.
Both API and persistence reject item parameters. Resolution validates unknown fields and treatment constraints. Structural
configuration of composed algorithms belongs to the dataset.

`context_schema` and `context_defaults` describe item evidence: previous history (`history`,
`messages`), clarifications, historical media, initial Topic, message metadata and previous
Goal tracking, depending on the treatment. Context fields are disjoint from shared parameters
and cannot override them. Captures preserve context and compare only shared settings.
Snapshots freeze item context for both passes and rejudging; corpus fingerprints include it.

The UI edits parameters on the dataset, the variable, context and reference on each item, with resolved input preview. Rendered
instructions are inspectable; later stages of composed algorithms also depend on intermediate
outputs.

Captures compare observed source parameters to dataset parameters. Differences return
HTTP 409 with a confirmation token bound to the dataset revision and source. A retry with
that token explicitly accepts the dataset parameters; the item becomes a draft for review.
Changes to the dataset or source require a new confirmation. Restoring a source follows
the same rule. Source parameters remain provenance only, never executable overrides.

Captures copy available evidence without changing the source. Insufficient traces remain drafts
to review: historical text cannot silently reconstruct all its original parameters.
Diagnosis benchmarks accept Task captures. Interactive Task analysis remains available.

## 3. Theoretical Foundations

### 3.1 Validity: Measuring the Right Construct

A measure is useful if it represents the phenomenon one wants to manage. Comparing two strings
answers the question “do they look alike?”, not the question “do they satisfy the same
objective?” The Lab therefore starts from the business construct, then operationalizes it:

```text
business objective
    → observable requirements
    → mechanism-specific dimensions
    → dimension scores
    → versioned aggregate
    → contextualized human decision
```

This approach is consistent with the **TEVV** discipline — test, evaluation, validation and verification — of the
[NIST](https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv): metrics,
datasets, and methods depend on the usage context, and no single measure covers accuracy,
robustness, safety, explainability, or bias.

### 3.2 Coverage: Multiple Scenarios Rather Than an Abstract Average

[HELM](https://crfm.stanford.edu/2022/11/17/helm.html) recommends evaluation covering multiple
scenarios and multiple metrics, while making what is missing explicit. Galaris applies this
principle at the mechanism level: a dataset must represent the situations actually
encountered, their boundaries, and their risks, not merely easy nominal cases.

A benchmark average is therefore interpretable only together with its coverage matrix. A score of
95% on five homogeneous cases does not prove system robustness across languages, lengths,
ambiguities, or constraints absent from the dataset.

### 3.3 Exact Measures for Closed Choices

Exact equality remains the best measure when a contract accepts only a finite set of
values and those values have normative meaning. This is the case for the Dispatcher for:

- the active route `EXEC` or `PLAN`;
- effort `standard` or `high`;
- whether an action is required;
- the normalized language.

The Lab does not use a semantic judge to treat two routes that would produce different
workflows as equivalent.

### 3.4 Semantic Evaluation for Open Outputs

For texts, plans, memory lists, or reasoned decisions, a single reference does not
describe the entire space of good answers. [G-Eval](https://aclanthology.org/2023.emnlp-main.153/)
shows in particular that traditional overlap-based metrics correlate poorly with
human judgment for open and diverse generations.

Galaris therefore treats the reference as a source of possible requirements, never as a template to
imitate. The judge must accept a different formulation, order, number of items, taxonomy,
confidence, or strategy when it satisfies the objective and contract just as well.

### 3.5 Multidimensional Rubrics

An overall verdict such as “this response seems good” is difficult to audit. The
[LLM-Rubric](https://aclanthology.org/2024.acl-long.745/) and
[Prometheus](https://arxiv.org/abs/2310.08491) approaches support the use of explicit and
customized criteria. [PaperBench](https://openai.com/index/paperbench/) likewise decomposes a
complex objective into gradable requirements and evaluates judge quality separately.

The Lab therefore requires five dimensions per mechanism. Each dimension has:

- a stable code;
- an observable criterion;
- an explicit weight;
- a score from 0 to 100;
- a short assessment based on the supplied data.

The model does not calculate the overall score. The server checks the returned codes and applies the
versioned weights.

### 3.6 Pointwise Judgment

The judge evaluates a candidate output independently, against the input, objective, contract, and
rubric. It does not choose a “winner” between two models. This pointwise format avoids making
candidate order a direct element of the decision.

The judge prompt:

- treats all data as untrusted and not as instructions;
- does not receive the candidate model’s identity;
- prohibits rewarding lexical similarity, verbosity, confidence, or identity;
- provides the 0, 25, 50, 75, and 100 anchors;
- requests exactly one score per dimension;
- reserves critical failures for defects capable of invalidating the result.

### 3.7 The Judge Is Not Ground Truth

LLM judges may favor a position, a longer response, a smoother style, or
their own outputs. These phenomena are documented by studies on
[position bias](https://aclanthology.org/2025.ijcnlp-long.18/),
[surface and verbosity bias](https://aclanthology.org/2024.ccl-1.101/), and
[self-preference](https://aclanthology.org/2025.emnlp-main.86/).

Consequence: the Lab percentage is an instrumented estimate, not an absolute truth. It
must be calibrated against human judgments and reviewed when the stakes are high. Even expert
benchmarks such as GDPval describe the LLM judge as an estimate and retain
[human expert preference as the standard](https://evals.openai.com/gdpval/grading).


## 4. Execution followed by judgment

```text
dataset + ready cases → frozen inputs, parameters and model bindings
                     → pass 1: all candidate outputs + objective checks
                     → pass 2: judge each persisted output
                     → aggregates, verdicts, coverage, costs and optional analysis
```

Candidates receive only resolved input. Executor tools record calls and return configurable
fixtures; they create no Task, Process or message. Other mechanisms use their business contracts
and corresponding shared services.

Runs freeze cases, instructions, parameters, rubric, reasoning profile and model bindings.
Separate fingerprints identify corpus, context, candidate and judge. Each inference verifies
its provider binding and fails explicitly if it changed. Credentials are not copied.
Snapshots cannot freeze remote provider weights or an earlier code implementation.

The shared worker claims one unit under a lock, releases the transaction during inference and
publishes only while owning the lease. A heartbeat renews that lease. All candidates are
published before judgments begin. Cancellation preserves published results; resume processes
only missing units.

A judgment campaign has its model, configuration, sequence and results. **Rejudge** creates a
new campaign from saved outputs without calling the candidate again. Earlier campaigns remain
inspectable. Runs expose the latest assessment and separately accumulate candidate and judge costs.

## 5. Checks, scores and verdicts

The first pass records candidate failures, output schema validation, treatment checks and
structural reference similarity. Closed Dispatcher comparisons are critical; open output
references remain examples.

The second pass uses a versioned weighted rubric. The server computes the dimension average;
a critical failure reported by the judge caps that score at 50%. A failed critical objective
check also prevents a passing verdict even when the semantic score is high.
The initial passing threshold is 75%.

`completed` describes technical completion, not candidate quality. Verdicts distinguish passing,
failing and inconclusive assessment. Judge outages do not manufacture a zero score: the score
stays absent, coverage decreases and a run can be `partial`. Candidate failures remain visible.
The UI separates both progress counters, score, coverage, verdicts and costs.

Reference similarity never replaces a missing judgment. Markdown analysis is an optional report
based on persisted results.

## 8. Building a Dataset Capable of Detecting Drift

### 8.1 Start with Risks, Not Volume

Before adding cases, write down the failures the benchmark must detect. For example:

- Briefing that forgets a prohibition but cites every tool;
- technically elegant Planner that changes the requested deliverable;
- memory extraction that retains ephemeral or sensitive information;
- learning that concludes an unproven cause;
- goal tracking that stops after enthusiastic text without evidence of completion.

Each important risk must be represented by at least one case that fails when it occurs.

### 8.2 Recommended Coverage Matrix

A robust dataset mixes:

| Family | Examples |
|---|---|
| Nominal cases | clear input, complete evidence, obvious expected solution |
| Valid alternatives | different order, another taxonomy, different decomposition, or another justified tool |
| Boundaries | two plausible routes, attachment ambiguity, intermediate confidence |
| Incomplete inputs | missing context, missing resource, insufficient evidence |
| Conflicting constraints | speed versus verification, concision versus coverage |
| Plausible negatives | fluent response but off-objective, credible invention, unproven success |
| Robustness | long context, unnecessary fields, disrupted order, boundary characters or JSON |
| Multilingual | French and English cases representative of production |
| Safety | content attempting to instruct the judge, sensitive data not to be memorized |
| Real regressions | incident or bad decision already observed in production |

Simple duplication with a few changed words does not create new coverage. It is useful only if it
isolates a hypothesis: length, language, ambiguity, constraint, or structure.

### 8.3 Separate Tuning and Validation

If all cases are used to correct the prompt, they gradually stop measuring
generalization. For demanding use, maintain:

- a **working** set, visible and used for tuning;
- a **validation** set, rerun before delivery;
- if possible, a small **holdout** set, not used during daily corrections.

The `purpose` field records these roles (`work`, `validation`, `holdout`) without changing
access rights. Item categories support filtering and ready/enabled coverage counts and
are frozen in benchmark snapshots.

### 8.4 Reference Quality

A good reference:

- genuinely satisfies the input;
- makes critical requirements visible;
- contains no invention or unavailable dependency;
- does not artificially impose a form when multiple forms are valid;
- is reviewed by a qualified human when the case becomes a delivery gate.

Generating a reference with the Lab model accelerates data entry but does not create ground truth.
The same model family may reproduce the same biases during generation and judgment.

### 8.5 Living Dataset but Interpretable Benchmark

A dataset evolves when a new drift is observed. To preserve interpretability:

- never modify an old run;
- duplicate a case before a radical experiment;
- rerun a baseline after any dataset modification;
- compare only runs having the same score version and equivalent case snapshots;
- document the reason for adding, removing, or changing a reference.

The Lab retains snapshots but does not yet calculate a comparability fingerprint. This
verification is currently the operator’s responsibility.

## 9. Calibrating the Judge with Humans

### 9.1 Build a Calibration Set

Select cases covering the full spectrum: excellent, acceptable, borderline, poor, and
critical. For each case, retain multiple candidate outputs whenever possible, including
valid alternatives very different from the reference.

### 9.2 Write a Human Protocol

Human evaluators must receive exactly:

- the definition of the mechanism;
- the input;
- the rubric and its anchors;
- the candidate output;
- the reference, specifying its non-normative role.

They score each dimension independently before seeing the LLM’s score. Two or more evaluators
make it possible to identify ambiguous criteria; their disagreements must be adjudicated and used
to improve the rubric.

### 9.3 Measure Agreement

Do not check only the overall average. Compare at minimum:

- mean absolute error by dimension;
- mean bias — judge systematically too generous or too severe;
- rank correlation between models or versions;
- false passes above an operational threshold;
- critical failures missed or invented;
- disagreements by language, length, case type, and model origin.

A good overall correlation can conceal a judge that is dangerous on critical cases.

### 9.4 Recalibrate

Repeat calibration when:

- the **Lab** use of the current profile changes;
- a rubric or its weight changes;
- the mechanism prompt changes materially;
- the dataset changes domain or language;
- a new bias or incident is discovered.

Changing a formula creates a new score version. Previous percentages are never silently
recalculated.

## 10. Detecting Drift

Drift is a lasting change in behavior relative to the intended construct. It may
come from the candidate, mechanism, dataset, or judge.

### 10.1 Minimum Conditions for Comparison

Two runs are directly comparable only if the following elements are controlled:

- same mechanism and same score version;
- same cases, inputs, and references;
- same relevant mechanism configuration;
- same judge, or recalibrated judge;
- comparable inference parameters;
- complete judgment coverage or an explicitly accounted-for difference.

Changing the candidate model is the intended variable in a model benchmark. Changing the
dataset and model at the same time prevents attributing the variation.

### 10.2 Read Drift by Dimension

A stable average can conceal compensation: +15 in plan style, −15 in
objective fidelity. Always examine:

- average by dimension;
- cases that change qualitative class;
- new critical failures;
- candidate and judge errors;
- dispersion and outlier cases;
- recurring patterns in the Markdown analysis.

### 10.3 Model Variance

A benchmark supports 1–20 repetitions per item on identical frozen inputs. Publication
identity includes the repetition, preserving resume and rejudge behavior. The UI shows
passes out of planned repetitions, coverage, mean, range and standard deviation of available
scores. Confidence intervals and output agreement are not computed; spread does not measure
generalization.

An optional USD budget covers recorded candidate and judgment costs. Under the run lock,
the worker stops starting evaluations once the threshold is reached. An ongoing evaluation
may exceed it; optional Markdown analysis is separate. The run becomes `partial` with
`stop_reason=budget_exhausted` and preserves saved results.

### 10.4 Decision Thresholds

A threshold such as 80% has meaning only after calibration on the domain and analysis of the cost of errors.
A memory system may require zero critical inventions even with a high average. An exploratory
ranking tool may tolerate more ambiguous cases.

Establish thresholds from human decisions, not from the gauge color. One
possible policy distinguishes:

- critical gate: no false pass on invalidating violations;
- dimension gate: no material decline on a priority dimension;
- aggregate gate: bounded average decrease on a stable dataset;
- reliability gate: maximum candidate error rate and minimum judge coverage.

These gates are not yet automated by the Lab.


## 11. Persistence, API and access

Existing dataset, case and run models are reused. `LabJudgmentCampaign` and
`LabJudgmentResult` hold campaigns and assessments with real foreign keys.
DbAdmin applies the declarative schema.

The `app.lab` API covers datasets, parameters, cases, captures, preview,
start, cancellation, resume, results and rejudging. Assertions enforce LAB privileges and source
agent scope. UI visibility never replaces API authorization.

## 12. Limits and separate work

Dimension trends, automatic comparability alerts,
judge ensembles, standard result export and CI gates remain in the
[quality plan](../../../project/plans/lab-evaluation-mecanismes-ia.md).
Fingerprints are persisted but do not yet provide an automatic comparison screen.
Human review hides model identities and automatic judgments until submission, persists an
immutable assessment per user, result and campaign, then shows dimension differences,
verdict disagreements and mean absolute difference. It cannot undo prior exposure to
results and does not replace a calibration protocol. See [ADR 0082](../../../project/decisions/0082-lab-stability-human-review.md).
Automated checks use controlled responses; they do not qualify a remote model's quality.

## 13. Code authority

| Contract | Files under `back/app/lab/` |
|---|---|
| Inputs and scope | `contracts.py` |
| Algorithms and rubrics | `mechanism_registry.py`, `mechanism_rubrics.py` |
| Persistence and API | `models.py`, `schemas.py`, `router.py`, `assertions.py` |
| Resolution and captures | `mechanism_evaluation_service.py`, `dispatcher_evaluation_service.py` |
| Two passes | `run_claims.py`, `run_inference.py`, `run_publication.py`, `run_lease.py` |
| Rejudge and resume | `judgment_service.py` |
| Checks and fingerprints | `objective_checks.py`, `inference_profile.py` |

The shared UI is `front/app/lab/components/LabWorkbench.vue`.
Contract and persistence tests live under `back/app/lab/tests/`; browser scenarios are in
`e2e/specs/lab.spec.mjs`.

## 17. References

- NIST, [AI Test, Evaluation, Validation and Verification](https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv).
- Stanford CRFM, [Holistic Evaluation of Language Models](https://crfm.stanford.edu/2022/11/17/helm.html).
- Liu et al., [G-Eval](https://aclanthology.org/2023.emnlp-main.153/), EMNLP 2023.
- Kim et al., [Prometheus](https://arxiv.org/abs/2310.08491), 2023.
- Hashemi et al., [LLM-Rubric](https://aclanthology.org/2024.acl-long.745/), ACL 2024.
- Zheng et al., [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685), 2023.
- OpenAI, [PaperBench](https://openai.com/index/paperbench/).
- Shi et al., [Judging the Judges: Position Bias](https://aclanthology.org/2025.ijcnlp-long.18/), 2025.
- Zhou et al., [Mitigating the Bias of LLM Evaluation](https://aclanthology.org/2024.ccl-1.101/), 2024.
- Chen et al., [Beyond the Surface: Measuring Self-Preference](https://aclanthology.org/2025.emnlp-main.86/), 2025.
- Pydantic AI, [Datasets and evaluators](https://ai.pydantic.dev/evals/how-to/dataset-serialization/).
