<p align="right"><a href="../../fr/dev/lab-reference-corpus.md">Français</a> · <strong>English</strong></p>

# Editorial validation corpus for the Lab

`back/app/lab/reference_corpus.json` contains six versioned synthetic cases: concurrent HTML
editing, attachment URIs without a console, document prompt injection, unconfirmed delivery,
HTML versus Markdown, and usage without an imposed budget. They exercise briefing and review
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
