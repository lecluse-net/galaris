import base64
from io import BytesIO
from unittest.mock import AsyncMock
from PIL import Image

import pytest

from core.preview import model3d, render_model_thumbnail, thumbnails


@pytest.mark.asyncio
async def test_model_transport_preserves_source_and_rejects_empty_or_oversized_input(tmp_path, monkeypatch):
    content = b"v -1 -1 0\nv 1 -1 0\nv 0 1 0\nf 1 2 3\n"
    source = tmp_path / "triangle.obj"
    source.write_bytes(content)
    rendered = BytesIO()
    Image.new("RGB", (320, 220), "blue").save(rendered, format="PNG")
    transport = AsyncMock(return_value=rendered.getvalue())
    monkeypatch.setattr(model3d, "post_buffered", transport)
    monkeypatch.setattr(model3d, "browser_executor_token", lambda: "synthetic-browser-token")
    monkeypatch.setattr(model3d, "MAX_MODEL_BYTES", len(content))

    thumbnail = await render_model_thumbnail(source, "triangle.obj", "model/obj")
    with Image.open(BytesIO(thumbnail)) as image:
        assert image.format == "WEBP" and image.size == (320, 220)
    request = transport.call_args
    assert request.args[0].endswith("/v1/render-model-thumbnail")
    assert request.kwargs["headers"]["x-galaris-browser-token"] == "synthetic-browser-token"
    payload = request.kwargs["json"]
    assert payload["name"] == "triangle.obj" and payload["media_type"] == "model/obj"
    assert base64.b64decode(payload["data"]) == content == source.read_bytes()
    assert 0 < request.kwargs["max_bytes"] <= thumbnails.MAX_BYTES
    assert 0 < request.kwargs["timeout"] <= 60

    transport.reset_mock()
    for invalid in (b"", content + b"\n"):
        source.write_bytes(invalid)
        with pytest.raises(ValueError):
            await render_model_thumbnail(source, "triangle.obj", "model/obj")
        assert source.read_bytes() == invalid
    transport.assert_not_awaited()
