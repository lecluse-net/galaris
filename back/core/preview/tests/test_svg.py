import base64
from io import BytesIO
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from core.preview import render_svg_thumbnail, thumbnails
from core.preview import svg


@pytest.mark.asyncio
async def test_svg_transport_bounds_input_and_validates_transparent_png(tmp_path, monkeypatch):
    original = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"/>'
    source = tmp_path / "vector"
    source.write_bytes(original)
    png = thumbnails.encode(Image.new("RGBA", (40, 20), (255, 0, 0, 0)))
    transport = AsyncMock(return_value=png)
    monkeypatch.setattr(svg, "post_buffered", transport)
    result = await render_svg_thumbnail(source)
    assert transport.call_args.args[0].endswith('/v1/render-svg-thumbnail')
    assert base64.b64decode(transport.call_args.kwargs['json']['data']) == original
    assert transport.call_args.kwargs['max_bytes'] <= thumbnails.MAX_BYTES
    with Image.open(BytesIO(result)) as image:
        assert image.size == (40, 20)
        assert image.getpixel((0, 0))[3] == 0
    assert source.read_bytes() == original
    transport.return_value = b'not a PNG'
    with pytest.raises(ValueError, match='Invalid SVG thumbnail'):
        await render_svg_thumbnail(source)
    transport.reset_mock()
    for content in [b'', b'x' * (svg.SVG_MAX_BYTES + 1)]:
        source.write_bytes(content)
        with pytest.raises(ValueError, match='preview limit'):
            await render_svg_thumbnail(source)
    transport.assert_not_awaited()
