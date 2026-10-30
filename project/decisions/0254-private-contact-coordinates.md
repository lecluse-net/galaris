# 0254 — Private contact phone numbers and postal addresses

Status: accepted. Date: 2026-10-30.

Canonical contacts remain private Memory projections administered by `app.contact`.
Their typed phone numbers and postal addresses live in `MemoryItem.metadata.coordinates`,
alongside the existing human-maintained contact metadata. There is no second address
book and no new SQL table. Both collections are limited to 50 entries per contact.

The Contacts API exposes these coordinates and permits explicit replacement; omission
preserves them. Contact creation requires a name and at least one email, phone number
or postal address. A contact without email has no invented Messenger identity.
Coordinates are rendered in the Memory projection and included in contact search.
Stored phone numbers retain the supplied notation; this change does not implement
international number normalization or extraction from conversation messages.

Incoming observations preserve coordinates. Merging combines distinct complete entries,
including their labels, in the existing transaction. Exceeding the collection limit
rejects the merge before rewiring references. Splitting an identity leaves coordinates
with the original contact and history, without claiming that they belong to the
separated identity.

The default country is an explicit country name or code in the free-form `LOCALIZATION`
setting, resolved offline using Babel territory names for the application's English,
French and Chinese languages. A city alone, timezone or language does not imply a
country. Each entry can override or clear its country. Saved entries remain unchanged
when the global location changes. Contact coordinates grant no additional access.

Self-service MCP functions `contact_list`, `contact_get`, `contact_create` and
`contact_update` belong to the existing `galaris` Tool and run in Tasks and conversations.
Ownership always comes from the injected caller context; no target-agent argument or
administrative scope can widen it. Updates reuse Contacts validation, preserve identities
and omitted coordinates, and replace only explicitly supplied coordinate collections.
Creation and updates use the shared approval mechanism with Ask defaults. Email creation
also changes whether that sender is known to the default inbound Mail admission policy;
this effect is described in the tool and runtime instructions. Merge, split, forgetting
and editing existing email or Messenger identities remain outside this MCP surface.

The adapter adds a reviewed `app.contact → app.tools` dependency through the public
decorator and injected context only. This follows other domain-owned native MCP adapters,
adds no reverse dependency from Tools to Contacts and introduces no new storage or port.
`app/contact/tests/test_mcp.py` verifies discovery, schemas, private ownership and persistence.

The File Sharing port also exposes conditional writes to `galaris://contact/<uuid>`.
`file_write` accepts partial editable JSON or a complete snapshot whose identity and metadata
fields are unchanged; `file_edit` validates the resulting complete JSON through the same writer.
The mandatory `expected_etag` comes from `file_info`/`file_read`. Contact compares the snapshot
under its row lock, serialized with directory reconciliation, before changing its name or
coordinates. Invalid JSON, stale reads, foreign ownership and identity changes cause no writes.
No SQL schema change or new reverse module dependency is required. The file-resource tests
cover persistence and errors; an independent-transaction test proves that only one of two
writers using the same snapshot succeeds.

Persistence and API guarantees are exercised by `app/contact/tests/test_coordinates.py`
and `test_router.py`; `front/browser-tests/contacts.spec.mjs` covers editing, creation
without email, retry, reopening, defaults and mobile interaction.
