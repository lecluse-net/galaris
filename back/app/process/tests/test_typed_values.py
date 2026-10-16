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
    ("Agent", 101), ("User", 102), ("File", "nextcloud://Shared/synthetic.pdf"),
    ("Document", "document://00000000-0000-4000-8000-000000000001"),
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


@pytest.mark.parametrize("boundary", ["external", "human_reply"])
@pytest.mark.parametrize("business_object", [{"nested": {"type": "File", "value": "ordinary text"}}, {"type": "int", "value": 7}])
def test_external_json_objects_do_not_infer_envelopes_from_business_keys(boundary, business_object):
    from app.process.values import external_outputs, unwrap
    from app.process.facade import normalize_human_reply
    declarations = [Variable(name="result", type="object", nullable=False)]
    raw = {"result": business_object}
    if boundary == "human_reply":
        def adapt(values, *, typed_values=False):
            return normalize_human_reply([item.model_dump(mode="json") for item in declarations], values, typed_values=typed_values)
    else:
        def adapt(values, *, typed_values=False):
            return external_outputs(declarations, values, path="api.output", typed_values=typed_values)
    adapted = adapt(raw)
    assert unwrap(adapted["result"]) == raw["result"]
    typed = {"result": {"type": "object", "value": {"file": {"type": "File", "value": None}}}}
    assert adapt(typed, typed_values=True) == typed


@pytest.mark.parametrize("kind", sorted(ACTIVITY_KINDS))
def test_every_activity_preserves_its_own_declarations_and_defaults_in_xml(kind):
    configuration = {"prompt": "Synthetic work", "tool": "synthetic", "tool_code": "synthetic", "process_code": "synthetic", "code": "output = {}"}
    config = deepcopy(configuration)
    if kind == "human_task":
        config["actor"] = "reviewer"
    definition = Workflow(schema_version="galaris.bpmn/v2", inputs=[], outputs=[],
        actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=101)],
        nodes=[Node(id="start", kind="start"), Node(id="work", kind=kind, config=config,
            inputs=[Variable(name="source", type="File", nullable=True)],
            outputs=[Variable(name="accepted", type="bool", nullable=False, default={"type": "bool", "value": False})]),
            Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="work"), Flow(id="b", source="work", target="end")])
    assert compile_bpmn(to_bpmn(definition)).model_dump() == definition.model_dump()
    definition.nodes[1].outputs = None
    with pytest.raises(ValueError, match="requires explicit"):
        to_bpmn(definition)
