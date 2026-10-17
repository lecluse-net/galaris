# 0197 — Process-owned BPMN definitions

Date: 2026-10-17
Status: accepted
Supersedes the definition-storage choice in [0174](0174-native-document-backed-business-processes.md).

## Decision

A Document is editorial HTML. A Dataset is JSON. A Process definition is BPMN and is
stored directly in `process_definitions.bpmn_xml`, never in the Documents domain.
Process owns definition revisions and collaborator grants in its own tables. Shared
picker presentation and collaborator-directory DTOs do not confer Document ownership.

Definition creation, edits, history, restore, sharing and launch authorization use
Process-owned state. Launch snapshots freeze BPMN, the compiled graph and revision;
they contain no definition Document identifier. Document creation APIs accept HTML only,
and the Documents library and editor exclude BPMN definitions.

## Existing data

The DbAdmin `app.process.native_definition_storage` action runs after expansion of the
Process columns and history/grant tables. Each bounded transaction transfers current
BPMN, retained revisions, ownership and rights, then archives the old Document/Memory
source and nulls the legacy FK. Invalid or missing current content aborts that batch.
The postcondition checks remaining source FKs, so retries resume without duplicates.
The nullable legacy FK and archived sources remain solely for safe transfer recovery
and audit; runtime reads and writes never use them.

## Regression protection

Persistence tests check that native creation and updates create no Document rows.
Upgrade tests cover rights, revision content, idempotence and invalid-batch rollback.
The native-storage database constraint forbids a populated BPMN definition from also
referencing a Document. API tests reject Process/Dataset types in Document creation;
the assembled Process journey checks that its definition is absent from Documents.
