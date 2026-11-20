"""Native mind-map content stored in ordinary Document revisions."""

from collections import defaultdict
from collections.abc import Mapping
from html import escape
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from core.util import image_references, normalize_html, visible_text
from ..tag_icons import validate_icon

MAX_NODES = 2000
MAX_DEPTH = 48
NodeKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
NodeTitle = Annotated[str, StringConstraints(max_length=500)]
NodeNote = Annotated[str, StringConstraints(max_length=16000)]
NodeLink = Annotated[str, StringConstraints(max_length=2048)]
NodeValue = Annotated[str, StringConstraints(max_length=2048)]
NodeBody = Annotated[str, StringConstraints(max_length=128_000)]
NodeIcon = Annotated[str, StringConstraints(max_length=1_000_000)]
PaletteKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
BackgroundColor = Annotated[str, StringConstraints(pattern=r"^(?:#[0-9a-fA-F]{6}|[a-z][a-z0-9-]{0,63})$")]


class MindMapNode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: NodeKey
    parent: NodeKey | None
    title: NodeTitle
    note: NodeNote = ""
    link: NodeLink = ""
    body_html: NodeBody = ""
    icon: NodeIcon = ""
    checked: bool | None = None
    value: NodeValue | None = None

    @field_validator("icon")
    @classmethod
    def valid_icon(cls, value: str) -> str:
        return validate_icon(value) if value else ""


class MindMapTheme(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: PaletteKey
    version: int = Field(ge=1, le=2**53 - 1)


class MindMapConnector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: NodeKey
    target: NodeKey
    label: Annotated[str, StringConstraints(min_length=1, max_length=120, pattern=r"\S")]


class MindMap(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    nodes: list[MindMapNode] = Field(min_length=1, max_length=MAX_NODES)
    connectors: list[MindMapConnector] = Field(default_factory=list[MindMapConnector], max_length=1000)
    theme: MindMapTheme | None = None
    background_color: BackgroundColor | None = None

    @model_validator(mode="after")
    def validate_tree(self) -> "MindMap":
        children = self.children()
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes) or len(children.get(None, [])) != 1:
            raise ValueError("A mind map needs unique node IDs and exactly one root")
        pairs: set[frozenset[str]] = set()
        for connector in self.connectors:
            pair = frozenset((connector.source, connector.target))
            if len(pair) != 2 or not pair <= ids or pair in pairs:
                raise ValueError("A mind map connector must link two existing nodes with no duplicate pair")
            pairs.add(pair)
        pending = [(self.root, 0)]
        visited = 0
        while pending:
            node, depth = pending.pop()
            if depth > MAX_DEPTH:
                raise ValueError("Mind map exceeds the maximum branch depth")
            visited += 1
            pending.extend((child, depth + 1) for child in children.get(node.id, []))
        if visited != len(self.nodes):
            raise ValueError("All mind map branches must connect to the root")
        return self

    @property
    def root(self) -> MindMapNode:
        return next(node for node in self.nodes if node.parent is None)

    def children(self) -> dict[str | None, list[MindMapNode]]:
        children: dict[str | None, list[MindMapNode]] = defaultdict(list)
        for node in self.nodes:
            children[node.parent].append(node)
        return children

    def ordered(self) -> list[MindMapNode]:
        children = self.children()
        pending = [self.root]
        ordered: list[MindMapNode] = []
        while pending:
            node = pending.pop()
            ordered.append(node)
            pending.extend(reversed(children.get(node.id, [])))
        return ordered

    def source(self) -> str:
        return self.model_dump_json(exclude_defaults=True)


INITIAL_CONTENT = MindMap(version=1, nodes=[MindMapNode(id="root", parent=None, title="")]).source()


def validate(content: str) -> None:
    normalize(content)


def normalize(content: str) -> str:
    mindmap = MindMap.model_validate_json(content)
    changed = False
    for node in mindmap.nodes:
        body = normalize_html(node.body_html, profile="document") if node.body_html else ""
        if body != node.body_html:
            node.body_html = body
            changed = True
    return mindmap.source() if changed else content


def attached_images(content: str) -> set[str]:
    mindmap = MindMap.model_validate_json(content)
    return {uri for node in mindmap.nodes if node.body_html for uri in image_references(node.body_html)}


def references(content: str) -> tuple[str, ...]:
    return tuple(sorted(attached_images(content)))


def remap_references(content: str, mapping: Mapping[str, str]) -> str:
    if not mapping:
        return content
    mindmap = MindMap.model_validate_json(content)
    for node in mindmap.nodes:
        node.link = mapping.get(node.link, node.link)
        for source, target in mapping.items():
            node.body_html = node.body_html.replace(source, target)
    return normalize(mindmap.source())


def extract(content: str) -> str:
    mindmap = MindMap.model_validate_json(content)
    return "\n".join([part for node in mindmap.ordered()
                      for part in (node.title, node.value, node.note, visible_text(node.body_html) if node.body_html else "") if part]
                     + [connector.label for connector in mindmap.connectors])


def static_snapshot(content: str) -> str:
    mindmap = MindMap.model_validate_json(content)
    children = mindmap.children()
    labels = {node.id: node.title or node.id for node in mindmap.nodes}
    descriptions: dict[str, list[str]] = defaultdict(list)
    for connector in mindmap.connectors:
        descriptions[connector.source].append(f"<p>{escape(connector.label)} → {escape(labels[connector.target])}</p>")

    def branch(node: MindMapNode) -> str:
        nested = "".join(branch(child) for child in children.get(node.id, []))
        note = f"<p>{escape(node.note)}</p>" if node.note else ""
        body = f"<p>{escape(visible_text(node.body_html))}</p>" if node.body_html else ""
        link = f"<p>{escape(node.link)}</p>" if node.link else ""
        checkbox = ("☑ " if node.checked else "☐ ") if node.checked is not None else ""
        value = f" {escape(node.value)}" if node.value else ""
        connectors = "".join(descriptions[node.id])
        return f"<li><strong>{checkbox}{escape(node.title)}</strong>{value}{note}{body}{link}{connectors}" + (f"<ul>{nested}</ul>" if nested else "") + "</li>"

    return f"<ul>{branch(mindmap.root)}</ul>"
