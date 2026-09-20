"""Versioned editorial HTML contract, independent of application domains.

The parser checks the input before nh3's HTML5 sanitizer runs: API callers receive
an error instead of silently losing active content or unsupported structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import nh3
from markdown_it import MarkdownIt

ContentProfile = Literal["rich-text", "document"]
PROFILE_VERSION = 1
EXTRACTOR_VERSION = 1
MAX_HTML_BYTES = 2_000_000
MAX_TEXT_CHARS = 500_000
MAX_NODES = 50_000
MAX_DEPTH = 64
TAGS = set(
    "p h1 h2 h3 h4 h5 h6 strong em u s blockquote ul ol li hr a table thead tbody tfoot tr th td pre code br mark span img figure figcaption caption colgroup col sub sup".split()
)
VOID = {"br", "hr", "img", "col", "input", "source", "wbr"}
DOCUMENT_TAGS = set("script style div section article main header footer nav aside form label input button select option optgroup textarea fieldset legend output progress meter datalist details summary canvas svg g path rect circle ellipse line polyline polygon text tspan defs lineargradient radialgradient stop clippath mask use symbol title desc audio video source wbr".split())
ATTRIBUTES: dict[str, set[str]] = {
    "*": {"style", "class"},
    "a": {"href", "title", "rel", "target"},
    "ol": {"start", "reversed"},
    "li": {"value"},
    "th": {"colspan", "rowspan", "colwidth"},
    "td": {"colspan", "rowspan", "colwidth"},
    "code": {"class", "data-code-lines", "data-code-nowrap"},
    "img": {"src", "alt", "title", "width", "height"},
    "mark": {"data-color"},
}
ALIGNMENTS = {"left", "center", "right", "justify"}
HIGHLIGHTS = {"#fff59d", "#a5d6a7", "#90caf9", "#f48fb1"}
SCRIPT_HOSTS = {"cdn.jsdelivr.net", "unpkg.com", "esm.sh", "cdnjs.cloudflare.com"}


def valid_script_source(value: str) -> bool:
    try:
        uri = urlsplit(value)
        return uri.scheme == "https" and uri.hostname in SCRIPT_HOSTS and not uri.username and not uri.password and uri.port in {None, 443}
    except ValueError:
        return False


class RichTextError(ValueError):
    """Invalid editorial content; the caller must preserve the previous revision."""


def attachment_reference(value: str) -> tuple[UUID, UUID] | None:
    uri = urlsplit(value)
    if uri.scheme != "document" or uri.query or uri.fragment:
        return None
    parts = uri.path.split("/")
    if len(parts) != 3 or parts[1] != "attachments":
        return None
    try:
        document, attachment = UUID(uri.netloc), UUID(parts[2])
    except ValueError:
        return None
    if value != f"document://{document}/attachments/{attachment}":
        return None
    return document, attachment


def valid_link(value: str) -> bool:
    if not value or any(ord(char) < 33 for char in value) or "\\" in value:
        return False
    uri = urlsplit(value)
    if uri.scheme in {"https", "http"}:
        return bool(uri.hostname) and not uri.username and not uri.password
    if uri.scheme == "mailto":
        return bool(uri.path) and not uri.netloc
    if uri.scheme == "document" and attachment_reference(value) is not None:
        return True
    if uri.scheme in {"document", "memory"}:
        try:
            identity = UUID(uri.netloc)
        except ValueError:
            return False
        return value == f"{uri.scheme}://{identity}"
    if uri.scheme == "galaris" and uri.netloc in {"goal", "task", "agent"}:
        if uri.query or uri.fragment or not uri.path.startswith("/"):
            return False
        locator = uri.path[1:]
        if uri.netloc == "agent":
            return locator.isdecimal() and int(locator) > 0
        try:
            return str(UUID(locator)) == locator
        except ValueError:
            return False
    return False


STYLE_PROPERTIES = {
    "text-align",
    "background-color",
    "color",
    "width",
    "height",
    "aspect-ratio",
    "border-color",
    "border-style",
    "border-width",
    "border",
    "border-collapse",
    "padding",
    "vertical-align",
    "float",
    "margin-left",
    "margin-right",
    "font-family",
    "font-size",
    "list-style-type",
}
EDITORIAL_CLASSES = {
    "image",
    "image-inline",
    "image_resized",
    "table",
    "table_resized",
    "image-style-side",
    "image-style-align-left",
    "image-style-align-center",
    "image-style-align-right",
    "image-style-block-align-left",
    "image-style-block-align-right",
    "marker-yellow",
    "marker-green",
    "marker-pink",
    "marker-blue",
    "pen-red",
    "pen-green",
    "galaris-link-card",
    "galaris-media-audio",
    "galaris-media-video",
    "galaris-media-pdf",
    "galaris-callout",
    "galaris-callout-info",
    "galaris-callout-warning",
    "galaris-callout-question",
    "galaris-callout-error",
    "galaris-callout-stop",
    "galaris-callout-forbidden",
    "galaris-callout-search",
}


def _editorial_color(value: str) -> bool:
    return bool(
        re.fullmatch(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?|(?:rgb|hsl)a?\([0-9.,% /]{1,65}\)", value)
    ) or value in {
        "black",
        "white",
        "red",
        "green",
        "blue",
        "yellow",
        "orange",
        "purple",
        "gray",
        "grey",
        "silver",
        "maroon",
        "navy",
        "teal",
        "lime",
        "aqua",
        "fuchsia",
        "transparent",
    }


def _editorial_length(value: str, maximum: float = 1600) -> bool:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(px|pt|em|rem|%)?", value)
    return bool(match and 0 <= float(match[1]) <= (100 if match[2] == "%" else maximum))


def _editorial_border(value: str) -> bool:
    if value == "none":
        return True
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?px) (solid|dashed|dotted|double|groove|ridge|inset|outset) (.+)", value
    )
    return bool(match and _editorial_length(match[1], 100) and _editorial_color(match[3]))


def _style(value: str) -> str:
    declarations: dict[str, str] = {}
    for declaration in value.split(";"):
        if not declaration.strip():
            continue
        key, separator, raw = declaration.partition(":")
        key, raw = key.strip().lower(), raw.strip().lower()
        valid = (
            (key == "text-align" and raw in ALIGNMENTS)
            or (key in {"color", "background-color", "border-color"} and _editorial_color(raw))
            or (key in {"width", "height"} and _editorial_length(raw))
            or (key in {"padding", "border-width", "font-size"} and _editorial_length(raw, 100))
            or (
                key in {"margin-left", "margin-right"}
                and (raw == "auto" or _editorial_length(raw, 320))
            )
            or (
                key == "border-style"
                and raw
                in {
                    "none",
                    "solid",
                    "dashed",
                    "dotted",
                    "double",
                    "groove",
                    "ridge",
                    "inset",
                    "outset",
                }
            )
            or (key == "border-collapse" and raw in {"collapse", "separate"})
            or (key == "border" and _editorial_border(raw))
            or (key == "vertical-align" and raw in {"top", "middle", "bottom", "baseline"})
            or (key == "float" and raw in {"left", "right", "none"})
            or (key == "aspect-ratio" and bool(re.fullmatch(r"[0-9.]{1,8}\s*/\s*[0-9.]{1,8}", raw)))
            or (
                key == "font-family"
                and all(
                    part.strip(" \"'")
                    in {
                        "arial",
                        "helvetica",
                        "sans-serif",
                        "georgia",
                        "serif",
                        "times new roman",
                        "courier new",
                        "courier",
                        "monospace",
                        "verdana",
                        "tahoma",
                        "trebuchet ms",
                    }
                    for part in raw.split(",")
                )
            )
            or (
                key == "list-style-type"
                and raw
                in {
                    "disc",
                    "circle",
                    "square",
                    "decimal",
                    "decimal-leading-zero",
                    "lower-roman",
                    "upper-roman",
                    "lower-latin",
                    "upper-latin",
                    "lower-alpha",
                    "upper-alpha",
                }
            )
        )
        if not separator or not valid:
            raise RichTextError("Unsupported editorial style.")
        declarations[key] = raw
    return "; ".join(f"{key}: {value}" for key, value in sorted(declarations.items()))


@dataclass
class HtmlNode:
    tag: str = ""
    attributes: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    children: list[HtmlNode | str] = field(default_factory=lambda: list[HtmlNode | str]())

    def html(self) -> str:
        content = "".join(
            child.html() if isinstance(child, HtmlNode) else escape(child, quote=False)
            for child in self.children
        )
        if not self.tag:
            return content
        if self.tag in {"script", "style"}:
            content = "".join(child for child in self.children if isinstance(child, str))
        attributes = "".join(
            f' {key}="{escape(value, quote=True)}"'
            for key, value in sorted(self.attributes.items())
        )
        return f"<{self.tag}{attributes}>" + ("" if self.tag in VOID else f"{content}</{self.tag}>")


class _Parser(HTMLParser):
    def __init__(self, *, validate: bool = True, profile: ContentProfile = "rich-text") -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode()
        self.stack = [self.root]
        self.validate = validate
        self.profile = profile
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = {"b": "strong", "i": "em", "del": "s"}.get(tag, tag)
        self.count += 1
        if self.count > MAX_NODES or len(self.stack) > MAX_DEPTH:
            raise RichTextError("Editorial structure exceeds its limit.")
        allowed_tags = TAGS | (DOCUMENT_TAGS if self.profile == "document" else set[str]())
        if self.validate and (tag not in allowed_tags or (tag == "img" and self.profile != "document")):
            raise RichTextError(f"Element {tag!r} is not allowed in this content profile.")
        attributes: dict[str, str] = {}
        for key, raw in attrs:
            value = raw or ""
            if self.validate:
                if self.profile == "document" and tag != "img":
                    if key in attributes or not re.fullmatch(r"[a-z_][a-z0-9_.:-]*", key):
                        raise RichTextError("Invalid or duplicate HTML attribute.")
                    if key == "data-html-page":
                        raise RichTextError("Archived page markers cannot be written.")
                    if key in {"data-code-lines", "data-code-nowrap"} and (tag != "code" or value != "true"):
                        raise RichTextError("Unsupported code display option.")
                    if key == "href" and not value.startswith("#") and not valid_link(value):
                        raise RichTextError("Unsupported link reference.")
                    if tag == "script" and key == "src" and not valid_script_source(value):
                        raise RichTextError("Scripts must use an approved HTTPS library CDN.")
                    attributes[key] = value
                    continue
                allowed_attributes = {"src", "type", "async", "defer"} if tag == "script" else ATTRIBUTES.get(tag, set()) | ATTRIBUTES["*"]
                if key not in allowed_attributes or key in attributes:
                    raise RichTextError(f"Attribute {key!r} is not allowed.")
                if key == "style":
                    value = _style(value)
                elif key == "href" and not valid_link(value):
                    raise RichTextError("Unsupported link reference.")
                elif tag == "script" and key == "src" and not valid_script_source(value):
                    raise RichTextError("Scripts must use an approved HTTPS library CDN.")
                elif tag == "script" and key == "type" and value not in {"module", "importmap", "text/javascript", "application/javascript"}:
                    raise RichTextError("Unsupported script type.")
                elif key == "src" and tag != "script" and attachment_reference(value) is None:
                    raise RichTextError("An image must reference a document attachment.")
                elif key in {"colspan", "rowspan", "width", "height", "start", "value"}:
                    maximum = 16000 if tag == "img" and key in {"width", "height"} else 1000
                    if not value.isdecimal() or not 1 <= int(value) <= maximum:
                        raise RichTextError(f"Invalid {key}.")
                elif key in {"data-code-lines", "data-code-nowrap"} and value != "true":
                    raise RichTextError("Unsupported code display option.")
                elif key == "colwidth" and not all(
                    part.isdecimal() and 0 <= int(part) <= 1600 for part in value.split(",")
                ):
                    raise RichTextError("Invalid column widths.")
                elif key == "class" and not (
                    (tag == "code" and re.fullmatch(r"language-[a-zA-Z0-9_+-]{1,40}", value))
                    or (value.split() and set(value.split()) <= EDITORIAL_CLASSES)
                ):
                    raise RichTextError("Unsupported editorial class.")
                elif key == "data-color" and value not in HIGHLIGHTS:
                    raise RichTextError("Unsupported highlight color.")
                elif key == "target" and value not in {"_blank", "_self"}:
                    raise RichTextError("Unsupported link target.")
                elif key == "rel":
                    value = "noopener noreferrer"
            attributes[key] = value
        if tag == "a" and attributes.get("target") == "_blank":
            attributes["rel"] = "noopener noreferrer"
        if self.validate and tag == "img" and "src" not in attributes:
            raise RichTextError("An image requires an attachment reference.")
        node = HtmlNode(tag, attributes)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = {"b": "strong", "i": "em", "del": "s"}.get(tag, tag)
        if tag in VOID:
            return
        if len(self.stack) < 2 or self.stack[-1].tag != tag:
            raise RichTextError("HTML must contain complete, correctly nested blocks.")
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def handle_decl(self, decl: str) -> None:
        raise RichTextError("Full HTML documents are not editorial fragments.")

    def handle_comment(self, data: str) -> None:
        if self.validate:
            raise RichTextError("Comments are not editorial content.")


def parse_html(content: str, *, profile: ContentProfile = "rich-text") -> HtmlNode:
    if len(content.encode("utf-8")) > MAX_HTML_BYTES:
        raise RichTextError("Serialized HTML exceeds its byte limit.")
    parser = _Parser(profile=profile)
    parser.feed(content)
    parser.close()
    if len(parser.stack) != 1:
        raise RichTextError("HTML contains an unclosed element.")
    return parser.root


def visible_text(content: str) -> str:
    # Archived experimental pages remain readable as literal code in history diffs.
    # parse_html/normalize_html still reject this former marker on every new write.
    if content.startswith('<pre data-html-page="true"><code class="language-html">'):
        content = content.replace(' data-html-page="true"', '', 1)
    root = parse_html(content, profile="document")

    def visit(node: HtmlNode, *, pre: bool = False) -> str:
        if node.tag in {"script", "style"}:
            return ""
        pre = pre or node.tag == "pre"
        text = "".join(
            visit(child, pre=pre)
            if isinstance(child, HtmlNode)
            else (child if pre else re.sub(r"\s+", " ", child))
            for child in node.children
        )
        if node.tag == "img":
            return node.attributes.get("alt", "")
        if node.tag == "br":
            return "\n"
        if node.tag in {"td", "th"}:
            return text + "\t"
        if node.tag == "ol":
            start = int(node.attributes.get("start", "1"))
            return "".join(
                f"{start + index}. " + visit(child).removeprefix("• ")
                for index, child in enumerate(node.children)
                if isinstance(child, HtmlNode)
            )
        if node.tag == "li":
            return "• " + text.strip() + "\n"
        if node.tag in {
            "p",
            "pre",
            "blockquote",
            "figure",
            "figcaption",
            "caption",
            "tr",
            "ul",
            "ol",
            "hr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            return text + "\n"
        return text

    return visit(root).strip()


def normalize_html(content: str, *, profile: ContentProfile = "rich-text") -> str:
    root = parse_html(content, profile=profile)
    def interactive(node: HtmlNode) -> bool:
        if node.tag in DOCUMENT_TAGS or any(key == "id" or key.startswith("on") or key.startswith("data-dataset") for key in node.attributes):
            return True
        if value := node.attributes.get("class"):
            if not (node.tag == "code" and re.fullmatch(r"language-[a-zA-Z0-9_+-]{1,40}", value)) and not set(value.split()) <= EDITORIAL_CLASSES:
                return True
        if value := node.attributes.get("style"):
            try:
                _style(value)
            except RichTextError:
                return True
        return any(interactive(child) for child in node.children if isinstance(child, HtmlNode))

    if profile == "document" and interactive(root):
        # Executable document HTML is stored as source. Every consumer must render
        # it through an opaque sandbox or an inert, sanitized projection.
        normalized = root.html()
        if len(visible_text(normalized)) > MAX_TEXT_CHARS:
            raise RichTextError("Visible text exceeds its character limit.")
        if not root.children:
            return ""
        return normalized
    def reject_scripts(node: HtmlNode) -> None:
        if node.tag == "script":
            raise RichTextError("Interactive HTML belongs in a document attachment.")
        for child in node.children:
            if isinstance(child, HtmlNode):
                reject_scripts(child)
    reject_scripts(root)

    def compact(node: HtmlNode) -> None:
        if node.tag in {"", "ul", "ol", "table", "thead", "tbody", "tfoot", "tr"}:
            node.children = [
                child for child in node.children if isinstance(child, HtmlNode) or child.strip()
            ]
        for child in node.children:
            if isinstance(child, HtmlNode):
                compact(child)

    compact(root)
    # Bare inline input is a paragraph, including text produced by simple callers.
    grouped: list[HtmlNode | str] = []
    inline: list[HtmlNode | str] = []
    for child in root.children:
        if isinstance(child, HtmlNode) and child.tag in {
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "pre",
            "blockquote",
            "ul",
            "ol",
            "table",
            "figure",
            "hr",
            "img",
        }:
            if inline:
                grouped.append(HtmlNode("p", children=inline))
                inline = []
            grouped.append(child)
        else:
            inline.append(child)
    if inline:
        grouped.append(HtmlNode("p", children=inline))
    root.children = grouped
    serialized = root.html()
    clean = nh3.clean(
        serialized,
        tags=(TAGS - {"img"}) if profile == "rich-text" else TAGS | {"script"},
        attributes={**ATTRIBUTES, "script": {"src", "type", "async", "defer"}} if profile == "document" else ATTRIBUTES,
        clean_content_tags=set() if profile == "document" else {"script", "style"},
        url_schemes={"https", "http", "mailto", "document", "memory", "galaris"},
        link_rel=None,
        strip_comments=True,
        filter_style_properties=STYLE_PROPERTIES,
    )
    normalized = parse_html(clean, profile=profile).html()
    text = visible_text(normalized)
    if len(text) > MAX_TEXT_CHARS:
        raise RichTextError("Visible text exceeds its character limit.")
    if (
        not text.replace("\xa0", " ").strip()
        and not (profile == "document" and "<script" in normalized)
        and not image_references(normalized)
        and not any(
            node.tag in {"hr", "table", "figure"}
            for node in root.children
            if isinstance(node, HtmlNode)
        )
    ):
        return ""
    return normalized


def archived_document_html(content: str) -> str:
    """Restore document source; the rendering boundary keeps scripts isolated."""
    if content.startswith('<pre data-html-page="true"><code class="language-html">'):
        content = content.replace(' data-html-page="true"', '', 1)
    return normalize_html(content, profile="document")


def image_references(content: str) -> set[str]:
    root = parse_html(content, profile="document")
    result: set[str] = set()

    def visit(node: HtmlNode) -> None:
        if node.tag == "img":
            result.add(node.attributes["src"])
        for child in node.children:
            if isinstance(child, HtmlNode):
                visit(child)

    visit(root)
    return result


def convert_to_html(content: str, media_type: str, *, profile: ContentProfile = "rich-text") -> str:
    """Explicit format conversion; legacy images fail for operator resolution."""
    if media_type == "text/html":
        return normalize_html(content, profile=profile)
    if media_type == "text/plain":
        return normalize_html(
            "".join(f"<p>{escape(line)}</p>" for line in content.split("\n")), profile=profile
        )
    if media_type in {"text/markdown", "text/x-markdown"}:
        renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
        return normalize_html(renderer.render(content), profile=profile)
    raise RichTextError("Unsupported editorial source format.")


def semantic_hash(content: str) -> str:
    return sha256(f"html-text-v{EXTRACTOR_VERSION}\n{visible_text(content)}".encode()).hexdigest()


def html_blocks(content: str) -> list[str]:
    root = parse_html(content, profile="document")
    return [
        child.html() if isinstance(child, HtmlNode) else f"<p>{escape(child)}</p>"
        for child in root.children
        if isinstance(child, HtmlNode) or child.strip()
    ]


def replace_visible_text(content: str, old: str, new: str) -> str:
    """Replace exactly one text-node match, never tags, attributes or split marks."""
    if not old:
        raise RichTextError("The searched text cannot be empty.")
    root = parse_html(content, profile="document")
    matches: list[tuple[HtmlNode, int]] = []

    def visit(node: HtmlNode) -> None:
        if node.tag in {"script", "style"}:
            return
        for index, child in enumerate(node.children):
            if isinstance(child, HtmlNode):
                visit(child)
            else:
                matches.extend((node, index) for _ in range(child.count(old)))

    visit(root)
    if len(matches) != 1:
        raise RichTextError(
            "The visible text must occur once in a single text node; read the current blocks and retry."
        )
    node, index = matches[0]
    child = node.children[index]
    assert isinstance(child, str)
    node.children[index] = child.replace(old, new, 1)
    return root.html()


def convert_legacy_to_html(
    content: str, media_type: str, *, profile: ContentProfile = "rich-text"
) -> tuple[str, tuple[str, ...]]:
    """Preserve malformed legacy link labels; retain destinations in source revisions."""
    if media_type != "text/markdown":
        return convert_to_html(content, media_type, profile=profile), ()
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = renderer.parse(content)
    warnings: list[str] = []
    for token in tokens:
        if token.children is None:
            continue
        invalid = False
        for child in token.children:
            if child.type == "link_open":
                href = str(child.attrGet("href") or "")
                invalid = not valid_link(href)
                if invalid:
                    child.tag = "span"
                    child.attrs = {}
                    warnings.append(
                        "Invalid link retained as text; original destination preserved in the source revision."
                    )
            elif child.type == "link_close" and invalid:
                child.tag = "span"
                invalid = False
    return normalize_html(
        renderer.renderer.render(tokens, renderer.options, {}), profile=profile
    ), tuple(warnings)


def read_html_page(content: str, *, offset: int, max_chars: int) -> dict[str, object]:
    """Read whole top-level blocks; cursor and block numbers are revision-scoped."""
    blocks = html_blocks(content)
    start = min(max(0, offset), len(blocks))
    end, length = start, 0
    while end < len(blocks) and length + len(blocks[end]) <= max_chars:
        length += len(blocks[end])
        end += 1
    if start == end and end < len(blocks):
        raise RichTextError(
            f"Block {start + 1} requires {len(blocks[start])} serialized characters; increase max_chars or read the complete resource."
        )
    return {
        "content": "".join(blocks[start:end]),
        "start": start,
        "end": end,
        "total": len(blocks),
        "next_offset": end if end < len(blocks) else None,
        "offset_unit": "block",
        "media_type": "text/html",
        "content_profile_version": PROFILE_VERSION,
        "blocks": [{"number": index + 1, "html": blocks[index]} for index in range(start, end)],
    }
