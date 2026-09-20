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
