<p align="right"><a href="../../fr/dev/document-qualification.md">Français</a> · <strong>English</strong></p>

# Document qualification

`core.document` prepares text and a rendered image for every PDF or converted Office
page. Its explicit worker limits are 512 MiB of source, 2,000 pages, 10 million text
characters, 2 GiB of memory and 20 minutes. Office macros are disabled. Pandoc handles
Markdown, HTML and EPUB; plain text and images are also supported. Unsupported or
failed conversions produce explicit failures. OCR must be checked against the image.

The Chat and Responses gateways accept `galaris_document_mode`: `auto`, `direct` or `prepared`.
Automatic mode sends a compatible PDF to a file-capable model with its rendered cover
when images are supported; other inputs use preparation. Document refusals and
structured answers reporting incomplete reading may trigger fallback. Apparently
valid free-form output does not prove correct reading. Open streams and tool effects
are never automatically replayed.

Prepared batches contain at most 80,000 characters and eight images. Pages with little text
may include a whole-page view and four enlarged quadrants,
preserving small details when the provider resizes images. Images request high detail.
Consolidation discards caveats about absence in one batch when another batch establishes
the complete answer, while preserving genuine uncertainty about the source. Multiple batches
are consolidated. Provider errors 502, 503 and 504 may be retried twice, only for
completed requests without streaming or tools. Retries count against the overall
call budget. A request accepts at most 64 MiB of inlined files and 64 calls;
`galaris_document_max_calls` can lower the call budget. Multi-batch consolidation
does not accept tools. `X-Galaris-Document-*` headers describe mode, source pages,
batches, calls and fallback reason. Source page counts do not prove semantic coverage.

## Reproducible protocol

Keep private sources under `refs/` and reports under `artifacts/`. Independently
review the question suite before evaluating model answers: visual titles, exact
numbers, tables, drawings, handwriting and facts on final pages. Keep historical
results separate from results for the current implementation.

```bash
make qualify-documents ARGS='prepare-pipeline /qualification/refs /qualification/results/pipeline-run'
make qualify-documents ARGS='trial /qualification/refs /qualification/results/corpus-smoke-suite.json /qualification/results/terra-auto.json --profile abonnement-openai --mode auto --max-calls 6 --max-tokens 2500 --base-url https://galaris.example.test'
make qualify-documents ARGS='trial /qualification/refs /qualification/results/corpus-smoke-suite.json /qualification/results/fireworks-prepared.json --profile exclusif-fireworks --model-slot text --mode prepared --max-calls 6 --max-tokens 2500 --base-url https://galaris.example.test'
```

Replace the example HTTPS origin with the local instance's origin. Pass the authorized account token through
`DOCUMENT_QUALIFICATION_TOKEN`, never a command-line argument. `--max-calls` limits
benchmark document requests; each may issue internal preparation/consolidation calls.
Reports sum their costs. `native` tests direct transport without preparation; `text`
tests common text extraction without images with the profile's text model. To test the new
preparation without file capability, use `prepared` with a profile and `--model-slot text`
to select its text model; do not change a shared profile solely for a measurement.

Compare identical sources, questions and budgets. `check` checks answers against the
reviewed reference and `qualify` combines evidence. Provider failures and missing
answers are failures. Synthetic tests live in `tests/test_document_pipeline.py` and
`tests/test_document_qualification.py`.

### Qualifying a source/model combination

Define the tested combination: format and structure, reader version, profile,
model, mode, language and budgets. Compare direct and prepared reading with identical
sources and FR/EN questions, an independently reviewed reference and a held-out corpus
that was not used for adjustments. Check facts, numbers, units, tables and citations
against the source, including expected absences. HTTP 200 or a claim of complete
reading cannot replace this review.

For large sources, include a 500-page text PDF, a 500-page scan, a mixed report larger
than 100 MB and multipage tables. Check final pages and consolidation for hidden
omissions and double counting. Exercise interruption/reopening, progress, errors and
authorized recovery, changed sources and revoked access; partial results must remain
identifiable. Record conversion, OCR and inference times, p50/p95, RAM, disk, bytes
and cost per page. Also assess whether estimates and progress adequately distinguish
preparation, processing, verification and unreadable parts.

The `qualify` command requires at least three independent successful trials for the
same combination; replaying one result does not count as another trial. Publish only
the formats, structures and conditions actually qualified, with measurements and
limitations. Synthetic 500-page tests prove preparation and recovery, rather than
comprehension. Local artifacts remain unversioned; published conclusions contain
only aggregate measurements and technical findings.

## Current scope

Chat/Tasks, Messenger/Hermes and Dream share local preparation. Inline contexts remain
bounded; notices point to `document_analyze` for large sources. Responses falls back
for inline files in messages; stateful items and provider-hosted file identifiers
retain their native transport.

`document_analyze(uri, question, model_slot="document", max_calls=256)` starts a private
analysis owned by `app.llm` and returns `analysis_id`. It does not appear in the business
process catalogue. Pass that identifier as `run_id` to `document_analysis_get` for progress, answer
and coverage after source checks. `document_analysis_cancel` requests cancellation
and waits for local inference termination. Completed batches are read again without
another billable admission, using stable inference identities. Interrupted inference
remains explicit and is not automatically billed again.

The profile's document slot is preferred, falling back to its standard text model
when absent. `model_slot="text"` selects that text model. When images are unsupported,
the same profile's configured vision model may prepare visual observations; coverage
identifies that model. Without vision, the limitation remains visible. Supplied-unit
coverage never certifies semantic accuracy (`semantic_accuracy_verified=false`).

The preparation cache uses a private process-owned temporary directory outside `/data`,
partitioned by agent, URI, checksum and reader version. Every access rechecks permissions
and source bytes. Opportunistic retention is seven days; quota is 2 GiB per agent and process.
Normal process termination cleans the cache. After a restart, sources are converted again
when needed; results and inference batches remain durable in the database without duplicate
billing. Atomic page checkpoints reuse completed conversion work while it remains available.
XLSX/ODS retain cells, formulas, caches, styles, hidden sheets, merges and comments
separately from printed pages. Formulas are not recalculated. A separate source reader
handles BIFF5/8 XLS caches, decodable formulas, original BIFF tokens, number formats,
date epoch, hidden sheets/rows/columns, merges and comments. It never recalculates caches.
Undecodable formulas retain their tokens and an explicit diagnostic. PDF rendering may
differ from source caches. Structural limits are 200,000 cells and 10 million characters;
older BIFF versions are rejected. Automated qualification covers synthetic BIFF8 and XLS
generated by the real LibreOffice, rather than every historical BIFF5 variant or formula.
Cache keys and checkpoints share the reader version so old XLS preparations without
structural evidence cannot be reused.

Tests cover a 500-page analysis with a simulated provider, recovery, access control,
changed sources, cancellation, corrupt/encrypted files and multi-frame TIFF. Real
trials and independent review remain in local artifacts. They do not qualify every
fact in arbitrary reports or every format. See the
[decision](../../../project/decisions/0151-resumable-document-analysis.md).

## Limitations and conditional extensions

| Scope | Current limitation and evidence required before extending support |
|---|---|
| Legacy XLS | BIFF5 is read, but historical variants remain to be qualified; undecodable expressions retain their tokens and a diagnostic, without recalculation or invented expressions. |
| Office, drawings and diagrams | DOC/ODG can be converted; qualify fonts, notes, objects, charts and pagination for the relevant structures before claiming fidelity. |
| PDF, scans, handwriting and images | Reproduce a loss of reading order, tables, figures, rotation or OCR before extending the reader; check against the source rendering. |
| XLSX/ODS and multi-frame TIFF | Readers and scenarios exist; support alone does not establish fidelity for complex structures. |
| EML/MIME and archives | The preparer does not inventory or recursively analyse child attachments. An extension must supply per-child locators and coverage, with bounded expansion and recursion. |
| Other formats | Qualified adapter or explicit diagnostic; no universal support claim. Audio and video use their dedicated facades. |

### Conversion isolation

A subprocess and disabled macros do not provide network isolation. The LibreOffice
conversion path does not establish explicit network confinement. Qualifying isolation
requires synthetic sources with remote references, excessive archives and hostile
files, observing that no implicit network access occurs. Retain CPU/RAM/size/time
limits and verify cleanup after interruption without invalidating completed checkpoints.

### Accuracy and transports

Existing fallback does not detect every incorrect or insufficient HTTP 200 answer.
Additional semantic checks must use independent evidence, preserve successful units
and fallback reasons, and bound alternatives. Access or authentication denials do not
trigger conversion; open streams or ambiguous effects do not permit automatic
resubmission. Stateful Responses inputs and hosted files retain their transport and
history; any preparation of these inputs requires separate qualification.

The catalogue and record maintenance belong to
[File Share indexing](../../../project/decisions/0155-durable-file-indexing.md).
Memory acquisition, provenance and extracted-text recall follow the
[Memory plan](../../../project/plans/amelioration-globale-memoire.md); mechanism
comparisons follow the [Lab](../../../project/plans/lab-evaluation-mecanismes-ia.md).
