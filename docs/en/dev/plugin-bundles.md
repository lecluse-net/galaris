<p align="right"><a href="../../fr/dev/plugin-bundles.md">Français</a> · <strong>English</strong></p>

# Plugin bundles

Manifest version `1` supports [Service presets](service-catalog.md).
A release may contain multiple presets. Selecting a release publishes them in the local
catalogue in one transaction. Saving a preset in the Service editor creates an independent
copy. Existing Services, connections and authorizations follow their ordinary workflows.
The [authoring guide](plugin-authoring.md) includes the reference sources and signing commands.

## Prepare an archive

The ZIP contains a UTF-8 `manifest.json`, its binary Ed25519 signature `manifest.sig`,
and a standalone `services/<code>.yaml` file for each contribution. Sign the exact
manifest bytes with the publisher's private key. Record the SHA-256 of each preset's
exact bytes in its manifest entry.

The manifest contains the following fields.

| Field | Value |
|---|---|
| `format_version` | `1` |
| `code` | Stable publisher-qualified code, such as `example.studio` |
| `version` | Stable `MAJOR.MINOR.PATCH` version |
| `label`, `description` | Objects with `en` and `fr` text |
| `minimum_galaris_version`, `maximum_galaris_version_exclusive` | Inclusive lower and exclusive upper bounds |
| `contributions` | For each preset, `family: service_preset`, its `code`, bilingual `label`, `contract_version: 1` and hexadecimal `sha256` |

Each YAML preset follows the Service catalogue contract, including its `catalog`
metadata and at least one available protocol. Its code must match the contribution.
Galaris adds provenance to the published preset. The limits are 2 MiB compressed,
4 MiB expanded and 16 presets. The installer reads files directly without extraction
and validates definitions using the portable Service rules.

Configure `PLUGIN_TRUSTED_PUBLISHERS` in the backend environment. The JSON value maps
each plugin code's first segment to a raw 32-byte Ed25519 public key encoded in hex.
The private key stays with the publisher. An empty map disables imports. Removing a
key withdraws its contributions from the catalogue at the next start.

## Install and verify

1. Select the archive and review its capabilities, signing key fingerprint and compatibility.
2. Install the inactive release and activate it. In **Configure → Services & connections**,
   open **New service**, find the preset and select **Configure a copy**. Adjust the
   settings and save the Service.
3. In **Plugins**, deactivate the release and confirm uninstallation. The catalogue
   withdraws the preset and the saved Service remains usable.

On a branch outside the declared host range, forcing is available only when
`APP_ENV=dev`. The exception is bound to the archive and the image revision.
Rebuild the image when switching branches to expose the new revision. An image
without a known revision accepts this exception for the lifetime of the current
process. The installer always verifies integrity, publisher trust and preset contracts.

## Add executable contributions

Use `format_version: 2` to combine Service presets and executable contributions in
one ZIP. The contribution family determines the file paths and digests.

| Family | Files and contract `1` |
|---|---|
| `document_format` | `backend/<code>.py` and `frontend/<code>.mjs`. Declare the format `version`, Python SHA-256 in `sha256` and browser module SHA-256 in `frontend_sha256`. |
| `llm_provider` | `backend/<code>.py` and `sha256`. `plugin_provider(context)` returns a `ProviderProfile`. |
| `preview_converter` | `backend/<code>.py` and `sha256`. `plugin_converter(context)` returns a `PreviewConverter`. |
| `file_share_protocol` | `backend/<code>.py` and `sha256`. `plugin_file_share_protocol(context)` returns a `FileShareBridge` whose `service` matches the contribution code. |
| `data_template` | `data/<code>.json` and `sha256`. After activation, download the source and import it through Documents. The copy owns its permissions and revisions. |

Executable contribution codes are the plugin code or a dot-qualified child. The
JSON list in `PLUGIN_EXECUTABLE_PUBLISHERS` identifies publishers the operator trusts
to run code in the Galaris server and browser. Loading follows signature verification
and explicit activation.

A file sharing protocol becomes selectable in Services as `<code>.file_share`.
A preset in the same ZIP can already reference it. The `FileShareBridge` declares
roles and builds a transport with the Service URL and the resolved Connection
parameters. For a read-only transport, set `writable=False` and reject uploads
in the adapter. The standard connection test can call `resource_list` with a limit
of one entry. Deactivation withdraws the protocol and the operations that depend
on it. Services and Connections retain their parameters.

`plugin_format(context)` returns a binary `DocumentFormatDefinition` matching the
declared code, provider and version. The browser module exports `createFormat(host)`
and returns `editor`, `snapshot` and optional `preview`. `host` supplies `vue`,
`useI18n`, `solaire`, `saveBlobAsResource` and the `QBanner`, `QBtn`, `QBtnToggle`,
`QSpace`, and `QSpinner` components under `host.quasar`. The editor receives
`DocumentContentSource`. The browser module is public while active.
The [frontend facade](../../../front/app/document/pluginHost.ts) lists the Vue functions
the host provides on demand.

Plugins that use the shared toolbar get the component from `host.DocumentToolbar`.
Declare a minimum Galaris version that provides it and verify that the editor opens on
that version. [Toolbar contract](document-formats.md)

`python_requirements` accepts exact versions of preinstalled dependencies.
`runtime_requirements` entries declare a `code` and digest-pinned `image`. The
operator starts the corresponding service and maps the same `image` and a `url`
per code in `PLUGIN_RUNTIME_BINDINGS`. Galaris checks for HTTP 200 at `/health`
before loading and passes resolved URLs in `context.endpoints`. The development
override covers the Galaris version range only.

The API publishes prepared registries after the transaction. The Process worker
reads the PostgreSQL selection at startup and reconciles it every two seconds.
It withdraws obsolete contributions before preparing replacements. Operations
already in progress can finish.

Before selecting a release, Chromium loads each self-contained module in a fresh
context with no application access or network requests and checks the `createFormat`
export. An import failure preserves the previous selection and records an event.
Calling `createFormat(host)`, mounting the editor and exercising interactions still
require qualification in the assembled frontend. Diagnostics in `/data/update-diagnostics`
retain the stage, release version and redacted cause of loading and installation failures.
At startup, the API checks selected archives and their dependencies before accepting
requests. Deactivation withdraws contributions and browser modules. The original
documents, their revisions and local configurations are preserved.

## Populate the catalogue

Place approved signed ZIPs in `PLUGIN_CATALOG_DIRECTORY`, which defaults to
`/data/plugins/catalog`. **Administer → Plugins → Catalogue** lists those releases
and uses the manual import's signed preview before installing an inactive release.
The operator manages this mirror.

### Curated remote catalogue

Set `PLUGIN_CATALOG_REMOTE_URL` to an operator-managed HTTPS directory and configure the
hexadecimal Ed25519 public key with `PLUGIN_CATALOG_REMOTE_PUBLIC_KEY`. The directory serves
`index.json`, `index.sig`, and `archives/<sha256>.zip`. The index has `format_version: 1`,
a strictly increasing integer `sequence`, UTC `issued_at` and `expires_at` with a lifetime
of up to seven days, `releases` with `manifest`, `digest`, and `signer` from the inspected
approved ZIPs, and `revoked`, the cumulative list of withdrawn digests. Sign the index bytes
with a key separate from the publisher keys.

```bash
python -m plugins.sample.package sign-index catalogue.pem index.json index.sig
```

Publish the digest-addressed archives first and then the new index and signature. Galaris keeps
the last accepted index on the catalogue volume. An older sequence or a removed revocation
cannot replace it. The cache stays usable until expiry. Downloads recheck the index, digest,
and publisher signature. The API checks for catalogue revocations every minute and
deactivates affected releases. The registry retains the block by digest after index
expiry, a catalogue outage or uninstallation. A revoked digest can no longer be
imported manually or reactivated. Documents, revisions, local Services and Connections
retain their data.

### Stage a declarative publication

The publisher uses the keys in `PLUGIN_TRUSTED_PUBLISHERS` to verify ZIPs.
For each `<name>.zip`, supply `<name>.qualification.json` and its binary Ed25519
signature `<name>.qualification.sig` from an authority separate from the publisher
and catalogue. The attestation has `format_version: 1`, `digest` (ZIP SHA-256),
`source_repository` (HTTPS), `source_commit` (Git hash), `report_digest` (SHA-256
of the report retained by the qualifier), and `checks` containing
`bundle`, `compatibility`, `permissions`, `localization`, and `lifecycle`.

```bash
python -m app.plugin.publication ./candidates ./next-catalogue \
  --catalogue-key catalogue.pem --qualification-key qualification-public.hex \
  --previous ./current-catalogue --revoke "$revoked_digest"
```

Omit `--previous` and `--revoke` for a first publication. The publisher creates a new
signed directory, continues the previous sequence and revocations, and stages
digest-addressed archives with their attestations. The operator publishes
`index.json`, `index.sig`, and `archives/` after review. Executable contributions
use the channel for publishers explicitly approved by the operator. Third-party
isolation and official hosting remain in the
[plugin plan](../../../project/plans/infrastructure-plugins-galaris.md).
