"""Standard file-transport facade for the image service.

Downloading treats the remote reference as a generation prompt and writes the resulting image.
Uploading treats the local source as an image to describe or analyze and returns the text result.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from . import image_service
from core.i18n import default_language, t

_DEFAULT_MIME = "image/png"


class ImageFileTransport:
    """Adapt the image service to the standard ``FileTransport`` interface."""

    @staticmethod
    def _guess_mime(filename: str) -> str:
        mime, _ = mimetypes.guess_type(filename)
        return mime or _DEFAULT_MIME

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = 512 * 1024 * 1024) -> int:
        """Generate an image from prompt ``remote``, write it to ``dest``, and return its size."""
        prompt = (remote or "").strip()
        if not prompt:
            raise ValueError(t("image.prompt_required", default_language()))
        data, _mime = await image_service.generate_image_bytes(prompt)
        if len(data) > max_bytes:
            raise ValueError("Generated image exceeds the requested byte limit")
        dest.write_bytes(data)
        return len(data)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Describe local image ``src`` using optional instruction ``target``."""
        data = src.read_bytes()
        mime = self._guess_mime(filename or src.name)
        return await image_service.describe_image(data, mime, instruction=target)
