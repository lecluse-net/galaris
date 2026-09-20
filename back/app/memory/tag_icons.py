"""Bounded SVG images, rendered by the client as images, never inline markup."""

import base64
import binascii
import json
import re
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

MAX_ICON_BYTES = 64_000
MAX_ICON_URI_LENGTH = 4 * ((MAX_ICON_BYTES + 2) // 3) + 26
SVG_PREFIX = "data:image/svg+xml;base64,"
BUILTIN_ICONS = frozenset(cast(list[str], json.loads(Path(__file__).with_name("icon_catalog.json").read_text())))


def validate_icon(value: str) -> str:
    legacy = re.fullmatch(r"/tag-icons/(?:openmoji|fluent)/([0-9A-F]+(?:-[0-9A-F]+)*)\.svg", value)
    if legacy:
        value = "emoji:" + "-".join(part for part in legacy[1].split("-") if part != "FE0F")
    if value in BUILTIN_ICONS:
        return value
    if not value.startswith(SVG_PREFIX):
        raise ValueError("Expected a local emoji or an SVG image")
    try:
        raw = base64.b64decode(value[len(SVG_PREFIX):], validate=True)
        source = raw.decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError("Invalid SVG encoding") from exc
    if len(raw) > MAX_ICON_BYTES or "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
        raise ValueError("SVG must be at most 64 KiB and contain no entities")
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
