"""Enforce explicit isolation boundaries for agent-authored HTML."""

import re
from collections import Counter
from collections.abc import Iterator
from hashlib import sha256

from core.util import HtmlNode, RichTextError, parse_html


_SVG_TAGS = frozenset(
    "svg g path rect circle ellipse line polyline polygon text tspan defs lineargradient radialgradient "
    "stop clippath mask use symbol title desc style".split()
)
_CSS_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
_CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^\s)]*))\s*\)""", re.IGNORECASE)
_SHARED_REFERENCE = re.compile(r"""url\(\s*['"]?#""", re.IGNORECASE)
_ACTIVE_TAGS = {"style", "script", "form"}
_INTERNAL_CODE = {"language-galaris-app", "language-galaris-raw-html", "language-galaris-svg"}


def _descendants(node: HtmlNode) -> Iterator[HtmlNode]:
    yield node
    for child in node.children:
        if isinstance(child, HtmlNode):
            yield from _descendants(child)


def _standalone_svg(node: HtmlNode) -> bool:
    elements = tuple(_descendants(node))
    references = {"#" + value for element in elements if (value := element.attributes.get("id"))}

    def local_urls(value: str) -> bool:
        value = _CSS_COMMENT.sub("", value)
        return "\\" not in value and not re.search(r"@import\b", value, re.IGNORECASE) and all(
            (match[1] or match[2] or match[3] or "") in references for match in _CSS_URL.finditer(value)
        )

    for element in elements:
        if element.tag not in _SVG_TAGS:
            return False
        for name, value in element.attributes.items():
            if name.startswith(("on", "data-dataset")) or name in {"src", "xml:base"}:
                return False
            if name in {"href", "xlink:href"}:
                if value not in references:
                    return False
            elif re.search(r"url\s*\(|\\", value, re.IGNORECASE) and not local_urls(value):
                return False
        if element.tag == "style" and not local_urls("".join(child for child in element.children if isinstance(child, str))):
            return False
    return True


def _layout_violations(content: str) -> Counter[tuple[str, str]]:
    root = parse_html(content, profile="document")
    results: Counter[tuple[str, str]] = Counter()

    def record(kind: str, node: HtmlNode) -> None:
        results[kind, sha256(node.html().encode()).hexdigest()] += 1

    def active(node: HtmlNode) -> bool:
        return node.tag in _ACTIVE_TAGS or any(
            name.startswith(("on", "data-dataset")) or _SHARED_REFERENCE.search(value)
            or node.tag != "a" and name in {"href", "xlink:href"} and value.startswith("#")
            for name, value in node.attributes.items()
        )

    def contains_application(node: HtmlNode) -> bool:
        return node.tag != "svg" and (active(node) or any(
            contains_application(child) for child in node.children if isinstance(child, HtmlNode)
        ))

    def visit(node: HtmlNode, *, figure_available: bool = False) -> None:
        if node.tag == "svg":
            if not figure_available or not _standalone_svg(node):
                record("svg", node)
            return
        if node.tag == "code" and _INTERNAL_CODE.intersection(node.attributes.get("class", "").split()):
            record("code", node)
        if active(node):
            record("section", node)
            return
        for child in node.children:
            if isinstance(child, HtmlNode):
                visit(child)

    for child in root.children:
        if not isinstance(child, HtmlNode) or child.tag == "section" and contains_application(child):
            continue
        if child.tag == "figure":
            parts = [value for value in child.children if isinstance(value, HtmlNode) or value.strip()]
            if (len(parts) in {1, 2} and isinstance(svg := parts[0], HtmlNode) and svg.tag == "svg"
                    and (len(parts) == 1 or isinstance(caption := parts[1], HtmlNode) and caption.tag == "figcaption")
                    and not any(name.startswith(("on", "data-dataset")) for name in child.attributes)):
                visit(svg, figure_available=True)
                if len(parts) == 2 and isinstance(parts[1], HtmlNode):
                    visit(parts[1])
                continue
        visit(child, figure_available=True)
    return results


def require_agent_html_layout(content: str, previous: str | None = None) -> None:
    violations = _layout_violations(content)
    if violations and previous:
        # Existing applications and legacy regions can be carried through an edit
        # verbatim. Adding another copy or changing a legacy block needs a boundary.
        violations -= _layout_violations(previous)
    if violations:
        if any(kind == "svg" for kind, _digest in violations):
            raise RichTextError("Use a standalone <svg> or <figure><svg>…</svg><figcaption>…</figcaption></figure>. "
                                "Keep SVG definitions, styles and references inside that SVG.")
        raise RichTextError("Put the HTML, CSS and JavaScript of each application in its own top-level <section>. "
                            "Keep editorial paragraphs outside the section and use ordinary HTML rather than application code markers.")
