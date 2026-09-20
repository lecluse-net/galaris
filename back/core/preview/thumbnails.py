"""Shared thumbnail cache keyed by canonical resource URI, independent of its UI.

Callers must authorize the resource before reading this internal cache. All producers
use the same bounded PNG representation; page metadata shares the resource key.
"""

from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageOps

from core.settings import settings

MAX_SIZE = (520, 320)
MAX_BYTES = 5 * 1_048_576


def cache_path(reference: str) -> Path:
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
    return Path(settings.GALARIS_THUMBNAIL_ROOT) / f"{digest}.png"


def read(path: Path, max_bytes: int = MAX_BYTES) -> bytes | None:
    try:
        with path.open("rb") as source:
            content = source.read(max_bytes + 1)
        return content if 0 < len(content) <= max_bytes else None
    except OSError:
        return None


def write(path: Path, content: bytes) -> None:
    """Publish complete bytes atomically, including concurrent generation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".thumbnail-", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o644)
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def encode(image: Image.Image) -> bytes:
    """Fit W×H without padding, cropping, upscaling or flattening alpha."""
    normalized = ImageOps.exif_transpose(image)
    normalized.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
    transparent = "A" in normalized.getbands() or "transparency" in normalized.info
    normalized = normalized.convert("RGBA" if transparent else "RGB")
    normalized.info.clear()
    output = BytesIO()
    normalized.save(output, format="PNG", optimize=True)
    return output.getvalue()


def from_image(source: Path | BytesIO) -> bytes | None:
    try:
        with Image.open(source) as image:
            image.load()
            content = encode(image)
        return content if len(content) <= MAX_BYTES else None
    except Exception:
        return None


def delete(reference: str) -> None:
    path = cache_path(reference)
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)
