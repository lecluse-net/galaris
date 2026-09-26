from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image

from core.preview import WebLinkPreview
from app.memory import service, document_links, document_export, document_image_import
from app.memory import document_attachment_service as attachments
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemoryGrantUpdate, DocumentLinkRequest


async def document(owner):
    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title="Report",
        node_kind="document", memory_type="working", media_type="text/html", payload=MemoryPayload(text="<p>Report</p>")))
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
    with pytest.raises(service.MemoryPermissionError):
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
async def test_link_card_owns_thumbnail_and_checks_write_before_fetch(agents, memory_storage, monkeypatch):
    owner, reader = agents
    item = await document(owner)
    await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    calls = []
    async def metadata(url, *, agent_id):
        assert agent_id == owner.id
        calls.append(url)
        return WebLinkPreview('A <video>', 'A & B', 'YouTube', output.getvalue())
    output = BytesIO(); Image.new("RGB", (20, 10), "blue").save(output, format="PNG")
    monkeypatch.setattr(document_links, "preview_web_link", metadata)
    with pytest.raises(service.MemoryPermissionError):
        await document_links.create_link_card(item.id, "https://youtu.be/dQw4w9WgXcQ", actor_agent_id=reader.id)
    assert not calls
    card = await document_links.create_link_card(item.id, "https://youtu.be/dQw4w9WgXcQ", actor_agent_id=owner.id)
    assert card.attachment is not None
    assert card.attachment.media_type == "image/jpeg"
    assert 'class="galaris-link-card"' in card.html
    assert "A &lt;video&gt;" in card.html and "A &amp; B" in card.html
    assert "iframe" not in card.html
    assert f"document://{item.id}/attachments/{card.attachment.id}" in card.html
    assert len(await attachments.list_document_attachments(item.id, actor_agent_id=reader.id)) == 1
    current, *_ = await service.get_item(item.id, agent_id=owner.id)
    assert current.revision == 1


@pytest.mark.parametrize("url", ["http://example.org", "https://user:secret@example.org", "javascript:alert(1)"])
def test_card_request_requires_https_without_credentials(url):
    with pytest.raises(ValueError):
        DocumentLinkRequest(url=url)


@pytest.mark.asyncio
async def test_pasted_image_is_an_owned_attachment_and_authorized_before_fetch(agents, memory_storage, monkeypatch):
    owner, reader = agents
    item = await document(owner)
    await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    output = BytesIO()
    Image.new("RGB", (24, 12), "blue").save(output, format="PNG")
    calls = []

    async def download(url):
        calls.append(url)
        return output.getvalue()

    monkeypatch.setattr(document_image_import, "read_web_image", download)
    with pytest.raises(service.MemoryPermissionError):
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
