# 0270 — Collect complete Process inputs before conversation launch

- Date: 2026-11-08
- Status: accepted and implemented
- Complements decisions 0195 and 0267.

## Decision

Every variable selected by a native v2 root Start is an input that must be supplied or
have a declared default before admission. Nullability permits an explicit null value;
it does not make an input omittable. Other registry variables may remain uninitialized.
This rule applies at the Process boundary, including direct calls and child launches.
Historical v1 and external workflow input contracts remain unchanged.

Conversation owns input collection. Its origin round stores bounded JSONB
`process_preparations`, keyed by workflow and scoped to room, agent and human participant.
Once human launch intent is established, Process reserves one real business ProcessRun
in `waiting`, with a frozen definition and partial typed data. It has no start job or
business activity. The conversation dossier and canonical run link commit atomically.
No auxiliary Task or technical workflow is created. A structured
`conversation.process_inputs` inference reads canonical human messages, attachments,
previous values, retrieved proposals and recent actual runs. It extracts supported values,
recognizes cancellation or unrelated messages, and suggests searches and missing questions.
The conversation controller searches authorized Memory/files, converts document formats
using existing resource tools and asks the human only for unresolved inputs.

The server validates partial updates against the reserved run's frozen definition and live resource
permissions and MIME constraints. Missing values are never replaced with invented nulls.
Except for an existing null or declared default, a nullable absence requires an exact quote
from the current human answer. Inferred file URIs must occur in supplied evidence.
False and zero remain values. The dossier survives later messages and controller retries.
Optimistic revisions and final freshness guards reject stale assessments; model calls hold
no dossier row lock. Provider failure or timeout cannot authorize a launch.

Assessment reuse is bound to the canonical admitted request, messages, participant and frozen
contract. Within that binding, repeated reads and verified field patches use deterministic
normalization and fresh resource metadata. Invalid fields remain unresolved until corrected.
Field normalization parses the declarations once; each URI is inspected once per batch and
never cached across requests. Questions about remaining fields are generated from the actual
missing/invalid names. Only a new semantic contribution requires another input assessment.
Prior attachments retain bounded exact-URI evidence; assistant questions and URI prefixes
cannot introduce a resource reference.

A complete, requested dossier goes through the existing frozen launch permission. The
permission receives the original request and recent actual runs for pronoun resolution.
When the input assessment explicitly establishes one unambiguous launch and all final values
were evaluated by that assessment, the server freezes the same launch plan without a second
model call. A digest binds the proof to those exact typed values. Later value changes,
uncertain intent, multiple launches, missing legacy proof or an existing frozen refusal
retain the ordinary admission checks. Earlier consent may be withdrawn without deleting
already collected data. A refusal cannot be expanded by a later prepared proof.
The same run moves from `waiting` to `queued` and gets one start job. Only an input wait
permits this transition. Refresh, debugger resume/step and missing values cannot start it.
Operational inspection, Process lists, conversation pending context and agent active work
expose the run and its missing inputs. Cancelling input collection terminates this waiting
run locally; external cancellation cannot be reversed by a late answer.
Invocation idempotency is tied to the origin dossier and requested occurrence; duplicate
recovery cannot create another run. Occurrences count identical executions requested in
the current message, not past runs. Once released, run cancellation uses the Process control API.
Completed dossier values are immutable; a new human launch request creates a new preparation.
Receipt replay checks parent access and input identity without re-opening original files that
may since have been removed. Partial preparation cannot initialize unselected runtime variables,
and the Process service derives completeness itself. Ordinary rereads with unchanged data
do not increment its revision. A human confirmation resolving an existing validation issue
advances the accepted-input revision even when its value equals a previously valid fallback.
Identical concurrent collections return the winner's receipt; different concurrent
patches report a conflict and can be retried without losing committed fields. Lock acquisition
is interruptible and cancellation restores the transaction before recovery.

Run modals render variables as resource cards with names and localized types, including
scalar, missing and null values. File/Document variables reuse attachment preview/download
components. The server resolves a variable name from the authorized run; clients cannot
substitute an arbitrary URI. Source access is rechecked under the run's launcher identity.
Standalone attachment sections and raw input/output JSON blocks are removed from run modals.

Variable declarations additionally carry optional bounded plain-text labels and descriptions.
Their business meaning accompanies the frozen contract; neither alters value transport or
grants authority to instructions embedded in metadata.

Authenticated human contributors with Process launch/control rights and management of the
launcher may edit selected initial inputs directly, or upload a run-owned File. This is an
initial input wait, not a reply form for an executing human activity (decision 0192 remains
unchanged). The dedicated port validates types, live resource access and MIME without AI,
checks the read revision and reserves explicit null for intentional human entry. Saving does
not execute. An explicit Start action may release the same complete run without an AI intent
check; identical release retries reuse the receipt. Later ordinary agent launches retain their
normal scope checks. The run is authoritative for human contributions; conversation overlays
them without losing other fields, invalidates older value proofs and checks the run revision
again after acquiring its origin lock. Reopening an editor must not silently advance the
revision attached to its existing draft.

File Sharing owns disposable operation memos, not Process. Conversion keys bind actual source
bytes, source URI/name/MIME, parameters and destination to one agent/runtime/task. Source
materialization and destination metadata remain live; only an unchanged checksummed output is
reusable. Conversion memos expire after 30 days. Identical searches during a pending input
collection may replay for 30 seconds within the same canonical human message; root/result
rights and result versions are rechecked. Unversioned hits and degraded responses are not
reused. A refresh flag handles known source changes; new input changes the scope. At most 200
memos remain per agent. Concurrent conversion cache misses may still render twice; these
receipts are neither exactly-once transport nor launch authorization.

Input origin audit belongs to `ProcessRun.input_provenance`, a dedicated JSONB column with
deferred loading and implicit-load rejection. Each accepted input stores only its origin
kind, bounded references/version stamps and a digest of the typed value, without copying
source content or the value. Changes append one batched `run.inputs.provenance` event in the
same transaction. Repeating the same origin/value does not add history. Ordinary run reads,
event lists and operational summaries exclude these audit details; conversation dossiers,
model output schemas and assessment prompts do not carry them.

Sources distinguish declared defaults, direct human input, agent proposals and the canonical
conversation context used for extraction. Precise Memory/document evidence is never invented
for a scalar proposal whose underlying source was not established. File/Document stamps reuse
metadata already fetched by validation. Verified conversion receipts add the source reference,
operation key and physical PDF page. No model call or source download is added for recording.
Historical runs have no retrospective fabricated origin.

Explicit readers request one variable through the Process API or the existing `file_read`
surface at `galaris://processes/runs/<uuid>/input-provenance/<encoded-name>`. They require parent
read access and the launcher's own agent/management scope. Current sources are checked live;
revoked/unavailable references are hidden. History uses a bounded cursor page, with at most
16 distinct source checks per response and a two-second deadline per check. Reference metadata
inspection does not recurse into provenance content. Source reads never grant source access.

## Verification

Synthetic DB integration scenarios exercise direct incomplete admission, multi-turn input
collection with one waiting run and one eventual start job, genuine false/zero/defaults,
date and MIME rejection, explicit nullable absence,
participant isolation, cancellation, unrelated messages, provider failure, superseded
assessments and relaunch context. Real Process admission and execution are used; only the
external model provider is replaced. These tests establish orchestration guarantees, not
perfect natural-language intent classification by every configured model.
