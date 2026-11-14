# 0284 — Server-owned document batch moves

Status: accepted. Date: 2026-11-13.

Document selection moves submit one bounded command containing the complete selection
(up to 5,000 distinct documents), rather than a component-owned loop of HTTP writes.
Folders/sub-documents, Topic classification and Agent ownership retain their existing
individual commands and authorization policies. Ownership changes from bulk dialogs use
the same batch command.

The server owns the transaction after receiving the command. Leaving the Documents view
does not cancel accepted work. Validate personal placement, destination ownership scope,
per-document access, optimistic versions and cycles; roll back the entire selection on
failure. Preserve content and unrelated tags, personal placements and sharing grants.
Reconcile inherited ACLs once and publish notifications after commit. An unanchored move
appends a block using aggregate positions; an anchored move reads sibling positions once
and preserves the selection's order.

This is an immediate domain operation, not a Process or a durable background job. A server
restart can roll back an uncommitted transaction. A lost response is an unknown outcome:
refresh before retrying, and never automatically repeat ownership/Topic mutations using
stale versions. Notifications report completion after navigation without publishing old
account results into a new session.

Verification covers 210-document selections, navigation during a pending request,
authorization denials, optimistic conflicts, cycles, anchored order, and preservation of
existing sharing/classification journeys. Compare SQL query counts and elapsed time for
equivalent sequential and batch moves in the same isolated database.

An editor opening acknowledgement must preserve Ctrl/Shift selection changes made while
that document was loading. Component coverage reproduces the delayed acknowledgement;
the assembled journey verifies the selected batch before it is submitted.
