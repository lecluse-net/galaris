"""Apply ordered branch commands as one validated revision."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import MAX_NODES, MindMap, MindMapNode, NodeBody, NodeIcon, NodeKey, NodeLink, NodeNote, NodeTitle


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    node_id: NodeKey


class NewBranch(_Command):
    parent_id: NodeKey
    title: NodeTitle
    note: NodeNote = ""
    link: NodeLink = ""
    body_html: NodeBody = ""
    icon: NodeIcon = ""
    checked: bool | None = Field(default=None, description="True creates a checked box, false creates an unchecked box.")
    index: int | None = Field(default=None, ge=0, lt=MAX_NODES)

    def as_command(self) -> "AddBranch":
        return AddBranch(operation="add", **self.model_dump(exclude={"operation"}))


class AddBranch(NewBranch):
    operation: Literal["add"]


class EditBranch(_Command):
    operation: Literal["edit"]
    title: NodeTitle | None = None
    note: NodeNote | None = None
    link: NodeLink | None = None
    body_html: NodeBody | None = None
    icon: NodeIcon | None = None
    checked: bool | None = Field(default=None, description="True checks the box, false unchecks it, and null removes it. Omit to keep the current state.")


class MoveBranch(_Command):
    operation: Literal["move"]
    parent_id: NodeKey
    index: int | None = Field(default=None, ge=0, lt=MAX_NODES)


class RemoveBranch(_Command):
    operation: Literal["remove"]


BranchCommand = Annotated[AddBranch | EditBranch | MoveBranch | RemoveBranch, Field(discriminator="operation")]


class BranchCommandError(ValueError):
    """A branch command cannot be applied to the current tree."""


def _place(nodes: list[MindMapNode], node: MindMapNode, index: int | None) -> None:
    if index is None:
        nodes.append(node)
        return
    siblings = [position for position, sibling in enumerate(nodes) if sibling.parent == node.parent]
    if index > len(siblings):
        raise BranchCommandError("Branch position is out of range")
    nodes.insert(siblings[index] if index < len(siblings) else len(nodes), node)


def apply_commands(mindmap: MindMap, commands: list[BranchCommand]) -> MindMap:
    nodes: list[MindMapNode] = mindmap.nodes.copy()
    connectors = mindmap.connectors
    for command in commands:
        by_id = {node.id: node for node in nodes}
        node = by_id.get(command.node_id)
        if isinstance(command, AddBranch):
            if node is not None or command.parent_id not in by_id:
                raise BranchCommandError("Adding a branch requires a new ID and an existing parent")
            _place(nodes, MindMapNode(id=command.node_id, parent=command.parent_id, title=command.title,
                                       note=command.note, link=command.link,
                                       body_html=command.body_html, icon=command.icon, checked=command.checked), command.index)
            continue
        if node is None:
            raise BranchCommandError(
                f"Mind map branch '{command.node_id}' does not exist. Choose an existing node ID, "
                "or create the branch with mindmap_add or an operation='add' command "
                "that supplies node_id, parent_id and title."
            )
        if isinstance(command, EditBranch):
            fields = {key: value for key, value in command.model_dump(exclude={"operation", "node_id"}).items()
                      if value is not None}
            if "checked" in command.model_fields_set:
                fields["checked"] = command.checked
            if not fields:
                raise BranchCommandError(
                    f"Editing mind map branch '{command.node_id}' requires at least one field to change."
                )
            nodes[nodes.index(node)] = MindMapNode.model_validate({**node.model_dump(), **fields})
            continue
        if node.parent is None:
            raise BranchCommandError("The root cannot be moved or removed")
        children: dict[str, list[str]] = {}
        for child in nodes:
            if child.parent is not None:
                children.setdefault(child.parent, []).append(child.id)
        pending = [node.id]
        subtree: set[str] = set()
        while pending:
            key = pending.pop()
            subtree.add(key)
            pending.extend(children.get(key, []))
        if isinstance(command, RemoveBranch):
            nodes = [child for child in nodes if child.id not in subtree]
            connectors = [link for link in connectors if link.source not in subtree and link.target not in subtree]
        else:
            if command.parent_id in subtree or command.parent_id not in by_id:
                raise BranchCommandError("Choose an existing parent outside the moved branch")
            nodes.remove(node)
            _place(nodes, node.model_copy(update={"parent": command.parent_id}), command.index)
    return MindMap(version=mindmap.version, nodes=nodes, connectors=connectors,
                   theme=mindmap.theme, background_color=mindmap.background_color)
