"""The orchestrator delegates recovery to an opaque, driver-owned policy."""

from dataclasses import replace
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agent import checkpoints, registry
from app.agent.contracts import AgentRunCheckpoint, CheckpointAssessment, ExecutionResult, HarnessFailure
from app.agent.execution_errors import HarnessCheckpointError
from app.harness.checkpoint_policy import InternalCheckpointPolicy
from app.task import scheduler
from app.task.models import TaskStatus


def test_new_driver_can_own_an_unfamiliar_checkpoint_format(monkeypatch):
    spec = replace(registry.INTERNAL_HARNESS, code="opaque-test", checkpoint_policy_path="test:policy")
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)

    class Policy:
        def assess(self, checkpoint):
            return CheckpointAssessment(state="reconcile", execution_strategy="custom-recover")

        def rebase(self, checkpoint):
            return replace(checkpoint, data={"cursor": checkpoint.data["cursor"], "amended": True})

    monkeypatch.setattr(registry, "_resolve_entrypoint", lambda _: Policy)
    checkpoint = AgentRunCheckpoint(driver_code=spec.code, runtime_run_id="opaque:17", status="unknown", data={"cursor": [1, 2]})
    assert checkpoints.assess_checkpoint(checkpoint).execution_strategy == "custom-recover"
    assert checkpoints.rebase_checkpoint(checkpoint).data == {"cursor": [1, 2], "amended": True}


@pytest.mark.parametrize("data,expected", [
    ({"version": 99, "resume_safe": True}, "unsafe"),
    ({"version": True, "resume_safe": True}, "unsafe"),
    ({"version": 3, "resume_safe": True, "effects": "invalid"}, "unsafe"),
    ({"version": 3, "resume_safe": True, "effects": [{"status": "invented"}]}, "unsafe"),
    ({"version": 3, "resume_safe": True, "effects": [{"status": "started", "effect_policy": "invented"}]}, "unsafe"),
    ({"version": 3, "resume_safe": True, "effects": [{"status": "started"}]}, "unsafe"),
    ({"version": 3, "resume_safe": True, "effects": [{"status": "failed", "outcome": "rejected"}]}, "safe"),
    ({"version": 3, "resume_safe": True, "effects": [{"status": "completed"}]}, "safe"),
    ({"version": 4, "resume_safe": True, "effects": [{"status": "error_reported", "outcome": "unknown",
        "result": {"schema": "galaris.tool-error/v1", "status": "error", "outcome": "unknown"}}]}, "safe"),
    ({"version": 4, "resume_safe": True, "effects": [{"status": "error_reported", "outcome": "unknown"}]}, "unsafe"),
    ({"version": 3, "resume_safe": True, "effects": [{"status": "error_reported", "outcome": "unknown",
        "result": {"schema": "galaris.tool-error/v1", "status": "error", "outcome": "unknown"}}]}, "unsafe"),
    ({"version": 3, "resume_safe": False, "resume_reconcilable": True, "effects": [{
        "status": "outcome_unknown", "tool_name": "console_exec", "operation_id": "op", "recovery_scope": "server",
    }]}, "reconcile"),
])
def test_internal_recovery_is_fail_closed(data, expected):
    checkpoint = AgentRunCheckpoint(driver_code="internal", runtime_run_id="r", status="interrupted", data=data)
    assert InternalCheckpointPolicy().assess(checkpoint).state == expected


def test_amendment_preserves_effect_evidence_but_discards_old_reasoning():
    data = {"version": 3, "resume_safe": True, "effects": [{"status": "completed", "tool_name": "send"}],
            "message_history": [{"text": "old objective"}]}
    checkpoint = AgentRunCheckpoint(driver_code="internal", runtime_run_id="r", status="interrupted", data=data,
                                    result=ExecutionResult(prompt="old", result="old"))
    rebased = InternalCheckpointPolicy().rebase(checkpoint)
    assert rebased is not None
    assert rebased.data["effects"] == data["effects"]
    assert not rebased.data["message_history"]
    assert rebased.result is None
    assert checkpoint.data["message_history"]


def test_remote_history_cannot_be_rebased_without_driver_support(monkeypatch):
    from bridge.hermes.checkpoint_policy import HermesCheckpointPolicy
    monkeypatch.setattr(checkpoints, "checkpoint_policy", lambda _: HermesCheckpointPolicy())
    with pytest.raises(HarnessCheckpointError):
        checkpoints.rebase_checkpoint(AgentRunCheckpoint(driver_code="remote", runtime_run_id="r", status="running"))


@pytest.mark.parametrize("scenario,active,allowed", [
    ("new", False, True), ("new", True, False),
    ("admitted", False, False), ("admitted", True, False),
    ("safe", False, True), ("safe", True, True),
    ("unsafe", False, False), ("unsafe", True, False),
    ("remote", False, False), ("remote", True, False),
    ("corrupt", False, False), ("mismatch", True, False),
])
def test_amendment_admission_preserves_execution_evidence(scenario, active, allowed):
    from app.agent import objective_amendment_blocker

    data = {}
    if scenario == "admitted":
        data["_agent_run_identity"] = {"driver_code": "hermes", "request_run_id": "admitted-run"}
    elif scenario != "new":
        data["_agent_run_checkpoint"] = {
            "driver_code": "hermes" if scenario == "remote" else "internal",
            "runtime_run_id": "synthetic-run", "status": "running",
            "data": {"version": 4, "resume_safe": True,
                "message_history": [{"text": "Keep original context"}],
                "effects": [{"status": "started" if scenario == "unsafe" else "completed"}]},
        }
        if scenario == "corrupt":
            data["_agent_run_checkpoint"] = {"receipt": "incomplete"}
        if scenario == "mismatch":
            data["_agent_run_identity"] = {"driver_code": "hermes"}
    original = deepcopy(data)
    assert (objective_amendment_blocker(data, execution_active=active) is None) is allowed
    assert data == original


@pytest.mark.parametrize("payload", ["corrupt", {}, {"driver_code": "internal"}, {"schema_version": 99}])
def test_corrupt_checkpoint_never_becomes_a_fresh_run(payload):
    from app.agent import facade
    task = SimpleNamespace(data={facade.RUN_CHECKPOINT_DATA_KEY: payload})
    assert not facade.has_resumable_run_checkpoint(task)
    assert facade.checkpoint_blocks_new_effects(task)
    with pytest.raises(HarnessCheckpointError):
        facade._read_run_checkpoint(task.data)


@pytest.mark.parametrize("retry,checkpoint_safe,expected", [
    ("never", True, False), ("reconcile", False, False), ("reconcile", True, True), ("safe", False, True),
])
def test_structured_failure_governs_retry_even_without_visible_tool_calls(retry, checkpoint_safe, expected, monkeypatch):
    import app.agent
    monkeypatch.setattr(app.agent, "has_resumable_run_checkpoint", lambda _: checkpoint_safe)
    result = ExecutionResult(prompt="", result="failed", success=False,
        failure=HarnessFailure(code="unavailable", message="Lost remote reply", retry=retry))
    task = SimpleNamespace(data={}, get_execution_result=lambda: result)
    assert scheduler._retry_is_safe(task, TaskStatus.DISPATCH) is expected
