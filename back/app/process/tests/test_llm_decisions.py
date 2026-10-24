"""IF decisions cross Process and durable LLM execution; only provider HTTP is replaced."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent import Agent
from app.agent.models import Title
from app.llm import LLMCall
from app.llm.facade import read_inference, run_decision
from app.process import process_service, registry
from app.process.bpmn import Actor, compile_bpmn, to_bpmn, validate_graph
from app.process.models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from app.process.native_definitions import create
from app.process.native_engine import NativeProcessEngine
from app.process.native_runs import run_metrics
from app.task import Task
from core.user import UserModel
from tests import test_decision_inference as decision_tests
from tests.conftest import responses_sse as responses_sse
from .test_decisions import decision_graph

runtime = decision_tests.runtime
decisions = decision_tests.decisions


@pytest_asyncio.fixture
async def workflow(decisions):
    db, request, calls, text_calls, mode = decisions
    user = UserModel(email=f"synthetic-if-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    title = Title(label="Synthetic reviewer", gender="X")
    db.add_all([user, title]); await db.flush()
    agent = Agent(user_id=user.id, title_id=title.id, code=f"if-{uuid4().hex}", first_name="Synthetic", last_name="Reviewer")
    db.add(agent); await db.commit()
    registry.register(NativeProcessEngine())
    return db, agent, request.llm_id, calls, text_calls, mode


async def launch(workflow, model_id, assigned_agent=None):
    db, agent, *_ = workflow
    graph = decision_graph("ai")
    graph.nodes[1].config.update(ai_mode="llm", llm_id=model_id)
    if assigned_agent is not None:
        graph.actors = [Actor(id="reviewer", name="Reviewer", kind="agent", agent_id=assigned_agent)]
        graph.nodes[1].config["actor"] = "reviewer"
    assert compile_bpmn(to_bpmn(graph)).model_dump() == graph.model_dump()
    definition = await create(actor_agent_id=agent.id, title="Synthetic direct IF", graph=graph)
    response = await process_service.start_process(agent_id=agent.id, workflow_id=definition.code,
        input_data={}, requester_user_id=agent.user_id)
    await process_service.process_start_jobs(engine_code="galaris")
    return response.run_id


async def drive(db, run_id, until=None):
    async with asyncio.timeout(15):
        while True:
            run = await process_service.refresh_run(run_id)
            if run.status in process_service.TERMINAL_STATUSES or until is not None and until():
                return run
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize("expected,delegated", [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize("specialized", [True, False])
async def test_simple_if_uses_selected_model_without_task_and_reuses_completed_inference(workflow, runtime, expected, delegated, specialized):
    db, agent, decision_model, calls, text_calls, mode = workflow
    _, text_model, _, text_mode = runtime
    mode["selections"] = {"decision": "true" if expected else "false"}
    text_mode["outputs"] = [json.dumps({"decision": expected})]
    executor = agent
    if delegated:
        executor = Agent(user_id=agent.user_id, title_id=agent.title_id, code=f"delegate-{uuid4().hex}", first_name="Synthetic", last_name="Delegate")
        db.add(executor); await db.commit()
    run_id = await launch(workflow, decision_model if specialized else text_model.id, executor.id if delegated else None)
    await drive(db, run_id, until=lambda: bool(calls or text_calls))
    occurrence = await db.scalar(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == "check"))
    inference_id = UUID(occurrence.context["llm_inference_id"])
    completed = await decision_tests.lifecycle.state(inference_id, "completed")
    # A new engine observes the committed answer after a scheduler restart.
    registry.register(NativeProcessEngine())
    run = await drive(db, run_id)
    assert run.status == "success", run.error_message
    assert "decision" not in run.data
    nodes = list(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run_id)))
    assert sorted(nodes) == sorted(["start", "check", "yes" if expected else "no"])
    assert await db.scalar(select(func.count()).select_from(Task)) == 0
    assert completed.request.llm_id == (decision_model if specialized else text_model.id)
    assert completed.request.agent_id == executor.id
    assert not completed.request.allow_profile_fallback
    assert len(calls) == int(specialized) and len(text_calls) == int(not specialized)
    if specialized:
        assert set(calls[0]["questions"]["decision"]["criteria"]) == {"true", "false"}
    metrics = await run_metrics(run_id, agent.id)
    assert metrics["direct"]["calls"] == 1
    assert metrics["occurrences"][str(occurrence.id)]["direct"]["calls"] == 1
    assert metrics["nodes"]["check"]["calls"] == 1
    assert (await db.scalar(select(LLMCall))).task_id is None
    await process_service.refresh_run(run_id)
    assert len(calls) + len(text_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_during_stop", [False, True])
async def test_stopping_if_cancels_silent_llm_and_never_admits_a_branch(workflow, monkeypatch, finish_during_stop):
    db, _, model_id, calls, text_calls, mode = workflow
    mode.update(selections={"decision": "true"}, gate=asyncio.Event())
    run_id = await launch(workflow, model_id)
    await drive(db, run_id, until=lambda: bool(calls))
    occurrence = await db.scalar(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == "check"))
    inference_id = UUID(occurrence.context["llm_inference_id"])
    if finish_during_stop:
        from app.process import llm_decisions
        control = llm_decisions.control_inference

        async def finish_before_stop(identity, action, **kwargs):
            if action == "stop":
                mode["gate"].set()
                await decision_tests.lifecycle.state(identity, "completed")
            return await control(identity, action, **kwargs)

        monkeypatch.setattr(llm_decisions, "control_inference", finish_before_stop)
    await process_service.cancel_run(run_id)
    await decision_tests.lifecycle.state(inference_id, "completed" if finish_during_stop else "stopped")
    run = await drive(db, run_id)
    assert run.status == "cancelled"
    mode["gate"].set()
    await process_service.refresh_run(run_id)
    assert list(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run_id).order_by(ProcessNodeRun.admission_order))) == ["start", "check"]
    assert len(calls) == 1 and text_calls == []
    assert await db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [503, "invalid"])
async def test_llm_if_failure_is_an_error_and_never_false(workflow, failure):
    db, _, model_id, calls, text_calls, mode = workflow
    mode["selections"] = {"decision": "unavailable" if failure == "invalid" else "false"}
    if failure == 503:
        mode["status"] = failure
    run_id = await launch(workflow, model_id)
    run = await drive(db, run_id)
    assert run.status == "error"
    assert run.error_code == "llm_if_failed"
    assert set(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run_id))) == {"start", "check"}
    assert len(calls) == 1 and text_calls == []


@pytest.mark.asyncio
async def test_recovery_after_lost_preparation_reply_reuses_the_same_inference(workflow, monkeypatch):
    from app.process import llm_decisions
    db, _, model_id, calls, _, mode = workflow
    mode["selections"] = {"decision": "true"}
    run_id = await launch(workflow, model_id)
    prepare = llm_decisions.prepare_inference

    async def lose_reply(*args, **kwargs):
        await prepare(*args, **kwargs)
        raise asyncio.CancelledError("Synthetic worker loss after durable admission")

    monkeypatch.setattr(llm_decisions, "prepare_inference", lose_reply)
    with pytest.raises(asyncio.CancelledError):
        await drive(db, run_id)
    assert calls == []
    await db.rollback()
    run = await db.get(ProcessRun, run_id)
    state = {**run.engine_metadata["native"]}
    state.pop("lease", None); state.pop("lease_until", None)
    run.engine_metadata = {**run.engine_metadata, "native": state}
    await db.commit()
    monkeypatch.setattr(llm_decisions, "prepare_inference", prepare)
    registry.register(NativeProcessEngine())
    assert (await drive(db, run_id)).status == "success"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unassigned_agent_cannot_attribute_inference_to_process_activity(workflow, decisions):
    db, agent, model_id, calls, _, mode = workflow
    mode.update(selections={"decision": "true"}, gate=asyncio.Event())
    run_id = await launch(workflow, model_id)
    await drive(db, run_id, until=lambda: bool(calls))
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id))
    outsider = Agent(user_id=agent.user_id, title_id=agent.title_id, code=f"unassigned-{uuid4().hex}", first_name="Synthetic", last_name="Unassigned")
    db.add(outsider); await db.commit()
    request = decisions[1].model_copy(update={"process_run_id": run_id, "agent_id": outsider.id,
        "correlation_ref": f"process-attempt:{attempt.id}"})
    with pytest.raises(RuntimeError, match="not assigned to agent"):
        await run_decision(request)
    assert len(calls) == 1
    await process_service.cancel_run(run_id)
    await drive(db, run_id)


@pytest.mark.parametrize("config", [{"ai_mode": "unknown"}, {"ai_mode": "llm"}, {"ai_mode": "llm", "llm_id": True}])
def test_simple_if_requires_known_mode_and_explicit_model(config):
    graph = decision_graph("ai")
    graph.nodes[1].config.update(config)
    with pytest.raises(ValueError):
        validate_graph(graph)
