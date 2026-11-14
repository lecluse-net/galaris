<p align="right"><a href="../../fr/dev/service-catalog.md">Français</a> · <strong>English</strong></p>

# Self-contained service catalog

The catalog ships in `back/app/services/service_catalog/`. `index.yaml` contains
`format_version: 1` and `services`, a list of YAML filenames. Each entry uses the standard
editor and import/export `ServiceCreate` contract, with two additional fields:

- `catalog`: `format_version`, preset SemVer `version`, `minimum_galaris_version`,
  `summary.fr` and `summary.en`, `documentation` URL and `icon_credit` attribution;
- `icon`: `media_type` (`image/svg+xml`, `image/png`, `image/gif`), `encoding` (`text` or
  `base64`) and `data`, embedded entirely in the YAML. Prefer a `|` block for readable SVG.

Configuration fields and parameter references follow existing contracts. Never include
personal connections or secret values. Use generic names (`url`, `login`, `password`,
`token`, `user_id`). Describe only supported executable protocols and capabilities,
including limits and addresses that users must complete. Preserve icon provenance and
licenses; trademarks do not imply their owners endorse Galaris.

Files and HTTP responses are limited to 512 KiB, indexes to 100 entries and refreshes to
60 seconds. Icons are limited to 128 KiB; PNG/GIF to 1024 pixels and 100 frames. The SVG
subset accepts explicit shapes and attributes without DTDs, scripts, styles, links,
external references or HTML objects. The frontend displays an image, never injected SVG
markup. Official presets cannot distribute stdio MCP commands or literal credentials.
Personal import/export retains existing MCP configuration contracts.

`GET /api/services/catalog` requires `SERVICE_ACCESS` or `SERVICE_EDIT`.
`POST /api/services/catalog/refresh` requires `SERVICE_EDIT`. Reads do not access the network.
Refreshes target only `lecluse-net/galaris`, resolve `main` and fetch the index and presets
at the same SHA. JSON cache snapshots are atomically published under `/data/service-catalog/`.
Network or validation failures retain the previous snapshot and expose `refresh_failed`.
Bundled entries remain a fallback, including when a remote preset becomes incompatible.

Preset provenance is retained on local copies to indicate differing versions, without
automatic replacement. Creation remains an ordinary Service save through the standard
editor. Credentials stay local to Connections.

The `app.services.rename_domain` DbAdmin `BEFORE_EXPAND` action performs the domain rename.
It runs through `make sync-db` in development and `make update` during deployment. Clients
must migrate `app.tools` to `app.services`, `/api/tools` to `/api/services`, `tool_id`/`tool_code`
to `service_id`/`service_code`, `TOOL_ACCESS`/`TOOL_EDIT` to `SERVICE_ACCESS`/`SERVICE_EDIT`,
`tool_admin_*` to `service_admin_*` and `tools_list` to `services_list`. Protocol-level MCP
tools, their calls and indexes retain their terminology. Historical DbAdmin action keys
remain stable for recovery.

Legacy BPMN and run-snapshot readers adapt affected REST references and administrative
calls without rewriting historical revisions or business data.

Initial REST presets follow official references:
[Qonto](https://docs.qonto.com/get-started/business-api/overview),
[GitLab](https://docs.gitlab.com/api/rest/authentication/),
[n8n](https://docs.n8n.io/api/authentication/),
[Redmine](https://www.redmine.org/projects/redmine/wiki/Rest_api).
