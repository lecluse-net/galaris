# 0255 — Deterministic contact coordinate detection in the Dispatcher

Status: accepted. Date: 2026-10-30.

The downstream acquisition and reconciliation stages are implemented by
[0256](0256-contact-acquisition-and-dream-reconciliation.md).

Every completed Dispatcher result adds `contact_infos`, defaulting to an empty list
when reading historical results. Detection is local and independent from routing:
human bypasses, forced Task choices, inferred choices and AI `END` guards all return
the same coordinate contract. Existing LLM prompts, frozen inference schemas,
permissions and routing policies retain their semantics.

The scanned source is the complete current message (`data.text`), otherwise the
Task objective, otherwise the last message. Routing-history truncation and sender
metadata do not supply coordinates. Editorial HTML contributes its visible text;
offsets refer to this scanned plain text, using Python string indices. Incomplete
transport HTML falls back to literal text rather than preventing dispatch.

Each occurrence contains `type`, `value`, `normalized_value`, `start`, `end`, and
optional `country` and `platform`. Types are `email`, `phone`, `postal_address` and
`instant_messaging`. Results follow source order without overlapping classifications.
Repeated occurrences retain their individual provenance; this list is not a set of
people. Country is a parsing hint, not evidence of residence.

The pure implementation lives in `core.util`; `app.agent` does not import
`app.contact`, which already consumes the agent facade. Country resolution is shared
with Contacts and uses the explicit country in `LOCALIZATION`, never a guessed city
or timezone. Email validation disables deliverability checks. Phone extraction uses
the offline `phonenumberslite` metadata and possible-number leniency, with E.164
normalization. Possibility does not prove allocation, reachability or ownership.
Recognizable invoice/order/registry references and generic HTTP URLs are excluded.
Known messaging labels and profile links identify their platform; an unqualified
handle requires an explicit handle label and retains an unknown platform.

Postal extraction uses bounded French/English street patterns and labeled postal
blocks, with limited multiline continuation. It does not claim universal coverage
or postal deliverability. Coordinates remain candidates requiring contextual review.
No DNS, database, LLM call, contact mutation or permission grant occurs in detection.

Parser caches and offline metadata are warmed during application startup. The 3 ms
target must be measured separately from routing inference, startup and downstream
identity resolution. Unbounded messages and arbitrary CPU scheduling cannot receive
a hard wall-clock guarantee; dense numeric input can exceed the target. No silent
message truncation or global result limit is introduced to hide this limit.

The synthetic corpus and Dispatcher-path tests are maintained in
`app/agent/tests/test_dispatcher_contacts.py` and
`fixtures/contact_detection_cases.json`. They exercise valid formats, false positives,
multiple coordinates, HTML, Unicode separators and historical serialization.

Owner attribution, known-coordinate lookup, contact creation/enrichment, independent
router-triggered processing and Dream reconciliation are subsequent stages. This
change supplies their input without implementing those decisions in the Dispatcher.
