import pytest
from pydantic import ValidationError

from app.agent.contracts import ExecutionResult, WorkingSet


def test_unversioned_working_set_and_result_remain_readable():
    working = WorkingSet.model_validate({"version": 7, "resources": []})
    result = ExecutionResult.model_validate({"prompt": "old task", "result": "already delivered"})
    assert working.version == 7
    assert working.schema_version == "galaris.working-set/v1"
    assert result.result == "already delivered"
    assert result.model_dump()["schema_version"] == "galaris.execution-result/v1"


@pytest.mark.parametrize("model, payload", [
    (WorkingSet, {"schema_version": "galaris.working-set/v2", "resources": []}),
    (ExecutionResult, {"schema_version": "galaris.execution-result/v2", "prompt": "future task"}),
])
def test_unknown_durable_version_is_not_silently_reinterpreted(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)
