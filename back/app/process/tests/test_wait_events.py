"""Business guarantees of durable waits and BPMN error handling."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.process import native_engine, process_service, registry
from app.process.bpmn import Flow, Node, Workflow, compile_bpmn, to_bpmn
from app.process.engine import ProcessEngineError
from app.process.models import ProcessNodeRun, ProcessRun, ProcessRunEvent
from app.process.native_definitions import create
from app.process.native_runs import control_run
from app.process.run_observation import observe_run
from app.process.values import Variable
from app.process.wait_events import ProcessSignal, signal_run

from .test_native_bpmn import api_server as api_server, finish_run, native as native


def workflow(*activities: Node, edges: tuple[tuple[str, str], ...]) -> Workflow:
    return Workflow(schema_version="galaris.bpmn/v2",
        variables=[Variable(name="order", type="string", nullable=False,
            default={"type": "string", "value": "order-42"})],
        nodes=[Node(id="start", kind="start", inputs=["order"]), *activities, Node(id="end", kind="end")],
        flows=[Flow(id=f"link_{index}", source=source, target=target)
               for index, (source, target) in enumerate(edges)])


async def launch(owner, graph):
    definition = await create(actor_agent_id=owner.id, title="Synthetic event workflow", graph=graph)
    result = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    return result.run_id


async def armed(db, run_id, key):
    for _ in range(10):
        run = await process_service.refresh_run(run_id)
        assert run.status not in process_service.TERMINAL_STATUSES, run.error_message
        occurrence = await db.scalar(select(ProcessNodeRun).where(
            ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == key,
            ProcessNodeRun.status == "waiting"))
        if occurrence is not None:
            return occurrence
    raise AssertionError("The event wait was not armed")


@pytest.mark.asyncio
@pytest.mark.parametrize("by", ["duration", "date", "input"])
async def test_deadline_survives_engine_reinstantiation(db, native, monkeypatch, by):
    owner, _ = native
    clock = datetime.now(timezone.utc)
    due = clock + timedelta(minutes=1)
    monkeypatch.setattr(native_engine, "now", lambda: clock)
    monkeypatch.setattr(process_service, "_utcnow", lambda: clock)
    config = {"duration": {"delay_seconds": 60}, "date": {"at": due.isoformat()},
              "input": {"date_variable": "deadline"}}[by]
    wait = Node(id="wait", kind="timer", config=config, inputs=["deadline"] if by == "input" else [])
    graph = workflow(wait, edges=(("start", "wait"), ("wait", "end")))
    if by == "input":
        graph.variables.append(Variable(name="deadline", type="datetime", nullable=False,
            default={"type": "datetime", "value": due.isoformat()}))
        graph.node("start").inputs.append("deadline")
    run_id = await launch(owner, graph)
    occurrence = await armed(db, run_id, "wait")
    snapshot = await observe_run(await db.get(ProcessRun, run_id), can_control=True, visible_children=set())
    assert snapshot["phase"] == "waiting"
    assert datetime.fromisoformat(snapshot["activities"][0]["waits"][0]["due_at"]) == due
    registry.register(native_engine.NativeProcessEngine())
    clock = due - timedelta(seconds=1)
    assert await process_service.refresh_active_runs(engine_code="galaris") == 0
    clock = due
    assert await process_service.refresh_active_runs(engine_code="galaris") == 1
    result = await finish_run(db, run_id)
    assert result.id == run_id and result.status == "success", result.error_message
    await db.refresh(occurrence)
    assert occurrence.output["kind"] == "timer"
    assert datetime.fromisoformat(occurrence.output["at"]) == due


def delivery_node():
    return Node(id="delivery", kind="event_wait", inputs=["order"],
                config={"event_name": "order.delivered", "correlation_variable": "order"})


@pytest.mark.asyncio
async def test_wait_requires_run_control_and_exact_signal_and_deduplicates(db, native):
    owner, outsider = native
    run_id = await launch(owner, workflow(delivery_node(), edges=(("start", "delivery"), ("delivery", "end"))))
    occurrence = await armed(db, run_id, "delivery")
    signal = ProcessSignal(event_id=uuid4(), name="order.delivered", correlation="order-42")
    run = await db.get(ProcessRun, run_id)
    run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    await db.commit()
    assert await process_service.refresh_active_runs(engine_code="galaris") == 0
    with pytest.raises(PermissionError):
        await signal_run(run_id, outsider.id, signal)
    for updates in ({"correlation": "order-99"}, {"name": "order.cancelled"}):
        with pytest.raises(ValueError, match="one active wait"):
            await signal_run(run_id, owner.id, signal.model_copy(update=updates))
    receipt = await signal_run(run_id, owner.id, signal)
    assert receipt["occurrence_id"] == str(occurrence.id)
    assert run.engine_metadata["next_refresh_at"] is None
    assert (await finish_run(db, run_id)).status == "success"
    assert await signal_run(run_id, owner.id, signal) == receipt
    with pytest.raises(ValueError, match="different signal"):
        await signal_run(run_id, owner.id, signal.model_copy(update={"correlation": "order-99"}))
    with pytest.raises(ValueError, match="no longer accepts"):
        await signal_run(run_id, owner.id, signal.model_copy(update={"event_id": uuid4()}))


@pytest.mark.asyncio
async def test_paused_run_accepts_the_event_but_only_resumes_its_successor_after_control(db, native):
    owner, _ = native
    run_id = await launch(owner, workflow(delivery_node(), edges=(("start", "delivery"), ("delivery", "end"))))
    occurrence = await armed(db, run_id, "delivery")
    await control_run(run_id, owner.id, "pause")
    signal = ProcessSignal(event_id=uuid4(), name="order.delivered", correlation="order-42")
    await signal_run(run_id, owner.id, signal)
    for _ in range(3):
        assert (await process_service.refresh_run(run_id)).status == "running"
    await db.refresh(occurrence)
    assert occurrence.status == "success"
    assert occurrence.output["event"]["event_id"] == str(signal.event_id)
    end = await db.scalar(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == "end"))
    assert end.status == "ready" and end.started_at is None
    await control_run(run_id, owner.id, "resume")
    assert (await finish_run(db, run_id)).status == "success"


@pytest.mark.asyncio
async def test_cancellation_reawakens_an_event_wait_after_an_interrupted_request(db, native, monkeypatch):
    owner, _ = native
    run_id = await launch(owner, workflow(delivery_node(), edges=(("start", "delivery"), ("delivery", "end"))))
    await armed(db, run_id, "delivery")
    run = await db.get(ProcessRun, run_id)

    async def interrupted_cancel(_):
        raise ProcessEngineError("engine_unreachable", "Synthetic interruption", retryable=True)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(registry.get("galaris"), "cancel_run", interrupted_cancel)
        with pytest.raises(ProcessEngineError, match="Synthetic interruption"):
            await process_service.cancel_run(run_id)
    run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    await db.commit()
    assert await process_service.refresh_active_runs(engine_code="galaris") == 1
    await db.refresh(run)
    assert run.status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["delivery", "deadline"])
async def test_only_first_event_path_is_executed(db, native, winner):
    owner, _ = native
    due = datetime.now(timezone.utc) + timedelta(hours=1 if winner == "delivery" else -1)
    graph = workflow(Node(id="choice", kind="event_choice"), delivery_node(),
        Node(id="deadline", kind="timer", config={"at": due.isoformat()}),
        edges=(("start", "choice"), ("choice", "delivery"), ("choice", "deadline"),
               ("delivery", "end"), ("deadline", "end")))
    xml = to_bpmn(graph)
    assert "eventBasedGateway" in xml and "messageEventDefinition" in xml and "timerEventDefinition" in xml
    run_id = await launch(owner, compile_bpmn(xml))
    await armed(db, run_id, "choice")
    event = ProcessSignal(event_id=uuid4(), name="order.delivered", correlation="order-42")
    if winner == "delivery":
        assert (await signal_run(run_id, owner.id, event))["node_key"] == winner
        with pytest.raises(ValueError, match="one active wait"):
            await signal_run(run_id, owner.id, event.model_copy(update={"event_id": uuid4()}))
    else:
        with pytest.raises(ValueError, match="one active wait"):
            await signal_run(run_id, owner.id, event)
    run = await finish_run(db, run_id)
    assert run.status == "success", run.error_message
    rows = list(await db.scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id)))
    assert sorted(item.node_key for item in rows) == sorted(["start", "choice", winner, "end"])
    assert next(item for item in rows if item.node_key == winner).output["kind"] == (
        "event" if winner == "delivery" else "timer")


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "filter_code", "expected"), [
    ("denied", "rest_http_error", "caught"),
    ("synthetic", "rest_http_error", "regular"),
    ("denied", "some_other_code", "error"),
])
async def test_boundary_handles_only_matching_confirmed_errors(db, native, api_server, path, filter_code, expected):
    from app.connection import connection_service
    from app.services import service
    from app.services.schemas import ServiceCreate

    owner, _ = native
    base, requests = api_server
    api = await service.create_service(ServiceCreate(code=f"synthetic_api_{uuid4().hex}", label="Synthetic API",
        rest_config={"base_url": base, "auth": {"type": "none"}}))
    await connection_service.get_or_create_connection(api.id, owner.id)
    graph = workflow(Node(id="api", kind="rest", config={"service_code": api.code,
            "request": {"method": "POST", "path": path}, "external_output": {}}),
        Node(id="caught", kind="error_boundary", config={"error_code": filter_code}),
        Node(id="regular", kind="end"),
        edges=(("start", "api"), ("api", "regular"), ("api", "caught"), ("caught", "end")))
    xml = to_bpmn(graph)
    assert 'attachedToRef="api"' in xml and "errorEventDefinition" in xml
    run_id = await launch(owner, compile_bpmn(xml))
    run = await finish_run(db, run_id)
    assert len(requests) == 1
    captured = await db.scalar(select(ProcessRunEvent).where(
        ProcessRunEvent.run_id == run_id, ProcessRunEvent.event_type == "node.error.caught"))
    keys = set(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run_id)))
    assert ("caught" in keys) == (expected == "caught")
    assert ("regular" in keys) == (expected == "regular")
    assert run.status == ("error" if expected == "error" else "success"), run.error_message
    if expected == "caught":
        assert captured is not None and captured.payload["error"]["code"] == "rest_http_error"
    else:
        assert captured is None


@pytest.mark.asyncio
async def test_boundary_handles_monty_failure(db, native):
    owner, _ = native
    graph = workflow(Node(id="calc", kind="code", config={"code": 'return {"amount": 1 // 0}', "dataset_code": True}),
        Node(id="caught", kind="error_boundary", config={"error_code": "isolated_code_failed"}),
        Node(id="regular", kind="end"),
        edges=(("start", "calc"), ("calc", "regular"), ("calc", "caught"), ("caught", "end")))
    run_id = await launch(owner, graph)
    run = await finish_run(db, run_id)
    assert run.status == "success", run.error_message
    result = await db.scalar(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == "caught"))
    assert result.output["code"] == "isolated_code_failed"
