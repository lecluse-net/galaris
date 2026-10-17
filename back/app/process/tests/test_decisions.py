"""Binary decisions share actor policy, durable waits and the run Dataset."""

import json
import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.process import process_service
from app.process.bpmn import Actor, Flow, Node, Workflow, compile_bpmn, to_bpmn, validate_graph
from app.process.isolated_code import MontyCodeRunner, CodeInvocation, dataset_program
from app.process.models import ProcessNodeRun, ProcessNodeAttempt
from app.process.native_actors import complete_human_work
from app.process.native_definitions import create
from app.process.values import Variable
from core.user import UserModel
from .test_native_bpmn import native as native, finish_run, typed_graph


def decision_graph(mode, expected=True):
    return Workflow(schema_version="galaris.bpmn/v2", inputs=[
        Variable(name="variable_1", type="int", nullable=False, default={"type": "int", "value": 123}),
        Variable(name="variable_2", type="string", nullable=False,
            default={"type": "string", "value": "mon projet" if expected else "pas mon projet"}),
    ], outputs=[], nodes=[Node(id="start", kind="start"), Node(id="check", kind="if", config={
        "mode": mode, "prompt": "Is this the requested project?", "code": 'return variable_2 != "pas mon projet"'}),
        Node(id="yes", kind="end"), Node(id="no", kind="end")], flows=[
            Flow(id="a", source="start", target="check"),
            Flow(id="yes_flow", source="check", target="yes", condition="decision"),
            Flow(id="no_flow", source="check", target="no")])


@pytest.mark.parametrize("mode", ["ai", "code"])
@pytest.mark.parametrize("expected", [True, False])
@pytest.mark.asyncio
async def test_binary_decision_executes_exactly_the_selected_branch(db, native, mode, expected):
    owner, _ = native
    graph = decision_graph(mode, expected)
    assert compile_bpmn(to_bpmn(graph)).model_dump() == graph.model_dump()
    definition = await create(actor_agent_id=owner.id, title="Synthetic binary decision", graph=graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, result={"decision": {"type": "bool", "value": expected}})
    assert run.status == "success", run.error_message
    if mode == "ai":
        attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id))
        assert attempt.input["variable_2"]["value"] == ("mon projet" if expected else "pas mon projet")
    nodes = list(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run.id)))
    assert sorted(nodes) == sorted(["start", "check", "yes" if expected else "no"])


@pytest.mark.parametrize("expected", [True, False])
@pytest.mark.asyncio
async def test_human_if_waits_for_assignee_and_replays_one_boolean_receipt(db, native, expected):
    owner, _ = native
    user = UserModel(email=f"decision-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add(user); await db.flush()
    graph = decision_graph("human")
    graph.actors = [Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)]
    graph.nodes[1].config["actor"] = "reviewer"
    definition = await create(actor_agent_id=owner.id, title="Synthetic human decision", graph=graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4): await process_service.refresh_run(launched.run_id)
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == launched.run_id))
    assert attempt.status == "human_waiting" and attempt.task_id is None
    scope = AgentManagementScope(user.id, frozenset())
    with pytest.raises(PermissionError):
        await complete_human_work(attempt.id, AgentManagementScope(user.id + 9999, frozenset()), {})
    with pytest.raises(ValueError):
        await complete_human_work(attempt.id, scope, {"decision": {"type": "string", "value": "true"}})
    result = {"decision": {"type": "bool", "value": expected}}
    await complete_human_work(attempt.id, scope, result)
    await complete_human_work(attempt.id, scope, result)
    run = await finish_run(db, launched.run_id)
    assert run.status == "success", run.error_message
    nodes = list(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run.id)))
    assert sorted(nodes) == sorted(["start", "check", "yes" if expected else "no"])


@pytest.mark.asyncio
async def test_code_task_integrates_plain_returned_variables_into_run_dataset(db, native):
    from app.process.run_resources import read_run_data
    owner, _ = native
    graph = decision_graph("code")
    graph.nodes = [graph.nodes[0], Node(id="work", kind="code", config={"dataset_code": True,
        "code": 'return {"variable_1": variable_1 + 1, "variable_2": variable_2.upper()}'}, inputs=[], outputs=[
            Variable(name="variable_1", type="int", nullable=False), Variable(name="variable_2", type="string", nullable=False)]), graph.nodes[2]]
    graph.outputs = graph.nodes[1].outputs
    graph.flows = [Flow(id="a", source="start", target="work"), Flow(id="b", source="work", target="yes")]
    definition = await create(actor_agent_id=owner.id, title="Synthetic Dataset computation", graph=graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id)
    assert run.status == "success", run.error_message
    data = (await read_run_data(run.id, owner.id))["data"]
    assert data == {"variable_1": {"type": "int", "value": 124}, "variable_2": {"type": "string", "value": "MON PROJET"}}


@pytest.mark.parametrize("source", ['return open("/etc/passwd").read()', 'from pathlib import Path\nreturn Path("/etc/passwd").read_text()', 'import os\nreturn os.environ',
    'import socket\nreturn socket.socket()', 'while True:\n    pass', 'return [0] * 100_000_000'])
@pytest.mark.asyncio
async def test_sandbox_denies_host_access_and_bounds_untrusted_computation(source):
    runner = MontyCodeRunner()
    invocation = CodeInvocation(uuid4(), uuid4(), uuid4(), 1, "activity", dataset_program(source, {}), {"dataset": {}})
    result = await runner.submit(invocation)
    for _ in range(200):
        if result.status not in {"queued", "running"}: break
        await asyncio.sleep(0.02)
        result = await runner.observe(invocation.id)
    assert result.status == "error" and result.stopped
    assert await runner.submit(invocation) == result
    with pytest.raises(ValueError, match="different inputs"):
        await runner.submit(replace(invocation, source="return True"))


def test_if_rejects_ambiguous_outputs_and_actor_mode_mismatch():
    graph = decision_graph("code")
    graph.flows.pop()
    graph.nodes.pop()
    with pytest.raises(ValueError, match="True and one False"):
        validate_graph(graph)
    graph = decision_graph("human")
    with pytest.raises(ValueError, match="human actor"):
        validate_graph(graph)


@pytest.mark.asyncio
async def test_sandbox_freezes_inputs_isolates_invocations_and_confirms_cancel():
    runner = MontyCodeRunner()
    dataset = {"name": "synthetic value", "count": 1}
    invocation = CodeInvocation(uuid4(), uuid4(), uuid4(), 1, "activity",
        dataset_program('return {"name": name}', dataset), {"dataset": dataset})
    assert (await runner.submit(invocation)).status == "queued"
    dataset["name"] = "changed after admission"
    observation = await runner.observe(invocation.id)
    for _ in range(200):
        if observation.stopped: break
        await asyncio.sleep(0.02)
        observation = await runner.observe(invocation.id)
    assert observation.status == "success" and observation.result["output"] == {"name": "synthetic value"}
    reordered = replace(invocation, values={"dataset": {"count": 1, "name": "synthetic value"}})
    assert await runner.submit(reordered) == observation
    spin = replace(invocation, id=uuid4(), source=dataset_program("while True:\n    pass", {}), values={"dataset": {}})
    await runner.submit(spin)
    await asyncio.sleep(0.05)
    cancelled = await runner.cancel(spin.id)
    assert cancelled.status == "cancelled" and cancelled.stopped
    assert await runner.observe(spin.id) == cancelled
    assert (await runner.observe(invocation.id)).result == observation.result


@pytest.mark.asyncio
async def test_real_sandbox_preserves_existing_preprocess_activity_and_postprocess_contract(db, native):
    owner, _ = native
    graph = typed_graph()
    graph.nodes[1].kind = "code"
    graph.nodes[1].config = {"preprocess": 'input["amount"] = data["amount"]',
        "code": 'output["accepted"] = {"type": "bool", "value": input["amount"]["value"] > 0}',
        "postprocess": 'data.update(output)'}
    definition = await create(actor_agent_id=owner.id, title="Synthetic isolated phases", graph=graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id)
    assert run.status == "success", run.error_message
    assert run.output == {"accepted": {"type": "bool", "value": True}}
