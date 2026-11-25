"""Paired qualification must detect missing effects and preserve uncertainty."""

from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from app.lab.contracts import resolve_input
from app.lab.objective_checks import check_output
from app.services.mcp_loader import load_mcp_tools
from core.util import validate_schema
from scripts.benchmark_operating_knowledge import aggregate, load_cases, case_checks, model_failure, digest, prompt_baseline
from scripts.benchmark_operating_knowledge import performance_summary, reported_tokens


@pytest.mark.parametrize("language", ["fr", "en"])
@pytest.mark.parametrize("mechanism", ["conversation_executor", "voice_executor"])
def test_capability_oracles_detect_missing_attempts_and_forbidden_or_unnecessary_tasks(language, mechanism):
    cases = [case for case in load_cases() if case["mechanism"] == mechanism
             and case["name"].startswith("capability-") and case["name"].endswith(f"-{language}")]
    assert len(cases) == 8
    for case in cases:
        reference = case["expected"]
        assert all(row["passed"] for row in case_checks(case, reference)), case["name"]
        broken = deepcopy(reference)
        if reference["outcome_checks"].get("required_calls"):
            broken["tool_calls"] = []
            broken["tool_results"] = []
        else:
            arguments = {"objective": "<p>Unrequested work.</p>"}
            broken["tool_calls"] = [{"name": "task_submit", "arguments": arguments}]
            broken["tool_results"] = [{"name": "task_submit", "arguments": arguments,
                                       "result": {"created": True}}]
        assert not all(row["passed"] for row in case_checks(case, broken)), case["name"]


@pytest.mark.parametrize("field", ["available_tools", "task_only_services", "available_processes", "resources"])
def test_case_inventory_can_inherit_or_explicitly_clear_shared_context(field):
    corpus = json.loads((Path(__file__).parents[1] / "latency_corpus_en.json").read_text())
    parameters = {**corpus["parameters"], field: (["memory_search"] if field == "available_tools"
                  else [{"code": "shape_lab"}] if field == "task_only_services" else [{"source": "synthetic"}])}
    _, inherited = resolve_input("conversation_executor", {"variable_value": "Synthetic request."}, parameters)
    _, cleared = resolve_input("conversation_executor", {
        "variable_value": "Synthetic request.", "context": {field: []}}, parameters)
    assert inherited[field] == parameters[field]
    assert cleared[field] == []


@pytest.mark.parametrize("change", [None, "prompt", "input", "binding", "effort"])
def test_complete_prompt_comparison_requires_unchanged_frozen_evidence(tmp_path, change):
    case = {"key": "synthetic", "native": {"message": "Try the work.", "available_tools": ["task_submit"]}}
    prompts = {"synthetic": {"before": "Old control.", "after": "Original complete production prompt."}}
    manifest = {"cases_sha256": digest([case]), "prompts_sha256": digest(prompts),
                "model_binding": "synthetic-binding", "reasoning_effort": None, "builder_sha256": "synthetic-builder"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "cases.json").write_text(json.dumps([case]))
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(prompts))
    selected = deepcopy(case)
    if change == "prompt":
        path.write_text(json.dumps({"synthetic": {"after": "Changed prompt."}}))
    if change == "input":
        selected["native"]["available_tools"] = []
    arguments = {"binding": "other" if change == "binding" else "synthetic-binding",
                 "effort": "high" if change == "effort" else None}
    if change:
        with pytest.raises(ValueError):
            prompt_baseline(path, [selected], **arguments)
    else:
        result, evidence = prompt_baseline(path, [selected], **arguments)
        assert result == {"synthetic": prompts["synthetic"]["after"]}
        assert evidence["prompts_sha256"] == manifest["prompts_sha256"]


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
        if case["name"] == "goal_create":
            # A successful creation receipt must describe what was requested;
            # a conflicting fixture legitimately triggers corrective tool calls.
            arguments = expected["tool_calls"][0]["arguments"]
            for receipt in (native["tool_responses"]["goal_create"][0], expected["tool_results"][0]["result"]):
                assert {key: receipt[key] for key in ("agent_id", "title", "description")} == {
                    key: arguments[key] for key in ("agent_id", "title", "description")}
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
            oracle = case["expected"]["outcome_checks"]
            if oracle.get("required_calls") or oracle.get("response_values"):
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


@pytest.mark.parametrize("identifier,passed", [
    ("00000000-0000-0000-0000-000000000041", True),
    ("galaris://task/00000000-0000-0000-0000-000000000041", True),
    ("00000000-0000-0000-0000-000000000042", False),
])
def test_task_status_oracle_accepts_both_public_reference_forms_without_changing_raw_evidence(identifier, passed):
    case = next(case for case in load_cases() if case["key"] == "latency_corpus_en.json/3/conversation_executor")
    arguments = {"task_id": identifier}
    actual = {"action": "read_status", "response": "Running.",
              "tool_calls": [{"name": "task_status", "arguments": arguments}],
              "tool_results": [{"name": "task_status", "arguments": arguments,
                                "result": {"status": "RUNNING"}}]}
    before = deepcopy(actual)
    assert all(row["passed"] for row in case_checks(case, actual)) == passed
    assert actual == before


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


def test_request_and_round_measurements_do_not_treat_unreported_cache_or_usage_as_zero():
    def request(input_tokens, output_tokens, cache_read_tokens):
        return dict(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cache_read_tokens)

    rows = [
        {"requests": [request(10, 2, 0), request(20, 3, 8)],
         "performance": {"performance": {"first_output_seconds": 0.2, "first_text_seconds": 1.5}}},
        {"requests": [request(None, None, None), request(15, 4, 0)],
         "performance": {"performance": {"first_output_seconds": 0.3}}},
        {"seconds": 3},  # Existing reports can be rescored without new gateway traces.
    ]
    result = performance_summary(rows)
    assert result["requests_per_round"] == {"measurements": 2, "median": 2, "total": 4}
    assert result["tokens_per_request"]["input_tokens"] == {"measurements": 3, "median": 15, "total": 45}
    assert result["tokens_per_request"]["cache_read_tokens"] == {"measurements": 3, "median": 0, "total": 8}
    assert result["tokens_per_round"]["input_tokens"] == {"measurements": 1, "median": 30, "total": 30}
    assert result["tokens_per_round"]["cache_read_tokens"] == {"measurements": 1, "median": 8, "total": 8}
    assert result["first_text_seconds"] == {"measurements": 1, "median": 1.5, "total": 1.5}
    assert reported_tokens(0, None) is None
    assert reported_tokens(0, 0) == 0
    assert reported_tokens(8) == 8
