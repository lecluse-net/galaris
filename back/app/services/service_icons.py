"""Portable, bounded service icons; never interpreted as application markup."""

import base64
import binascii
from io import BytesIO
from typing import Literal, Self
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ICON_BYTES = 131_072
_SVG_TAGS = frozenset({"svg", "g", "path", "circle", "rect", "ellipse", "line",
    "polyline", "polygon", "defs", "linearGradient", "radialGradient", "stop",
    "clipPath", "title", "desc"})
_SVG_ATTRIBUTES = frozenset({"viewBox", "width", "height", "fill", "fill-rule", "fill-opacity",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-opacity", "opacity",
    "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "x2", "y1", "y2", "points",
    "transform", "id", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "clip-rule", "version", "preserveAspectRatio", "role", "aria-label"})


class ServiceIcon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: Literal["image/svg+xml", "image/png", "image/gif"]
    encoding: Literal["text", "base64"]
    data: str = Field(min_length=1, max_length=MAX_ICON_BYTES * 2)

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        try:
            content = self.bytes()
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid service icon encoding") from exc
        if len(content) > MAX_ICON_BYTES:
            raise ValueError("Service icons must be at most 128 KiB")
        if self.media_type == "image/svg+xml":
            if b"<!" in content:
                raise ValueError("SVG declarations and entities are not supported")
            try:
                root = ElementTree.fromstring(content)
            except ElementTree.ParseError as exc:
                raise ValueError("Invalid SVG icon") from exc
            if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
                raise ValueError("Expected an SVG image")
            for node in root.iter():
                tag = node.tag.removeprefix("{http://www.w3.org/2000/svg}")
                if tag not in _SVG_TAGS or len(node.attrib) > 40:
                    raise ValueError("Unsupported SVG element")
                for name, value in node.attrib.items():
                    if name not in _SVG_ATTRIBUTES or any(part in value.lower() for part in ("url(", "javascript:", "data:")):
                        raise ValueError("Unsupported SVG attribute or external content")
        else:
            try:
                with Image.open(BytesIO(content)) as image:
                    expected = "PNG" if self.media_type == "image/png" else "GIF"
                    if image.format != expected or max(image.size) > 1024 or getattr(image, "n_frames", 1) > 100:
                        raise ValueError("Invalid icon format, dimensions or animation length")
                    image.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise ValueError("Invalid service image") from exc
        return self

    def bytes(self) -> bytes:
        if self.encoding == "text":
            if self.media_type != "image/svg+xml":
                raise ValueError("Raster icons require base64 encoding")
            return self.data.encode("utf-8")
        return base64.b64decode(self.data, validate=True)
