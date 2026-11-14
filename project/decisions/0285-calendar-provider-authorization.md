# 0285 — Calendar providers and account authorization

Status: accepted, implemented with the explicit limits below.

## Decision

Keep `caldav.calendar` as the existing capability and select the provider in standard
Tool settings. `app.calendar` owns persistence, permissions, outbox, leases and schedules;
`bridge.calendar` adapts external protocols. No separate parameter editor is introduced.

| Provider | Authorization | Transport |
| --- | --- | --- |
| Nextcloud and generic CalDAV | Account/application password or configured OAuth | CalDAV discovery, sync tokens, conditional writes |
| Google Calendar | Delegated OAuth, offline refresh | Calendar API v3 |
| Microsoft personal/work accounts | Delegated OAuth, offline refresh, configurable directory tenant | Graph v1.0 |
| Apple iCloud | Apple account and app-specific password | CalDAV, validated Apple shard discovery |
| Private/public ICS subscription | Private URL, optional HTTP credentials | HTTPS, read only |

Shared CalDAV roots and OAuth application registrations use existing global Tool parameters
with forced inheritance where appropriate. Account credentials and private ICS URLs belong
to connections. Native providers use fixed API endpoints. Generic CalDAV OAuth endpoints
and scopes are explicit Tool settings and may use private enterprise HTTPS origins.

Reuse connection OAuth PKCE S256, user-bound single-use callbacks, encrypted grants,
serialized refresh and refresh-token rotation. Store calendar grants separately from MCP
grants on the same connection. Callback purpose comes from the encrypted pending grant.
Changed registration/resource bindings invalidate authorization. Removing calendar consent
preserves MCP grants and fences calendar leases; authorization requests a new read.

Discover each provider calendar and preserve its current write permissions. Default to
two-hour synchronization, individual integer-hour settings and sequential processing.
Google/Microsoft currently read complete paginated snapshots without date windows: a
Graph calendarView window must never be interpreted as the whole historical calendar.
Incomplete responses abort before local deletions; page/event limits bound each snapshot.

Native writes use ETags, stable creation identities and reconciliation after lost replies.
A private provider extension retains the original ICS resource and UID; patches preserve
provider-owned fields outside the adapter. Never send credentials to an untrusted API
continuation or redirect. Only the iCloud profile permits CalDAV navigation between
`caldav.icloud.com` and `p<digits>-caldav.icloud.com` HTTPS origins.

## Explicit limits and qualification

Native Google/Microsoft adapters create, update and delete single events, including
all-day dates and explicit reminders. Recurring masters, moved exceptions, cancellations
and timezone changes are imported. Creating/editing series or individual occurrences is
rejected before local mutation; users make these changes in Google Calendar/Outlook.
Entire-series deletion remains available. CalDAV keeps recurrence mutation support.

Provider application registration, allowed callback URLs, account consent and enterprise
administrator policies remain prerequisites. Synthetic HTTP/DB and real component tests
qualify isolation, refresh, safe retries and codecs. They do not replace live qualification
with configured provider accounts; no account consent is inferred.

Primary contracts: [Google events](https://developers.google.com/workspace/calendar/api/v3/reference/events),
[Microsoft events](https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0),
[Graph series exceptions](https://learn.microsoft.com/en-us/graph/api/event-get?view=graph-rest-1.0),
[Apple app passwords](https://support.apple.com/en-us/102654).
