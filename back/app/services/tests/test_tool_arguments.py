"""MCP argument correction preserves input contracts and execution results."""

import json

import pytest
from fastmcp import Client, FastMCP
from pydantic import BaseModel, ConfigDict

from app.services.contracts import EXECUTION_META_KEY
from app.services.execution_evidence import ExecutionEvidenceMiddleware
from app.services.tool_arguments import ToolArgumentsMiddleware, normalize_tool_arguments
from app.services.tool_errors import argument_validation_diagnostic
from app.agent import WorkPlan


@pytest.mark.parametrize("schema,expected", [
    ({"additionalProperties": False, "properties": {"value": {}}}, {"value": 3}),
    ({"properties": {"value": {}}}, {"value": 3, "extra": 4}),
    ({"additionalProperties": True}, {"value": 3, "extra": 4}),
    ({"additionalProperties": {"type": "integer"}}, {"value": 3, "extra": 4}),
    ({"additionalProperties": False, "patternProperties": {"^extra$": {}}}, {"extra": 4}),
    ({"additionalProperties": False, "allOf": [{"properties": {"value": {}}}]}, {"value": 3, "extra": 4}),
])
def test_only_undeclared_keys_in_closed_schemas_are_removed(schema, expected):
    original = {"value": 3, "extra": 4}
    normalized, ignored = normalize_tool_arguments(original, schema)
    assert normalized == expected
    assert set(ignored) == set(original) - set(expected)
    assert original == {"value": 3, "extra": 4}


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,successful", [
    ({"value": 3, "unused": "private"}, True),
    ({"unused": "private"}, False),
    ({"value": "bad", "unused": "private"}, False),
    ({"value": 3, "payload": {"value": 2, "unknown": 4}}, False),
])
async def test_unknown_arguments_do_not_bypass_required_type_or_nested_validation(arguments, successful):
    server = FastMCP("argument-validation")
    server.add_middleware(ToolArgumentsMiddleware())
    server.add_middleware(ExecutionEvidenceMiddleware({"write"}))
    calls = []

    @server.tool
    def write(value: int, payload: Payload | None = None) -> dict[str, int]:
        calls.append((value, payload))
        return {"saved": value}

    async with Client(server) as client:
        result = await client.call_tool("write", arguments, raise_on_error=False)
    assert result.is_error is not successful
    assert len(calls) == int(successful)
    assert result.meta[EXECUTION_META_KEY]["outcome"] == ("returned" if successful else "rejected")
    if "unused" in arguments:
        warning = json.loads(result.content[-1].text)
        assert warning["available_parameters"] == ["payload", "value"]
        assert warning["required_parameters"] == ["value"]
        assert warning["ignored_parameters"] == ["unused"]
        assert "private" not in result.content[-1].text
    if not successful:
        assert '"available_parameters": ["payload", "value"]' in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("defect,location,reason", [
    ("next_action", "plan", "Unfinished work must retain its next action"),
    ("observation", "plan.milestones.0", "requires an observed result"),
    ("state", "plan.milestones.0.state", "Input should be"),
])
async def test_work_plan_rejection_explains_nested_constraint_and_accepts_correction(defect, location, reason):
    server = FastMCP("work-plan-validation")
    server.add_middleware(ExecutionEvidenceMiddleware({"task_work_update"}))
    calls = []

    @server.tool(name="task_work_update")
    def update(plan: WorkPlan, expected_revision: int) -> dict[str, int]:
        calls.append(plan)
        return {"work_plan_revision": expected_revision + 1}

    milestone = {"key": "inspect", "label": "Inspect the synthetic input",
                 "acceptance": "The input can be read", "state": "doing"}
    plan = {"milestones": [milestone], "next_action": "Read the input"}
    if defect == "next_action":
        plan.pop("next_action")
    elif defect == "observation":
        milestone["state"] = "done"
    else:
        milestone["state"] = "synthetic-private-invalid-state"
    async with Client(server) as client:
        failure = await client.call_tool("task_work_update", {"plan": plan, "expected_revision": 0}, raise_on_error=False)
        assert failure.is_error
        assert calls == []
        assert failure.meta[EXECUTION_META_KEY]["outcome"] == "rejected"
        rendered = failure.content[0].text
        assert location in rendered
        assert reason in rendered
        assert "synthetic-private-invalid-state" not in rendered
        assert "Inspect the synthetic input" not in rendered
        milestone.update(state="done", observation="The synthetic input was read")
        plan["next_action"] = ""
        corrected = await client.call_tool("task_work_update", {"plan": plan, "expected_revision": 0})
        assert not corrected.is_error
        assert len(calls) == 1


def test_validation_diagnostics_exclude_inputs_context_and_bound_the_report():
    from pydantic import ValidationError, field_validator

    class SecretInput(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def reject(cls, value):
            raise ValueError("Invalid credential password=synthetic-private-password")

    with pytest.raises(ValidationError) as caught:
        SecretInput(value="synthetic-private-input")
    wrapped = RuntimeError("synthetic-private-wrapper")
    wrapped.__cause__ = caught.value
    details = argument_validation_diagnostic(wrapped)
    assert details[0]["path"] == "value"
    assert details[0]["type"] == "value_error"
    assert "Invalid credential" in details[0]["message"]
    assert "synthetic-private" not in json.dumps(details)
    assert argument_validation_diagnostic(RuntimeError("private fallback")) == []

    with pytest.raises(ValidationError) as many:
        WorkPlan.model_validate({"milestones": [{} for _ in range(20)]})
    assert len(argument_validation_diagnostic(many.value)) == 8
