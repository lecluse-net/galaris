<p align="right"><a href="../../fr/dev/plugin-authoring.md">Français</a> · <strong>English</strong></p>

# Build a Galaris plugin

Use the public contract of the domain that owns the operation. A preset for an
existing HTTP or MCP Service contains a definition and connection parameter
bindings. A document format supplies its codec and renderers, while Documents
owns permissions, publication, revisions and the library. The
[plugin plan](../../../project/plans/infrastructure-plugins-galaris.md) tracks
the other extension families.

The [bundle contract](plugin-bundles.md) defines what the loader accepts. The
[Plugin API](plugin-api.md) documents previewing, installing and activating signed releases.

## Working reference samples

In `APP_ENV=dev`, **Administer → Plugins** shows the three checkout samples.
Each card has an **Activation** switch that controls publication of the format
or Service preset. The instance retains the switch state.
For Drawing, create a **Drawing (Sample)** document in Documents. For REST and MCP,
create a Service from the matching preset, which prefills the demo URL.
The REST connection uses the token `sample-token`. The REST `GET /status` endpoint
and the MCP `sample_value` function return `sample-ok`.

To exercise installation and removal in the registry, use the signed ZIPs below.
A registry-managed release takes precedence over the checkout sample with the same
code, including after removal.

| Sample | Source | How it runs |
|---|---|---|
| **Sample REST** | `plugins/sample/rest/` | Signed Service preset using `rest.api`. The connection owns the endpoint and bearer token. |
| **Sample MCP** | `plugins/sample/mcp/` | Signed Service preset using `http.mcp`. The connection owns the MCP endpoint. |
| **Drawing (Sample)** | `plugins/sample/drawing/` | Native development contribution. Select **Drawing (Sample)** when creating a Document. |
| **Drawing (ZIP)** | `plugins/sample/drawing/` | Signed executable archive. Create the **Drawing (ZIP)** format after activation. |
| **Sample AI Provider** | `plugins/sample/provider/` | Executable archive. Configure the OpenAI-compatible profile in development using `sample-token`. |
| **Sample Preview Converter** | `plugins/sample/preview/` | Executable archive. Request a preview of a UTF-8 `.sample-note` attachment after activation. |
| **Sample Data** | `plugins/sample/data/` | Signed JSON template. Download it from the card and import it into Documents. |
| **Sample File Sharing** | `plugins/sample/file_share/` | Protocol and Service preset in one ZIP. In dev, activate, create a Service from the preset, then set `sample-token` on its Connection. The connection test and `file_read` on `sample-storage://note.txt` use that Connection. |

A plugin has one source directory and one archive per release. Its backend,
frontend and data sit in the same directory. The shared preset signing tool
requires Python and `cryptography`.

```text
plugins/sample/
├── rest/                     manifest and services/sample-rest.yaml
├── mcp/                      manifest and services/sample-mcp.yaml
├── provider/                 provider profile and source manifest
├── preview/                  preview converter and source manifest
├── data/                     declared, versioned JSON template
├── drawing/
│   ├── __init__.py            codec, initial PNG and register()
│   ├── index.ts               registration and inert snapshot
│   ├── manifest.json          sample identity and document capability
│   ├── bundle.json             installable release manifest
│   ├── build.mjs               Vue compilation from the same sources
│   ├── DrawingEditor.vue     drawing editor
│   ├── DrawingPreview.vue    historical revision reader
│   └── messages.ts           French, English and Chinese UI text
├── native.py                 provider and conversion examples
├── inventory.py              development sample inventory
├── fixtures.py               local REST and MCP targets
└── package.py                digests, signature and deterministic ZIP
```

## Sign a Service bundle

These example commands use the local Docker development backend. Keep the
private key within the publisher's environment.

```bash
backend="${APP_NAME:-galaris}-back"
work=$(docker exec "$backend" mktemp -d /tmp/galaris-plugin.XXXXXX)
docker exec "$backend" python -m plugins.sample.package init-key "$work/publisher.pem"
docker exec "$backend" python -m plugins.sample.package public-key "$work/publisher.pem"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/rest "$work/sample-rest.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/mcp "$work/sample-mcp.zip"
docker cp "$backend:$work/sample-rest.zip" .
docker cp "$backend:$work/sample-mcp.zip" .
```

Ask the operator to approve the publisher prefix and public key for
`PLUGIN_TRUSTED_PUBLISHERS`. See the [bundle contract](plugin-bundles.md) for
the ZIP layout, compatibility, development override and removal. Preview and
install the release inactive in **Administer → Plugins**, then activate it
and choose **Configure a copy** in the Services catalogue. Configure account
values and secrets in the regular Connection editor. Use a synthetic external
endpoint for transport tests. Uninstalling withdraws the preset and keeps
the locally saved Service.
Keep the publisher key for later releases of the same code. Use a separate
test key and registry for disposable trials.

## Implement a document format

The [document format contract](document-formats.md) defines the host API. The
Drawing sample uses code and provider `sample.drawing` and format version `1`
on both sides. Its backend entry point registers a validator, MIME type,
initial bytes and declared capabilities. It accepts a single PNG frame, up to
2048 pixels per side and 8 MiB.

The frontend registers the drawing editor, a revision reader and an inert PNG
snapshot for PDF. The editor only uses the provided `DocumentContentSource` and
passes the expected revision when saving. Drawing autosaves after a short pause
at the end of a stroke. `flush` saves pending changes before leaving the editor.
The editor retains the draft on failure and supports explicit discard. The historical reader gets
a read-only source. Thumbnails and embeds use the host fallbacks. The original
and its revisions remain accessible through Documents.

Drawing uses `DocumentToolbar` to declare its tools, their state and brush
settings. The checkout and ZIP use the same component.
[Toolbar contract](document-formats.md)

The development composition loads both Drawing entry points from this directory
when `APP_ENV=dev`. From the repository root, use the following command to create
one source ZIP containing the codec and the interface.

```bash
zip -X -r sample-drawing-source.zip plugins/sample/drawing -x '*/__pycache__/*'
```

The source ZIP is for review. To build the installable ZIP with the same editor,
reuse `backend`, `work` and the signing key from the Service example above.

```bash
frontend="${APP_NAME:-galaris}-front"
staging=$(mktemp -d)
docker exec "$frontend" node plugins/sample/drawing/build.mjs /tmp/sample-drawing-build
docker cp "$frontend:/tmp/sample-drawing-build" "$staging/drawing"
docker cp "$staging/drawing" "$backend:$work/drawing"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" "$work/drawing" "$work/sample-drawing.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/provider "$work/sample-provider.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/preview "$work/sample-preview.zip"
docker exec "$backend" python -m plugins.sample.package build "$work/publisher.pem" plugins/sample/data "$work/sample-data.zip"
```

Copy the ZIPs as you did for REST and MCP. Have the operator approve `sample` in
`PLUGIN_EXECUTABLE_PUBLISHERS` on the qualification instance. After activating
**Drawing (ZIP)**, create the format in Documents, draw and reopen the saved PNG.
Deactivate and uninstall the release, then verify the original download. Drawing
(Sample) keeps its separate checkout format code.

## Extension point index

| Capability | Public contract and reference |
|---|---|
| REST and MCP | [Services catalogue](service-catalog.md), Sample REST and Sample MCP. |
| Mail and Calendar | [Capabilities and protocols](../../../project/decisions/0274-provider-tool-protocols.md), [protocol configuration tests](../../../back/app/services/tests/test_protocols.py). |
| AI provider | [Provider registration](../../../back/app/llm/provider_facade.py), `plugins/sample/provider/` archive. The profile uses the host's OpenAI-compatible protocol. |
| Document format | [Format façade](document-formats.md), Drawing and [synthetic structured format](../../../back/app/document/tests/test_formats.py). |
| Resource reader | `registerResourceViewer` and `ResourceViewerSource`, used by `front/test-support/browser/ResourceViewerHarness.vue`. |
| Preview converter | [PreviewConverter](../../../back/core/preview/contracts.py), `plugins/sample/preview/` archive and [its host contract tests](../../../back/core/preview/tests/test_conversion.py). |
| Installable file protocol | [`FileShareBridge`](../../../back/app/file_share/bridges.py) and the Sample File Sharing archive. Galaris owns Connections and access control. |
| Messenger bridge | [Messenger façade](../../../back/app/messenger/facade.py), [bridge configuration tests](../../../back/app/messenger/tests/test_bridge_configuration.py). |
| Process engine | [ProcessEngine](process-engines.md), [synthetic engine](../../../back/app/process/fake_engine.py). |
| Agent driver | [Agent contracts](../../../back/app/agent/contracts.py), [driver testkit](../../../back/app/agent/tests/test_driver_testkit.py). |
| Skills and data | [Development guide](README.md), existing domain importers and [DbAdmin](dbadmin.md). Sample Data distributes an importable template. Skill packs and registry-managed datasets remain planned. |
| Panels, external file editors and installable new protocols | Refer to the [plugin plan](../../../project/plans/infrastructure-plugins-galaris.md) for the publication contracts still to design. |

## Examples to adapt

### Distribute a data template

Put this `manifest.json` in the staging directory. Adjust the range to the Galaris version
you qualify. The packager computes `sha256` before signing the manifest.

```json
{
  "format_version": 2,
  "code": "example.inventory",
  "version": "1.0.0",
  "label": {"fr": "Inventaire de démonstration", "en": "Demo inventory"},
  "description": {"fr": "Modèle JSON importable.", "en": "Importable JSON template."},
  "minimum_galaris_version": "0.3.2",
  "maximum_galaris_version_exclusive": "1.0.0",
  "contributions": [{
    "family": "data_template",
    "code": "example.inventory",
    "label": {"fr": "Inventaire", "en": "Inventory"},
    "contract_version": 1
  }]
}
```

In the same directory, create `data/example.inventory.json`.

```json
[
  {"sku": "DEMO-001", "quantity": 3, "available": true},
  {"sku": "DEMO-002", "quantity": 0, "available": false}
]
```

Build the ZIP with the `example` publisher key using the signing command above. After activation,
download the template from its card or through the API. Import the JSON using
**Documents → New document from…**. Change a quantity in the copy and verify that another download
of the template retains the original quantities.

### Connect a REST or MCP Service

For REST, create a directory with this `manifest.json`. The `service_preset` contribution
uses the code of the YAML preset.

```json
{
  "format_version": 1,
  "code": "example.stock",
  "version": "1.0.0",
  "label": {"fr": "Stock", "en": "Stock"},
  "description": {"fr": "Connecteur REST.", "en": "REST connector."},
  "minimum_galaris_version": "0.3.2",
  "maximum_galaris_version_exclusive": "1.0.0",
  "contributions": [{
    "family": "service_preset",
    "code": "example-stock",
    "label": {"fr": "Service Stock", "en": "Stock service"},
    "contract_version": 1
  }]
}
```

Create `services/example-stock.yaml` with the same contribution code.

```yaml
code: example-stock
label: Example Stock
catalog:
  format_version: 1
  version: 1.0.0
  summary:
    en: Read stock from a configured connection.
    fr: Lire le stock via une connexion configurée.
capabilities:
  - rest.api
rest_config:
  base_url: ${connection:url}
  auth:
    type: bearer
    param: token
connection_schema:
  params:
    url: {type: string, label: URL, required: true}
    token: {type: password, label: Token, required: true}
```

Configure a copy of the Service after activation. Set a synthetic server URL and token on its
Connection. Use a known read-only route such as `GET /status`.
For MCP, use the same manifest structure with a new identity such as `example.inventory-tools`
and a contribution code of `example-inventory-tools`. Put this preset in
`services/example-inventory-tools.yaml`.

```yaml
code: example-inventory-tools
label: Example Inventory Tools
catalog:
  format_version: 1
  version: 1.0.0
  summary:
    en: Connect to an inventory MCP server.
    fr: Connecter un serveur MCP d’inventaire.
capabilities:
  - http.mcp
mcp_config:
  type: http
  auth:
    type: none
    url_param: url
connection_schema:
  params:
    url: {type: string, label: URL, required: true}
```

Set the synthetic server's Streamable HTTP MCP endpoint in the Connection. Verify tool
discovery and call a read-only function on the fixture. If the target requires authentication,
choose a mode described in the [Services catalogue](service-catalog.md).

In development, the same server provides `sample_inventory`. Use
`http://127.0.0.1:8000/api/plugin-samples/mcp/` from the backend, enable the Service
for conversations and assign an active Connection to the agent. To try **Filter**
in internal Chat, set the `sample_inventory` tool and the `ui://sample/inventory.html`
resource to **Enabled** in that Connection. Ask the agent to use Sample MCP to show stock.
The **Lyon** filter should return two rows with quantities of 18 and 7. The sample server
uses JSON responses over Streamable HTTP.

The server provides `structuredContent.table` with a `title`, 1 to 16 `columns` and
up to 100 `rows`. Each row has one JSON scalar or `null` per column. The form uses
`_meta.ui.resourceUri` with a self-contained `text/html;profile=mcp-app` resource.
The tool declares `annotations.readOnlyHint` and allows calls from the app. Galaris
checks current Connection permissions and lets the form call the same tool again.
Connection credentials stay on the server.
[Chat workflow](../user/documents.md#mcp-tables)

### Implement an executable contribution

| Case | Example to follow and scenario to verify |
|---|---|
| Signed document format | The Drawing Sample build wraps the codec in `plugin_format(context)` and exports `createFormat(host)` for the browser. A document opens an authorized PNG, saves against the observed revision and provides a historical preview. Verify that the original can still be downloaded after removal. |
| Document editor with references | Use `host.DocumentLink`, `host.DocumentCard` and `host.DocumentEmbed` in the Vue module to compose references. The editor chooses modes per resource type. Declare Embed support on both sides and supply a complete read-only viewer so other documents can embed the format. [Reference contract](document-references.md) |
| AI provider | Sample AI Provider returns a `ProviderProfile` from `plugin_provider(context)` and uses the host's OpenAI-compatible transport. Verify a response through a synthetic Connection and its parameters. |
| Attachment conversion | Sample Preview Converter returns a `PreviewConverter` from `plugin_converter(context)`. It recognizes `.sample-note`, reads a bounded amount, validates UTF-8 and produces a temporary preview. Verify an ordinary download preserves the original bytes. |
| File protocol | Sample File Sharing publishes `plugin_file_share_protocol(context)` and a preset in the same ZIP. Test listing and reading `note.txt` through Connection parameters, then verify that the read-only transport refuses writes. |

## Agent authoring workflow

Use the `galaris-plugin-author` and `galaris-plugin-qualification` skills in
`.agents/skills`. Select the relevant contract, keep fixtures synthetic, verify
permission denials, retry and removal, and report the evidence for the exact
bundle and capabilities. Codec results, API integration and browser journeys
provide different evidence.

The bundled Galaris assistant receives the `galaris-plugin-development` system skill by default.
It loads the skill on demand. Assign it to another agent through **Configure → Skills → Authorizations**.
The skill can read these guides through authorized documentation functions. Building and qualifying
a ZIP also requires a workspace, suitable tools and access to source or examples. The private key
stays in the publisher's signing environment. See the [Skills guide](../user/skills.md) for access
and assignment permissions.

```bash
make tests ARGS='app/plugin/tests app/document/tests/test_sample_drawing.py app/document/tests/test_formats.py'
make tests-front-components ARGS='document-formats.spec.mjs plugins.spec.mjs --project chromium'
make typecheck
make docs-prepare
```
