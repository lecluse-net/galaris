"""Verify the signed reference archives with the production bundle reader."""

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.plugin.bundles import read_bundle
from app.services import service
from core import settings
from plugins.sample.package import build
from plugins.sample import __file__ as samples_package


@pytest.mark.parametrize("name,capability", [("rest", "rest.api"), ("mcp", "http.mcp")])
@pytest.mark.asyncio
async def test_each_reference_archive_signs_and_creates_a_service(name, capability, monkeypatch, db):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {"sample": key.public_key().public_bytes_raw().hex()})
    source = Path(samples_package).with_name(name)
    archive = build(source, key)
    assert build(source, key) == archive
    bundle = read_bundle(archive)
    assert bundle.manifest.code == f"sample.{name}"
    assert bundle.presets[0].capabilities == [capability]
    assert bundle.presets[0].catalog.plugin_code == bundle.manifest.code
    saved = await service.create_service(bundle.presets[0])
    assert saved.code == f"sample-{name}" and saved.capabilities == [capability]
    assert "url" in saved.connection_schema["params"]


@pytest.mark.asyncio
async def test_signed_preview_sample_converts_and_releases_temporary_source(monkeypatch, tmp_path):
    from app.plugin import runtime
    from core.preview import PreviewFile, conversion, prepare_preview
    import plugin_composition

    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(plugin_composition, "_loaded", {})
    monkeypatch.setattr(conversion, "_plugin_converters", {})
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {"sample": key.public_key().public_bytes_raw().hex()})
    bundle = read_bundle(build(Path(samples_package).with_name("preview"), key))
    runtime.prepare_change(bundle.manifest.code, bundle)()
    path = tmp_path / "synthetic.sample-note"
    content = "Synthetic note, révision 1".encode()
    path.write_bytes(content)
    source = PreviewFile(path, path.name, "application/octet-stream")
    async with prepare_preview(source) as preview:
        assert preview.media_type == "text/plain" and preview.path.read_bytes() == content
        derived = preview.path
    assert not derived.exists() and path.read_bytes() == content
    runtime.prepare_change(bundle.manifest.code, None)()
    async with prepare_preview(source) as preview:
        assert preview == source
