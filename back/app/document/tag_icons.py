"""Personal image icons, rendered by the client as images, never inline markup."""

import base64
import binascii
import json
import re
from io import BytesIO
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError

SVG_PREFIX = "data:image/svg+xml;base64,"
BUILTIN_ICONS = frozenset(cast(list[str], json.loads(Path(__file__).with_name("icon_catalog.json").read_text())))


def inherited_folder_icon(icon: str | None) -> str | None:
    """Copy only a Galaris folder color, independently of expansion state."""
    if icon is not None and icon.startswith(("folder:", "folder-open:")):
        return "folder:" + icon.split(":", 1)[1]
    return None


def validate_icon(value: str) -> str:
    legacy = re.fullmatch(r"/tag-icons/(?:openmoji|fluent)/([0-9A-F]+(?:-[0-9A-F]+)*)\.svg", value)
    if legacy:
        value = "emoji:" + "-".join(part for part in legacy[1].split("-") if part != "FE0F")
    if value in BUILTIN_ICONS:
        return value
    match = re.fullmatch(r"data:image/([\w.+-]+);base64,(.*)", value, re.DOTALL)
    if match is None:
        raise ValueError("Expected a local icon or an image")
    try:
        raw = base64.b64decode(match[2], validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid image encoding") from exc
    if match[1] != "svg+xml":
        return _raster_icon(raw)
    try:
        source = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Invalid SVG encoding") from exc
    if "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
        raise ValueError("SVG must contain no entities")
    if "<?xml-stylesheet" in source.lower():
        raise ValueError("SVG must not load external stylesheets")
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise ValueError("Invalid SVG") from exc
    namespace = "{http://www.w3.org/2000/svg}"
    if root.tag != f"{namespace}svg":
        raise ValueError("Expected an SVG root")
    forbidden = {"script", "foreignObject", "image", "animate", "animateMotion", "animateTransform", "set"}
    for node in root.iter():
        local_name = node.tag.removeprefix(namespace)
        if not node.tag.startswith(namespace) or local_name in forbidden:
            raise ValueError("SVG contains active or external content")
        # CSS can load external content. Presentation attributes cover normal icons.
        if local_name == "style":
            raise ValueError("Use SVG presentation attributes instead of stylesheets")
        for key, attribute in node.attrib.items():
            name = key.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or name in {"style", "base"}:
                raise ValueError("SVG contains active content")
            if name == "href" and not attribute.startswith("#"):
                raise ValueError("SVG references must stay inside the image")
            if re.search(r"url\s*\(", attribute, re.IGNORECASE) and not re.fullmatch(r"url\(#[\w.-]+\)", attribute):
                raise ValueError("SVG references must stay inside the image")
    return value


def _raster_icon(raw: bytes) -> str:
    """Detect the actual format; convert other Pillow formats for browser display."""
    try:
        with Image.open(BytesIO(raw)) as image:
            media_type = {
                "PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif",
                "WEBP": "image/webp", "AVIF": "image/avif", "BMP": "image/bmp",
                "ICO": "image/vnd.microsoft.icon",
            }.get(image.format or "")
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if media_type is None:
                output = BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                raw, media_type = output.getvalue(), "image/png"
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid or unsupported image") from exc
    return f"data:{media_type};base64," + base64.b64encode(raw).decode("ascii")
