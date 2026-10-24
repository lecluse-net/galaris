from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image

from core.preview import WebLinkPreview, thumbnails
from app.document import resource_service as service
from app.document import document_links, document_export, document_image_import
from app.document import document_attachment_service as attachments
from app.document.schemas import DocumentItemCreate, DocumentPayload, DocumentGrantUpdate, DocumentLinkRequest


async def document(owner):
    item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner.id, title="Report",
        node_kind="document",  media_type="text/html", payload=DocumentPayload(text="<p>Report</p>")))
    return item


@pytest.mark.asyncio
async def test_html_attachment_bundle_is_portable_and_keeps_revision(agents, memory_storage):
    owner, other = agents
    item = await document(owner)
    source = b'<!doctype html><html><script>document.body.append("3D")</script></html>'
    attachment = await attachments.add_document_attachment_bytes(item.id, actor_agent_id=owner.id,
        name="scene #1.html", media_type="text/html", content=source)
    uri = f"document://{item.id}/attachments/{attachment.id}"
    html = f'<!doctype html><html><body><a href="{uri}">Scene</a></body></html>'
    with pytest.raises(service.DocumentPermissionError):
        await document_export.export_document_bundle(item.id, html, actor_agent_id=other.id)
    # Removal preserves links already authored in a document or draft.
    await attachments.delete_document_attachment(item.id, attachment.id, actor_agent_id=owner.id)
    raw = await document_export.export_document_bundle(item.id, html, actor_agent_id=owner.id)
    with ZipFile(BytesIO(raw)) as archive:
        assert len(archive.namelist()) == 2
        name = next(value for value in archive.namelist() if value.startswith("attachments/"))
        assert archive.read(name) == source
        page = archive.read("document.html").decode()
        assert uri not in page
        assert "scene%20%231.html" in page
    current, *_ = await service.get_item(item.id, agent_id=owner.id)
    assert current.revision == 1


@pytest.mark.asyncio
async def test_link_card_keeps_thumbnail_in_shared_cache_and_checks_write_before_fetch(agents, memory_storage, monkeypatch, tmp_path):
    from core.settings import settings
    monkeypatch.setattr(type(settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    owner, reader = agents
    item = await document(owner)
    await service.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    calls = []
    async def metadata(url, *, agent_id):
        assert agent_id == owner.id
        calls.append(url)
        return WebLinkPreview('A <video>', 'A & B', 'YouTube', output.getvalue())
    output = BytesIO(); Image.new("RGB", (20, 10), "blue").save(output, format="PNG")
    monkeypatch.setattr(document_links, "preview_web_link", metadata)
    with pytest.raises(service.DocumentPermissionError):
        await document_links.create_link_card(item.id, "https://youtu.be/dQw4w9WgXcQ", actor_agent_id=reader.id)
    assert not calls
    card = await document_links.create_link_card(item.id, "https://youtu.be/dQw4w9WgXcQ", actor_agent_id=owner.id)
    assert card.attachment is None
    assert "galaris-web-card" in card.html
    assert "A &lt;video&gt;" in card.html and "A &amp; B" in card.html
    assert "iframe" not in card.html
    assert "<img" not in card.html and "/attachments/" not in card.html
    assert await attachments.list_document_attachments(item.id, actor_agent_id=reader.id) == []
    current, *_ = await service.get_item(item.id, agent_id=owner.id)
    assert current.revision == 1
    url = "https://youtu.be/dQw4w9WgXcQ"
    cached = await document_links.link_thumbnail(url, actor=reader.id)
    assert len(calls) == 1
    with Image.open(BytesIO(cached)) as image:
        assert image.format == "WEBP" and image.size == (20, 10)
    thumbnails.delete(url)
    assert await document_links.link_thumbnail(url, actor=owner.id) == cached
    assert len(calls) == 2
    assert await attachments.list_document_attachments(item.id, actor_agent_id=owner.id) == []


@pytest.mark.parametrize("url", ["http://example.org", "https://user:secret@example.org", "javascript:alert(1)"])
def test_card_request_requires_https_without_credentials(url):
    with pytest.raises(ValueError):
        DocumentLinkRequest(url=url)


@pytest.mark.asyncio
async def test_link_thumbnail_http_checks_auth_and_agent_scope_without_attachments(client, monkeypatch, tmp_path):
    from core.settings import settings
    from sqlalchemy import select
    from core.authorize.models import Assignment, Privilege, Role
    from core.user import UserModel
    from core.user.auth_service import create_access_token
    from core.database import get_db_session
    monkeypatch.setattr(type(settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    calls = []
    output = BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="PNG")

    async def preview(url, *, agent_id):
        calls.append((url, agent_id))
        return WebLinkPreview("Synthetic page", "", "Example", output.getvalue())

    monkeypatch.setattr(document_links, "preview_web_link", preview)
    path = "/api/documents/link-card/thumbnail"
    body = {"url": "https://example.org/synthetic-page"}
    assert (await client.post(path, json=body)).status_code == 401
    assert not calls
    credentials = {"email": "preview-owner@example.com", "password": "Synthetic-preview-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    choices = (await client.get("/api/agents/selection", headers=headers)).json()
    agent_id = choices[0]["id"]
    async with get_db_session() as db:
        user = await db.scalar(select(UserModel).where(UserModel.email == credentials["email"]))
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "DOCUMENT_ACCESS"))
        role = Role(code="synthetic-preview-reader", privileges=[privilege])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
        await db.commit()
        headers = {"Authorization": "Bearer " + create_access_token({
            "sub": user.email, "user_id": user.id, "role_id": role.id,
        })}
    invalid = await client.post(path, json={"url": "http://example.org"}, headers=headers)
    assert invalid.status_code == 422 and not calls
    denied = await client.post(path, json=body, params={"agent_id": 2147483647}, headers=headers)
    assert denied.status_code in {403, 404} and not calls
    response = await client.post(path, json=body, params={"agent_id": agent_id}, headers=headers)
    assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
    assert calls == [(body["url"], agent_id)]
    assert (await client.post(path, json=body, headers=headers)).content == response.content
    assert len(calls) == 1
    thumbnails.delete(body["url"])
    async def no_thumbnail(*args, **kwargs):
        return WebLinkPreview("Synthetic page", "", "Example")
    monkeypatch.setattr(document_links, "preview_web_link", no_thumbnail)
    assert (await client.post(path, json=body, headers=headers)).status_code == 204


@pytest.mark.asyncio
async def test_pasted_image_is_an_owned_attachment_and_authorized_before_fetch(agents, memory_storage, monkeypatch):
    owner, reader = agents
    item = await document(owner)
    await service.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    output = BytesIO()
    Image.new("RGB", (24, 12), "blue").save(output, format="PNG")
    calls = []

    async def download(url):
        calls.append(url)
        return output.getvalue()

    monkeypatch.setattr(document_image_import, "read_web_image", download)
    with pytest.raises(service.DocumentPermissionError):
        await document_image_import.import_document_image(item.id, "https://example.org/photo", actor=reader.id)
    assert calls == []
    result = await document_image_import.import_document_image(item.id, "https://example.org/photo", actor=owner.id)
    assert result.media_type == "image/png"
    assert result.size_bytes == len(output.getvalue())
    _, stored = await attachments.read_document_attachment(item.id, result.id, actor_agent_id=reader.id)
    assert stored == output.getvalue()
    assert [entry.id for entry in await attachments.list_document_attachments(item.id, actor_agent_id=reader.id)] == [result.id]
    current, *_ = await service.get_item(item.id, agent_id=owner.id)
    assert current.revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"<html>Login required</html>", b'<svg xmlns="http://www.w3.org/2000/svg"/>', b"invalid"])
async def test_pasted_non_image_creates_no_attachment(agents, memory_storage, monkeypatch, content):
    owner, _ = agents
    item = await document(owner)

    async def download(url):
        return content

    monkeypatch.setattr(document_image_import, "read_web_image", download)
    with pytest.raises(ValueError, match="not a raster image"):
        await document_image_import.import_document_image(item.id, "https://example.org/photo", actor=owner.id)
    assert await attachments.list_document_attachments(item.id, actor_agent_id=owner.id) == []


@pytest.mark.asyncio
async def test_generated_native_image_can_be_copied_and_embedded_in_a_document(
    agents, memory_storage, monkeypatch, tmp_path,
):
    from app.file_share import ResourceContext, resource_copy, resource_service
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.image import mcp as image_mcp
    from app.tools.mcp_loader import McpToolContext
    from app.document.schemas import DocumentUpdate

    owner, reader = agents
    item = await document(owner)
    await service.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    output = BytesIO()
    Image.new("RGB", (24, 12), "blue").save(output, format="PNG")
    source = output.getvalue()
    console = TemporaryFileTransport(tmp_path / "console")

    async def resolve(ctx):
        return console

    async def generate(*args, **kwargs):
        return source, "image/png"

    monkeypatch.setattr(resource_service, "_console_transport", resolve)
    monkeypatch.setattr(image_mcp.image_service, "generate_image_bytes", generate)
    result = await image_mcp.generate_image(
        McpToolContext(agent_id=owner.id, runtime="internal", resources={"console": object()}),
        "A synthetic illustration", destination="console://gallery/scene.jpg",
    )
    assert "console://gallery/scene.png" in result
    ctx = ResourceContext(agent_id=owner.id, runtime="internal", console_resource=object())
    copied = await resource_copy(ctx, "console://gallery/scene.png", f"document://{item.id}/attachments/")
    attachment = (await attachments.list_document_attachments(item.id, actor_agent_id=reader.id))[0]
    assert attachment.name == "scene.png"
    assert attachment.media_type == "image/png"
    _, stored = await attachments.read_document_attachment(item.id, attachment.id, actor_agent_id=reader.id)
    assert stored == source
    await service.update_item(item.id, DocumentUpdate(
        expected_revision=item.revision, expected_lock_version=item.lock_version,
        payload=DocumentPayload(text=f'<p><img src="{copied.uri}" alt="Synthetic illustration"></p>'),
    ), actor_agent_id=owner.id)
    current, content, *_ = await service.get_item(item.id, agent_id=reader.id)
    assert copied.uri.encode() in content
    assert current.revision == 2
    with pytest.raises(service.DocumentPermissionError):
        await resource_copy(ResourceContext(agent_id=reader.id, runtime="internal", console_resource=object()),
                            "console://gallery/scene.png", f"document://{item.id}/attachments/")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["bytes", "upload", "copy", "create"])
async def test_animated_svg_attachment_preserves_source_and_document_access(
    agents, memory_storage, monkeypatch, tmp_path, method,
):
    from fastapi import UploadFile
    from starlette.datastructures import Headers

    from app.file_share import ResourceContext, resource_service
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.document.schemas import DocumentUpdate

    owner, reader = agents
    item = await document(owner)
    await service.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    source = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        '<title>Synthetic animated drawing</title>'
        '<desc>' + 'Synthetic description. ' * 1600 + '</desc>'
        '<circle cx="10" cy="10" r="8"><animate attributeName="opacity" '
        'values="0.5;1;0.5" dur="3s" repeatCount="indefinite"/></circle></svg>'
    ).encode()
    destination = f"document://{item.id}/attachments/"
    ctx = ResourceContext(agent_id=owner.id, runtime="internal", console_resource=object())
    if method == "bytes":
        await attachments.add_document_attachment_bytes(item.id, actor_agent_id=owner.id,
            name="drawing.svg", media_type="image/svg+xml", content=source)
    elif method == "upload":
        await attachments.add_document_attachment(item.id, actor_agent_id=owner.id,
            upload=UploadFile(filename="drawing.svg", file=BytesIO(source),
                headers=Headers({"content-type": "image/svg+xml; charset=utf-8"})))
    elif method == "create":
        await resource_service.resource_create(ctx, destination, source, name="drawing.svg")
    else:
        console = TemporaryFileTransport(tmp_path / "console")
        console.resolve_path("drawing.svg").write_bytes(source)

        async def resolve(_ctx):
            return console

        monkeypatch.setattr(resource_service, "_console_transport", resolve)
        await resource_service.resource_copy(ctx, "console://drawing.svg", destination)

    attachment, = await attachments.list_document_attachments(item.id, actor_agent_id=reader.id)
    assert (attachment.name, attachment.media_type, attachment.size_bytes) == (
        "drawing.svg", "image/svg+xml", len(source),
    )
    _, stored = await attachments.read_document_attachment(item.id, attachment.id, actor_agent_id=reader.id)
    assert stored == source
    current, *_ = await service.get_item(item.id, agent_id=reader.id)
    assert current.revision == 1
    uri = f"{destination}{attachment.id}"
    await service.update_item(item.id, DocumentUpdate(
        expected_revision=item.revision, expected_lock_version=item.lock_version,
        payload=DocumentPayload(text=f'<p>Report</p><p><img src="{uri}" alt="Animated drawing"></p>'),
    ), actor_agent_id=owner.id)
    current, content, access, *_ = await service.get_item(item.id, agent_id=reader.id)
    assert current.revision == 2 and uri.encode() in content
    assert access.can_read and not access.can_write


@pytest.mark.asyncio
@pytest.mark.parametrize("name,mime,source", [
    ("drawing.svg", "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"><script>window.parent.svgRan=true</script><circle r="5"/></svg>'),
    ("module.js", "application/javascript", b'window.sourceExecuted = true;\nexport const answer = 42;\n'),
    ("script.sh", "application/x-sh", b'#!/bin/sh\nprintf "synthetic source\\n"\n'),
    ("script.py", "application/octet-stream", b'#!/usr/bin/env python3\nprint("synthetic source")\n'),
    ("component.vue", "text/html", b'<script>window.sourceExecuted = true</script><template><b>Source</b></template>'),
    ("module.ts", "video/mp2t", b'export const answer: number = 42;\n'),
    ("source", "text/javascript", b'window.sourceExecuted = true;\n'),
    ("Dockerfile", "text/html", b'FROM alpine\nRUN echo "synthetic source"\n'),
])
async def test_attachment_http_upload_round_trips_with_inert_source_reads(client, name, mime, source):
    credentials = {"email": "svg-owner@example.com", "password": "Synthetic-svg-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {
        "Authorization": "Bearer " + login.json()["access_token"],
        "X-Editorial-Profile-Version": "1",
    }
    choices = (await client.get("/api/agents/selection", headers=headers)).json()
    agent_id = choices[0]["id"]
    created = await client.post("/api/documents", headers=headers, json={
        "title": "Synthetic vector document", "owner_kind": "agent",
        "owner_id": agent_id, "actor_agent_id": agent_id,
    })
    assert created.status_code == 201, created.text
    path = f"/api/documents/{created.json()['id']}/attachments"
    uploaded = await client.post(path, params={"actor_agent_id": agent_id}, headers=headers,
        files={"file": (name, source, mime)})
    assert uploaded.status_code == 201, uploaded.text
    response = await client.get(f"{path}/{uploaded.json()['id']}", params={"agent_id": agent_id}, headers=headers)
    assert response.status_code == 200 and response.content == source
    assert response.headers["content-type"] == ("image/svg+xml" if name.endswith(".svg") else "text/plain; charset=utf-8")
    if not name.endswith(".svg"):
        assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    policy = response.headers["content-security-policy"]
    assert "sandbox" in policy.split("; ") and "default-src 'none'" in policy
    assert "allow-scripts" not in policy and "allow-same-origin" not in policy
    client.cookies.clear()
    assert (await client.get(f"{path}/{uploaded.json()['id']}", params={"agent_id": agent_id})).status_code == 401
