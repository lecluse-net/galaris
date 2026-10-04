"""Bounded SVG rasterization through the existing isolated Chromium renderer."""

import asyncio
import base64
from io import BytesIO
from pathlib import Path

from core.secrets import browser_executor_token
from core.settings import settings
from core.util import post_buffered

from . import thumbnails

SVG_MAX_BYTES = 5 * 1_048_576


async def render_svg_thumbnail(path: Path) -> bytes:
    def read() -> bytes:
        with path.open("rb") as source:
            content = source.read(SVG_MAX_BYTES + 1)
        if not content or len(content) > SVG_MAX_BYTES:
            raise ValueError("SVG is empty or exceeds the preview limit")
        return content

    content = await asyncio.to_thread(read)
    result = await post_buffered(
        f"{settings.BROWSER_EXECUTOR_URL}/v1/render-svg-thumbnail",
        headers={"x-galaris-browser-token": browser_executor_token()},
        json={"data": base64.b64encode(content).decode("ascii")},
        max_bytes=thumbnails.MAX_BYTES, timeout=40,
    )
    png = await asyncio.to_thread(thumbnails.from_image, BytesIO(result))
    if png is None:
        raise ValueError("Invalid SVG thumbnail response")
    return png
