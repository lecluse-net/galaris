"""Deterministic output checks whose failures cannot be overridden by a judge."""

from typing import Any, cast
from dataclasses import replace
from .mechanism_registry import get_mechanism
from app.agent import resolve_pipeline_policy


def check_output(mechanism: str, native: Any, output: Any) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(code: str, passed: bool, detail: str) -> None:
        checks.append({"code": code, "passed": passed, "detail": detail, "critical": True})

    try:
        get_mechanism(mechanism).validate_output(output)
        check("output_schema", True, "Output matches the declared contract")
    except ValueError as exc:
        check("output_schema", False, str(exc))
        return checks
    if mechanism == "topic_classification":
        check(
            "topic_alignment",
            len(output["topics"]) == len(native["messages"]),
            "Exactly one Topic per input message",
        )
    elif mechanism == "dispatcher":
        check(
            "active_route",
            output.get("route") in {"EXEC", "PLAN"},
            "Active Task routes are EXEC and PLAN",
        )
        policy = resolve_pipeline_policy(native.get("driver_code") or "internal")
        if native.get("pipeline_policy"):
            policy = replace(policy, **native["pipeline_policy"])
        check(
            "harness_choice",
            (output.get("route"), output.get("effort")) in policy.dispatch_choices(),
            "The route/effort pair must be exposed by the selected harness",
        )
        for key, field in (("forced_route", "route"), ("forced_effort", "effort")):
            if native.get(key):
                check(
                    key,
                    output.get(field) == native[key],
                    "Forced routing constraints must be respected",
                )
    elif mechanism == "planner":
        has_questions = bool(output.get("clarification_questions"))
        has_steps = bool(output.get("steps"))
        has_brief = bool(output.get("brief"))
        check(
            "plan_completeness",
            (has_questions and not has_steps and not has_brief)
            or (not has_questions and has_steps and has_brief),
            "Return a brief and executable steps, or clarification questions without a plan",
        )

        def sizes(steps: list[dict[str, Any]], depth: int = 1) -> tuple[int, int]:
            leaves = 0
            maximum = depth if steps else 0
            for step in steps:
                children = cast(list[dict[str, Any]], step.get("steps", step.get("children", [])))
                ends, level = sizes(children, depth + 1)
                leaves += ends if children else 1
                maximum = max(maximum, level)
                if step.get("collection"):
                    maximum = max(maximum, depth + 1)
            return leaves, maximum

        leaves, depth = sizes(output.get("steps", []))
        check(
            "plan_limits",
            leaves <= native["max_leaves"]
            and depth <= native["max_depth"],
            "Plan depth and leaf budgets",
        )
        check(
            "clarification_policy",
            native["can_clarify"] or not output.get("clarification_questions"),
            "Clarification requires permission",
        )
    elif mechanism == "memory_extraction":
        allowed = {str(memory["id"]) for memory in native["existing_memories"]}
        targets = [
            str(op["target_memory_id"])
            for op in output.get("operations", [])
            if op.get("action") == "LINK"
        ]
        check(
            "memory_links",
            set(targets) <= allowed and len(targets) == len(set(targets)),
            "LINK targets belong to the provided corpus and are unique",
        )
    elif mechanism.endswith("_executor"):
        results = output.get("tool_results", [])
        calls = output.get("tool_calls", [])
        check("tool_evidence", len(calls) == len(results), "Every tool call has a recorded result")
        if mechanism == "task_executor":
            allowed = set(native.get("available_tools", []))
            check(
                "allowed_task_tools",
                all(call.get("arguments", {}).get("tool_name") in allowed for call in calls),
                "Requested Task tools belong to the supplied catalog",
            )
    return checks
