<p align="right"><a href="../../../fr/architecture/flows/mail.md">Français</a> · <strong>English</strong></p>

# Mail IMAP/SMTP Tool Flow

The `bridge.mail` adapts an external mailbox to Galaris's Tool and Messenger contracts.
The agent invokes MCP functions scoped to its single active `mail` connection; the
canonical listener also polls the INBOX and admits each new email as a dedicated Task.

```text
Agent / Task
   → mail_* MCP functions
   → effective parameters: connection override, otherwise the Tool's global value
   → agent's active Mail connection
   ├── IMAP TLS/STARTTLS: folders, search, read, flags, move, trash
   ├── SMTP TLS/STARTTLS: send, reply, forward
   ├── mail_outbound_deliveries: MIME content + envelope + validation + durable outcome
   ├── app.messenger → Memory: one private contact per observed account
   └── app.file_share: read-only mail:// attachments

Active Mail connection
   → IMAP polling every poll_interval_s
   → durable UIDVALIDITY + UID cursor in app.messenger
   → canonical inbound journal and deduplication
   → immediate Task requesting mail_get for the opaque reference
```

## Reception and polling

`poll_interval_s` is a parameter of the Mail Tool, configurable globally and overridable per
connection unless a global value is imposed. It defaults to 60 seconds and is bounded between
5 seconds and 24 hours. The first activation establishes a baseline on `UIDNEXT` without turning
the history already present into Tasks. Subsequent UIDs are processed in ascending order, in
batches capped at 50.

The cursor persists `UIDVALIDITY + UID` in `messenger_listener_state`. A change in
`UIDVALIDITY` establishes a new baseline instead of replaying a reconstructed mailbox. Each email
is first journaled by `app.messenger`, then directly admitted as a Task; it does not pass through
the short conversational controller. The Task does not automatically deliver its terminal text
to the sender: any reply or mutation requires an explicit call to `mail_reply`,
`mail_send`, `mail_move`, `mail_set_flags`, or `mail_trash`.

## Identity and inbound content

A message reference opaquely encodes the `mailbox + UIDVALIDITY + UID` tuple. The
bridge rejects the reference when `UIDVALIDITY` has changed, so it can never act on another
message after a mailbox reconstruction. Bodies are paginated in the MCP response, the RFC822
size is checked before the complete download, and the number of MIME parts is capped.
The content of an email remains marked as external and untrusted; it never constitutes a
system instruction for the agent.

After journaling, the human sender is projected into Memory with the canonical identity
`(mail, normalized address)`. The MIME display name is preserved when present. The projection's
unique constraint makes observation idempotent, including when two messages from the same
account arrive concurrently.

An attachment receives a URI
`mail://attachment/<message-ref>/<part-id>/<filename>`. The two opaque identifiers are
authoritative; the name is descriptive only. The `file_*` facade allows `info`, `list`, `read`,
and `copy`, but rejects create, write, move, and delete.

## Sending and AI transparency

`mail_send`, `mail_reply`, and `mail_forward` require an idempotency key. The corresponding
row is created before any submission with the agent, sender, recipients, subject, bodies,
attachment metadata, and final MIME message. It therefore remains accessible after a
connection is deleted; the raw MIME required for deferred validation is never exposed
through the administration API. The row is locked before submission: a concurrent call sees
the `submitting` state instead of launching a second SMTP submission. A disconnection with an
unknown outcome produces `uncertain` and is not blindly replayed; the bridge only attempts
reconciliation by `Message-ID` in Sent.

When the effective `approval_required` parameter is active, the first claim transitions to
`pending_approval` and immediately returns this receipt to the agent without contacting SMTP.
The effective `approver_user_id` is fixed on the row: only that authenticated USER, with access
to the connections, can approve or reject the message. An approval locks the row and then sends
exactly the persisted MIME; a rejection is terminal and preserves the optional reason. A later
change to the connection policy does not affect an email already awaiting approval.

The server always appends, after the content provided by the model, the following signature in the
text part and its HTML equivalent:

```text
---
Ce message a été envoyé par un agent d'intelligence artificielle via Galaris.
```

This signature is neither a connection parameter nor an MCP argument, so an agent cannot disable
it. `Bcc` is passed to the SMTP envelope without being written to the MIME headers.

A durably `sent` submission also projects each distinct recipient from `To`, `Cc`, and
`Bcc` as a private contact. An idempotent replay refreshes this projection without creating a
duplicate; an `error` or `uncertain` send creates no contact. Two different addresses remain two
items, even if their display name is identical. Dream may later link them to the same individual
through non-destructive links, without merging or rewriting the source identities.

When `mail_send`, `file_search`, and `file_read` are all authorized, the Tool registry
automatically asks the agent to search `memory://` if the recipient is provided only by name.
An address explicitly provided in the request is used as provided after validation. The agent
never guesses an address: zero or multiple matches trigger a request for clarification. The two
read functions remain within the scope of a scheduled Task that exposes `mail_send`.

## Configuration and security

The connection accepts only the mailbox address and a password shared by IMAP and SMTP.
The address also serves as the identifier with both servers. Hosts, ports, security, timeouts,
and the polling interval are configurable globally on the Tool; attachment limits are expressed
there in MB and then converted to bytes at the bridge boundary. A connection can customize them
unless a value is imposed. All `password` parameters, global or local, remain encrypted
at rest. Only implicit TLS and STARTTLS with certificate validation are accepted. The form
allows IMAP and SMTP to be tested after registration. `approval_required` and `approver_user_id`
follow the same global/local override cascade: the policy can therefore be shared by the Tool or
customized for an agent's Mail connection. An active policy without an active USER is rejected
before the mail is created. The Tool is not auto-connected and remains absent from an agent's
catalog until an administrator has created and activated its connection.

The `/connection/mail` page, protected by `CONNECTION_ACCESS`, displays `pending_approval`
emails first, followed by the complete history. Both lists use server-side pagination capped
at 500, an agent filter, and a search across the agent, sender, recipients, subject, and
body. The details expose the relevant content, reviewer, and SMTP outcome, but never the raw
MIME payload. Its navigation entry is visible only if at least one active Mail connection
exists; the page privilege continues to be checked independently. Approval and rejection
routes add a contextual assertion: the current USER must be the official approver fixed on the
mail, in addition to possessing `CONNECTION_ACCESS`.
