<p align="right"><a href="../../fr/admin/product-knowledge.md">Français</a> · <strong>English</strong></p>

# Give an agent knowledge of Galaris

Any agent can explain Galaris and guide users while keeping its existing role and personality.
The capability combines the official documentation shipped with the installed version, hybrid
retrieval and the **Galaris knowledge** system skill (`galaris-knowledge`).

## Enable access

1. In **Configure → Tools & connections → Connections** (`/tools?tab=connections`),
   enable the agent's **Galaris Admin** connection.
2. Keep `documentation_catalog` and `documentation_search` enabled in its function permissions.
3. For documentation-only access, disable `conversation_round_get`, `voice_turn_get`, `llm_call`
   and `llm_calls`. These inspection functions expose sensitive execution data and are not
   required to understand the product.
4. Enable the Tool's **conversation mode** to expose these functions in Chat.
5. Check skill assignments: `galaris-knowledge` is globally enabled by default, while skill and
   category overrides can disable it for an agent. Its effective projection additionally
   requires `documentation_catalog` permission.

Galaris Admin remains inactive by default. Enabling a connection preserves the usual function
authorization cascade: explicitly disable inspections for agents intended only to guide users.

The skill supplies core concepts, retrieval guidance and assistance boundaries. It is available
to subsequent executions through normal skill handling in the internal harness and compatible
external harnesses. Existing conversations or executions may retain loaded instructions; every
new tool call still undergoes server-side authorization.

## Search and read

The [navigation guide](../user/navigation.md) describes workflows and tabs; the
[menu map](../architecture/generated/navigation.md), generated from the frontend,
provides routes, translated labels and visibility conditions. Both belong to the searchable
corpus and catalogue entrypoints. The skill uses them to give
**section → screen → tab → action** instructions without assuming the human account's permissions.

`documentation_catalog` reports version, languages, domains and entrypoints. It also controls
read access below `galaris://documentation/`. `documentation_search` accepts a question and
optional `language`, `domain`, `kind` and `path_prefix` filters. Results contain source titles,
sections, excerpts, status, checksums and read positions.

```text
documentation_search(query="How do I share a document?", language="en", domain="user")
file_read(uri=<result URI>, offset=<offset>, max_chars=<max_chars>)
```

Offsets count Unicode characters starting at zero. Long reads return `next_offset`. `file_list`
paginates sources with a cursor; a corpus change invalidates that cursor and requires restarting
the listing. Sources retain their native Markdown, JSON or HTML format and are read-only. Use
`documentation_search` for retrieval rather than `file_search` on this collection.

Sources include `docs/`, project decisions and plans. Plans are explicitly prospective and retain
their status; approval does not establish implementation. Decisions explain historical rationale,
while current guides take precedence.

## Updating documentation and retrieval

After editing documentation or navigation, in the development checkout:

```bash
make docs-update
```

This command regenerates project and menu maps, checks their freshness, FR/EN guides and
documentation links, then compares prepared sources with those actually visible in the running
backend. It synchronizes the shared lexical index and verifies retrieval and reading of both
navigation guides. Updates reach all already-authorized agents without changing permissions
or skill assignments. Editing documentation does not require a restart.

If the backend image or mounts are outdated, the command fails explicitly: use `make update`
in development. Do not hide a corpus mismatch by copying files into an individual container.

Use `make docs-prepare` to prepare sources without a running backend. `make docs-check`
checks sources without regenerating them. These checks detect missing translations, but do
not write translations or verify their semantic accuracy: update affected guides and workflows
in both French and English.

Before publication, run `make validate` on prepared sources. In production, use the normal
update of the validated version: `make update`, or `make update RELEASE_DIR=…` for a qualified
image bundle. From sources, `make update` automatically runs `docs-prepare` before building:
project and menu maps are regenerated, then packaged in the images. After startup, it updates
the shared lexical index and verifies the result. No prior `docs-update` is needed.
With `RELEASE_DIR`, it updates that index from the documentation already generated and packaged
in the qualified images, without modifying those images. A failed refresh or verification
prevents reporting deployment success. This check does not automatically restore a version
that has already been replaced. Distributed bundles are checked during build and E2E tests too.

The check reports the content fingerprint, corpus fingerprint, version and indexed passage
count. Embeddings continue updating in the background when a vector model is configured;
their completion and provider availability do not block lexical search or the update.
Existing conversations retain previous answers; a new documentation read uses current sources.

## Search availability

Text retrieval and exact matches work without an embedding model. With a configured vector
model, a background job progressively builds a semantic index and retrieval combines both
rankings. Results report missing models, provider failures and incomplete coverage. Unchanged
passages are not embedded again.

Backend images contain the source corpus, updated with Galaris. Development mounts documentation
read-only and detects edits automatically. A corpus hash identifies the exact sources even when
the build label is unknown.

Disabling the connection or `documentation_catalog` also denies known source URIs, metadata and
copies. Disabling `documentation_search` denies retrieval while retaining reading if the catalog
remains enabled.

This capability does not establish the requesting user's permissions or the actual state of
their settings and connections. Agents must verify those through authorized tools or request
the missing information. Reading documentation never authorizes changes.
