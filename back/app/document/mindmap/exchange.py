"""Bounded structural interchange for Freeplane, FreeMind, OPML and XMind."""

from io import BytesIO
import json
from pathlib import PurePosixPath
import re
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring
from pydantic import JsonValue, TypeAdapter

from . import MAX_DEPTH, MAX_NODES, MindMap, MindMapNode

MEDIA_TYPE = "application/vnd.galaris.mindmap+json"
IMPORT_TYPES = {
    "application/x-freemind": ".mm",
    "application/x-freeplane": ".mm",
    "application/x-opml+xml": ".opml",
    "text/x-opml": ".opml",
    "application/vnd.xmind.workbook": ".xmind",
    MEDIA_TYPE: ".mindmap",
}
IMPORT_EXTENSIONS = (".mindmap", ".mm", ".opml", ".xmind")
OPML_NOTE = "{https://galaris.org/ns/mindmap}_note"
JSON_VALUES = TypeAdapter(JsonValue)
MAX_XMIND_CONTENT = 16 * 1024 * 1024
INVALID_XML_CHARACTERS = re.compile(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")
XML_LITERAL_OR_NBSP = re.compile(
    rb"<!--.*?(?:-->|\Z)|<!\[CDATA\[.*?(?:\]\]>|\Z)|<\?.*?(?:\?>|\Z)|&nbsp;",
    re.DOTALL,
)


def _xml(content: bytes) -> Element:
    try:
        return fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError, DefusedXmlException, LookupError) as exc:
        raise ValueError("Invalid mind map XML") from exc


def _rich_text(element: Element | None) -> str:
    if element is None:
        return ""
    body = element.find(".//body")
    if body is None:
        body = element

    def parts(node: Element, depth: int = 0) -> list[str]:
        if depth > MAX_DEPTH:
            raise ValueError("Mind map note is too deeply nested")
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script", "style", "head"}:
            return []
        result = [node.text or ""]
        for child in node:
            result.extend(parts(child, depth + 1))
            result.append(child.tail or "")
        if tag in {"p", "div", "li", "br"}:
            result.append("\n")
        return result

    return "".join(parts(body)).strip()


class _ImportTree:
    def __init__(self) -> None:
        self.nodes: list[MindMapNode] = []
        self.ids: set[str] = set()

    def add(self, parent: str | None, depth: int, title: str, note: str = "", link: str = "", key: str = "") -> str:
        if len(self.nodes) >= MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("Mind map exceeds its node or depth limit")
        if not key or key in self.ids or len(key) > 80 or any(
            not (character.isascii() and (character.isalnum() or character in "_-")) for character in key
        ):
            key = uuid4().hex
        self.nodes.append(MindMapNode(id=key, parent=parent, title=title, note=note, link=link))
        self.ids.add(key)
        return key

    def freemind(self, element: Element, parent: str | None = None, depth: int = 0) -> None:
        title = element.get("TEXT", "") or _rich_text(element.find("richcontent[@TYPE='NODE']"))
        note = _rich_text(element.find("richcontent[@TYPE='NOTE']"))
        details = _rich_text(element.find("richcontent[@TYPE='DETAILS']"))
        key = self.add(parent, depth, title, "\n\n".join(filter(None, (details, note))),
                       element.get("LINK", ""), element.get("ID", ""))
        for child in element.findall("node"):
            self.freemind(child, key, depth + 1)

    def outline(self, element: Element, parent: str | None, depth: int) -> None:
        key = self.add(parent, depth, element.get("text", ""),
                       element.get(OPML_NOTE, element.get("_note", "")),
                       element.get("htmlUrl", element.get("url", element.get("xmlUrl", ""))))
        for child in element.findall("outline"):
            self.outline(child, key, depth + 1)

    def xmind(self, topic: JsonValue, parent: str | None, depth: int) -> None:
        if not isinstance(topic, dict):
            raise ValueError("Invalid XMind topic")
        notes = topic.get("notes")
        plain = notes.get("plain") if isinstance(notes, dict) else None
        key = self.add(parent, depth, _string(topic.get("title")),
                       _string(plain.get("content")) if isinstance(plain, dict) else "",
                       _string(topic.get("href")), _string(topic.get("id")))
        children = topic.get("children")
        if isinstance(children, dict):
            for group in ("attached", "detached"):
                items = children.get(group)
                if isinstance(items, list):
                    for child in items:
                        self.xmind(child, key, depth + 1)


def _string(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _portable_link(link: str) -> str:
    # Desktop clients may attach execution semantics to imported link schemes.
    return link if link == link.strip() and not any(ord(char) < 32 for char in link) and (
        link.lower().startswith(("https://", "http://", "mailto:")) or link.startswith("#")
    ) else ""


def _xmind_sheets(content: bytes) -> list[JsonValue]:
    if len(content) > MAX_XMIND_CONTENT:
        raise ValueError("XMind archive exceeds its size limit")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = [entry for entry in archive.infolist() if entry.filename == "content.json"]
            if len(entries) != 1 or entries[0].file_size > MAX_XMIND_CONTENT:
                raise ValueError("XMind requires one bounded content.json entry")
            with archive.open(entries[0]) as source:
                data = source.read(MAX_XMIND_CONTENT + 1)
        if len(data) > MAX_XMIND_CONTENT:
            raise ValueError("XMind content exceeds its size limit")
        sheets = JSON_VALUES.validate_json(data)
    except (BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError("Invalid or unsupported XMind archive") from exc
    if not isinstance(sheets, list) or not sheets or any(
        not isinstance(sheet, dict) or "rootTopic" not in sheet for sheet in sheets
    ):
        raise ValueError("XMind archive has no map sheets")
    return sheets


def import_source(name: str, media_type: str, content: bytes) -> str:
    extension = PurePosixPath(name).suffix.lower()
    if extension not in IMPORT_EXTENSIONS:
        extension = IMPORT_TYPES.get(media_type.split(";", 1)[0].strip().lower(), ".mindmap")
    if extension == ".mindmap":
        return MindMap.model_validate_json(content.decode("utf-8-sig")).source()

    tree = _ImportTree()
    if extension == ".xmind":
        sheets = _xmind_sheets(content)
        parent = tree.add(None, 0, PurePosixPath(name).stem) if len(sheets) > 1 else None
        for sheet in sheets:
            assert isinstance(sheet, dict)
            tree.xmind(sheet["rootTopic"], parent, int(parent is not None))
    else:
        if extension == ".mm" and b"&nbsp;" in content and b"\x00" not in content:
            # Older Freeplane exports use the HTML spelling of a non-breaking space in XML.
            content = XML_LITERAL_OR_NBSP.sub(lambda match: b"&#160;" if match[0] == b"&nbsp;" else match[0], content)
        root = _xml(content)
        if extension == ".mm":
            nodes = root.findall("node")
            if root.tag != "map" or len(nodes) != 1:
                raise ValueError("Freeplane/FreeMind requires a map with one root node")
            tree.freemind(nodes[0])
        else:
            outlines = root.findall("./body/outline")
            if root.tag != "opml" or not outlines:
                raise ValueError("OPML requires an outline")
            parent = tree.add(None, 0, root.findtext("./head/title") or PurePosixPath(name).stem) if len(outlines) > 1 else None
            for outline in outlines:
                tree.outline(outline, parent, int(parent is not None))
    return MindMap(version=1, nodes=tree.nodes).source()


def export_source(content: str, target: str) -> tuple[bytes, str, str]:
    mindmap = MindMap.model_validate_json(content)
    children = mindmap.children()

    if target == "xmind":
        def topic(node: MindMapNode) -> dict[str, JsonValue]:
            result: dict[str, JsonValue] = {"id": node.id, "class": "topic", "title": node.title}
            if node.note:
                result["notes"] = {"plain": {"content": node.note}}
            if link := _portable_link(node.link):
                result["href"] = link
            if branches := children.get(node.id):
                result["children"] = {"attached": [topic(child) for child in branches]}
            return result

        output = BytesIO()
        data = json.dumps([{
            "id": uuid4().hex, "class": "sheet", "title": mindmap.root.title, "rootTopic": topic(mindmap.root),
        }], ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_XMIND_CONTENT:
            raise ValueError("This mind map exceeds the XMind export size limit")
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr("content.json", data)
            archive.writestr("metadata.json", json.dumps({"creator": {"name": "Galaris"}}))
            archive.writestr("manifest.json", json.dumps({"file-entries": {"content.json": {}, "metadata.json": {}}}))
        return output.getvalue(), "application/vnd.xmind.workbook", ".xmind"

    if target not in {"freeplane", "freemind", "opml"}:
        raise ValueError("Unsupported mind map export format")
    if any(INVALID_XML_CHARACTERS.search(value) for node in mindmap.nodes for value in (node.title, node.note, node.link)):
        raise ValueError("This mind map contains characters that XML cannot represent")
    if target == "opml":
        root = Element("opml", version="2.0")
        SubElement(SubElement(root, "head"), "title").text = mindmap.root.title
        body = SubElement(root, "body")
    else:
        root = body = Element("map", version="freeplane 1.9.13" if target == "freeplane" else "1.0.1")

    def add(node: MindMapNode, parent: Element) -> None:
        link = _portable_link(node.link)
        if target == "opml":
            element = SubElement(parent, "outline", text=node.title)
            if node.note:
                element.set(OPML_NOTE, node.note)
            if link:
                element.set("htmlUrl", link)
        else:
            element = SubElement(parent, "node", TEXT=node.title, ID=node.id)
            if link:
                element.set("LINK", link)
            if node.note:
                rich = SubElement(element, "richcontent", TYPE="NOTE")
                container = SubElement(SubElement(rich, "html"), "body")
                for line in node.note.split("\n"):
                    SubElement(container, "p").text = line
        for child in children.get(node.id, []):
            add(child, element)

    add(mindmap.root, body)
    if target == "opml":
        return tostring(root, encoding="utf-8", xml_declaration=True), "application/x-opml+xml", ".opml"
    return tostring(root, encoding="utf-8", xml_declaration=True), "application/x-freemind", ".mm"
