"""Ordered JSON prompt trees and their single Markdown renderer."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal, NotRequired, TypedDict


ExecutorKind = Literal["task", "conversation", "voice"]
PromptNodeType = Literal["section", "raw_markdown"]

PROMPT_TREE_SCHEMA = "galaris.system-prompt/v1"
EXECUTOR_SUFFIX_SOURCE = "executor_prompt_suffix"


class PromptNode(TypedDict):
    """One JSON-compatible ordered node in a system prompt."""

    type: PromptNodeType
    key: str
    title: NotRequired[str]
    text: NotRequired[str]
    content_format: NotRequired[Literal["html", "markdown"]]
    fields: NotRequired[dict[str, str]]
    field_formats: NotRequired[dict[str, Literal["html"]]]
    children: NotRequired[list["PromptNode"]]
    source: NotRequired[str]


class PromptTree(TypedDict):
    """JSON-compatible document converted to Markdown at the provider boundary."""

    schema: str
    executor: ExecutorKind
    children: list[PromptNode]


def section(
    key: str,
    *,
    title: str,
    text: str = "",
    content_format: Literal["html", "markdown"] = "markdown",
    fields: dict[str, str] | None = None,
    field_formats: dict[str, Literal["html"]] | None = None,
    children: list[PromptNode] | None = None,
) -> PromptNode:
    """Build a section node while retaining only meaningful JSON properties."""

    node: PromptNode = {"type": "section", "key": key, "title": title}
    if text.strip():
        node["text"] = text if content_format == "html" else text.strip()
        if content_format == "html":
            node["content_format"] = "html"
    if fields:
        node["fields"] = {key: value for key, value in fields.items() if value.strip()}
    if field_formats:
        node["field_formats"] = field_formats
    if children:
        node["children"] = children
    return node


def raw_markdown(
    text: str | None,
    *,
    key: str = "executor-prompt-suffix",
    source: str = EXECUTOR_SUFFIX_SOURCE,
) -> PromptNode:
    """Build an unwrapped Markdown node used for the executor-specific suffix."""

    return {
        "type": "raw_markdown",
        "key": key,
        "source": source,
        "text": (text or "").strip(),
    }


def system_prompt_tree(
    executor: ExecutorKind,
    children: list[PromptNode],
    *,
    suffix: str | None,
) -> PromptTree:
    """Build a complete tree whose final node is always the configurable suffix."""

    return {
        "schema": PROMPT_TREE_SCHEMA,
        "executor": executor,
        "children": [*children, raw_markdown(suffix)],
    }


def insert_before_suffix(tree: PromptTree, nodes: list[PromptNode]) -> PromptTree:
    """Return a copy with runtime nodes inserted without moving the final suffix."""

    copied = deepcopy(tree)
    children = copied["children"]
    if not children or children[-1].get("source") != EXECUTOR_SUFFIX_SOURCE:
        raise ValueError("Executor prompt trees must end with the configurable suffix")
    copied["children"] = [*children[:-1], *nodes, children[-1]]
    return copied


def suffix_text(tree: PromptTree) -> str:
    """Return the effective suffix and validate its final-node invariant."""

    children = tree["children"]
    if not children or children[-1].get("source") != EXECUTOR_SUFFIX_SOURCE:
        raise ValueError("Executor prompt trees must end with the configurable suffix")
    return children[-1].get("text", "")


def _render_node(node: PromptNode, *, level: int) -> str:
    if node["type"] == "raw_markdown":
        return node.get("text", "").strip()

    text = node.get("text", "")
    if node.get("content_format") != "html":
        text = text.strip()
    fields = node.get("fields", {})
    rendered_children = [
        rendered
        for child in node.get("children", [])
        if (rendered := _render_node(child, level=level + 1))
    ]
    if not text and not fields and not rendered_children:
        return ""

    parts: list[str] = []
    title = node.get("title", "").strip()
    if title:
        parts.append(f"{'#' * max(1, min(level, 6))} {title}")
    if text:
        parts.append(text)
    if fields:
        parts.append(
            "\n".join(f"- **{label}:** {value}" for label, value in fields.items())
        )
    parts.extend(rendered_children)
    return "\n\n".join(parts)


def render_prompt_tree(tree: PromptTree) -> str:
    """Render one validated JSON tree as Markdown, preserving node order exactly."""

    if tree.get("schema") != PROMPT_TREE_SCHEMA:
        raise ValueError(f"Unsupported prompt tree schema: {tree.get('schema')}")
    suffix_text(tree)
    return "\n\n".join(
        rendered
        for node in tree["children"]
        if (rendered := _render_node(node, level=1))
    )


__all__ = [
    "EXECUTOR_SUFFIX_SOURCE",
    "ExecutorKind",
    "PROMPT_TREE_SCHEMA",
    "PromptNode",
    "PromptTree",
    "insert_before_suffix",
    "raw_markdown",
    "render_prompt_tree",
    "section",
    "suffix_text",
    "system_prompt_tree",
]
