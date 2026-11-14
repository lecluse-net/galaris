# 0287 — Optional local contact references on calendar events

Date: 2026-11-14
Status: Accepted

## Decision

A Calendar event may reference one canonical Contact from its owning agent's private
directory. `contact_id` is a nullable foreign key to the backing Memory item, validated
through `app.contact.facade`; Calendar never reads Contact or Memory ORM models.
The association belongs to the whole event/series. A split series inherits the reference.
Ordinary edits and provider refreshes preserve it; explicit removal clears it.

The reference is local metadata, retained in event revisions and exposed in event reads,
agent context and scheduled Task data. It is absent from exported iCalendar and provider
payloads. A link grants no access, sends no invitation and does not become the Task's
requester/contact scope. Agents resolve canonical IDs through their Contact tools.

Contact lifecycle callbacks registered by Calendar rewrite references during a merge and
clear current and historical references when a Contact is forgotten, in the same transaction.
Reference admission acquires the contact-directory lock used by those operations before the
event lock. This avoids a Contact-to-Calendar domain dependency and keeps ownership checks
and deletion consistent under concurrency. No architecture debt baseline is increased.

## Dependency review

Calendar gains one declared dependency on `app.contact.facade`, raising its intentional
domain fan-out from four to five. Contact owns canonical identity validation and its
lifecycle; using Memory storage directly would bypass that contract. The new edge uses
only the public facade, and the callback inversion introduces no reverse import or cycle.
Tests verify private ownership, atomic merge/forget effects and unchanged Task requester
scope. Private-import and cycle debt baselines remain unchanged.
