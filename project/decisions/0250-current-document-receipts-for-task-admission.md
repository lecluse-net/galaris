# 0250 — Current document receipts in Task admission

Status: accepted. Date: 2026-10-29.

A conversation can create a Document after human approval and then delegate its continuation
to a background Task in the same turn. Task preparation must identify that Document from a
successful tool receipt, even before the conversation has a final response or historical trace.

The internal harness projects at most 50 distinct canonical Document URIs from successful
`file_create` and `file_copy` receipts in its existing checkpoint journal. The runtime-neutral
Conversation contract provides a callback so Task preparation reads the current receipts,
including effects restored after approval. Text and turn-based voice use the same projection.
No extra persistence or content copy is introduced.

The projection supplies context, not authority. Task preparation still requires an exact quote
from the current human request, a contextual URI quote and the selected URI in its objective.
Submission hints alone remain insufficient. Pending, denied, failed and uncertain effects,
ordinary reads and model prose cannot supply creation provenance. Resource ACLs, execution
scope and per-function human approvals remain independent and are rechecked at execution.

Previously, preparation only consulted conversation history, memory and linked work. A document
created in the active turn existed in its checkpoint but was missing from that context. Its
write-target binding failed validation, preventing admission of the continuation Task.
The earlier assembled fixtures replaced Task preparation and could not expose this failure.

The document authorization journey now keeps the real Chat controller, internal harness,
Task preparation and scope validation, MCP, approval journal, scheduler and Document storage.
Only model answers are scripted. It checks creation approval or denial, background continuation,
another approval or denial for the update, reopening, lease release, preserved content and
absence of duplicate Documents or revisions. Unit coverage also rejects unsupported provenance
and checks that checkpoint restoration preserves only successful creation references.
