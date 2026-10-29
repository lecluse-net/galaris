# 0206 — Resolve contextual write targets at Task admission

Date: 2026-10-19
Status: accepted

## Context

A continuation can refer to an existing tracking document without repeating its URI.
Conversation preparation resolved that document in the standalone objective, while
execution scope retained only literal URIs from the latest source request. A child
therefore refused an update required by the prepared work. Existing scope tests covered
unsourced target rejection and explicit amendments, but not this admission boundary.

## Decision

The existing objective preparation inference explicitly selects existing resources to
update for the current request. Each selection carries a verbatim current-request quote
and a context quote identifying its exact URI. The server checks both quotes, the URI's
presence in context independently of submission hints, and its presence in the objective.
The complete source request remains the `demand` requirement. Evidence is persisted with
the Task; grants reference the canonical conversation round.

Only `file.write` is granted by this resolution. Context does not independently authorize
work, and mentioning a resource in the objective does not select it. No grants are derived
automatically from all history, memory or objective references. Native resource permissions,
scope revision checks and refusal before effects remain mandatory. Children inherit the
root scope and cannot expand it through their own bindings or objectives.

This refines decision 0170: context may identify an implicit target of current work, while
the current request remains the authority. Semantic relevance is selected by the existing
preparation inference; deterministic checks prove reference and quote provenance, not intent.
Deletion and transport still require their existing authorization paths. This change does
not rewrite or restart terminal Tasks created with an earlier scope.

An admitted Document folder also bounds updates to its current readable descendants.
Before dispatch, the Task adapter asks a domain resolver registered by Document at
bootstrap to verify membership in the live folder branch, including nested documents.
Agent owns the resolver contract and never imports Document internals. Resolution adds
no durable grant and is repeated at each preflight: removal from the branch or loss of
folder access withdraws this admission. Exact folder URIs are required; URI prefixes,
discovery results and attachment collections do not imply membership. Only `file.write`
mutations qualify; deletion and transport retain their exact-target requirements.
Native write permissions and revision checks remain mandatory.

## Verification

Synthetic conversation tests cover continuation, unselected context resources, fabricated
quotes and targets, submission-hint-only references, durable admission, idempotent submission,
child inheritance, and rejection of deletion and transport. Existing scope tests continue
to cover unknown versions, stale revisions and persistence before an effect.
Folder coverage exercises a native title rename with preserved content, nested membership,
removal and access revocation, unrelated targets, attachments, deletion and transport.
