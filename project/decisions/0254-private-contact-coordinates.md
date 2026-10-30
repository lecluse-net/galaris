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

Persistence and API guarantees are exercised by `app/contact/tests/test_coordinates.py`
and `test_router.py`; `front/browser-tests/contacts.spec.mjs` covers editing, creation
without email, retry, reopening, defaults and mobile interaction.
