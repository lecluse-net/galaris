"""Semantic qualification must catch invented, ambiguous and unauthorized values."""

from scripts.qualify_process_inputs import expectation_errors, synthetic_cases


def test_trial_expectations_reject_wrong_person_missing_questions_and_broadened_consent():
    for case in synthetic_cases():
        expected = case["expected"]
        actual = {key: value for key, value in expected.items() if key not in {"absent", "question_required"}}
        actual.setdefault("values", {})
        actual["question"] = "Synthetic clarification" if expected.get("question_required") else ""
        assert expectation_errors(actual, expected) == []
    assert expectation_errors({"values": {"birth": "1980-06-15"}}, {"values": {"birth": "2000-02-29"}})
    assert expectation_errors({"values": {"birth": None}}, {"absent": ["birth"]})
    assert expectation_errors({"question": ""}, {"question_required": True})
    assert expectation_errors({"launch_requested": True}, {"launch_requested": False})
