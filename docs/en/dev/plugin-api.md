<p align="right"><a href="../../fr/dev/plugin-api.md">Français</a> · <strong>English</strong></p>

# Plugin administration API

The HTTP API manages signed archives and installed releases. To build an archive, see
the [authoring guide with examples](plugin-authoring.md) and the [bundle contract](plugin-bundles.md).
Request and response schemas are in the [registry contracts](../../../back/app/plugin/contracts.py)
and routes are in the [plugin router](../../../back/app/plugin/router.py).

## Routes and authorization

| Method and route | Authorization | Input and result |
|---|---|---|
| `GET /api/plugins` | `PLUGIN_ACCESS` or `PLUGIN_EDIT` | Inventory of releases and development Samples. |
| `GET /api/plugins/{code}` | `PLUGIN_ACCESS` or `PLUGIN_EDIT` | Releases and events for the requested identity. |
| `POST /api/plugins/preview` | `PLUGIN_EDIT` | Multipart `file`. Verifies the archive and returns its manifest, digest, signer and compatibility. |
| `POST /api/plugins/install` | `PLUGIN_EDIT` | Multipart `file`, `digest`, `host_identity` and optional `force`. Saves a release inactive on first installation. |
| `POST /api/plugins/{code}/{version}/{operation}` | `PLUGIN_EDIT` | `activate`, `deactivate` or `remove` with a JSON body of `{"host_identity":"…"}` for an archive. To activate or deactivate a development Sample, send `{"source":"development_sample"}`. |
| `GET /api/plugins/catalog` | `PLUGIN_EDIT` | Managed catalogue releases with their preview information. |
| `GET /api/plugins/catalog/{digest}` | `PLUGIN_EDIT` | Downloads the catalogue ZIP at the given digest. |
| `GET /api/plugins/{code}/templates/{template_code}` | `PLUGIN_ACCESS` or `PLUGIN_EDIT` | Downloads the JSON source of an active template. |

The browser fetches the frontend module of an active plugin from
`GET /api/plugins/assets/{digest}/{code}.mjs`. Here `code` identifies the document
contribution. The public module contains static code only. The editor obtains user content from
the authorized document source provided by the host.

## Verify and install an archive

This example targets a qualification instance. Set an API URL ending in `/api`, an authorized
user token and the ZIP path in the variables shown. Preview verifies the archive. Review the
publisher code, signer, contributions and compatibility before performing the following mutations.

```bash
set -euo pipefail
: "${GALARIS_API:?}" "${GALARIS_PLUGIN_TOKEN:?}" "${PLUGIN_ZIP:?}"
auth="Authorization: Bearer $GALARIS_PLUGIN_TOKEN"
preview=$(curl -fsS -H "$auth" -F "file=@$PLUGIN_ZIP" "$GALARIS_API/plugins/preview")
printf '%s\n' "$preview" | jq '{manifest, digest, signer, compatibility, host_version, can_force}'
```

Reuse the preview values with the same ZIP bytes. This example requires ordinary compatibility
and leaves the development override off.

```bash
printf '%s\n' "$preview" | jq -e '.compatibility == "supported"' >/dev/null
digest=$(printf '%s\n' "$preview" | jq -er '.digest')
host=$(printf '%s\n' "$preview" | jq -er '.host_identity')
code=$(printf '%s\n' "$preview" | jq -er '.manifest.code')
version=$(printf '%s\n' "$preview" | jq -er '.manifest.version')

curl -fsS -H "$auth" -F "file=@$PLUGIN_ZIP" -F "digest=$digest" \
  -F "host_identity=$host" "$GALARIS_API/plugins/install" |
  jq '{installed, selected, active}'
```

Send the confirmation once activation is authorized. Qualification and production use the same
routes. The `force=true` override is available only for a host-version mismatch in development
when preview returns `can_force=true`. Publisher trust still applies.

```bash
confirmation=$(jq -cn --arg host "$host" '{host_identity: $host}')
curl -fsS -H "$auth" -H 'Content-Type: application/json' -d "$confirmation" \
  "$GALARIS_API/plugins/$code/$version/activate" | jq '{installed, selected, active}'
curl -fsS -H "$auth" "$GALARIS_API/plugins/$code" | jq '.events'
```

To withdraw the plugin from the qualification instance, use the same body with `deactivate`
and then `remove`. Data already imported and Services already copied remain local resources.
Documents and their revisions retain their source.

## Read results and recover after an error

- `digest` is the SHA-256 of the ZIP. `signer` fingerprints the signing key.
  `host_identity` identifies the current build, including for development override.
- Distinguish `installed`, `selected` and `active`. A selected release can lose compatibility
  or fail to load effectively. Read its state and events after a lost response.
- Different ZIP bytes under the same code and version are rejected (`version_conflict`).
  After `preview_changed`, preview again. Reinstalling the same bundle reuses its release.
  A revoked archive cannot be activated again.
- `detail` can contain a domain error code or parameter validation entries. An oversized ZIP
  returns HTTP 413. An invalid archive or one without a trusted publisher signature returns
  HTTP 422. Check plugin events after an activation failure.

The [native MCP inventory](../architecture/generated/project-map.md) and the tools mounted for
the agent determine what is callable. The routes above require an authorized HTTP API identity.
