"""Paired qualification must detect missing effects and preserve uncertainty."""

from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from app.lab.contracts import resolve_input
from app.lab.objective_checks import check_output
from app.tools.mcp_loader import load_mcp_tools
from core.util import validate_schema
from scripts.benchmark_operating_knowledge import aggregate, load_cases, case_checks, model_failure


@pytest.mark.parametrize("language", ["fr", "en"])
def test_operating_references_use_real_contracts_and_detect_each_missing_effect(language):
    corpus = json.loads((Path(__file__).parents[1] / f"operating_knowledge_corpus_{language}.json").read_text())
    functions = {definition.name: definition.function for definition in load_mcp_tools()}
    schemas = {spec["name"]: spec["parameters"] for spec in corpus["parameters"]["tool_catalog"]}
    for case in corpus["cases"]:
        _, native = resolve_input(corpus["mechanism"], case["input_data"], corpus["parameters"])
        expected = case["expected_output"]
        if case["name"] == "goal_revision_conflict":
            receipts = native["tool_responses"]
            # Pausing must preserve the concurrent title observed on the fresh read.
            assert receipts["goal_pause"][1]["title"] == receipts["file_read"][1]["title"]
        checks = check_output(corpus["mechanism"], native, expected, expected=expected)
        assert all(row["passed"] for row in checks), (case["name"], checks)
        for index, call in enumerate(expected["tool_calls"]):
            inspect.signature(functions[call["name"]]).bind(object(), **call["arguments"])
            validate_schema(call["arguments"], schemas[call["name"]])
            missing = deepcopy(expected)
            del missing["tool_calls"][index]
            del missing["tool_results"][index]
            assert not all(row["passed"] for row in check_output(
                corpus["mechanism"], native, missing, expected=expected)), case["name"]


def test_qualification_uses_multiple_domains_and_both_foreground_modes():
    cases = load_cases()
    assert len({case["key"] for case in cases}) == len(cases)
    assert {case["mechanism"] for case in cases} == {"task_executor", "conversation_executor", "voice_executor"}
    assert {case["native"]["language"] for case in cases} == {"fr", "en"}
    for case in cases:
        assert "outcome_checks" in case["expected"]
        if case["key"].startswith("latency_"):
            assert not all(row["passed"] for row in case_checks(case, {
                "action": "reply", "response": "Invented success", "tool_calls": [], "tool_results": []})), case["key"]


def test_pairing_excludes_missing_arms_and_clusters_repetitions():
    def row(key, repetition, variant, passed):
        return {"case": key, "repetition": repetition, "variant": variant, "passed": passed,
                "categories": ["synthetic"], "seconds": 1, "tool_calls_count": 1,
                "cost": {"recorded_cost": .01, "unknown_calls": 0}}
    results = [row("improved", i, variant, variant == "after") for i in range(3) for variant in ("before", "after")]
    results += [row("regressed", i, variant, variant == "before") for i in range(3) for variant in ("before", "after")]
    results.append(row("unpaired", 0, "after", True))
    report = aggregate(results, planned=14)
    assert not report["complete"]
    assert report["paired"]["cases"] == 2
    assert report["paired"]["wins"] == report["paired"]["losses"] == 3
    assert report["paired"]["mean_case_delta"] == 0


@pytest.mark.parametrize("response,passed", [("16h00", True), ("16:00", True), ("16 h", True), ("16h30", False), ("17:00", False)])
def test_clock_fact_checks_accept_equivalent_notation_but_reject_a_different_time(response, passed):
    case = {"mechanism": "task_executor", "native": {"available_tools": []},
            "expected": {"outcome_checks": {"response_values": ["16:00"]}}}
    actual = {"response": response, "tool_calls": [], "tool_results": []}
    assert all(row["passed"] for row in case_checks(case, actual)) == passed
    assert actual["response"] == response


def test_exhausted_simulation_is_a_model_failure_but_other_value_errors_stop_the_campaign():
    assert model_failure(ValueError("The tool response fixture is exhausted"))
    assert not model_failure(ValueError("Invalid frozen model configuration"))
    assert not model_failure(TimeoutError())


def test_translations_share_a_statistical_cluster_and_outages_do_not_count_as_prompt_regressions():
    def row(key, name, variant, passed, **extra):
        return {"case": key, "name": name, "repetition": 1, "variant": variant, "passed": passed,
                "categories": [], "seconds": 1, "cost": {"recorded_cost": 0, "unknown_calls": 0}, **extra}
    rows = [row(language, f"example-{language}", variant, variant == "after")
            for language in ("fr", "en") for variant in ("before", "after")]
    rows += [row("outage", "unrelated", "before", False, error_type="TimeoutError"),
             row("outage", "unrelated", "after", True)]
    report = aggregate(rows, planned=6)
    assert report["paired"]["cases"] == 2
    assert report["paired"]["scenario_clusters"] == 1
    assert report["paired"]["excluded_infrastructure_pairs"] == 1
    assert report["paired"]["mean_case_delta"] == 1
