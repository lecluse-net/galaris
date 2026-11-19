<p align="right"><a href="../../fr/dev/plugin-authoring.md">Français</a> · <strong>English</strong></p>

# Build a Galaris plugin

Use the public contract of the domain that owns the operation. A preset for an
existing HTTP or MCP Service contains a definition and connection parameter
bindings. A document format supplies its codec and renderers, while Documents
owns permissions, publication, revisions and the library. The
[plugin plan](../../../project/plans/infrastructure-plugins-galaris.md) tracks
the other extension families.

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

## Agent authoring workflow

Use the `galaris-plugin-author` and `galaris-plugin-qualification` skills in
`.agents/skills`. Select the relevant contract, keep fixtures synthetic, verify
permission denials, retry and removal, and report the evidence for the exact
bundle and capabilities. Codec results, API integration and browser journeys
provide different evidence.

Agents working in the repository use these skills in their workspace. To make them
available to Galaris agents, import the two `SKILL.md` files or their individual ZIP
files via **Configure → Skills → Import**, then assign them to authors and reviewers.
Give those agents access to the repository and the tools needed for testing. Links
to contracts and Samples point to the repository. See the [Skills guide](../user/skills.md)
for access and assignment permissions.

```bash
make tests ARGS='app/plugin/tests app/document/tests/test_sample_drawing.py app/document/tests/test_formats.py'
make tests-front-components ARGS='document-formats.spec.mjs plugins.spec.mjs --project chromium'
make typecheck
make docs-prepare
```
