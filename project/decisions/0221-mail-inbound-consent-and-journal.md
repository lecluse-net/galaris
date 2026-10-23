# 0221 — Mail reception consent and journal

Status: accepted, 2026-10-23.

## Context

IMAP polling previously dispatched every new message to Messenger. The outbound journal
already used common action authorizations, but reception had neither a visible durable
journal nor a contact/consent gate. Canonical admission also required an internal team
identity, silently preventing Tasks for ordinary external email senders.

## Decision

Mail owns a durable header-only receipt, unique by connection and opaque IMAP reference,
persisted before cursor advancement. Message bodies and attachments remain on IMAP until
processing is authorized. The agent's canonical Contacts, reached through `app.contact`,
provide exact email identity matching; display names and other agents' contacts do not grant trust.

`mail_process` is a native prepared capability governed by existing Tool/connection function
policies. Its software default asks for unknown senders and accepts existing contacts.
Explicit Ask applies to every sender; Enabled accepts all and Disabled blocks processing.
Common authorizations provide the responsible human, private Chat notification, expiration,
first-answer-wins decisions and optional permanent consent on this agent's connection.
Sending permissions remain independent. Denial never adds a contact or reads content.
Messenger retains its normal contact projection after an authorized admission.

A lifecycle guard and durable waker bind consent to the receipt and resume reception. The
bridge proves that exact receipt's authorization to Messenger through an inbound-contact
port; no payload flag bypasses admission. Other bridges retain their team identity rules.
Canonical Messenger still owns deduplication and Task creation. Mail never implements a
second task workflow. Reading, replies, forwarding and attachment downloads check the same
receipt, live connection and processing policy. Changes to connection configuration invalidate
reuse of a previous grant. Context waiters and recovery batches are bounded.

Reception and Sending are separate tabs on the existing Mail page. Reception displays all
observed receipts and their decisions, read/admission timestamps and failures, scoped to
managed agents. Content snapshots contain a bounded initial page, with truncation explicit;
attachment bytes remain at their canonical Mail source. Polling preserves its initial
baseline and existing cursor, without automatically replaying historical mailbox contents.

## Verification

Synthetic PostgreSQL integration scenarios exercise unknown and known senders, explicit
policies, common consent, permanent grants, denials, cross-agent isolation, all content
access paths, duplicate delivery, revocation and recovery after a claimed consent. Browser
journeys exercise approval and retry on mobile and desktop, with inert content and read-only
viewers. Assembled application scenarios cover reception and existing outbound approval.
