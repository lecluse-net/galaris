"""Portable presets preserve local configuration and survive offline refreshes."""

import base64
from io import BytesIO
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest
from sqlalchemy import select, text
import yaml

from app.services import service
from app.services import service_catalog as catalog
from app.services.models import Service
from app.services.schemas import ServiceCreate
from app.services.service_icons import ServiceIcon


def test_bundled_presets_are_self_contained_supported_and_secret_free():
    entries = catalog.bundled_catalog().entries
    assert {entry.definition.code for entry in entries} >= {"qonto", "nextcloud", "gitlab", "matrix", "n8n", "redmine", "telegram", "suno"}
    for entry in entries:
        assert entry.compatible
        assert entry.definition.icon is not None
        ServiceIcon.model_validate(entry.definition.icon.model_dump())
        assert not any(parameter.type == "password" and parameter.default
            for parameter in entry.definition.connection_schema.params.values())


@pytest.mark.parametrize("format,media_type", [("SVG", "image/svg+xml"), ("PNG", "image/png"), ("GIF", "image/gif")])
@pytest.mark.asyncio
async def test_single_yaml_roundtrip_keeps_icon_and_existing_connections(db, format, media_type):
    if format == "SVG":
        icon = ServiceIcon(media_type=media_type, encoding="text", data='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#397CA1"/></svg>')
    else:
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, format=format)
        icon = ServiceIcon(media_type=media_type, encoding="base64", data=base64.b64encode(buffer.getvalue()).decode())
    record = await service.create_service(ServiceCreate(code="synthetic-portable", label="Synthetic portable", icon=icon,
        rest_config={"base_url": "https://service.example.test", "auth": {"type": "none"}}))
    exported = service.serialize_to_yaml(record)
    assert yaml.safe_load(exported)["icon"] == icon.model_dump()
    copied, created = await service.import_from_yaml_string(exported.replace("synthetic-portable", "synthetic-copy"))
    assert created and copied.icon == record.icon
    # Legacy files without an icon remain importable.
    legacy, created = await service.import_from_yaml_string("code: synthetic-legacy\nlabel: Synthetic legacy\n")
    assert created and legacy.icon is None
    record_id = record.id
    await service.import_from_yaml_string(exported, overwrite=True)
    assert (await db.get(Service, record_id)).icon == icon.model_dump()


@pytest.mark.parametrize("content", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/a.png"/></svg>',
    '<!DOCTYPE svg [<!ENTITY x "secret">]><svg>&x;</svg>',
])
def test_service_icons_reject_active_or_external_svg(content):
    with pytest.raises(ValueError):
        ServiceIcon(media_type="image/svg+xml", encoding="text", data=content)


@pytest.mark.asyncio
async def test_catalog_refresh_is_pinned_atomic_and_does_not_change_local_services(db, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    monkeypatch.setattr(catalog, "CACHE", cache)
    source = catalog.BUNDLED / "gitlab.yaml"
    body = source.read_text()
    revision = "a" * 40
    requested = []
    fail = False

    def respond(request):
        requested.append(str(request.url))
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"sha": revision})
        assert f"/{revision}/" in request.url.path
        if request.url.path.endswith("index.yaml"):
            return httpx.Response(200, text="format_version: 1\nservices: [gitlab.yaml]\n")
        return httpx.Response(503 if fail else 200, text=body)

    client = httpx.AsyncClient
    monkeypatch.setattr(catalog.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    existing = await service.create_service(ServiceCreate(code="gitlab", label="Synthetic local configuration"))
    identifier = existing.id
    result = await catalog.refresh_catalog()
    assert result.source == "github" and result.revision == revision and not result.refresh_failed
    saved = cache.read_bytes()
    assert len(requested) == 3
    assert (await db.get(Service, identifier)).label == "Synthetic local configuration"
    fail = True
    result = await catalog.refresh_catalog()
    assert result.refresh_failed and result.revision == revision
    assert cache.read_bytes() == saved
    assert {entry.definition.code for entry in result.entries} >= {"gitlab", "nextcloud"}


def test_cache_compatibility_is_rechecked_and_invalid_cache_falls_back(monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    monkeypatch.setattr(catalog, "CACHE", cache)
    snapshot = catalog.bundled_catalog()
    snapshot.source = "github"; snapshot.revision = "b" * 40
    gitlab = next(entry for entry in snapshot.entries if entry.definition.code == "gitlab")
    gitlab.definition.catalog.minimum_galaris_version = "999.0.0"
    cache.write_text(snapshot.model_dump_json())
    result = catalog.read_catalog()
    assert next(entry for entry in result.entries if entry.definition.code == "gitlab").compatible
    cache.write_text("corrupted")
    assert catalog.read_catalog().source == "bundled"


@pytest.mark.asyncio
async def test_catalog_http_denies_unprivileged_clients(client):
    assert (await client.get("/api/services/catalog")).status_code in {401, 403}
    assert (await client.post("/api/services/catalog/refresh")).status_code in {401, 403}
