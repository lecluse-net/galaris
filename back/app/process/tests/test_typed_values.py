"""Every activity shares one strict JSON transport and omission policy."""

from copy import deepcopy
import json

from pydantic import ValidationError
import pytest

from app.process.values import (VALUE_TYPES, MAX_INTEGER, Variable, ValueContractError,
    loads_values, normalize, validate_value)
from app.process.bpmn import ACTIVITY_KINDS, Actor, Flow, Node, Workflow, compile_bpmn, to_bpmn


@pytest.mark.parametrize("kind,value", [
    ("int", 0), ("float", 1), ("float", 0.25), ("bool", False), ("string", "é"),
    ("date", "2000-02-29"), ("date", "1992-10-24"),
    ("datetime", "2026-11-08T14:30:00Z"), ("datetime", "2026-11-08T14:30:00.123456+01:00"),
    ("datetime", "2026-11-08T14:30:00-05:30"),
    ("Agent", 101), ("User", 102), ("File", "nextcloud://Shared/synthetic.pdf"),
    ("Document", "document://00000000-0000-4000-8000-000000000001"),
    ("Document", "data://00000000-0000-4000-8000-000000000001"),
    *[(kind, 101) for kind in ("Team", "Tool", "Connection", "Model", "Skill")],
    *[(kind, "00000000-0000-4000-8000-000000000001") for kind in ("Topic", "Conversation", "VoiceSession")],
    *[(kind, f"galaris://{collection}/00000000-0000-4000-8000-000000000001") for kind, collection in (
        ("Task", "task"), ("Goal", "goal"), ("GoalCycle", "goal_cycle"), ("Contact", "contact"),
        ("ConversationRound", "text"), ("VoiceConversation", "voice"), ("CodeWorkspace", "code"))],
    ("Memory", "memory://00000000-0000-4000-8000-000000000001"),
    ("Process", "galaris://process/synthetic_process"),
    ("ProcessRun", "galaris://processes/runs/00000000-0000-4000-8000-000000000001"),
    ("array", []), ("object", {}),
])
def test_typed_values_roundtrip_and_do_not_replace_false_or_empty_values(kind, value):
    declaration = Variable(name="result", type=kind, nullable=True,
        default={"type": kind, "value": None})
    transmitted = {"result": {"type": kind, "value": value}}
    assert normalize([declaration], json.loads(json.dumps(transmitted)), path="activity.output") == transmitted
    assert normalize([declaration], {}, path="activity.output") == {"result": {"type": kind, "value": None}}
    assert loads_values(json.dumps(transmitted), path="activity.output") == transmitted


@pytest.mark.parametrize("kind", sorted(VALUE_TYPES))
def test_every_type_can_be_omitted_if_nullable_but_not_if_notnull(kind):
    nullable = Variable(name="result", type=kind, nullable=True)
    assert normalize([nullable], {}, path="work.output") == {"result": {"type": kind, "value": None}}
    assert normalize([Variable.model_validate(nullable.model_dump())], {}, path="work.output") == {"result": {"type": kind, "value": None}}
    notnull = Variable(name="result", type=kind, nullable=False)
    with pytest.raises(ValueContractError, match="work.output.result.*missing"):
        normalize([notnull], {}, path="work.output")
    with pytest.raises(ValueContractError, match="null is not allowed"):
        normalize([notnull], {"result": {"type": kind, "value": None}}, path="work.output")


def test_defaults_apply_only_to_absence_and_are_copied_for_each_invocation():
    declaration = Variable(name="items", type="array", nullable=True,
        default={"type": "array", "value": [{"type": "object", "value": {"amount": {"type": "int", "value": 1}}}]})
    first = normalize([declaration], {}, path="work.input")
    first["items"]["value"][0]["value"]["amount"]["value"] = 7
    assert normalize([declaration], {}, path="work.input")["items"]["value"][0]["value"]["amount"]["value"] == 1
    assert normalize([declaration], {"items": {"type": "array", "value": None}}, path="work.input")["items"]["value"] is None
    with pytest.raises(ValueContractError, match="expected type array"):
        normalize([declaration], {"items": {"type": "int", "value": 1}}, path="work.input")


@pytest.mark.parametrize("envelope", [
    {"type": "int", "value": True}, {"type": "int", "value": 1.0},
    {"type": "int", "value": MAX_INTEGER + 1}, {"type": "float", "value": float("inf")},
    {"type": "int", "value": "1"}, {"type": "bool", "value": 0},
    {"type": "User", "value": 0}, {"type": "Date", "value": None},
    {"type": "File", "value": "/tmp/synthetic.pdf"}, {"type": "File", "value": "nextcloud://Shared/"},
    {"type": "Document", "value": "nextcloud://Shared/synthetic.pdf"},
    {"type": "array", "value": [1]}, {"type": "object", "value": {"untyped": False}},
    {"type": "int"}, {"type": "int", "value": 1, "extra": "ignored?"},
    {"type": "Task", "value": "galaris://goal/00000000-0000-4000-8000-000000000001"},
    {"type": "ProcessRun", "value": "galaris://processes/runs/not-a-uuid"},
    {"type": "Conversation", "value": "invalid"}, {"type": "Team", "value": -1},
    {"type": "Skill", "value": "synthetic"}, {"type": "Memory", "value": "document://00000000-0000-4000-8000-000000000001"},
    *[{"type": "date", "value": value} for value in
        ("", 123, True, "2001-02-29", "2026-04-31", "0000-01-01", "2026-1-01", "08/11/2026", "20261108", "2026-11-08T00:00:00Z")],
    *[{"type": "datetime", "value": value} for value in
        ("", 123, "2026-11-08", "2026-11-08T14:30:00", "2026-11-08T14:30Z", "2026-02-30T14:30:00Z",
         "2026-11-08T24:00:00Z", "2026-11-08T14:30:00+24:00", "2026-11-08T14:30:00+01:60", "2026-11-08 14:30:00Z")],
])
def test_invalid_values_cannot_cross_the_boundary(envelope):
    with pytest.raises(ValueContractError):
        validate_value(envelope)


def test_invalid_declarations_fail_before_any_activity_runs():
    for default in (None, {"type": "int", "value": None}, {"type": "string", "value": "1"}):
        with pytest.raises(ValidationError):
            Variable(name="amount", type="int", nullable=False, default=default)
    with pytest.raises(ValueContractError, match="duplicate"):
        normalize([Variable(name="x", type="int", nullable=True)] * 2, {}, path="work")
    with pytest.raises(ValueContractError, match="undeclared"):
        normalize([], {"extra": {"type": "int", "value": 1}}, path="work.output")
    assert normalize([], {"extra": {"type": "int", "value": 1}}, path="work.input", allow_extra=True) == {}
    with pytest.raises(ValueContractError, match="duplicate JSON key"):
        loads_values('{"x":{"type":"int","value":1,"value":2}}', path="work")


@pytest.mark.parametrize("boundary", ["external", "human_reply", "launch"])
@pytest.mark.parametrize("business_object", [{"nested": {"type": "File", "value": "ordinary text"}}, {"type": "int", "value": 7}])
def test_external_json_objects_do_not_infer_envelopes_from_business_keys(boundary, business_object):
    from app.process.values import external_outputs, unwrap
    from app.process.facade import normalize_human_reply
    declarations = [Variable(name="result", type="object", nullable=False)]
    raw = {"result": business_object}
    if boundary == "human_reply":
        def adapt(values, *, typed_values=False):
            return normalize_human_reply([item.model_dump(mode="json") for item in declarations], values, typed_values=typed_values)
    elif boundary == "launch":
        from app.process.values import conversational_patch
        def adapt(values, *, typed_values=False):
            return conversational_patch(declarations, values, path="process.input", typed_values=typed_values)
    else:
        def adapt(values, *, typed_values=False):
            return external_outputs(declarations, values, path="api.output", typed_values=typed_values)
    adapted = adapt(raw)
    assert unwrap(adapted["result"]) == raw["result"]
    typed = {"result": {"type": "object", "value": {"file": {"type": "File", "value": None}}}}
    assert adapt(typed, typed_values=True) == typed


@pytest.mark.parametrize("kind", sorted(ACTIVITY_KINDS))
def test_every_activity_uses_process_declarations_and_preserves_them_in_xml(kind):
    configuration = {"prompt": "Synthetic work", "tool": "synthetic", "tool_code": "synthetic", "process_code": "synthetic", "code": "output = {}"}
    config = deepcopy(configuration)
    if kind == "human_task":
        config["actor"] = "reviewer"
    definition = Workflow(schema_version="galaris.bpmn/v2", variables=[
        Variable(name="source", type="File", nullable=True),
        Variable(name="accepted", type="bool", nullable=False, default={"type": "bool", "value": False})],
        actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=101)],
        nodes=[Node(id="start", kind="start"), Node(id="work", kind=kind, config=config),
            Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="work"), Flow(id="b", source="work", target="end")])
    assert compile_bpmn(to_bpmn(definition)).model_dump() == definition.model_dump()
    with pytest.raises(ValidationError):
        Node.model_validate({**definition.nodes[1].model_dump(), "outputs": [{"name": "local", "type": "int"}]})


def test_process_defaults_initialize_once_and_partial_updates_preserve_omissions():
    from app.process.values import initialize_variables, normalize_patch, normalize_reply, external_patch
    declarations = [Variable(name="count", type="int", nullable=False, default={"type": "int", "value": 0}),
        Variable(name="accepted", type="bool", nullable=True), Variable(name="later", type="string", nullable=False)]
    initial = initialize_variables(declarations, {"accepted": {"type": "bool", "value": None}})
    assert initial == {"count": {"type": "int", "value": 0}, "accepted": {"type": "bool", "value": None}}
    assert normalize_patch(declarations, {}, path="activity") == {}
    assert external_patch(declarations, {"accepted": False}, path="activity") == {"accepted": {"type": "bool", "value": False}}
    for declaration in declarations:
        with pytest.raises(ValueContractError, match="missing requested"):
            normalize_reply([declaration], {}, path="question")
    for normalize_changes in (normalize_patch, external_patch):
        with pytest.raises(ValueContractError, match="undeclared"):
            normalize_changes(declarations, {"unknown": 1}, path="activity")
    with pytest.raises(ValueContractError, match="null is not allowed"):
        normalize_patch(declarations, {"later": {"type": "string", "value": None}}, path="activity")


@pytest.mark.parametrize("options", [
    {"type": "File", "document_format": "text"}, {"type": "Document", "mime_type": "application/pdf"},
    {"type": "File", "mime_type": "image"}, {"type": "File", "mime_type": "text/html; charset=utf-8"},
    {"type": "Document", "document_format": "process"},
    {"type": "Document", "document_format": "data", "default": {"type": "Document", "value": "document://00000000-0000-4000-8000-000000000001"}},
])
def test_variable_constraints_cannot_be_applied_to_an_unrelated_type(options):
    with pytest.raises(ValidationError):
        Variable(name="resource", nullable=True, **options)


def test_resource_constraints_survive_bpmn_save_and_reload():
    definition = Workflow(schema_version="galaris.bpmn/v2", variables=[
        Variable(name="attachment", type="File", nullable=True, mime_type="image/*"),
        Variable(name="report", type="Document", nullable=True, document_format="data")],
        nodes=[Node(id="start", kind="start"), Node(id="end", kind="end")], flows=[Flow(id="a", source="start", target="end")])
    assert compile_bpmn(to_bpmn(definition)).model_dump() == definition.model_dump()


def test_temporal_variables_survive_bpmn_and_human_answers_without_timezone_conversion():
    from app.process.facade import normalize_human_reply
    from app.process.values import external_outputs, unwrap
    values = {"birth_date": {"type": "date", "value": "2000-02-29"},
        "appointment": {"type": "datetime", "value": "2026-11-08T14:30:00+01:00"}}
    variables = [Variable(name=name, type=value["type"], nullable=False, default=value) for name, value in values.items()]
    graph = Workflow(schema_version="galaris.bpmn/v2", variables=variables,
        nodes=[Node(id="start", kind="start"), Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="end")])
    restored = compile_bpmn(to_bpmn(graph))
    assert restored.model_dump() == graph.model_dump()
    assert normalize(restored.variables, {}, path="process.input") == values
    declarations = [variable.model_dump(mode="json") for variable in restored.variables]
    raw = {name: unwrap(value) for name, value in values.items()}
    assert normalize_human_reply(declarations, raw) == values
    assert external_outputs(restored.variables, raw, path="activity.output") == values
    for name in values:
        invalid = {**raw, name: "2001-02-29"}
        with pytest.raises(ValueContractError):
            normalize_human_reply(declarations, invalid)


def test_variable_bindings_are_only_names_and_share_the_registry_in_inline_bodies():
    from app.process.bpmn import validate_graph, activity_variables
    body = Workflow(schema_version="galaris.bpmn/v2", nodes=[Node(id="begin", kind="start", inputs=["source"]),
        Node(id="inside", kind="task", inputs=["source"], outputs=["answer"], config={"prompt": "Synthetic work"}),
        Node(id="finish", kind="end", outputs=["answer"])], flows=[Flow(id="ba", source="begin", target="inside"), Flow(id="bb", source="inside", target="finish")])
    graph = Workflow(schema_version="galaris.bpmn/v2", variables=[
        Variable(name="source", type="array", nullable=False), Variable(name="answer", type="string", nullable=True)],
        nodes=[Node(id="start", kind="start", inputs=["source"]),
            Node(id="loop", kind="for", inputs=["source"], outputs=["answer"], config={"items": "data.source.value"}, body=body),
            Node(id="end", kind="end", outputs=["answer"])], flows=[Flow(id="a", source="start", target="loop"), Flow(id="b", source="loop", target="end")])
    assert compile_bpmn(to_bpmn(graph)).model_dump() == graph.model_dump()
    assert graph.inputs == ["source"]
    assert "inputs" not in graph.model_dump()
    assert "outputs" not in graph.model_dump()
    assert activity_variables(graph, graph.nodes[1], direction="inputs") == [graph.variables[0]]
    for owner in [graph, graph.nodes[1], body.nodes[1]]:
        for names in (["missing"], ["source", "source"]):
            copy = graph.model_copy(deep=True)
            target = copy if owner is graph else copy.nodes[1] if owner is graph.nodes[1] else copy.nodes[1].body.nodes[1]
            target.inputs = names
            with pytest.raises(ValueError, match="unique declared"):
                validate_graph(copy)


@pytest.mark.parametrize("kind,direction", [("if", "outputs"), ("start", "outputs"), ("end", "inputs")])
def test_control_nodes_reject_forbidden_variable_bindings(kind, direction):
    from app.process.bpmn import validate_graph
    graph = Workflow(schema_version="galaris.bpmn/v2", variables=[Variable(name="value", type="int", nullable=True)],
        nodes=[Node(id="start", kind="start"), Node(id="check", kind="if"), Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="check"), Flow(id="b", source="check", target="end")])
    setattr(next(node for node in graph.nodes if node.kind == kind), direction, ["value"])
    with pytest.raises(ValueError, match=f"{kind} nodes cannot have"):
        validate_graph(graph)
