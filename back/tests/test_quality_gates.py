"""Negative controls: the gates must reject plausible but insufficient evidence."""

import json
import sys

import pytest

from scripts.check_critical_coverage import main as coverage_main


@pytest.mark.parametrize("fault", ["branch_gap", "missing_domain", "unassigned_source", "xml_entity"])
def test_coverage_gate_rejects_hidden_gaps(tmp_path, monkeypatch, fault):
    config = tmp_path / "domains.json"
    config.write_text(json.dumps({
        "critical": {"prefixes": ["app/critical/"], "line_min": 100, "branch_min": 100},
        "easy": {"prefixes": ["core/easy/"], "line_min": 100, "branch_min": 100},
    }))
    critical = '<class filename="app/critical/service.py"><lines><line number="1" hits="1" branch="true" condition-coverage="100% (2/2)"/></lines></class>'
    if fault == "branch_gap":
        critical = critical.replace("100% (2/2)", "50% (1/2)")
    elif fault == "missing_domain":
        critical = ""
    elif fault == "unassigned_source":
        critical = critical.replace("app/critical/", "app/new/")
    report = tmp_path / "coverage.xml"
    report.write_text('<coverage><packages><package><classes>' + critical +
                      '<class filename="core/easy/service.py"><lines><line number="1" hits="1"/></lines></class>' +
                      '</classes></package></packages></coverage>')
    if fault == "xml_entity":
        report.write_text('<!DOCTYPE coverage [<!ENTITY hits "1">]>' +
                          report.read_text().replace('hits="1"', 'hits="&hits;"'))
    monkeypatch.setattr(sys, "argv", ["coverage", "--xml", str(report), "--config", str(config),
                                     "--report", str(tmp_path / "result.json")])
    from defusedxml.common import DefusedXmlException

    with pytest.raises((SystemExit, ValueError, DefusedXmlException)):
        coverage_main()


def lab_run():
    from datetime import datetime, timezone
    from uuid import uuid4
    from app.lab.schemas import EvaluationRunDetail, EvaluationRunCaseRead

    run_id, dataset_id, case_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    results = [EvaluationRunCaseRead(
        id=uuid4(), run_id=run_id, case_id=case_id, repetition=index,
        case_snapshot={"id": str(case_id), "categories": ["nominal", "security", "robustness"],
                       "input_data": {"objective": "Check the original resource"}, "expected_output": {}},
        actual_output={"result": "Verified"}, verdict="pass", score_percent=90,
        score_details={"checks": [{"code": "resource", "passed": True}]},
        structured_score_percent=100, cost=0.01, duration=1, created_at=now,
    ) for index in range(1, 4)]
    return EvaluationRunDetail(
        id=run_id, dataset_id=dataset_id, llm_id=1, judge_llm_id=2, status="completed", phase="finished",
        configuration_snapshot={"dataset_purpose": "validation"}, repetitions=3, max_cost=1,
        total_cases=3, completed_cases=3, judged_cases=3, cost=0.03, score_version="1",
        llm_snapshot={"model": "candidate"}, judge_llm_snapshot={"model": "judge"},
        cancel_requested=False, created_at=now, results=results,
    )


@pytest.mark.parametrize("fault", [None, "same_run", "critical_failure", "category_drop", "missing_repeat", "changed_corpus", "changed_judge", "missing_budget"])
def test_lab_qualification_cannot_hide_a_critical_or_incomparable_result(fault):
    from uuid import uuid4
    from scripts.qualify_lab import Policy, compare

    baseline = lab_run()
    candidate = baseline.model_copy(deep=True)
    if fault != "same_run":
        candidate.id = uuid4()
        for result in candidate.results:
            result.run_id = candidate.id
    if fault == "critical_failure":
        candidate.results[0].score_details["checks"][0]["passed"] = False
    elif fault == "category_drop":
        candidate.results[0].score_percent = 50
    elif fault == "missing_repeat":
        candidate.results.pop()
    elif fault == "changed_corpus":
        candidate.results[0].case_snapshot["input_data"] = {"objective": "Easier question"}
    elif fault == "changed_judge":
        candidate.judge_llm_snapshot = {"model": "different"}
    elif fault == "missing_budget":
        candidate.max_cost = None
    result = compare(baseline, candidate, Policy())
    assert result["qualified"] == (fault is None), result


@pytest.mark.parametrize("fault", [None, "missing_test", "skipped_test", "surviving_mutation", "xml_entity"])
def test_regression_links_require_executed_tests_and_detected_faults(tmp_path, fault):
    from scripts.check_regression_evidence import check

    manifest = tmp_path / "regressions.json"
    manifest.write_text(json.dumps([{"id": "incident", "guarantee": "No duplicate effect", "evidence": "audit.md",
                                    "test": "app/task/tests/test_budget.py::test_budget", "mutation": "budget"}]))
    junit = tmp_path / "junit.xml"
    case = '<testcase classname="app.task.tests.test_budget" name="test_budget" time="0.1">'
    if fault == "skipped_test":
        case += "<skipped/>"
    case += "</testcase>"
    junit.write_text("<testsuites><testsuite>" + ("" if fault == "missing_test" else case) + "</testsuite></testsuites>")
    if fault == "xml_entity":
        junit.write_text('<!DOCTYPE testsuites [<!ENTITY duration "0.1">]>' +
                         junit.read_text().replace('time="0.1"', 'time="&duration;"'))
    mutations = tmp_path / "mutations.json"
    mutations.write_text(json.dumps({"expected": 1, "mutations": [{"name": "budget", "detected": fault != "surviving_mutation"}]}))
    if fault:
        from defusedxml.common import DefusedXmlException

        with pytest.raises((ValueError, DefusedXmlException)):
            check(manifest, junit, mutations)
    else:
        assert check(manifest, junit, mutations)["linked_regressions"] == 1


def test_changed_branch_gate_checks_new_lines_without_flagging_untouched_debt():
    from scripts.check_critical_coverage import changed_branches

    diff = '''diff --git a/back/app/task/budget.py b/back/app/task/budget.py
--- a/back/app/task/budget.py
+++ b/back/app/task/budget.py
@@ -9,0 +10,2 @@
+if guarded:
+    return False
@@ -29 +31 @@
-old()
+new()
'''
    assert changed_branches(diff, {"app/task/budget.py": {2, 10, 31, 90}}) == [
        "back/app/task/budget.py:10", "back/app/task/budget.py:31",
    ]
    assert changed_branches(diff, {"app/task/budget.py": {2, 90}}) == []


def test_full_coverage_reports_unexecuted_bridges_and_separates_lines_from_branches(tmp_path):
    from scripts.report_full_coverage import report

    xml = tmp_path / "full.xml"
    xml.write_text('''<coverage><packages><package><classes>
      <class filename="bridge/unused/__init__.py"><lines/></class>
      <class filename="bridge/unused/client.py"><lines>
        <line number="1" hits="0" branch="true" condition-coverage="0% (0/2)"/>
      </lines></class>
      <class filename="app/chat/service.py"><lines>
        <line number="1" hits="1" branch="true" condition-coverage="50% (1/2)"/>
      </lines></class>
    </classes></package></packages></coverage>''')
    output = tmp_path / "report.json"
    report(xml, output)
    domains = json.loads(output.read_text())["domains"]
    assert domains["bridge/unused/"]["lines"] == 0
    assert domains["bridge/unused/"]["missing_branches"] == 2
    assert domains["app/chat/"]["lines"] == 100
    assert domains["app/chat/"]["branches"] == 50
