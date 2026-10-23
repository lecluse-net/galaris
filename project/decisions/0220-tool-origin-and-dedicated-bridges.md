# 0220 — Tool origin and dedicated bridges

Status: accepted, 2026-10-23.

## Context

The human Tool catalogue reused translation codes to infer software ownership. Known
bridge names therefore moved editable custom Tools into the Galaris group and replaced
their saved labels and descriptions. n8n also had an integrated definition with no MCP
functions, although its dedicated bridge implements the Process engine contract.

## Decision

The integrated definitions declared by `app.tools` are software-owned and protected.
The client follows the backend's definition-editability contract for origin instead
of recognizing bridge names. Native translation overrides apply only to native Tool
codes. A dedicated bridge supplies integration capabilities without defining a standard
Tool. This includes n8n, Nextcloud, AFFiNE and the external messaging bridges.

Remove n8n from the integrated definitions. Synchronization no longer creates or overwrites
it. Preserve existing entries, connections, Process references and history; the definition
becomes administrator-owned and editable. The current Process model still identifies an
external engine through a Tool row: installations using n8n explicitly configure that
custom entry if absent. This correction does not change Process persistence or engine routing.

## Verification

Frontend rules cover bridge origins and preservation of custom labels and descriptions.
Real PostgreSQL tests cover repeated synchronization, administrator-owned settings,
editability and resolution of existing n8n Process references.
