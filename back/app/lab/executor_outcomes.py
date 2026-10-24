"""Case-owned, deterministic outcome oracles, never sent to the candidate model."""

from collections.abc import Mapping
import json
from typing import Annotated, Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class RequiredCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    argument_values: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    argument_any_values: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    argument_forbidden_values: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    argument_json: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    successful: bool = True


class OutcomeChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_calls: list[RequiredCall] = Field(default_factory=list[RequiredCall], max_length=30)
    ordered_calls: bool = True
    forbidden_tools: list[str] = Field(default_factory=list[str], max_length=100)
    max_tool_calls: int | None = Field(default=None, ge=0, le=100)
    tool_call_limits: dict[str, Annotated[int, Field(ge=0, le=100)]] = Field(default_factory=dict[str, int])
    response_values: list[str] = Field(default_factory=list[str], max_length=30)


def selected_call(call: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Normalize the Task recorder and native foreground calls for the same oracle."""
    raw_arguments = call.get("arguments", {})
    if not isinstance(raw_arguments, dict):
        return "", {}
    arguments = cast(dict[str, Any], raw_arguments)
    if call.get("name") == "executor_tool_call":
        nested = arguments.get("arguments", {})
        return str(arguments.get("tool_name", "")), cast(dict[str, Any], nested) if isinstance(nested, dict) else {}
    return str(call.get("name", "")), arguments


def contains_json(actual: Any, expected: JsonValue) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and contains_json(actual[key], value)
                                               for key, value in expected.items())
    # JSON true must never satisfy a revision, amount or count of 1.
    return type(actual) is type(expected) and actual == expected


def _successful(result: object) -> bool:
    if not isinstance(result, dict):
        return True
    mapping = cast(dict[str, Any], result)
    return not (mapping.get("success") is False or bool(mapping.get("error")))


def _json_contains(actual: object, expected: JsonValue) -> bool:
    if not isinstance(actual, str):
        return False
    try:
        return contains_json(json.loads(actual), expected)
    except ValueError:
        return False


def outcome_checks(output: dict[str, Any], expected: object) -> list[dict[str, Any]]:
    if not isinstance(expected, dict) or "outcome_checks" not in expected:
        return []
    oracle = OutcomeChecks.model_validate(expected["outcome_checks"])
    calls = [selected_call(call) for call in output.get("tool_calls", [])]
    results = [row.get("result") for row in output.get("tool_results", [])]
    checks: list[dict[str, Any]] = []

    def check(code: str, passed: bool, detail: str) -> None:
        checks.append({"code": code, "passed": passed, "detail": detail, "critical": True})

    candidates = [
        [position for position in range(len(calls))
                      if calls[position][0] == required.tool
                      and contains_json(calls[position][1], required.arguments)
                      and position < len(results)
                      and _successful(results[position]) == required.successful
                      and all(_json_contains(calls[position][1].get(key), value)
                              for key, value in required.argument_json.items())
                      and all(isinstance(calls[position][1].get(key), str)
                              and not any(value in calls[position][1][key] for value in values)
                              for key, values in required.argument_forbidden_values.items())
                      and all(isinstance(calls[position][1].get(key), str)
                              and all(value in calls[position][1][key] for value in values)
                              for key, values in required.argument_values.items())
                      and all(isinstance(calls[position][1].get(key), str)
                              and any(value in calls[position][1][key] for value in values)
                              for key, values in required.argument_any_values.items())]
        for required in oracle.required_calls
    ]
    assigned: dict[int, int] = {}

    def assign(index: int, visited: set[int]) -> bool:
        for position in candidates[index]:
            if position in visited:
                continue
            visited.add(position)
            if position not in assigned or assign(assigned[position], visited):
                assigned[position] = index
                return True
        return False

    cursor = 0
    for index, required in enumerate(oracle.required_calls):
        if oracle.ordered_calls:
            found = next((position for position in candidates[index] if position >= cursor), None)
            passed = found is not None
            if found is not None:
                cursor = found + 1
        else:
            passed = assign(index, set())
        check(f"outcome_call_{index + 1}", passed,
              f"Required distinct effect: {required.tool}, with the case's target and arguments")
    check("outcome_forbidden_tools", not any(name in oracle.forbidden_tools for name, _ in calls),
          "No case-forbidden effect, redundant resource or unauthorized alternative")
    if oracle.max_tool_calls is not None:
        check("outcome_call_budget", len(calls) <= oracle.max_tool_calls, "Case-owned bound on unnecessary actions")
    for name, limit in oracle.tool_call_limits.items():
        check(f"outcome_limit_{name}", sum(tool == name for tool, _ in calls) <= limit,
              "No duplicate effect beyond the case's allowed function count")
    response = str(output.get("response", ""))
    for index, value in enumerate(oracle.response_values):
        check(f"outcome_fact_{index + 1}", value in response, "Required exact factual value or canonical reference preserved")
    return checks
