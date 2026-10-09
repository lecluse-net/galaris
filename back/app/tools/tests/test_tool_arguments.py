"""MCP argument correction preserves input contracts and execution results."""

import json

import pytest
from fastmcp import Client, FastMCP
from pydantic import BaseModel, ConfigDict

from app.tools.contracts import EXECUTION_META_KEY
from app.tools.execution_evidence import ExecutionEvidenceMiddleware
from app.tools.tool_arguments import ToolArgumentsMiddleware, normalize_tool_arguments


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
