"""Publish checkout samples through the ordinary Plugin and Service catalogues."""

from pathlib import Path
from typing import Literal

from app.plugin.contracts import SampleManifest, SampleRelease
from app.plugin.facade import register_development_samples
from app.services import ServiceCreate
from app.services.facade import parse_catalog_definition

ROOT = Path(__file__).parent
HTTP_ROOT = "http://127.0.0.1:8000/api/plugin-samples"
REST_ENDPOINT = f"{HTTP_ROOT}/rest"
MCP_ENDPOINT = f"{HTTP_ROOT}/mcp/"
REST_TOKEN = "sample-token"


def register() -> None:
    drawing = SampleRelease(
        manifest=SampleManifest.model_validate_json((ROOT / "drawing" / "manifest.json").read_bytes()),
        target="documents",
    )
    samples: list[SampleRelease] = [drawing]
    presets: list[ServiceCreate] = []
    targets: tuple[tuple[Literal["rest", "mcp"], str], ...] = (("rest", REST_ENDPOINT), ("mcp", MCP_ENDPOINT))
    for target, endpoint in targets:
        folder = ROOT / target
        manifest = SampleManifest.model_validate_json((folder / "manifest.json").read_bytes())
        samples.append(SampleRelease(manifest=manifest, target=target, endpoint=endpoint))
        for contribution in manifest.contributions:
            definition = parse_catalog_definition(
                (folder / "services" / f"{contribution.code}.yaml").read_text(encoding="utf-8"),
            )
            assert definition.catalog is not None
            definition.catalog.plugin_code = manifest.code
            definition.catalog.plugin_version = manifest.version
            definition.connection_schema.params["url"].default = endpoint
            presets.append(definition)
    register_development_samples(samples, presets)
