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

The preparation cache is private per agent, URI, checksum and reader version. Every
access rechecks permissions and source bytes. Opportunistic retention is seven days;
quota is 2 GiB per agent. Atomic page checkpoints preserve completed conversion work.
XLSX/ODS retain cells, formulas, caches, styles, hidden sheets, merges and comments
separately from printed pages. Formulas are not recalculated. Legacy XLS retains an
explicit limitation on structural extraction.

Tests cover a 500-page analysis with a simulated provider, recovery, access control,
changed sources, cancellation, corrupt/encrypted files and multi-frame TIFF. Real
trials and independent review remain in local artifacts. They do not qualify every
fact in arbitrary reports or every format. See the
[plan](../../../project/plans/analyse-documentaire-unifiee.md) and
[decision](../../../project/decisions/0151-resumable-document-analysis.md).
