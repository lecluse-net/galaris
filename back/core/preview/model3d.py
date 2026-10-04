"""Bounded offline 3D captures through the isolated Chromium renderer."""

import asyncio
import base64
from pathlib import Path

from core.settings import settings
from core.secrets import browser_executor_token
from core.util import post_buffered

MAX_MODEL_BYTES = 32_000_000
MODEL_EXTENSIONS = {".glb", ".gltf", ".obj", ".stl", ".ply"}
MODEL_TYPES = {
    "model/gltf-binary", "model/gltf+json", "model/obj", "application/x-wavefront-obj",
    "model/stl", "application/sla", "model/x.stl", "application/x-stl",
    "model/ply", "application/ply", "application/x-ply",
}


def supports_model(media_type: str, name: str) -> bool:
    return media_type in MODEL_TYPES or Path(name).suffix.casefold() in MODEL_EXTENSIONS


async def render_model_thumbnail(path: Path, name: str, media_type: str) -> bytes:
    def read() -> bytes:
        with path.open("rb") as source:
            content = source.read(MAX_MODEL_BYTES + 1)
        if not content or len(content) > MAX_MODEL_BYTES:
            raise ValueError("Model is empty or exceeds the preview limit")
        return content

    content = await asyncio.to_thread(read)
    return await post_buffered(
        f"{settings.BROWSER_EXECUTOR_URL}/v1/render-model-thumbnail",
        headers={"x-galaris-browser-token": browser_executor_token()},
        json={"name": name, "media_type": media_type, "data": base64.b64encode(content).decode("ascii")},
        max_bytes=5 * 1_048_576, timeout=40,
    )
