"""The reference drawing uses the normal binary-document revision lifecycle."""

import base64
from io import BytesIO
import json

from PIL import Image
import pytest

from app.document import (
    DocumentFormatRegistry, DocumentPayload, DocumentRevisionRegion, DocumentUpdate,
    FormatExample, qualify_document_format, register_document_format,
)
from app.document import document_service, formats, mcp, resource_service
from app.file_share import ResourceContext, prepared_resource, resource_read
from app.services import McpToolContext
from plugins.sample.drawing import definition


@pytest.mark.asyncio
async def test_sample_drawing_uses_immutable_document_revisions(client, memory_storage, monkeypatch):
    monkeypatch.setattr(formats, "registry", DocumentFormatRegistry())
    monkeypatch.setattr(formats, "_native_registered", False)
    monkeypatch.setattr(formats, "_format_availability", {})
    drawing = definition()
    available = True
    register_document_format(drawing, available=lambda: available)
    subject = FormatExample("blank-canvas", drawing.initial_binary, "")
    assert all(check.status == "passed" for check in qualify_document_format(
        drawing, (subject,), invalid_contents=(b"invalid PNG", drawing.initial_binary[:64]),
    ))
    credentials = {"email": "synthetic-drawing-owner@example.com", "password": "Synthetic-drawing-password-123"}
    registered = await client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/auth/login-json", json=credentials)
    auth = {"Authorization": "Bearer " + login.json()["access_token"]}
    headers = {**auth, "X-Editorial-Profile-Version": "1"}
    created = await client.post("/api/documents", headers=headers, json={
        "owner_kind": "user", "owner_id": registered.json()["id"],
        "title": "Synthetic Drawing Sample", "document_format": drawing.code,
    })
    assert created.status_code == 201, created.text
    path = f"/api/documents/{created.json()['id']}"
    source = await client.get(f"{path}/source", headers=headers)
    assert source.status_code == 200 and source.headers["content-type"] == "image/png"
    assert source.content == drawing.initial_binary

    pixels = BytesIO()
    with Image.new("RGB", (32, 24), "#087ff5") as image:
        image.save(pixels, format="PNG")
    update = {"expected_revision": 1, "payload": {"base64": base64.b64encode(pixels.getvalue()).decode()}}
    older_client = await client.patch(path, headers=auth, json=update)
    assert older_client.status_code == 409 and "Editorial HTML profile" in older_client.text
    saved = await client.patch(path, headers=headers, json=update)
    assert saved.status_code == 200 and saved.json()["revision"] == 2, saved.text
    assert (await client.get(f"{path}/source", headers=headers)).content == pixels.getvalue()
    assert (await client.patch(path, headers=headers, json=update)).status_code == 409

    available = False
    assert drawing.code not in formats.document_format_codes()
    assert (await client.get(f"{path}/source", headers=headers)).content == pixels.getvalue()
    assert (await client.get(f"{path}/source?revision=1", headers=headers)).content == drawing.initial_binary


@pytest.mark.asyncio
async def test_agent_can_read_and_compare_only_authorized_drawing_revisions(agents, memory_storage, monkeypatch):
    monkeypatch.setattr(formats, "registry", DocumentFormatRegistry())
    monkeypatch.setattr(formats, "_native_registered", False)
    monkeypatch.setattr(formats, "_format_availability", {})
    drawing = definition()
    register_document_format(drawing)
    owner, peer = agents
    owner_ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    peer_ctx = McpToolContext(agent_id=peer.id, runtime="internal")
    item = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic canvas",
        content="", task_id=None, document_format=drawing.code)
    identity = item.id
    uri = f"document://{identity}"
    output = BytesIO()
    with Image.open(BytesIO(drawing.initial_binary)) as image:
        image.putpixel((5, 4), (12, 34, 56, 255))
        image.putpixel((15, 14), (76, 54, 32, 255))
        image.save(output, format="PNG")
    updated = await resource_service.update_item(identity, DocumentUpdate(expected_revision=1,
        payload=DocumentPayload(base64=base64.b64encode(output.getvalue()).decode())), actor_agent_id=owner.id)
    assert updated.revision == 2

    history = json.loads(await mcp.document_revision_list(owner_ctx, uri))
    assert [entry["revision"] for entry in history["items"]] == [2, 1]
    resource_context = ResourceContext(agent_id=owner.id, runtime="internal")
    early = await resource_read(resource_context, uri, revision=1)
    assert early.revision == 1 and base64.b64decode(early.content) == drawing.initial_binary
    async with prepared_resource(resource_context, uri, revision=1) as (prepared, directory):
        assert prepared.pages and prepared.image_path(prepared.pages[0], directory) is not None
        from hashlib import sha256
        assert prepared.sha256 == sha256(drawing.initial_binary).hexdigest()
    result = json.loads(await mcp.document_revision_compare(owner_ctx, uri, 1, 2))
    assert result["details"]["changed_pixels"] == 2
    assert result["details"]["changed_bounds"] == {"x": 5, "y": 4, "width": 11, "height": 11}
    cropped = json.loads(await mcp.document_revision_compare(owner_ctx, uri, 1, 2,
        region=DocumentRevisionRegion(x=0, y=0, width=10, height=10)))
    assert cropped["details"]["changed_pixels"] == 1
    assert cropped["details"]["changed_bounds"] == {"x": 5, "y": 4, "width": 1, "height": 1}

    with pytest.raises(resource_service.DocumentPermissionError):
        await mcp.document_revision_list(peer_ctx, uri)
    with pytest.raises(resource_service.DocumentPermissionError):
        await mcp.document_revision_compare(peer_ctx, uri, 1, 2)
    with pytest.raises(resource_service.DocumentPermissionError):
        await resource_read(ResourceContext(agent_id=peer.id, runtime="internal"), uri, revision=1)
