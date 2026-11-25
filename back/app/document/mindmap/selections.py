"""File selection syntax and mutations for native mind map source."""

import json
from typing import Annotated

from pydantic import Field, TypeAdapter

from . import MindMap, MindMapNode
from .commands import BranchCommand, apply_commands

_BRANCHES = "/nodes"
_OPERATIONS = TypeAdapter(Annotated[list[BranchCommand], Field(min_length=1, max_length=50)])


def _branch(mindmap: MindMap, selector: str) -> tuple[MindMapNode, bool]:
    identity, separator, field = selector.partition("/")
    if separator and field != "body_html":
        raise ValueError("Select a branch by ID, or use <branch-id>/body_html.")
    for node in mindmap.nodes:
        if node.id == identity:
            return node, bool(separator)
    raise ValueError(f"Mind map branch '{identity}' does not exist.")


def read(source: str, selector: str) -> tuple[str, str]:
    mindmap = MindMap.model_validate_json(source)
    if selector == _BRANCHES:
        nodes = [{**node.model_dump(exclude={"body_html", "icon"}),
                  "has_body": bool(node.body_html), "selector": node.id} for node in mindmap.ordered()]
        return json.dumps({"root_id": mindmap.root.id, "nodes": nodes}, ensure_ascii=False), "application/json"
    node, body_only = _branch(mindmap, selector)
    if body_only:
        return node.body_html, "text/html"
    return node.model_dump_json(), "application/json"


def write(source: str, selector: str, replacement: str) -> str:
    mindmap = MindMap.model_validate_json(source)
    node, body_only = _branch(mindmap, selector)
    updated = (MindMapNode.model_validate({**node.model_dump(), "body_html": replacement}) if body_only
               else MindMapNode.model_validate_json(replacement))
    if (updated.id, updated.parent) != (node.id, node.parent):
        raise ValueError("A branch replacement must keep its ID and parent. Use file_edit to move it.")
    mindmap.nodes[mindmap.nodes.index(node)] = updated
    return mindmap.source()


def edit(source: str, selector: str, operations: str) -> str:
    if selector != _BRANCHES:
        raise ValueError("Use selector='/nodes' to apply branch operations, or file_write to replace one branch.")
    return apply_commands(MindMap.model_validate_json(source), _OPERATIONS.validate_json(operations)).source()
