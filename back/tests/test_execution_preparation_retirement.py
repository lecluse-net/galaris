"""Upgrade-only coverage: remove obsolete data without changing admitted work."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.lab.models import LabEvaluationDataset, LabEvaluationRun
from app.llm.models import LLMCall, LLMCallEvent, LLMInference, LLMInferenceAttempt, LLMInferenceCommand
from app.task.models import Task, TaskAttempt, TaskStatus
from core.dbadmin import DbAdminRegistry, SchemaTransitionSet
from dbadmin_composition import (
    _execution_preparation_is_purged,
    _purge_execution_preparation,
    _retires_execution_preparation,
    register_dbadmin,
)


def test_cutover_requires_removed_column_and_declares_total_enum_mapping():
    assert not _retires_execution_preparation(SchemaTransitionSet())
    assert _retires_execution_preparation(SchemaTransitionSet(
        removed_columns=frozenset({"tasks.briefing_result"}),
    ))
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    assert registry.enum_mapping("taskstatus").values == {"BRIEFING": "DISPATCH"}


@pytest.mark.asyncio
async def test_cutover_purges_archives_atomically_and_preserves_tasks(db):
    task = Task(
        label="Synthetic admitted work", objective="<p>Create a report</p>",
        status=TaskStatus.DISPATCH, forced_route="BRIEFING", effort="high", paused=True,
        data={"briefing_used": True, "plan_tools": ["search_web"],
              "history": "before<execution_briefing>obsolete</execution_briefing>after"},
        dispatch_result={"prompt": "Synthetic routing", "decision": {"route": "BRIEFING", "effort": "high"}},
    )
    retired = LabEvaluationDataset(name="Synthetic retired experiment", mechanism="briefing")
    retained = LabEvaluationDataset(
        name="Synthetic retained experiment", mechanism="dispatcher",
        parameters={"pipeline_policy": {"use_briefing": True, "briefing_efforts": ["high"], "use_planner": True}},
    )
    inference = LLMInference(request={"purpose": "lab.mechanism_run", "output": {"contract": "galaris.briefing/v1"}})
    old_dispatch = LLMInference(request={"output": {"contract": "galaris.dispatcher.active/v3"}})
    current = LLMInference(request={"output": {"contract": "galaris.dispatcher.active/v4"}})
    db.add_all([task, retired, retained, inference, old_dispatch, current])
    await db.flush()
    current.replay_of_id = inference.id
    run = LabEvaluationRun(dataset_id=retired.id)
    attempt = LLMInferenceAttempt(inference_id=inference.id, number=1)
    task_attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="BRIEFING",
                               worker_id="synthetic", lease_token=uuid4())
    db.add_all([run, attempt, task_attempt])
    await db.flush()
    call = LLMCall(inference_attempt_id=attempt.id, purpose="agent.briefing", task_id=task.id)
    retained_call = LLMCall(purpose="agent.exec", task_id=task.id,
                           prompt="Objective\n<execution_briefing>obsolete</execution_briefing>\nContext")
    command = LLMInferenceCommand(id=uuid4(), inference_id=inference.id,
                                   attempt_id=attempt.id, action="replay", replay_id=current.id)
    db.add_all([call, retained_call, command])
    await db.flush()
    db.add(LLMCallEvent(call_id=call.id, sequence=1, inference_id=inference.id, payload={}))
    await db.flush()
    delta = SchemaTransitionSet(removed_columns=frozenset({"tasks.briefing_result"}))
    assert not await _execution_preparation_is_purged(db, delta)

    with pytest.raises(RuntimeError, match="rollback proof"):
        async with db.begin_nested():
            await _purge_execution_preparation(db, delta)
            assert await _execution_preparation_is_purged(db, delta)
            raise RuntimeError("rollback proof")
    assert not await _execution_preparation_is_purged(db, delta)
    assert await db.scalar(select(LLMCall.id).where(LLMCall.id == call.id)) == call.id

    await _purge_execution_preparation(db, delta)
    await _purge_execution_preparation(db, delta)
    assert await _execution_preparation_is_purged(db, delta)
    await db.refresh(task)
    await db.refresh(retained)
    await db.refresh(current)
    await db.refresh(task_attempt)
    await db.refresh(retained_call)
    assert retained_call.prompt.split() == ["Objective", "Context"]
    assert (task.objective, task.effort, task.paused, task.status) == (
        "<p>Create a report</p>", "high", True, TaskStatus.DISPATCH,
    )
    assert task.forced_route == "EXEC"
    assert task.get_dispatch_result().decision.route == "EXEC"
    assert task.data == {"plan_tools": ["search_web"], "history": "beforeafter"}
    assert retained.parameters == {"pipeline_policy": {"use_planner": True}}
    assert task_attempt.phase == "DISPATCH"
    assert current.replay_of_id is None
    for table, key in (("llm_calls", call.id), ("llm_inferences", inference.id),
                       ("llm_inferences", old_dispatch.id), ("lab_evaluation_datasets", retired.id),
                       ("lab_evaluation_runs", run.id)):
        assert await db.scalar(text(f'SELECT count(*) FROM "{table}" WHERE id = :id'), {"id": key}) == 0
    assert await db.scalar(select(LLMCall.id).where(LLMCall.id == retained_call.id)) == retained_call.id
