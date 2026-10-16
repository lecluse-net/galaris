"""BPMN 2.0 XML and the executable Galaris profile, independent of persistence."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, TypeAlias, cast
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .expressions import parse_expression
from .values import Variable, validate_declarations

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
GALARIS = "https://galaris.ai/bpmn/v1"
DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DD = "http://www.omg.org/spec/DD/20100524/DI"
for prefix, namespace in (("bpmn", BPMN), ("galaris", GALARIS), ("bpmndi", DI), ("dc", DC), ("di", DD)):
    ET.register_namespace(prefix, namespace)


class Flow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=255)
    source: str
    target: str
    condition: str | None = None


NodeKind: TypeAlias = Literal["start", "end", "task", "human_task", "tool_call", "rest", "code", "program", "call", "if", "parallel", "for", "while"]
ACTIVITY_KINDS = frozenset({"task", "human_task", "tool_call", "rest", "code", "program", "call"})


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=255)
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["agent", "human"]
    agent_id: int | None = Field(default=None, gt=0)
    user_id: int | None = Field(default=None, gt=0)


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=255)
    kind: NodeKind
    title: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    x: float = Field(default=0, allow_inf_nan=False)
    y: float = Field(default=0, allow_inf_nan=False)
    body: Workflow | None = None
    inputs: list[Variable] | None = Field(default=None, exclude_if=lambda value: value is None)
    outputs: list[Variable] | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_data_contracts(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(cast(dict[str, Any], value))
            raw_config: Any = value.get("config", {})
            if not isinstance(raw_config, dict):
                return value
            config = dict(cast(dict[str, Any], raw_config))
            for key in ("input_schema", "output_schema", "output_mapping", "output", "result_format", "result_condition", "files", "catch", "retry"):
                config.pop(key, None)
            if value.get("kind") not in {"tool_call", "program"}:
                config.pop("input", None)
            value["config"] = config
        return value


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["galaris.bpmn/v1", "galaris.bpmn/v2"] = "galaris.bpmn/v1"
    nodes: list[Node]
    flows: list[Flow]
    actors: list[Actor] = Field(default_factory=lambda: list[Actor]())
    execution_agent_id: int | None = Field(default=None, gt=0)
    inputs: list[Variable] | None = Field(default=None, exclude_if=lambda value: value is None)
    outputs: list[Variable] | None = Field(default=None, exclude_if=lambda value: value is None)

    @property
    def typed(self) -> bool:
        return self.schema_version == "galaris.bpmn/v2"

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_data_contracts(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(cast(dict[str, Any], value))
            # Remove only paths belonging exclusively to retired error handlers.
            # Other disconnected nodes still fail the ordinary graph validation.
            raw_nodes: Any = value.get("nodes", [])
            raw_flows: Any = value.get("flows", [])
            if isinstance(raw_nodes, list) and isinstance(raw_flows, list):
                records = [node.model_dump() if isinstance(node, Node) else node for node in cast(list[Any], raw_nodes)]
                links = [flow.model_dump() if isinstance(flow, Flow) else flow for flow in cast(list[Any], raw_flows)]
                if all(isinstance(node, dict) for node in records) and all(isinstance(flow, dict) for flow in links):
                    nodes = cast(list[dict[str, Any]], records)
                    flows = cast(list[dict[str, Any]], links)
                    targets = {str(node["config"]["catch"]) for node in nodes if isinstance(node.get("config"), dict) and node["config"].get("catch")}
                    if value.get("error_handler"):
                        targets.add(str(value["error_handler"]))
                    def reachable(roots: set[str]) -> set[str]:
                        result = set(roots)
                        pending = list(roots)
                        while pending:
                            source = pending.pop()
                            for flow in flows:
                                target = flow.get("target")
                                if flow.get("source") == source and isinstance(target, str) and target not in result:
                                    result.add(target)
                                    pending.append(target)
                        return result
                    if targets:
                        ordinary = reachable({str(node["id"]) for node in nodes if node.get("kind") == "start" and "id" in node})
                        removed = reachable(targets) - ordinary
                        value["nodes"] = [node for node in nodes if node.get("id") not in removed]
                        value["flows"] = [flow for flow in flows if flow.get("source") not in removed and flow.get("target") not in removed]
            for key in ("input_schema", "output_schema", "files", "error_handler"):
                value.pop(key, None)
        return value

    def outgoing(self, key: str) -> list[Flow]:
        return [flow for flow in self.flows if flow.source == key]

    def incoming(self, key: str) -> list[Flow]:
        return [flow for flow in self.flows if flow.target == key]

    def node(self, key: str) -> Node:
        return next(node for node in self.nodes if node.id == key)


_TAGS: dict[str, NodeKind] = {"startEvent": "start", "endEvent": "end", "task": "task", "userTask": "human_task", "serviceTask": "tool_call",
         "scriptTask": "program", "callActivity": "call", "exclusiveGateway": "if", "parallelGateway": "parallel"}
_TAGS_BACK = {kind: tag for tag, kind in _TAGS.items()}


def decision_activity(node: Node) -> Node:
    """Reuse durable activity execution for an explicitly configured binary IF."""
    mode = node.config.get("mode") if node.kind == "if" else None
    if mode not in ("ai", "code", "human"):
        return node
    kind: NodeKind = "human_task" if mode == "human" else "code" if mode == "code" else "task"
    return node.model_copy(update={"kind": kind, "inputs": [],
        "outputs": [Variable(name="decision", type="bool", nullable=False)],
        "config": {**node.config, **({"dataset_code": True} if mode == "code" else {})}})


def validate_graph(graph: Workflow, _identities: set[str] | None = None) -> Workflow:
    if graph.typed:
        if graph.inputs is None or graph.outputs is None:
            raise ValueError("The typed profile requires explicit process inputs and outputs")
        validate_declarations(graph.inputs, path="process.inputs")
        validate_declarations(graph.outputs, path="process.outputs")
    elif graph.inputs is not None or graph.outputs is not None:
        raise ValueError("Data declarations require the galaris.bpmn/v2 profile")
    identities = [node.id for node in graph.nodes] + [flow.id for flow in graph.flows]
    if len(set(identities)) != len(identities):
        raise ValueError("Node and flow identifiers must be unique")
    global_ids: set[str] = _identities if _identities is not None else set()
    if global_ids.intersection(identities):
        raise ValueError("BPMN identifiers must also be unique across subprocess bodies")
    global_ids.update(identities)
    nodes = {node.id: node for node in graph.nodes}
    actors = {actor.id: actor for actor in graph.actors}
    if len(actors) != len(graph.actors):
        raise ValueError("Actor identifiers must be unique within a graph")
    for actor in graph.actors:
        if not actor.name.strip() or (actor.kind == "agent" and actor.user_id is not None) or (actor.kind == "human" and actor.agent_id is not None):
            raise ValueError("An actor must have a name and an assignment of its own type")
    for node in graph.nodes:
        mode = node.config.get("mode")
        if node.kind == "if" and mode is not None:
            if not graph.typed or mode not in ("ai", "code", "human"):
                raise ValueError("IF processing modes require the typed profile and ai, code or human")
            if mode == "code" and not str(node.config.get("code", "")).strip():
                raise ValueError("A code IF requires Python source")
            if mode != "code" and not str(node.config.get("prompt", "")).strip():
                raise ValueError("An AI or human IF requires instructions")
            assigned = actors.get(str(node.config.get("actor", "")))
            if mode == "human" and (assigned is None or assigned.kind != "human"):
                raise ValueError("A human IF requires a human actor")
            if mode != "human" and assigned is not None and assigned.kind != "agent":
                raise ValueError("An AI actor permits only AI or code processing")
        if "external_output_typed" in node.config and type(node.config["external_output_typed"]) is not bool:
            raise ValueError(f"{node.id}: external_output_typed must be a boolean")
        if "dataset_code" in node.config and type(node.config["dataset_code"]) is not bool:
            raise ValueError(f"{node.id}: dataset_code must be a boolean")
        for script in ("preprocess", "postprocess", "code"):
            if script in node.config and (not graph.typed or not isinstance(node.config[script], str) or len(node.config[script]) > 100_000):
                raise ValueError(f"{node.id}: scripts require bounded Python source and the typed profile")
        if node.kind == "code" and (not graph.typed or not str(node.config.get("code", "")).strip()):
            raise ValueError(f"{node.id}: a Code activity requires Python source and the typed profile")
        if graph.typed and node.kind in ACTIVITY_KINDS:
            if node.inputs is None or node.outputs is None:
                raise ValueError(f"{node.id}: each activity requires explicit inputs and outputs")
            validate_declarations(node.inputs, path=f"{node.id}.inputs")
            validate_declarations(node.outputs, path=f"{node.id}.outputs")
        elif node.inputs is not None or node.outputs is not None:
            raise ValueError(f"{node.id}: declarations belong to typed activities")
        actor_key = node.config.get("actor")
        if actor_key is not None:
            if not isinstance(actor_key, str) or actor_key not in actors:
                raise ValueError("An activity references an unknown actor")
            required = "human" if node.kind == "human_task" else "agent" if node.kind == "task" or graph.typed and node.kind in ACTIVITY_KINDS else None
            if required and actors[actor_key].kind != required:
                raise ValueError("Human and agent tasks cannot exchange actor types")
        elif node.kind == "human_task":
            raise ValueError("A human task requires a human actor")
    starts = [node for node in graph.nodes if node.kind == "start"]
    if len(starts) != 1 or not any(node.kind == "end" for node in graph.nodes):
        raise ValueError("A workflow requires exactly one start and at least one end")
    for flow in graph.flows:
        if flow.source not in nodes or flow.target not in nodes:
            raise ValueError("A sequence flow references an unknown node")
        if flow.condition is not None:
            parse_expression(flow.condition)
            if nodes[flow.source].kind != "if":
                raise ValueError("Conditions belong to exclusive gateways")
    visited: set[str] = set()
    active: set[str] = set()

    def walk(key: str) -> None:
        if key in active:
            raise ValueError("Cycles must be expressed with a FOR or WHILE subprocess")
        if key in visited:
            return
        active.add(key)
        for flow in graph.outgoing(key):
            walk(flow.target)
        active.remove(key)
        visited.add(key)

    walk(starts[0].id)
    if visited != set(nodes):
        raise ValueError("Every node must be reachable from the start")
    for node in graph.nodes:
        outgoing = graph.outgoing(node.id)
        if node.kind == "end" and outgoing or node.kind != "end" and not outgoing:
            raise ValueError("Only end events may have no outgoing flow")
        if node.kind == "start" and graph.incoming(node.id):
            raise ValueError("Start events cannot have incoming flows")
        if node.kind == "if":
            if node.config.get("mode") is not None and (len(outgoing) != 2 or {flow.condition for flow in outgoing} != {"decision", None}):
                raise ValueError("A configured IF requires exactly one True and one False output")
            defaults = [flow for flow in outgoing if flow.condition is None]
            if len(defaults) != 1:
                raise ValueError("An IF gateway requires exactly one default flow")
        if node.kind in {"for", "while"}:
            if node.body is None:
                raise ValueError("A loop requires a subprocess body")
            validate_graph(node.body, global_ids)
            if node.body.schema_version != graph.schema_version:
                raise ValueError("Inline subprocesses must use the same data profile")
            if not isinstance(node.config.get("items" if node.kind == "for" else "condition"), str):
                raise ValueError("A loop requires an items or condition expression")
            parse_expression(node.config["items" if node.kind == "for" else "condition"])
        elif node.body is not None:
            raise ValueError("Only loop nodes have inline bodies")
        if node.kind in {"task", "human_task"} and not str(node.config.get("prompt", "")).strip():
            raise ValueError("Each Task requires instructions for its prompt")
        if node.kind == "call" and not str(node.config.get("process_code", "")).strip():
            raise ValueError("A call activity requires a process code")
        if node.kind == "tool_call" and not str(node.config.get("tool", "")).strip():
            raise ValueError("A tool activity requires an operation name")
        if node.kind == "rest" and (not graph.typed or not str(node.config.get("tool_code", "")).strip()):
            raise ValueError("A REST activity requires the typed profile and a Tool code")
        if node.kind == "parallel" and len(graph.incoming(node.id)) > 1 and len(outgoing) > 1:
            raise ValueError("Use distinct parallel split and join gateways")
    return graph


def compile_bpmn(xml: str) -> Workflow:
    if len(xml.encode("utf-8")) > 2_000_000 or re.search(r"<!\s*(DOCTYPE|ENTITY)", xml, re.IGNORECASE):
        raise ValueError("BPMN exceeds the XML limit or contains forbidden entities")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ValueError("Invalid BPMN XML") from error
    if root.tag != f"{{{BPMN}}}definitions":
        raise ValueError("BPMN definitions namespace is required")
    xml_ids = [element.attrib["id"] for element in root.iter() if "id" in element.attrib]
    if len(xml_ids) != len(set(xml_ids)):
        raise ValueError("BPMN XML identifiers must be globally unique")
    processes = root.findall(f"{{{BPMN}}}process")
    if len(processes) != 1:
        raise ValueError("Exactly one executable process is required")
    positions: dict[str, tuple[float, float]] = {}
    for shape in root.iter(f"{{{DI}}}BPMNShape"):
        bounds = shape.find(f"{{{DC}}}Bounds")
        if bounds is not None:
            positions[shape.get("bpmnElement", "")] = (float(bounds.get("x", "0")), float(bounds.get("y", "0")))

    def parse(element: ET.Element) -> Workflow:
        settings = element.find(f"{{{BPMN}}}extensionElements/{{{GALARIS}}}workflow")
        props: dict[str, Any] = json.loads(settings.text or "{}") if settings is not None else {}
        nodes: list[dict[str, Any]] = []
        flows: list[Flow] = []
        for child in element:
            tag = child.tag.removeprefix(f"{{{BPMN}}}")
            if tag in {"extensionElements", "laneSet"}:
                continue
            if tag == "sequenceFlow":
                condition = child.find(f"{{{BPMN}}}conditionExpression")
                flows.append(Flow(id=child.get("id", ""), source=child.get("sourceRef", ""),
                                        target=child.get("targetRef", ""), condition=condition.text if condition is not None else None))
                continue
            if tag not in _TAGS and tag != "subProcess":
                raise ValueError(f"Unsupported BPMN element: {tag}")
            config = child.find(f"{{{BPMN}}}extensionElements/{{{GALARIS}}}config")
            properties: dict[str, Any] = json.loads(config.text or "{}") if config is not None else {}
            declaration = {key: properties.pop(key) for key in ("inputs", "outputs") if key in properties}
            service_kind = properties.pop("activity_kind", None)
            kind = properties.pop("loop_kind", "for") if tag == "subProcess" else _TAGS[tag]
            if service_kind is not None:
                if (tag, service_kind) not in {("serviceTask", "rest"), ("scriptTask", "code")}:
                    raise ValueError("Unsupported service activity kind")
                kind = service_kind
            x, y = positions.get(child.get("id", ""), (0, 0))
            nodes.append({"id": child.get("id", ""), "kind": kind, "title": child.get("name", ""),
                "config": properties, **declaration, "x": x, "y": y, "body": parse(child) if tag == "subProcess" else None})
        return validate_graph(Workflow.model_validate({**props, "nodes": nodes, "flows": flows}))

    return parse(processes[0])


def to_bpmn(graph: Workflow, code: str = "workflow") -> str:
    validate_graph(graph)
    used: set[str] = set()
    bodies = [graph]
    while bodies:
        body = bodies.pop()
        used.update(node.id for node in body.nodes)
        used.update(flow.id for flow in body.flows)
        bodies.extend(node.body for node in body.nodes if node.body is not None)

    def identifier(base: str) -> str:
        candidate = base
        while candidate in used:
            candidate += "_"
        used.add(candidate)
        return candidate

    root = ET.Element(f"{{{BPMN}}}definitions", {"targetNamespace": GALARIS})
    process_key = identifier("Process_" + code)
    process = ET.SubElement(root, f"{{{BPMN}}}process", {"id": process_key, "isExecutable": "true"})
    diagram = ET.SubElement(root, f"{{{DI}}}BPMNDiagram", {"id": identifier("Diagram")})
    plane = ET.SubElement(diagram, f"{{{DI}}}BPMNPlane", {"id": identifier("Plane"), "bpmnElement": process_key})

    def write(parent: ET.Element, workflow: Workflow) -> None:
        ext = parent.find(f"{{{BPMN}}}extensionElements")
        if ext is None:
            ext = ET.SubElement(parent, f"{{{BPMN}}}extensionElements")
        ET.SubElement(ext, f"{{{GALARIS}}}workflow").text = json.dumps(workflow.model_dump(exclude={"nodes", "flows"}))
        if workflow.actors:
            lane_set = ET.SubElement(parent, f"{{{BPMN}}}laneSet", {"id": identifier("Lanes")})
            for actor in workflow.actors:
                lane = ET.SubElement(lane_set, f"{{{BPMN}}}lane", {"id": identifier("Lane_" + actor.id), "name": actor.name})
                for node in workflow.nodes:
                    if node.config.get("actor") == actor.id:
                        ET.SubElement(lane, f"{{{BPMN}}}flowNodeRef").text = node.id
        for node in workflow.nodes:
            tag = "subProcess" if node.body else "serviceTask" if node.kind == "rest" else "scriptTask" if node.kind == "code" else _TAGS_BACK[node.kind]
            element = ET.SubElement(parent, f"{{{BPMN}}}{tag}", {"id": node.id, "name": node.title})
            extension = ET.SubElement(element, f"{{{BPMN}}}extensionElements")
            config = {**node.config, **({"loop_kind": node.kind} if node.body else {})}
            if node.kind in {"rest", "code"}:
                config["activity_kind"] = node.kind
            if node.inputs is not None:
                config["inputs"] = [variable.model_dump(mode="json") for variable in node.inputs]
            if node.outputs is not None:
                config["outputs"] = [variable.model_dump(mode="json") for variable in node.outputs]
            ET.SubElement(extension, f"{{{GALARIS}}}config").text = json.dumps(config, ensure_ascii=False, allow_nan=False)
            if node.body:
                write(element, node.body)
            shape = ET.SubElement(plane, f"{{{DI}}}BPMNShape", {"id": identifier("Shape_" + node.id), "bpmnElement": node.id})
            ET.SubElement(shape, f"{{{DC}}}Bounds", {"x": str(node.x), "y": str(node.y), "width": "160", "height": "70"})
        for flow in workflow.flows:
            element = ET.SubElement(parent, f"{{{BPMN}}}sequenceFlow", {"id": flow.id, "sourceRef": flow.source, "targetRef": flow.target})
            if flow.condition is not None:
                ET.SubElement(element, f"{{{BPMN}}}conditionExpression").text = flow.condition
            edge = ET.SubElement(plane, f"{{{DI}}}BPMNEdge", {"id": identifier("Edge_" + flow.id), "bpmnElement": flow.id})
            for node in (workflow.node(flow.source), workflow.node(flow.target)):
                ET.SubElement(edge, f"{{{DD}}}waypoint", {"x": str(node.x + 80), "y": str(node.y + 35)})

    write(process, graph)
    return ET.tostring(root, encoding="unicode")
