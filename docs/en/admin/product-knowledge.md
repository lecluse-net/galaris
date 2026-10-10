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
5. Authorize `galaris-knowledge` for the agent in skill assignments. Its global default is
   disabled; skill and category overrides still apply. Its effective projection additionally
   requires `documentation_catalog` permission.

Galaris Admin remains inactive by default. Enabling a connection preserves the usual function
authorization cascade: explicitly disable inspections for agents intended only to guide users.

The skill supplies core concepts, retrieval guidance and assistance boundaries. It is available
to subsequent executions through normal skill handling in the internal harness and compatible
external harnesses. Existing conversations or executions may retain loaded instructions; every
new tool call still undergoes server-side authorization.

## The Galaris assistant supplied at installation

The Galaris assistant already receives documentation access and this skill when created.
The internal harness loads its product guide on the first model request in text conversations,
turn-based voice and Tasks: concepts, source retrieval, menu verification and the distinction
between shipped features and plans. Loading still requires effective assignments and access;
it enables no connection or function. It uses the skill configuration, independently of
the agent's name, code or installation marker.

### Skill loading policy

An optional `runtime.yaml` at a skill's root configures loading in the internal harness:
`loading: eager` loads instructions on the first request in Tasks, text conversations and
turn-based voice. Without this file, or with `loading: deferred`, skills remain available
on demand in Tasks; this mechanism does not add them to conversations. Invalid configuration
preserves this default. The `SKILL.md` frontmatter remains unchanged.

The system skill `galaris-knowledge` supplies `loading: eager`. Any agent effectively assigned
this skill with documentation access therefore receives the same loading behavior. The file
grants no rights and activates no skills; this skill's global default remains disabled.
User skills can supply the same file through their resource editor. External harnesses
retain their own loading mechanism.

Tools remain those authorized in the current context. If search is only available in Tasks,
`file_read` can still read a known source with documentation access; a Task can perform the
search. Realtime voice retains its limited inventory and Task handoff. Skills without explicit
configuration retain their usual loading policy. These instructions and retrieval do not by themselves guarantee every
answer is correct: check cited sources and tool use in the conversation activity.

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
image bundle. Generate and check maps with `make docs-prepare` in development, then commit
them with their source changes. In every environment, including `dev`, `demo` and `prod`,
`make update` packages this prepared documentation without regenerating maps or rerunning
static documentation checks. After startup, it updates
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

Under heavy load, indexing processes at most eight passages per batch and allows 60 seconds
for the provider. After a failure, this job waits 1, 2, 4, 8 and then at most 10 minutes
between attempts, per backend process. Success restores its normal 30-second schedule.
A warning reports the failure type and retry delay. Completed batches are retained;
new passages become available to lexical search before embeddings are computed.
Interactive searches keep their short timeout and can run concurrently with other LLM
calls and background indexing.

Backend images contain the source corpus, updated with Galaris. Development mounts documentation
read-only and detects edits automatically. A corpus hash identifies the exact sources even when
the build label is unknown.

Disabling the connection or `documentation_catalog` also denies known source URIs, metadata and
copies. Disabling `documentation_search` denies retrieval while retaining reading if the catalog
remains enabled.

This capability does not establish the requesting user's permissions or the actual state of
their settings and connections. Agents must verify those through authorized tools or request
the missing information. Reading documentation never authorizes changes.
