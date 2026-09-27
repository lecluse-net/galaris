"""Web previews fail explicitly until their transport is available."""

import pytest

from core.preview import web


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["image", "page"])
async def test_web_import_recovers_when_its_transport_becomes_available(monkeypatch, operation):
    monkeypatch.setattr(web, "_image_provider", None)
    monkeypatch.setattr(web, "_provider", None)
    url = "https://example.org/preview"
    received = []

    async def image_provider(reference):
        received.append(reference)
        return b"image bytes"

    async def page_provider(reference, *, agent_id):
        received.append((reference, agent_id))
        return web.WebLinkPreview("Synthetic page", "Description", "Example")

    async def read():
        if operation == "image":
            return await web.read_web_image(url)
        return await web.preview_web_link(url, agent_id=7)

    with pytest.raises(ValueError, match="unavailable"):
        await read()
    assert received == []

    web.register_web_image_provider(image_provider)
    web.register_web_preview_provider(page_provider)
    result = await read()
    if operation == "image":
        assert result == b"image bytes"
        assert received == [url]
    else:
        assert result == web.WebLinkPreview("Synthetic page", "Description", "Example")
        assert received == [(url, 7)]
