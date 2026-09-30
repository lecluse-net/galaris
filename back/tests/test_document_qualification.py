"""A qualification gate must reject incomplete or mismatched evidence."""

import hashlib
import json

import pytest

from scripts.qualify_documents import check, qualify, write_json


@pytest.fixture
def evidence(tmp_path):
    categories = ["text", "numbers", "table", "layout", "visual", "coverage", "absence"]
    suite = {"reference_reviewed": True, "documents": [{"file": "doc1.pdf", "sha256": "synthetic"}],
             "required_categories": categories,
             "cases": [{"id": category, "category": category, "file": "doc1.pdf",
                        "question": "Synthetic question", "expected": "Synthetic answer",
                        "source": "page 1", "reviewed": True} for category in categories]}
    suite_path = tmp_path / "suite.json"
    write_json(suite_path, suite)
    responses = {"documents": suite["documents"], "run": {
        "model": "synthetic-reader", "transport": "synthetic", "prompt_sha256": "synthetic",
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "latency_seconds": 1.0, "cost": 0.0}, "answers": [
            {"id": category, "answer": "Synthetic answer", "source": "page 1", "limitations": [],
             "review": {"approved": True, "reviewer": "independent synthetic reviewer",
                        "reason": "Checked answer and citation against original source"}} for category in categories]}
    return suite_path, suite, responses, tmp_path / "responses.json", tmp_path / "verdict.json"


def test_complete_independently_reviewed_run_passes(evidence):
    suite_path, _, responses, response_path, verdict_path = evidence
    write_json(response_path, responses)
    assert check(suite_path, response_path, verdict_path) == 0
    assert json.loads(verdict_path.read_text())["passed"] is True


@pytest.mark.parametrize("defect", ["empty", "unreviewed", "missing", "duplicate", "wrong_source",
                                   "reader_unreviewed", "limitation", "uncovered", "failed_trial", "changed_suite"])
def test_incomplete_or_untrustworthy_evidence_never_passes(evidence, defect):
    suite_path, suite, responses, response_path, verdict_path = evidence
    if defect == "empty":
        suite["cases"] = []
        responses["answers"] = []
    elif defect == "unreviewed":
        suite["cases"][0]["reviewed"] = False
    elif defect == "missing":
        responses["answers"].pop()
    elif defect == "duplicate":
        responses["answers"].append(responses["answers"][0])
    elif defect == "wrong_source":
        responses["documents"] = [{"file": "doc1.pdf", "sha256": "changed"}]
    elif defect == "reader_unreviewed":
        responses["answers"][0].pop("review")
    elif defect == "limitation":
        responses["answers"][0]["limitations"] = ["Unreadable table"]
    elif defect == "uncovered":
        suite["documents"].append({"file": "doc2.pdf", "sha256": "synthetic-2"})
    elif defect == "failed_trial":
        responses["trials"] = [{"error": "provider_rejected"}]
    elif defect == "changed_suite":
        suite["cases"][0]["expected"] = "Changed after trial"
    write_json(suite_path, suite)
    # Most cases test the guarantee itself rather than incidental fingerprint rejection.
    if defect != "changed_suite":
        responses["run"]["suite_sha256"] = hashlib.sha256(suite_path.read_bytes()).hexdigest()
    write_json(response_path, responses)
    assert check(suite_path, response_path, verdict_path) == 2
    assert json.loads(verdict_path.read_text())["passed"] is False


@pytest.mark.parametrize("defect", [None, "two_runs", "replay", "different_candidate", "failed_review"])
def test_repeated_qualification_requires_independent_successful_runs(evidence, defect):
    suite_path, _, responses, response_path, verdict_path = evidence
    runs = []
    for repetition in range(3):
        current = json.loads(json.dumps(responses))
        current["trials"] = [{"inference_id": f"synthetic-{repetition}"}]
        if repetition == 2:
            if defect == "replay":
                current["trials"][0]["inference_id"] = "synthetic-0"
            elif defect == "different_candidate":
                current["run"]["model"] = "another-reader"
            elif defect == "failed_review":
                current["answers"][0]["review"]["approved"] = False
        path = response_path.with_name(f"run-{repetition}.json")
        write_json(path, current)
        runs.append(path)
    if defect == "two_runs":
        runs.pop()
    assert qualify(suite_path, runs, verdict_path) == (0 if defect is None else 2)
    assert json.loads(verdict_path.read_text())["qualified"] is (defect is None)
