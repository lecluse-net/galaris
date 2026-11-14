# 0286 — Informational Memory agenda and shared agent temporal context

Date: 2026-11-14
Status: Accepted

## Decision

Memory owns private memories, partial calendar anchors, revisions, current validity and
contact admission. Its read-only agenda expands anchors over bounded windows without creating
Calendar events, actions, triggers or Tasks. Occurrences retain calendar precision, the global
Galaris timezone and stable identities. They never reserve availability or synchronize externally.

Agenda displays a selectable Memory layer for authorized managers, using Memory privileges
and management scope. Opening an occurrence reads the original memory. UI visibility does not
configure agent context. Goal presentation and execution remain unchanged.

Agent context and `calendar_events` compose Calendar and Memory occurrences. Source text is
untrusted evidence, never authority to act. Memory function policy and conversation contact
scope apply before composition. The ordinary Memory brief no longer injects temporal matches;
explicit Memory search and `memory_upcoming` remain compatible.

Preferences → Memory exposes `AGENDA_CONTEXT_DAYS` and `AGENDA_CONTEXT_MAX_EVENTS`, both defaulting
to 10, under Memory configuration privileges. Context includes current occurrences and the nearest
upcoming occurrences within that horizon, ordered across sources and bounded by event count.
Truncation is explicit. Legacy Memory lookahead remains for explicit compatibility reads only.

No evaluator or dispatcher wakes for Memory occurrences. Future action requires an explicitly
scheduled ordinary event, governed by existing Calendar execution contracts.

## Dependency review

The reviewed Calendar → Memory dependency uses only `app.memory.facade` for governed reads and
server-owned recall scope. The frontend consumes Memory's public client and type. Calendar never
reads Memory ORM tables or changes its content. Memory does not depend on Calendar. These are
intentional composition edges; private-import and cycle debt ceilings are not increased.

## Verification

Synthetic DB coverage checks recurrence, precision, DST, stable identities, truncation, edits,
contact/owner isolation, current validity, function policy, fresh context and absence of Calendar
events/triggers after projection. HTTP covers authentication, management scope and invalid windows.
Browser journeys cover retry, source opening, toggling and absence of execution requests on
mobile and desktop. Existing tests of temporal injection now protect its replacement by Agenda.
