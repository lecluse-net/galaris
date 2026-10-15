# ADR 0185 — Internal colleague messages use delegated Tasks

- Status: Accepted
- Date: 2026-10-15

## Problem

The native Chat provider resolves private rooms for human contacts only. A Task sending
`messenger_send_message_to_user` to an internal colleague therefore failed while looking
for a human room. Agent identity lookup based on external connection parameters also missed
native `agent:<ID>` addresses.

## Decision

Resolve native colleague addresses exactly, including canonical Messenger identity UUIDs.
For a current Task, admit the message through the existing delegated Task lifecycle via
`app.task.facade`. Convert its Markdown transport content into the Task's editorial HTML.
Return the child's canonical URI as an admission receipt. The parent waits and resumes
with the child's terminal result through the ordinary fan-in mechanism.

Do not create a human Chat room or an external delivery receipt for this operation. Contact,
document access, action authorization, source ownership, terminal-state protection, human
pauses and collaboration limits remain mandatory. This path requires a current Task and
does not add Task creation to short conversations. External messaging retains its existing
transport and awaited-reply lifecycle.

## Verification

A synthetic PostgreSQL regression reproduces the missing-human-room exception before the
fix. It exercises native addresses and canonical identities, durable child lineage, Markdown
conversion and refusal without a created child. Existing collaboration and journal tests
cover result fan-in and ordinary deliveries. No production conversation is copied into fixtures.
