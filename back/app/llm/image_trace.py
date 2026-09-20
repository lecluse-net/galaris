"""Compact images before persisting LLM traces."""

from __future__ import annotations

import base64
import re
from io import BytesIO
from typing import Any

from loguru import logger
from PIL import Image, ImageOps

from core.util import as_dict, as_list


_PREVIEW_MAX_SIZE = (320, 240)
_PREVIEW_JPEG_QUALITY = 70
_DATA_IMAGE_PREFIX = "data:image/"
_DATA_IMAGE_URL = re.compile(
    r"data:image/[A-Za-z0-9.+-]+"
    r"(?:;[A-Za-z0-9.+_-]+=[A-Za-z0-9.+_-]+)*"
    r";base64,[A-Za-z0-9+/=_-]+",
    re.IGNORECASE,
)


def _jpeg_preview_data_url(value: str) -> str:
    header, separator, encoded = value.partition(",")
    if (
        not separator
        or not header.casefold().startswith(_DATA_IMAGE_PREFIX)
        or ";base64" not in header.casefold()
    ):
        return ""

    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail(_PREVIEW_MAX_SIZE, Image.Resampling.LANCZOS)

            has_alpha = "A" in image.getbands() or (
                image.mode == "P" and "transparency" in image.info
            )
            if has_alpha:
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                image = rgb
            elif image.mode != "RGB":
                image = image.convert("RGB")

            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=_PREVIEW_JPEG_QUALITY,
                optimize=True,
            )
    except Exception as exc:
        logger.warning("Unable to create stored LLM image preview: {}", exc)
        return ""

    preview = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{preview}"


def _compact_string(value: str) -> str:
    """Replace every embedded image data URL without altering surrounding text."""
    compacted, replacements = _DATA_IMAGE_URL.subn(
        lambda match: _jpeg_preview_data_url(match.group(0)),
        value,
    )
    if replacements:
        return compacted
    if value.casefold().startswith(_DATA_IMAGE_PREFIX):
        # A malformed full data URL must never fall through into the stored trace.
        return _jpeg_preview_data_url(value)
    return value


def compact_trace_images(value: Any) -> Any:
    """Return a detached value with all image data URLs replaced by JPEG previews."""
    if isinstance(value, str):
        return _compact_string(value)
    if isinstance(value, list):
        return [compact_trace_images(item) for item in as_list(value)]
    if isinstance(value, dict):
        return {
            key: compact_trace_images(item)
            for key, item in as_dict(value).items()
        }
    return value


def compact_request_images(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a detached trace containing small JPEG previews instead of full images."""
    return [
        {
            str(key): compact_trace_images(value)
            for key, value in message.items()
        }
        for message in messages
    ]
