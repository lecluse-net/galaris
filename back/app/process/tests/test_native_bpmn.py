from app.process.models import ProcessDefinition
"""Business guarantees of the executable profile and durable native admission."""

from app.share import set_grant

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, func

from app.agent import Agent, Title
from app.memory import read_workflow_document, write_workflow_document
from app.memory.storage import NativeFileStorage, register_storage, reset_storage_registry
from app.memory import service as memory
from app.memory.schemas import MemoryGrantUpdate
from app.process import process_service, registry
from app.process.bpmn import Flow, Node, Workflow, compile_bpmn, to_bpmn
from app.process.bpmn import Actor, validate_graph
from app.process.expressions import evaluate, ExpressionError
from app.process.models import ProcessDefinition, ProcessRun, ProcessNodeRun, ProcessNodeAttempt, ProcessRunFile
from app.process.run_resources import read_run_data, write_run_data
from app.process.run_data import run_files, RunDataConflictError
from app.process.native_definitions import create, read, update, restore, DefinitionConflictError
from app.process.native_engine import NativeProcessEngine
from app.task import TaskStatus, task_service
from app.task.workflow import TaskEvent, transition
from app.tools.tests.test_rest import api_server



async def write_run_json(identity, actor, content, *, expected_revision):
    return await write_run_data(identity, actor, json.loads(content), expected_revision=expected_revision)


def graph(prompt="Prepare the synthetic result"):
    return Workflow(nodes=[Node(id="start", kind="start"), Node(id="work", kind="task", config={"prompt": prompt}),
        Node(id="end", kind="end", config={"output": {"$expr": "results.work"}})],
        flows=[Flow(id="first", source="start", target="work"), Flow(id="last", source="work", target="end")])


def test_bpmn_roundtrip_preserves_instructions_conditions_and_layout():
    definition = graph()
    assert definition.execution_agent_id is None
    assert compile_bpmn(to_bpmn(definition)).execution_agent_id is None
    definition.execution_agent_id = 7
    definition.nodes[1].x = 123
    definition.nodes[1].title = "Synthetic activity"
    assert compile_bpmn(to_bpmn(definition)).model_dump() == definition.model_dump()
    body = graph()
    loop = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="loop", kind="for", body=body, config={"items": "input.values"}),
        Node(id="finish", kind="end")], flows=[Flow(id="a", source="begin", target="loop"), Flow(id="b", source="loop", target="finish")])
    assert compile_bpmn(to_bpmn(loop)).model_dump() == loop.model_dump()
    reserved = Workflow(nodes=[Node(id="Process_1", kind="start"), Node(id="Diagram_1", kind="end")],
        flows=[Flow(id="Plane_1", source="Process_1", target="Diagram_1")])
    assert compile_bpmn(to_bpmn(reserved)).model_dump() == reserved.model_dump()


def test_legacy_mappings_and_schemas_do_not_create_hidden_task_requirements():
    value = graph().model_dump()
    value.update(input_schema={"required": ["old"]}, output_schema={"required": ["old"]}, files={"old": "image/*"})
    value["nodes"][1]["config"].update(input={"isolated": True}, output_mapping={"old": True},
        result_format="json", output_schema={"required": ["old"]}, result_condition="false")
    simplified = validate_graph(Workflow.model_validate(value))
    assert simplified.nodes[1].config == {"prompt": "Prepare the synthetic result"}
    assert set(simplified.model_dump()).isdisjoint({"input_schema", "output_schema", "files"})
    assert compile_bpmn(to_bpmn(simplified)).model_dump() == simplified.model_dump()
    from xml.etree import ElementTree as ET
    from app.process.bpmn import BPMN, GALARIS
    root = ET.fromstring(to_bpmn(simplified))
    process = root.find(f"{{{BPMN}}}process")
    settings = process.find(f"{{{BPMN}}}extensionElements/{{{GALARIS}}}workflow")
    settings.text = json.dumps({**json.loads(settings.text), "error_handler": "legacy_recovery"})
    recovery = ET.SubElement(process, f"{{{BPMN}}}task", {"id": "legacy_recovery"})
    extension = ET.SubElement(recovery, f"{{{BPMN}}}extensionElements")
    ET.SubElement(extension, f"{{{GALARIS}}}config").text = json.dumps({"prompt": "Retired recovery"})
    ET.SubElement(process, f"{{{BPMN}}}sequenceFlow", {"id": "legacy_flow", "sourceRef": "legacy_recovery", "targetRef": "end"})
    assert compile_bpmn(ET.tostring(root, encoding="unicode")).model_dump() == simplified.model_dump()
    from app.process.native_engine import local_graph
    frozen = simplified.model_dump()
    frozen["error_handler"] = "legacy_recovery"
    frozen["nodes"].append({"id": "legacy_recovery", "kind": "task", "config": {"prompt": "Retired recovery"}})
    run = ProcessRun(launcher_agent_id=3, launch_snapshot={"definition": {"graph": frozen}})
    occurrence = ProcessNodeRun(node_key="legacy_recovery", context={})
    assert local_graph(run, occurrence).node("legacy_recovery").id == "legacy_recovery"
    assert run.launch_snapshot["definition"]["graph"] == frozen


@pytest.mark.parametrize("process_agent,actor_agent,expected", [(None, None, 3), (7, None, 7), (None, 11, 11), (7, 11, 11)])
def test_execution_agent_defaults_to_launcher_and_inherits_into_loop(process_agent, actor_agent, expected):
    from app.process.native_actors import execution_agent
    from app.process.native_engine import local_graph
    body = graph()
    body.actors = [Actor(id="executor", name="Executor", kind="agent", agent_id=actor_agent)]
    body.nodes[1].config["actor"] = "executor"
    definition = Workflow(execution_agent_id=process_agent,
        nodes=[Node(id="begin", kind="start"), Node(id="loop", kind="for", body=body, config={"items": "input.values"}),
            Node(id="finish", kind="end")], flows=[Flow(id="a", source="begin", target="loop"), Flow(id="b", source="loop", target="finish")])
    persisted = compile_bpmn(to_bpmn(definition))
    run = ProcessRun(launcher_agent_id=3, launch_snapshot={"definition": {"graph": persisted.model_dump()}})
    occurrence = ProcessNodeRun(node_key="work", context={"body_path": ["loop"]})
    inherited = local_graph(run, occurrence)
    assert execution_agent(inherited, inherited.node("work"), run.launcher_agent_id) == expected
    assert run.launch_snapshot["definition"]["graph"]["nodes"][1]["body"]["execution_agent_id"] is None
    inherited.execution_agent_id = None
    assert execution_agent(inherited, inherited.node("work"), run.launcher_agent_id) == (actor_agent or 3)


def test_named_actor_assignments_roundtrip_and_reject_task_type_inversion():
    value = graph()
    value.actors = [Actor(id="executor", name="Executor", kind="agent", agent_id=7),
        Actor(id="reviewer", name="Reviewer", kind="human", user_id=11)]
    value.nodes[1].config["actor"] = "executor"
    assert compile_bpmn(to_bpmn(value)).model_dump() == value.model_dump()
    value.nodes[1].config["actor"] = "reviewer"
    with pytest.raises(ValueError, match="cannot exchange"):
        validate_graph(value)
    value.nodes[1].kind = "human_task"
    assert compile_bpmn(to_bpmn(value)).model_dump() == value.model_dump()
    value.nodes[1].config["actor"] = "executor"
    with pytest.raises(ValueError, match="cannot exchange"):
        validate_graph(value)
    value.nodes[1].config["actor"] = "missing"
    with pytest.raises(ValueError, match="unknown actor"):
        validate_graph(value)
    value.nodes[1].config.pop("actor")
    with pytest.raises(ValueError, match="requires a human actor"):
        validate_graph(value)


@pytest.mark.asyncio
async def test_human_options_use_goal_directory_and_active_local_humans(db, native, monkeypatch):
    from unittest.mock import AsyncMock
    from core.user import UserModel
    from app.contact import service as contacts
    from app.memory import MessengerContactObservation, observe_messenger_contact
    from app.messenger import MessengerUser
    from app.process.native_actors import human_options
    from app.process import human_directory
    from main import ProcessHumanDirectoryAdapter
    monkeypatch.setattr(human_directory, "_directory", ProcessHumanDirectoryAdapter())

    owner, _ = native
    active = UserModel(email=f"manager-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    inactive = UserModel(email=f"disabled-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=False)
    unrelated = UserModel(email=f"unrelated-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add_all([active, inactive, unrelated]); await db.flush()
    await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id="internal", user_id=f"user:{active.id}", display_name="Synthetic manager", galaris_user_id=active.id))
    # Only the messaging directory boundary is replaced; contact resolution and User lookup remain real.
    search = AsyncMock(return_value=[
        (1, 1, "internal", MessengerUser(id=uuid4(), external_id=f"user:{active.id}",
            display_name="Route label", galaris_user_id=active.id, is_ai=False)),
        (2, 2, "matrix", MessengerUser(id=uuid4(), external_id="@manager:example.invalid",
            display_name="Duplicate route", galaris_user_id=active.id, is_ai=False)),
        (1, 1, "internal", MessengerUser(id=uuid4(), external_id=f"user:{inactive.id}",
            display_name="Disabled", galaris_user_id=inactive.id, is_ai=False)),
        (2, 2, "matrix", MessengerUser(id=uuid4(), external_id="@unlinked:example.invalid",
            display_name="Unlinked human", is_ai=False)),
        (1, 1, "internal", MessengerUser(id=uuid4(), external_id="agent:7",
            display_name="Agent", agent_id=owner.id, is_ai=True)),
    ])
    monkeypatch.setattr(contacts, "search_agent_users", search)
    assert await human_options(owner.id) == [{"id": active.id, "label": "Synthetic manager"}]
    search.assert_awaited_once_with(owner.id, "")


@pytest.mark.asyncio
async def test_human_activity_waits_for_assignee_and_replays_one_receipt(db, native):
    from core.user import UserModel
    from app.agent import AgentManagementScope
    from app.process.native_actors import human_work, complete_human_work
    owner, _ = native
    user = UserModel(email=f"synthetic-human-{uuid4().hex}@example.com", hashed_password="unused", is_active=True)
    other = UserModel(email=f"synthetic-other-{uuid4().hex}@example.com", hashed_password="unused", is_active=True)
    db.add_all([user, other]); await db.flush()
    scope = AgentManagementScope(user.id, frozenset())
    foreign = AgentManagementScope(other.id, frozenset())
    value = graph()
    value.actors = [Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)]
    value.nodes[1].kind = "human_task"
    value.nodes[1].config.update(actor="reviewer")
    definition = await create(actor_agent_id=owner.id, title="Synthetic human approval", graph=value)
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"amount": 3})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4):
        await process_service.refresh_run(response.run_id)
    items = await human_work(scope, page=1, page_size=50)
    assert items["total"] == 1 and items["items"][0]["input"] == {"amount": 3}
    assert (await human_work(foreign, page=1, page_size=50))["total"] == 0
    identity = UUID(items["items"][0]["attempt_id"])
    with pytest.raises(PermissionError):
        await complete_human_work(identity, foreign, {"approved": True})
    from core.user import HumanActor
    run = await db.get(ProcessRun, response.run_id)
    await set_grant(definition.share_id, "user", user.id, True)
    await db.commit()
    shared = await read_run_data(run.id, scope)
    assert shared["can_write"]
    await write_run_json(run.id, scope, '{"approved": true}', expected_revision=shared["revision"])
    user.is_active = False; await db.commit()
    with pytest.raises(PermissionError, match="inactive"):
        await complete_human_work(identity, scope, {"approved": True})
    user.is_active = True; await db.commit()
    receipt = await complete_human_work(identity, scope, {"approved": True})
    assert await complete_human_work(identity, scope, {"approved": True}) == receipt
    with pytest.raises(memory.MemoryConflictError):
        await complete_human_work(identity, scope, {"approved": False})
    await finish_run(db, response.run_id)
    run = await db.get(ProcessRun, response.run_id)
    assert run.status == "success" and run.output == {"approved": True}
    assert (await human_work(scope, page=1, page_size=500))["total"] == 0
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).where(ProcessNodeAttempt.task_id.is_not(None))) == 0
    cancelled = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(3):
        await process_service.refresh_run(cancelled.run_id)
    pending = (await human_work(scope, page=1, page_size=50))["items"][0]
    await process_service.cancel_run(cancelled.run_id)
    with pytest.raises(ValueError, match="no longer"):
        await complete_human_work(UUID(pending["attempt_id"]), scope, {"approved": True})
    assert (await human_work(scope, page=1, page_size=50))["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_kind", ["human", "agent"])
async def test_unused_actor_does_not_block_launch_or_grant_execution_access(db, native, actor_kind):
    from app.process import mcp
    from app.tools import McpToolContext

    owner, _ = native
    value = graph()
    value.schema_version = "galaris.bpmn/v2"
    value.inputs = []; value.outputs = []
    value.nodes[1].inputs = []; value.nodes[1].outputs = []
    value.nodes[1].title = "Prepare synthetic result"
    value.actors = [Actor(id="unused", name="Unused lane", kind=actor_kind,
        agent_id=2147483647 if actor_kind == "agent" else None)]
    definition = await create(actor_agent_id=owner.id, title="Synthetic unused lane", graph=value)
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(3):
        await process_service.refresh_run(response.run_id)
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun)
        .where(ProcessNodeRun.run_id == response.run_id, ProcessNodeAttempt.task_id.is_not(None)))
    task = await task_service.get_by_id(attempt.task_id)
    assert task.agent_id == owner.id
    assert (await db.get(ProcessRun, response.run_id)).status == "running"
    summary = await mcp.process_get(McpToolContext(agent_id=owner.id, runtime="internal"), definition.code)
    assert summary["inputs"] == [] and summary["outputs"] == []
    assert summary["activities"] == [{"id": "work", "kind": "task", "title": "Prepare synthetic result"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_used_human_actor_still_requires_an_active_assignee(db, native, nested):
    from core.user import UserModel
    from app.process.native_actors import validate_assignments

    owner, _ = native
    body = graph()
    body.actors = [Actor(id="reviewer", name="Synthetic reviewer", kind="human")]
    body.nodes[1].kind = "human_task"
    body.nodes[1].config["actor"] = "reviewer"
    value = Workflow(nodes=[Node(id="start", kind="start"),
        Node(id="loop", kind="for", body=body, config={"items": "input.values"}),
        Node(id="end", kind="end")], flows=[Flow(id="a", source="start", target="loop"),
        Flow(id="b", source="loop", target="end")]) if nested else body
    with pytest.raises(ValueError, match="active assigned user"):
        await validate_assignments(value, owner.id)
    user = UserModel(email=f"synthetic-inactive-{uuid4().hex}@example.invalid", hashed_password="unused", is_active=False)
    db.add(user); await db.flush()
    body.actors[0].user_id = user.id
    with pytest.raises(ValueError, match="active assigned user"):
        await validate_assignments(value, owner.id)
    user.is_active = True
    await validate_assignments(value, owner.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment", ["actor", "process"])
async def test_assigned_agent_is_forced_with_shared_writable_dataset_and_scope_check(db, native, assignment):
    from core.user import UserModel
    from app.agent import AgentManagementScope
    from app.process.native_actors import validate_assignments
    owner, executor = native
    user = UserModel(email=f"synthetic-manager-{uuid4().hex}@example.com", hashed_password="unused", is_active=True)
    db.add(user); await db.flush()
    owner.user_id = user.id; executor.user_id = user.id
    value = graph()
    value.execution_agent_id = executor.id if assignment == "process" else None
    value.actors = [Actor(id="executor", name="Executor", kind="agent", agent_id=executor.id if assignment == "actor" else None)]
    value.nodes[1].config["actor"] = "executor"
    unknown = graph()
    if assignment == "process":
        unknown.execution_agent_id = 2147483647
    else:
        unknown.actors = [Actor(id="missing", name="Missing executor", kind="agent", agent_id=2147483647)]
        unknown.nodes[1].config["actor"] = "missing"
    with pytest.raises(ValueError, match="no longer exists"):
        await validate_assignments(unknown, AgentManagementScope(user.id, None))
    definition = await create(actor_agent_id=owner.id, title="Synthetic assigned agent", graph=value)
    with pytest.raises(PermissionError):
        await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
        input_data={}, requester_user_id=user.id)
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(3):
        await process_service.refresh_run(response.run_id)
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == response.run_id))
    task = await task_service.get_by_id(attempt.task_id)
    assert task.agent_id == executor.id and task.forced_route == "EXEC"
    run = await db.get(ProcessRun, response.run_id)
    await set_grant(definition.share_id, "agent", executor.id, True)
    await db.commit()
    assert (await read_run_data(run.id, executor.id))["can_write"]
    shared = await read_run_data(run.id, executor.id)
    await write_run_json(run.id, executor.id, '{"executor": "synthetic"}', expected_revision=shared["revision"])
    assert (await read_run_data(run.id, owner.id))["data"] == {"executor": "synthetic"}
    task_identity = task.id
    attempt.task_id = None; attempt.status = "intent"; await db.commit()
    await process_service.refresh_run(run.id)
    assert attempt.task_id == task_identity


@pytest.mark.parametrize("expression", ["__import__('os')", "data.__class__", "[x for x in input]", "2 ** 999999", "lambda: 1"])
def test_expressions_cannot_execute_code(expression):
    with pytest.raises(ExpressionError):
        evaluate(expression, {"data": {}})


def test_expressions_have_missing_null_and_short_circuit_semantics():
    assert evaluate("data.missing == null", {"data": {}})
    assert not evaluate("false and 1 / 0", {})
    assert evaluate("input.total > 10 and input.ready", {"input": {"total": 11, "ready": True}})
    with pytest.raises(ValueError):
        compile_bpmn('<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x/>')


@pytest.mark.asyncio
async def test_http_native_and_lab_pagination_accepts_encoded_sizes_with_real_authorization(client, inference_db, committed_native, tmp_path):
    from core.user import UserModel
    from core.user.user_service import encrypt_password
    from core.authorize.models import Assignment, Role, Privilege
    from app.agent import AgentManagementScope
    from app.lab.process_evaluation import create_synthetic_dataset, start_campaign, ProcessCaseInput

    owner, other_agent = committed_native
    db = inference_db
    user = UserModel(email=f"process-http-{uuid4().hex}@example.com", hashed_password=encrypt_password("synthetic-http-password"), is_active=True)
    rights = list(await db.scalars(select(Privilege).where(Privilege.code.in_([
        "PROCESS_READ", "PROCESS_EDIT", "PROCESS_LAUNCH", "PROCESS_EVALUATION_ACCESS",
    ]))))
    assert len(rights) == 4
    role = Role(code=f"process-http-{uuid4().hex}", privileges=rights)
    db.add_all([user, role])
    await db.flush()
    db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
    owner.user_id = user.id
    owner_id, other_agent_id, user_id, email = owner.id, other_agent.id, user.id, user.email
    await db.commit()
    login = await client.post("/api/auth/login-json", json={"email": email, "password": "synthetic-http-password"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    humans_path = "/api/processes/internal/humans"
    assert (await client.get(humans_path, headers=headers, params={"agent_id": owner_id})).status_code == 200
    assert (await client.get(humans_path, headers=headers, params={"agent_id": other_agent_id})).status_code == 403
    assert (await client.get(humans_path, headers=headers)).status_code == 422
    sharing_options = await client.get("/api/processes/internal/sharing-options", headers=headers, params={"agent_id": owner_id})
    assert sharing_options.status_code == 200, sharing_options.text
    assert sharing_options.json()["owner"]["kind"] == "user"
    assert sharing_options.json()["owner"]["id"] == user_id
    assert (await client.get("/api/processes/internal/sharing-options", headers=headers, params={"agent_id": other_agent_id})).status_code == 403
    definition_graph = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="finish", kind="end")],
        flows=[Flow(id="a", source="begin", target="finish")])
    created = await client.post("/api/processes/internal/definitions", headers=headers, json={
        "agent_id": owner_id, "owner": "user", "title": "Synthetic HTTP definition",
        "description": "Synthetic plain text description\nSecond line.", "graph": definition_graph.model_dump(mode="json")})
    assert created.status_code == 201, created.text
    assert created.json()["description"] == "Synthetic plain text description\nSecond line."
    code = created.json()["code"]
    admission = await client.post(f"/api/processes/internal/definitions/{code}/runs", headers=headers, json={"agent_id": owner_id})
    assert admission.status_code == 202, admission.text
    run_id = UUID(admission.json()["run_id"])
    await process_service.process_start_jobs(engine_code="galaris")
    from app.process.run_data import create_workflow_attachment
    source = tmp_path / "report.txt"
    source.write_bytes(b"Entirely synthetic HTTP attachment")
    attached = await create_workflow_attachment(run_id, key="http-report", source_uri="https://example.test/report.txt",
        path=source, name="report.txt", media_type="text/plain")
    file_path = f"/api/processes/internal/runs/{run_id}/files/{attached['uri'].rsplit('/', 1)[-1]}"
    downloaded = await client.get(file_path, headers=headers)
    assert downloaded.status_code == 200 and downloaded.content == source.read_bytes()
    assert downloaded.headers["cache-control"] == "private, no-store"
    outsider = UserModel(email=f"process-reader-{uuid4().hex}@example.com",
        hashed_password=encrypt_password("synthetic-reader-password"), is_active=True)
    db.add(outsider); await db.flush()
    db.add(Assignment(user_id=outsider.id, role_id=role.id, is_default=True))
    await db.commit()
    from httpx import ASGITransport, AsyncClient
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url=client.base_url) as outsider_client:
        outsider_login = await outsider_client.post("/api/auth/login-json", json={"email": outsider.email, "password": "synthetic-reader-password"})
        assert outsider_login.status_code == 200, outsider_login.text
        outsider_headers = {"Authorization": f"Bearer {outsider_login.json()['access_token']}"}
        assert (await outsider_client.get(file_path, headers=outsider_headers)).status_code == 403
    await finish_run(db, run_id)
    assert (await client.get(file_path, headers=headers)).content == source.read_bytes()
    scope = AgentManagementScope(user_id, frozenset({owner_id}))
    dataset = await create_synthetic_dataset(scope, agent_id=owner_id, title="Synthetic HTTP inputs",
        cases=[ProcessCaseInput(input={})], invocation_key=uuid4().hex)
    campaign = await start_campaign(scope, agent_id=owner_id, code=code,
        dataset_document_id=UUID(dataset["document_id"]), title="Synthetic HTTP campaign", invocation_key=uuid4().hex)
    campaign_id = campaign.id
    await db.commit()
    paths = ["/api/processes/internal/definitions", f"/api/processes/internal/definitions/{code}/history",
        "/api/processes/internal/runs", f"/api/processes/internal/runs/{run_id}",
        f"/api/processes/internal/runs/{run_id}/activities/begin",
        f"/api/processes/internal/runs/{run_id}/children", f"/api/evaluation/process-campaigns/{campaign_id}"]
    for path in paths:
        for size in (50, 500):
            response = await client.get(path, headers=headers, params={"page": "1", "page_size": str(size)})
            assert response.status_code == 200, (path, response.text)
        assert (await client.get(path, headers=headers, params={"page_size": "501"})).status_code == 422
    definition_graph.nodes[0].title = "Synthetic updated start"
    updated = await client.put(f"/api/processes/internal/definitions/{code}", headers=headers,
        json={"expected_revision": 1, "graph": definition_graph.model_dump(mode="json")})
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == created.json()["description"]
    definition_path = f"/api/processes/internal/definitions/{code}"
    for description in ("Updated synthetic description", ""):
        metadata = {"expected_revision": 2, "graph": definition_graph.model_dump(mode="json"), "description": description}
        assert (await client.put(definition_path, headers=outsider_headers, json=metadata)).status_code == 403
        response = await client.put(definition_path, headers=headers, json=metadata)
        assert response.status_code == 200, response.text
        assert (await client.get(definition_path, headers=headers)).json()["description"] == description
    history_path = f"/api/processes/internal/definitions/{code}/history"
    assert (await client.delete(f"{history_path}/2", headers=headers)).status_code == 409
    foreign = await create(actor_agent_id=other_agent_id, title="Synthetic private history", graph=graph())
    assert (await client.delete(f"/api/processes/internal/definitions/{foreign.code}/history/1", headers=headers)).status_code == 403
    assert (await client.delete(f"{history_path}/1", headers=headers)).status_code == 204
    assert (await client.get(f"{history_path}/1", headers=headers)).status_code == 404
    assert (await client.delete(f"{history_path}/1", headers=headers)).status_code == 404
    remaining = await client.get(history_path, headers=headers)
    assert [entry["revision"] for entry in remaining.json()["items"]] == [2]
    past_only = await client.get(history_path, headers=headers, params={"exclude_current": "true", "page_size": 10})
    assert past_only.json()["items"] == [] and past_only.json()["total"] == 0


@pytest.mark.asyncio
async def test_incomplete_parallel_convergence_fails_instead_of_waiting_forever(db, native):
    owner, _ = native
    value = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="fork", kind="parallel"),
        Node(id="left", kind="task", config={"prompt": "Invent a left result"}),
        Node(id="right", kind="task", config={"prompt": "Invent a right result"}),
        Node(id="join", kind="parallel"), Node(id="finish", kind="end")],
        flows=[Flow(id="a", source="begin", target="fork"), Flow(id="b", source="fork", target="left"),
            Flow(id="c", source="fork", target="right"), Flow(id="d", source="left", target="join"),
            Flow(id="e", source="right", target="finish"), Flow(id="f", source="join", target="finish"),
            Flow(id="g", source="begin", target="join")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic incompatible convergence", graph=value)
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, response.run_id)
    assert run.status == "error"


@pytest.mark.asyncio
async def test_recursive_current_calls_finish_after_restart_with_distinct_datasets(db, native):
    owner, _ = native
    owner_id = owner.id
    code = "synthetic_recursive_" + uuid4().hex
    value = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="condition", kind="if"),
        Node(id="decrement", kind="task", config={"prompt": "Decrement shared remaining"}),
        Node(id="recurse", kind="call", config={"process_code": code}),
        Node(id="recursive_end", kind="end"), Node(id="base_end", kind="end")],
        flows=[Flow(id="a", source="begin", target="condition"),
            Flow(id="b", source="condition", target="decrement", condition="data.remaining > 0"),
            Flow(id="c", source="condition", target="base_end"), Flow(id="d", source="recurse", target="recursive_end"),
            Flow(id="e", source="decrement", target="recurse")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic recursive process", code=code, graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"remaining": 3})
    for _ in range(50):
        registry.register(NativeProcessEngine())
        db.expire_all()
        await process_service.process_start_jobs(engine_code="galaris")
        runs = list(await db.scalars(select(ProcessRun).order_by(ProcessRun.created_at)))
        for run in runs:
            if run.status not in process_service.TERMINAL_STATUSES:
                await tick_run(db, run.id, workspace_update=lambda attempt, data: {"remaining": data["remaining"] - 1})
        root = await db.get(ProcessRun, launched.run_id)
        if root.status in process_service.TERMINAL_STATUSES:
            break
    assert root.status == "success" and root.output == {"remaining": 2}, root.error_message
    runs = list(await db.scalars(select(ProcessRun)))
    assert len(runs) == len({run.id for run in runs}) == 4
    assert all(run.status == "success" for run in runs)
    assert all(run.root_run_id == launched.run_id for run in runs if run.id != launched.run_id)
    for run in runs:
        dataset = (await read_run_data(run.id, owner_id))["data"]
        assert dataset == run.output == {"remaining": max(0, run.input["remaining"] - 1)}


@pytest.mark.asyncio
async def test_nonterminating_recursive_process_remains_cancellable_without_a_depth_budget(db, native):
    owner, _ = native
    owner_id = owner.id
    code = "synthetic_unbounded_" + uuid4().hex
    value = Workflow(nodes=[Node(id="begin", kind="start"),
        Node(id="recurse", kind="call", config={"process_code": code}), Node(id="finish", kind="end")],
        flows=[Flow(id="a", source="begin", target="recurse"), Flow(id="b", source="recurse", target="finish")])
    await create(actor_agent_id=owner_id, title="Synthetic unbounded process", code=code, graph=value)
    launched = await process_service.start_process(agent_id=owner_id, workflow_id=code, input_data={})
    for _ in range(8):
        await process_service.process_start_jobs(engine_code="galaris")
        for run in list(await db.scalars(select(ProcessRun))):
            await process_service.refresh_run(run.id)
    runs = list(await db.scalars(select(ProcessRun)))
    assert len(runs) > 2 and all(run.status not in process_service.TERMINAL_STATUSES for run in runs)
    count = len(runs)
    await process_service.cancel_run(launched.run_id)
    for _ in range(30):
        registry.register(NativeProcessEngine())
        db.expire_all()
        await process_service.process_start_jobs(engine_code="galaris")
        runs = list(await db.scalars(select(ProcessRun)))
        for run in runs:
            await process_service.refresh_run(run.id)
        if all(run.status == "cancelled" for run in runs):
            break
    assert len(runs) == count and all(run.status == "cancelled" for run in runs)


async def native_agents(db, tmp_path):
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=2_000_000))
    title = Title(label="Synthetic process", gender="X")
    db.add(title)
    await db.flush()
    first = Agent(title_id=title.id, code="native-" + uuid4().hex, first_name="Native", last_name="Owner", agent_driver="internal")
    second = Agent(title_id=title.id, code="native-" + uuid4().hex, first_name="Native", last_name="Reader", agent_driver="internal")
    db.add_all([first, second])
    await db.flush()
    registry.register(NativeProcessEngine())
    return first, second


@pytest_asyncio.fixture
async def native(db, tmp_path):
    agents = await native_agents(db, tmp_path)
    try:
        yield agents
    finally:
        reset_storage_registry()


@pytest_asyncio.fixture
async def committed_native(inference_db, tmp_path):
    agents = await native_agents(inference_db, tmp_path)
    try:
        yield agents
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_definition_acl_current_save_history_restore_and_frozen_run(db, native):
    owner, reader = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic workflow", graph=graph())
    with pytest.raises(PermissionError):
        await read(definition.code, reader.id)
    assert definition.document_id is None and definition.bpmn_xml
    from app.process.native_sharing import grant_agent
    await grant_agent(definition.code, owner.id, reader.id)
    assert not (await read(definition.code, reader.id))["can_write"]
    with pytest.raises(PermissionError):
        await update(definition.code, reader.id, expected_revision=1, graph=graph("Unauthorized"))
    first = await process_service.start_process(agent_id=reader.id, workflow_id=definition.code, input_data={})
    saved = await update(definition.code, owner.id, expected_revision=1, graph=graph("Updated instructions"))
    with pytest.raises(DefinitionConflictError):
        await update(definition.code, owner.id, expected_revision=1, graph=graph("Stale"))
    second = await process_service.start_process(agent_id=reader.id, workflow_id=definition.code, input_data={})
    first_run = await db.get(ProcessRun, first.run_id)
    second_run = await db.get(ProcessRun, second.run_id)
    assert first_run.launch_snapshot["definition"]["revision"] == 1
    assert second_run.launch_snapshot["definition"]["revision"] == saved["revision"] == 2
    restored = await restore(definition.code, owner.id, 1, 2)
    assert restored["revision"] == 3
    assert restored["graph"]["nodes"][1]["config"]["prompt"] == graph().nodes[1].config["prompt"]
    assert first_run.launch_snapshot["definition"]["revision"] == 1
    from app.process.native_definitions import page_for
    assert (await page_for(reader.id))["items"][0]["title"] == "Synthetic workflow"
    await process_service.process_start_jobs(engine_code="galaris")
    await finish_run(db, first.run_id)
    from app.process import mcp
    from app.tools.mcp_loader import McpToolContext
    caller = McpToolContext(agent_id=owner.id, runtime="internal")
    retry = await mcp.process_run_retry(caller, str(first.run_id), "synthetic-retry")
    assert (await mcp.process_run_retry(caller, str(first.run_id), "synthetic-retry"))["run_id"] == retry["run_id"]
    from uuid import UUID
    assert (await db.get(ProcessRun, UUID(retry["run_id"]))).launch_snapshot["definition"]["revision"] == 3
    with pytest.raises(PermissionError):
        await mcp.process_run_retry(McpToolContext(agent_id=reader.id, runtime="internal"), str(first.run_id), "foreign-retry")
    from app.process.native_definitions import delete_revision, history, revision_detail
    with pytest.raises(PermissionError):
        await delete_revision(definition.code, reader.id, 2)
    with pytest.raises(DefinitionConflictError):
        await delete_revision(definition.code, owner.id, 3)
    await delete_revision(definition.code, owner.id, 2)
    assert [entry["revision"] for entry in (await history(definition.code, owner.id))["items"]] == [3, 1]
    past_only = await history(definition.code, owner.id, limit=1, exclude_current=True)
    assert [entry["revision"] for entry in past_only["items"]] == [1]
    assert past_only["total"] == 1 and not past_only["has_more"]
    with pytest.raises(LookupError):
        await revision_detail(definition.code, owner.id, 2)
    with pytest.raises(LookupError):
        await restore(definition.code, owner.id, 2, 3)
    assert (await read(definition.code, owner.id))["revision"] == 3
    assert second_run.launch_snapshot["definition"]["revision"] == 2
    await finish_run(db, second.run_id)
    assert second_run.status == "success"


@pytest.mark.asyncio
async def test_activity_inspection_is_independent_of_global_pagination_and_scoped_to_run_and_body(db, native):
    from app.process.native_runs import activity_occurrences, inspect_run, inspect_occurrence
    owner, stranger = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic activity inspection", graph=graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    nested = [ProcessNodeRun(run_id=launched.run_id, node_key="work", occurrence=f"synthetic-loop:{index}", admission_order=index,
        status="success", context={"body_path": ["loop"], "loop": {"index": index}}, output={"sample": index}) for index in range(55)]
    current = ProcessNodeRun(run_id=launched.run_id, node_key="work", occurrence="synthetic-current", admission_order=55,
        status="running", context={}, output={"sample": "current"})
    db.add_all([*nested, current])
    await db.flush()
    db.add(ProcessNodeAttempt(node_run_id=current.id, number=1, status="accepted", input={"sample": "input"},
        prompt="Synthetic executed instructions", receipt={"output": {"sample": "result"}}))
    await db.commit()
    first_page = await inspect_run(launched.run_id, owner.id)
    assert str(current.id) not in [node["id"] for node in first_page["nodes"]]
    root = await activity_occurrences(launched.run_id, "work", owner.id)
    assert root["total"] == 1 and root["items"][0]["id"] == str(current.id)
    second_page = await activity_occurrences(launched.run_id, "work", owner.id, body_path=["loop"], page=2)
    assert second_page["total"] == 55
    assert [entry["iteration"] for entry in second_page["items"]] == [4, 3, 2, 1, 0]
    assert (await activity_occurrences(launched.run_id, "work", owner.id, body_path=["loop"], page_size=500))["total"] == 55
    assert (await activity_occurrences(launched.run_id, "work", owner.id, body_path=["other-loop"]))["items"] == []
    detail = await inspect_occurrence(launched.run_id, current.id, owner.id)
    assert detail["attempts"][0]["input"] == {"sample": "input"}
    assert detail["attempts"][0]["receipt"]["output"] == {"sample": "result"}
    with pytest.raises(PermissionError):
        await activity_occurrences(launched.run_id, "work", stranger.id)
    # Sharing the Process immediately authorizes inspection of its existing run.
    await set_grant(definition.share_id, "agent", stranger.id, False)
    await db.commit()
    assert (await activity_occurrences(launched.run_id, "work", stranger.id))["total"] == 1


@pytest.mark.asyncio
async def test_task_admission_restart_reattaches_and_shared_dataset_preserves_revision_checks(db, native):
    owner, stranger = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic execution", graph=graph())
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"amount": 3})
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(response.run_id)  # start event
    await process_service.refresh_run(response.run_id)  # Task admission
    run = await db.get(ProcessRun, response.run_id)
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id))
    assert attempt.task_id is not None and "amount" in attempt.prompt
    task_id = attempt.task_id
    registry.register(NativeProcessEngine())  # empty in-memory engine after restart
    attempt.task_id = None  # admission committed but its receipt was lost
    attempt.status = "intent"
    await db.commit()
    await process_service.refresh_run(run.id)
    assert (await db.scalar(select(ProcessNodeAttempt.task_id).where(ProcessNodeAttempt.id == attempt.id))) == task_id
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).where(ProcessNodeAttempt.node_run_id == attempt.node_run_id)) == 1
    dataset = await read_run_data(run.id, owner.id)
    assert dataset["data"] == {"amount": 3}
    with pytest.raises(PermissionError):
        await read_run_data(run.id, stranger.id)
    # Runs inherit read access from their Process, without any separate grants.
    from app.process.native_runs import inspect_run, list_runs
    await set_grant(definition.share_id, "agent", stranger.id, False)
    await db.commit()
    assert not (await inspect_run(run.id, stranger.id))["can_control"]
    assert (await list_runs(stranger.id))["total"] == 1
    await write_run_json(run.id, owner.id, '{"amount": 3, "kept": true}', expected_revision=dataset["revision"])
    from app.file_share import ResourceRevisionConflict
    with pytest.raises(ResourceRevisionConflict):
        await write_run_json(run.id, owner.id, "{}", expected_revision=dataset["revision"])
    with pytest.raises(PermissionError):
        await write_run_json(run.id, stranger.id, "{}", expected_revision=dataset["revision"] + 1)
    # Cancellation must also recover an admitted Task whose receipt was lost.
    attempt.task_id = None
    attempt.status = "intent"
    await db.commit()
    await process_service.cancel_run(run.id)
    await process_service.refresh_run(run.id)
    assert (await task_service.get_by_id(task_id)).status == TaskStatus.ERROR
    assert (await process_service.get_run(run.id)).status == "cancelled"


async def tick_run(db, run_id, *, result=None, fail_first=False, fail_always=False, workspace_update=None):
    """Simulate only the external agent boundary, retaining real Task persistence."""
    attempts = list(await db.scalars(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id)))
    for attempt in attempts:
        if attempt.status in {"rest_ready", "tool_ready"}:
            from app.process.activity_jobs import execute_external_activity
            await execute_external_activity(attempt.id)
            await db.refresh(attempt)
        if attempt.task_id is None:
            continue
        task = await task_service.get_by_id(attempt.task_id)
        if task.status == TaskStatus.DISPATCH and task.ai:
            transition(task, TaskEvent.START_EXECUTION)
            failed = fail_always or fail_first and attempt.number == 1
            if not failed and workspace_update is not None:
                run = await db.get(ProcessRun, run_id)
                document = await read_run_data(run.id, task.agent_id)
                updated = workspace_update(attempt, document["data"])
                await write_run_json(run.id, task.agent_id, json.dumps(updated), expected_revision=document["revision"])
            emitted = result(attempt) if callable(result) else result if result is not None else attempt.input
            task.execution_result = {"prompt": "Synthetic driver result", "success": not failed, "result": json.dumps(emitted), "error": "Synthetic failure" if failed else ""}
            task.last_error = "Synthetic failure" if failed else None
            transition(task, TaskEvent.EXECUTION_FAILED if failed else TaskEvent.EXECUTION_SUCCEEDED)
            await task_service.update(task.id, task)
    return await process_service.refresh_run(run_id)


async def finish_run(db, run_id, **kwargs):
    for _ in range(60):
        run = await tick_run(db, run_id, **kwargs)
        if run.status in process_service.TERMINAL_STATUSES:
            return run
    raise AssertionError("Synthetic process did not finish")


def typed_graph():
    from app.process.values import Variable
    value = graph()
    value.schema_version = "galaris.bpmn/v2"
    value.inputs = [Variable(name="amount", type="int", nullable=False,
        default={"type": "int", "value": 7})]
    value.outputs = [Variable(name="accepted", type="bool", nullable=False)]
    value.nodes[1].inputs = [Variable(name="amount", type="int", nullable=False),
        Variable(name="reviewer", type="User", nullable=True)]
    value.nodes[1].outputs = [Variable(name="accepted", type="bool", nullable=False,
        default={"type": "bool", "value": False}), Variable(name="note", type="string", nullable=True)]
    return value


@pytest.mark.asyncio
async def test_typed_task_local_values_defaults_and_engine_only_global_integration(db, native):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic typed activity", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, result={})
    assert run.status == "success", run.error_message
    assert run.output == {"accepted": {"type": "bool", "value": False}}
    assert not {"integrations", "integration_results", "attachments", "execution_state"}.intersection(run.data)
    assert run.execution_state["integrations"]
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id))
    assert attempt.input == {"amount": {"type": "int", "value": 7}, "reviewer": {"type": "User", "value": None}}
    assert "Shared run Dataset (read/write)" not in attempt.prompt
    content = await read_run_data(run.id, owner.id)
    assert {"data": content["data"], "files": content["files"]} == {"data": {
        "amount": {"type": "int", "value": 7}, "accepted": {"type": "bool", "value": False},
        "note": {"type": "string", "value": None}}, "files": []}
    with pytest.raises(RunDataConflictError, match="stopped run"):
        await write_run_json(run.id, owner.id, '{}', expected_revision=content["revision"])


@pytest.mark.asyncio
async def test_typed_invalid_input_never_admits_an_activity_or_partial_output(db, native):
    from app.process.values import Variable, ValueContractError
    owner, _ = native
    value = typed_graph()
    definition = await create(actor_agent_id=owner.id, title="Synthetic invalid input", graph=value)
    with pytest.raises(ValueContractError, match="process.input.amount"):
        await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
            input_data={"amount": {"type": "string", "value": "7"}})
    assert await db.scalar(select(func.count()).select_from(ProcessRun).where(ProcessRun.process_id == definition.id)) == 0
    value.nodes[1].inputs.append(Variable(name="missing", type="File", nullable=False))
    await update(definition.code, owner.id, expected_revision=(await read(definition.code, owner.id))["revision"], graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, result={})
    assert run.status == "error" and "work.input.missing" in run.error_message
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).join(ProcessNodeRun)
        .where(ProcessNodeRun.run_id == run.id)) == 0
    assert (await read_run_data(run.id, owner.id))["data"] == {"amount": {"type": "int", "value": 7}}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"accepted": {"type": "int", "value": 1}}, "No validated output was submitted."])
async def test_typed_invalid_output_is_not_integrated_and_does_not_launch_successor(db, native, response):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic invalid output", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, result=response)
    assert run.status == "error" and "work.output" in run.error_message
    assert "process_activity_complete" in run.error_message
    assert not await db.scalar(select(ProcessNodeRun.id).where(ProcessNodeRun.run_id == run.id, ProcessNodeRun.node_key == "end"))
    assert (await read_run_data(run.id, owner.id))["data"] == {"amount": {"type": "int", "value": 7}}


@pytest.mark.asyncio
async def test_typed_file_manifests_keep_source_uris_without_transferring_bytes(db, native, monkeypatch):
    from app.memory import document_service
    from app.process import ProcessFileInput
    import app.file_share as file_share
    owner, _ = native
    source = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic reference",
        content='{"invented": true}', task_id=None, document_type="dataset")
    async def no_transfer(*args, **kwargs):
        raise AssertionError("Typed admission must not materialize files")
    monkeypatch.setattr(file_share, "materialize_resource", no_transfer)
    definition = await create(actor_agent_id=owner.id, title="Synthetic references", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
        input_data={}, files=[ProcessFileInput(uri=f"document://{source.id}")])
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, result={})
    assert run.status == "success", run.error_message
    content = await read_run_data(run.id, owner.id)
    assert [entry["uri"] for entry in content["files"]] == [f"document://{source.id}"]
    assert "workflow_attachments" not in run.data


@pytest.mark.asyncio
async def test_typed_integrations_preserve_disjoint_writes_and_deduplicate_receipts(db, native):
    from app.process.run_data import integrate_workflow_values
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic merge", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await db.get(ProcessRun, launched.run_id)
    first = {"a": {"type": "int", "value": 1}}
    result = await integrate_workflow_values(run.id, command="first", baseline={}, changes=first, files=[])
    replay = await integrate_workflow_values(run.id, command="first", baseline={}, changes=first, files=[])
    assert replay["revision"] == result["revision"]
    second = {"b": {"type": "int", "value": 2}}
    merged = await integrate_workflow_values(run.id, command="second", baseline={}, changes=second, files=[])
    assert merged["data"] == {"amount": {"type": "int", "value": 7}, **first, **second}
    with pytest.raises(RunDataConflictError, match="variable a"):
        await integrate_workflow_values(run.id, command="conflict", baseline={},
            changes={"a": {"type": "int", "value": 3}}, files=[])
    assert set(run.execution_state["integrations"]) == {"first", "second"}
    with pytest.raises(RunDataConflictError, match="different result"):
        await integrate_workflow_values(run.id, command="first", baseline={}, changes=second, files=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("child_typed", [False, True])
async def test_typed_calls_map_local_names_and_preserve_legacy_child_json(db, native, child_typed):
    from app.process.values import Variable
    owner, _ = native
    child_graph = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="finish", kind="end")],
        flows=[Flow(id="done", source="begin", target="finish")])
    if child_typed:
        child_graph.schema_version = "galaris.bpmn/v2"
        child_graph.inputs = [Variable(name="child_amount", type="int", nullable=False)]
        child_graph.outputs = [Variable(name="answer", type="int", nullable=False, default={"type": "int", "value": 9})]
    child_definition = await create(actor_agent_id=owner.id, title="Synthetic child contract", graph=child_graph)
    output = Variable(name="answer", type="int", nullable=False)
    config = {"process_code": child_definition.code, "input_mapping": {"child_amount": {"$expr": "data.amount"}}}
    if not child_typed:
        config["external_output"] = {"answer": {"$expr": "result.child_amount"}}
    parent = await create(actor_agent_id=owner.id, title="Synthetic local call", graph=Workflow(
        schema_version="galaris.bpmn/v2", inputs=[Variable(name="amount", type="int", nullable=False, default={"type": "int", "value": 7})],
        outputs=[output], nodes=[Node(id="start", kind="start"), Node(id="child", kind="call", config=config,
            inputs=[Variable(name="child_amount", type="int", nullable=False)], outputs=[output]), Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="child"), Flow(id="b", source="child", target="end")]))
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=parent.code, input_data={})
    nested = None
    for _ in range(20):
        await process_service.process_start_jobs(engine_code="galaris")
        run = await tick_run(db, launched.run_id)
        nested = await db.scalar(select(ProcessRun).where(ProcessRun.parent_run_id == run.id))
        if nested is not None:
            await tick_run(db, nested.id)
        if run.status in process_service.TERMINAL_STATUSES:
            break
    child_nodes = list((await db.execute(select(ProcessNodeRun.node_key, ProcessNodeRun.status).where(ProcessNodeRun.run_id == nested.id))).all())
    assert run.status == "success", (run.error_message, nested.status, nested.engine_metadata.get("native"), child_nodes)
    assert run.output == {"answer": {"type": "int", "value": 9 if child_typed else 7}}
    assert nested.input == {"child_amount": {"type": "int", "value": 7}} if child_typed else nested.input == {"child_amount": 7}


@pytest.mark.asyncio
async def test_native_poll_before_admission_does_not_skip_the_start_job(db, native):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic early observation", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    observed = await process_service.refresh_run(launched.run_id)
    assert observed.status == "queued" and observed.data == {}
    await process_service.process_start_jobs(engine_code="galaris")
    assert (await finish_run(db, launched.run_id, result={})).status == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("a", "b", "c"), ("c", "b", "a"), ("b", "a", "c"), ("b", "c", "a"), ("a", "c", "b"), ("c", "a", "b")])
@pytest.mark.parametrize("nested", ["direct", "activity", "legacy_gateway"])
async def test_typed_human_branches_converge_once_after_all_predecessors(db, native, order, nested):
    from app.agent import AgentManagementScope
    from core.user import UserModel
    from app.process.native_actors import human_work, complete_human_work
    from app.process.values import Variable, ValueContractError
    owner, _ = native
    user = UserModel(email=f"synthetic-join-{uuid4().hex}@example.invalid", hashed_password="unused", is_active=True)
    db.add(user); await db.flush()
    scope = AgentManagementScope(user.id, frozenset())
    nodes = [Node(id="start", kind="start"), Node(id="end", kind="end")]
    for index, name in enumerate(("a", "b", "c")):
        nodes.append(Node(id=name, kind="human_task", config={"prompt": "Synthetic branch", "actor": "reviewer"}, inputs=[],
            outputs=[Variable(name=name, type="int", nullable=False, default={"type": "int", "value": index})]))
    accepted = Variable(name="accepted", type="bool", nullable=False, default={"type": "bool", "value": False})
    nodes.append(Node(id="converge", kind="human_task", config={"prompt": "Review all three values", "actor": "reviewer"},
        inputs=[Variable(name=name, type="int", nullable=False) for name in ("a", "b", "c")], outputs=[accepted]))
    value = Workflow(schema_version="galaris.bpmn/v2", inputs=[], outputs=[accepted], nodes=nodes,
        actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)],
        flows=[*[Flow(id="start_" + name, source="start", target=name) for name in ("a", "b", "c")],
            *[Flow(id=name + "_join", source=name, target="converge") for name in ("a", "b", "c")],
            Flow(id="done", source="converge", target="end")])
    if nested != "direct":
        value.nodes.append(Node(id="split", kind="human_task", config={"prompt": "Start both branches", "actor": "reviewer"}, inputs=[], outputs=[])
            if nested == "activity" else Node(id="split", kind="parallel"))
        value.flows = [flow for flow in value.flows if flow.id not in {"start_a", "start_b"}]
        value.flows.extend([Flow(id="start_split", source="start", target="split"),
            Flow(id="split_a", source="split", target="a"), Flow(id="split_b", source="split", target="b")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic convergence", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4):
        await process_service.refresh_run(launched.run_id)
    work = (await human_work(scope, page=1, page_size=50))["items"]
    if nested == "activity":
        # The ordinary activity and the independent third branch are both admitted.
        assert len(work) == 2
        for item in work:
            attempt = await db.get(ProcessNodeAttempt, UUID(item["attempt_id"]))
            if (await db.get(ProcessNodeRun, attempt.node_run_id)).node_key == "split":
                await complete_human_work(attempt.id, scope, {})
        for _ in range(4):
            await process_service.refresh_run(launched.run_id)
        work = (await human_work(scope, page=1, page_size=50))["items"]
    assert len(work) == 3
    by_name = {str((await db.get(ProcessNodeRun, (await db.get(ProcessNodeAttempt, UUID(item["attempt_id"]))).node_run_id)).node_key): item for item in work}
    for index, name in enumerate(order):
        attempt_id = UUID(by_name[name]["attempt_id"])
        with pytest.raises(ValueContractError, match="null is not allowed"):
            await complete_human_work(attempt_id, scope, {name: {"type": "int", "value": None}})
        await complete_human_work(attempt_id, scope, {})
        # The same omitted result reuses its normalized completion receipt.
        assert (await complete_human_work(attempt_id, scope, {}))["completed"]
        for _ in range(3):
            await process_service.refresh_run(launched.run_id)
        joins = list(await db.scalars(select(ProcessNodeAttempt).join(ProcessNodeRun).where(
            ProcessNodeRun.run_id == launched.run_id, ProcessNodeRun.node_key == "converge")))
        assert len(joins) == (1 if index == 2 else 0)
    assert joins[0].input == {name: {"type": "int", "value": index} for index, name in enumerate(("a", "b", "c"))}
    await complete_human_work(joins[0].id, scope, {})
    run = await finish_run(db, launched.run_id)
    assert run.status == "success", run.error_message
    assert run.output == {"accepted": {"type": "bool", "value": False}}


@pytest.mark.asyncio
async def test_typed_parallel_end_events_validate_output_only_after_all_branches(db, native):
    from app.agent import AgentManagementScope
    from core.user import UserModel
    from app.process.native_actors import human_work, complete_human_work
    from app.process.values import Variable
    owner, _ = native
    user = UserModel(email=f"synthetic-ends-{uuid4().hex}@example.invalid", hashed_password="unused", is_active=True)
    db.add(user); await db.flush()
    scope = AgentManagementScope(user.id, frozenset())
    outputs = [Variable(name=name, type="int", nullable=False) for name in ("a", "b")]
    value = Workflow(schema_version="galaris.bpmn/v2", inputs=[], outputs=outputs,
        actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)],
        nodes=[Node(id="start", kind="start"), *[
            node for output in outputs for node in (
                Node(id=output.name, kind="human_task", inputs=[], outputs=[output], config={"actor": "reviewer", "prompt": "Return the synthetic branch value."}),
                Node(id="end_" + output.name, kind="end"))]],
        flows=[flow for name in ("a", "b") for flow in (
            Flow(id="start_" + name, source="start", target=name), Flow(id="done_" + name, source=name, target="end_" + name))])
    definition = await create(actor_agent_id=owner.id, title="Synthetic parallel ends", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(3):
        await process_service.refresh_run(launched.run_id)
    work = (await human_work(scope, page=1, page_size=50))["items"]
    by_name = {item["outputs"][0]["name"]: UUID(item["attempt_id"]) for item in work}
    await complete_human_work(by_name["a"], scope, {"a": {"type": "int", "value": 1}})
    for _ in range(4):
        run = await process_service.refresh_run(launched.run_id)
    assert run.status == "running", run.error_message
    await complete_human_work(by_name["b"], scope, {"b": {"type": "int", "value": 2}})
    run = await finish_run(db, launched.run_id)
    assert run.status == "success", run.error_message
    assert run.output == {"a": {"type": "int", "value": 1}, "b": {"type": "int", "value": 2}}


@pytest.mark.asyncio
@pytest.mark.parametrize("denied", [False, True])
async def test_typed_rest_activity_uses_the_live_connection_and_retains_remote_denials(db, native, api_server, denied):
    from app.tools import tool_service
    from app.tools.schemas import ToolCreate
    from app.connection import connection_service
    from app.process.values import Variable
    owner, _ = native
    base, requests = api_server
    tool = await tool_service.create_tool(ToolCreate(code=f"synthetic_api_{uuid4().hex}", label="Synthetic API",
        rest_config={"base_url": base, "auth": {"type": "none"}}))
    await connection_service.get_or_create_connection(tool.id, owner.id)
    output = Variable(name="method", type="string", nullable=False)
    value = Workflow(schema_version="galaris.bpmn/v2", inputs=[], outputs=[output],
        nodes=[Node(id="start", kind="start"), Node(id="api", kind="rest", inputs=[], outputs=[output],
            config={"tool_code": tool.code, "request": {"method": "POST", "path": "denied" if denied else "synthetic"},
                "external_output": {"method": {"$expr": "result.body.method"}}}), Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="api"), Flow(id="b", source="api", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic REST activity", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id)
    assert len(requests) == 1
    if denied:
        assert run.status == "error" and run.error_code == "rest_http_error"
        assert "403" in run.error_message
    else:
        assert run.status == "success", run.error_message
        assert run.output == {"method": {"type": "string", "value": "POST"}}


@pytest.mark.asyncio
async def test_typed_result_integration_recovers_a_lost_ack_without_reexecuting_the_task(db, native, monkeypatch):
    import asyncio
    import app.process.native_engine as facade
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic lost integration reply", graph=typed_graph())
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(launched.run_id)
    await process_service.refresh_run(launched.run_id)
    real = facade.integrate_workflow_values
    revisions = []
    async def lose_reply(*args, **kwargs):
        result = await real(*args, **kwargs)
        revisions.append(result["revision"])
        if len(revisions) == 1:
            raise asyncio.CancelledError()
        return result
    monkeypatch.setattr(facade, "integrate_workflow_values", lose_reply)
    with pytest.raises(asyncio.CancelledError):
        await tick_run(db, launched.run_id, result={})
    run = await db.get(ProcessRun, launched.run_id)
    state = dict(run.engine_metadata["native"])
    state.pop("lease_until", None); state.pop("lease", None)
    run.engine_metadata = {**run.engine_metadata, "native": state}
    await db.commit()
    run = await finish_run(db, run.id, result={})
    assert run.status == "success", run.error_message
    assert len(revisions) == 2 and revisions[0] == revisions[1]
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 1


@pytest.mark.asyncio
async def test_inline_code_has_no_backend_fallback_without_a_qualified_runner(db, native, monkeypatch):
    from app.process import isolated_code
    owner, _ = native
    monkeypatch.setattr(isolated_code, "_runner", None)
    value = typed_graph()
    value.nodes[1].kind = "code"
    value.nodes[1].config = {"code": "raise AssertionError('must never run in the backend')"}
    definition = await create(actor_agent_id=owner.id, title="Synthetic confinement gate", graph=value)
    assert (await read(definition.code, owner.id))["diagnostics"][0]["code"] == "isolated_runner_unavailable"
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id)
    assert run.status == "error" and run.error_code == "isolated_runner_unavailable"
    assert (await read_run_data(run.id, owner.id))["data"] == {"amount": {"type": "int", "value": 7}}


@pytest.mark.asyncio
async def test_isolated_phases_freeze_requests_and_wait_for_confirmed_stop_before_integration(db, native, monkeypatch):
    from app.process import isolated_code
    from app.process.isolated_code import CodeObservation
    from app.process.values import Variable
    owner, _ = native
    invocations = {}
    observations = {}
    class Runner:
        async def submit(self, invocation):
            assert invocation.id not in invocations
            invocations[invocation.id] = invocation
            observations[invocation.id] = 0
            return CodeObservation(status="queued")
        async def observe(self, identity):
            invocation = invocations[identity]
            observations[identity] += 1
            if observations[identity] == 1:
                return CodeObservation(status="success", stopped=False, result={"output": {}})
            if invocation.phase == "preprocess":
                result = {"input": {"local": invocation.values["data"]["amount"]}, "input_files": []}
            elif invocation.phase == "activity":
                assert invocation.values["input"] == {"local": {"type": "int", "value": 7}}
                result = {"output": {"accepted": {"type": "bool", "value": True}}, "output_files": []}
            else:
                result = {"data": {**invocation.values["data"], **invocation.values["output"]}, "files": []}
            return CodeObservation(status="success", stopped=True, result=result)
        async def cancel(self, identity):
            return CodeObservation(status="cancelled", stopped=True)
    monkeypatch.setattr(isolated_code, "_runner", Runner())
    value = typed_graph()
    value.nodes[1].kind = "code"
    value.nodes[1].inputs = [Variable(name="local", type="int", nullable=False)]
    value.nodes[1].config = {"code": "output['accepted'] = {'type': 'bool', 'value': True}",
        "preprocess": "input['local'] = data['amount']", "postprocess": "data.update(output)"}
    definition = await create(actor_agent_id=owner.id, title="Synthetic remote phases", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id)
    assert run.status == "success", run.error_message
    assert run.output == {"accepted": {"type": "bool", "value": True}}
    assert [invocation.phase for invocation in invocations.values()] == ["preprocess", "activity", "postprocess"]
    assert all(invocation.agent_id == owner.id and invocation.run_id == run.id for invocation in invocations.values())
    assert all(count == 2 for count in observations.values())


@pytest.mark.asyncio
async def test_isolated_code_cancellation_requires_the_runners_physical_stop_receipt(db, native, monkeypatch):
    from app.process import isolated_code
    from app.process.isolated_code import CodeObservation
    owner, _ = native
    invocations = []
    cancelled = []
    class Runner:
        async def submit(self, invocation):
            invocations.append(invocation.id)
            return CodeObservation(status="running")
        async def observe(self, identity):
            return CodeObservation(status="running")
        async def cancel(self, identity):
            cancelled.append(identity)
            return CodeObservation(status="cancelled", stopped=len(cancelled) > 1)
    monkeypatch.setattr(isolated_code, "_runner", Runner())
    value = typed_graph()
    value.nodes[1].kind = "code"
    value.nodes[1].config = {"code": "while True: pass"}
    definition = await create(actor_agent_id=owner.id, title="Synthetic remote stop", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(launched.run_id)
    await process_service.refresh_run(launched.run_id)
    assert len(invocations) == 1
    first = await process_service.cancel_run(launched.run_id)
    assert first.status == "cancelling"
    second = await process_service.refresh_run(launched.run_id)
    assert second.status == "cancelled" and cancelled == [invocations[0], invocations[0]]
    assert second.output is None


@pytest.mark.asyncio
async def test_slow_rest_activity_does_not_block_its_human_branch_or_allow_double_dispatch(inference_db, committed_native):
    import asyncio
    from core.database import get_db_session
    from core.user import UserModel
    from app.agent import AgentManagementScope
    from app.tools import tool_service
    from app.tools.schemas import ToolCreate
    from app.connection import connection_service
    from app.process.activity_jobs import execute_external_activity
    from app.process.native_actors import human_work, complete_human_work
    from app.process.values import Variable
    db = inference_db
    owner, _ = committed_native
    started, release = asyncio.Event(), asyncio.Event()
    requests = []
    async def handle(reader, writer):
        try:
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            started.set()
            await release.wait()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    worker = None
    try:
        tool = await tool_service.create_tool(ToolCreate(code=f"synthetic_slow_{uuid4().hex}", label="Synthetic gated API",
            rest_config={"base_url": f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"}))
        await connection_service.get_or_create_connection(tool.id, owner.id)
        user = UserModel(email=f"synthetic-fast-{uuid4().hex}@example.invalid", hashed_password="unused", is_active=True)
        db.add(user); await db.flush()
        scope = AgentManagementScope(user.id, frozenset())
        output = Variable(name="fast", type="bool", nullable=False, default={"type": "bool", "value": True})
        definition = await create(actor_agent_id=owner.id, title="Synthetic independent branches", graph=Workflow(
            schema_version="galaris.bpmn/v2", inputs=[], outputs=[output],
            actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)],
            nodes=[Node(id="start", kind="start"), Node(id="slow", kind="rest", inputs=[], outputs=[], config={"tool_code": tool.code}),
                Node(id="fast", kind="human_task", inputs=[], outputs=[output], config={"prompt": "Synthetic fast branch", "actor": "reviewer"}),
                Node(id="end", kind="end")], flows=[Flow(id="a", source="start", target="slow"), Flow(id="b", source="start", target="fast"),
                    Flow(id="c", source="slow", target="end"), Flow(id="d", source="fast", target="end")]))
        launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
        await process_service.process_start_jobs(engine_code="galaris")
        for _ in range(3):
            await process_service.refresh_run(launched.run_id)
        attempt_id = await db.scalar(select(ProcessNodeAttempt.id).join(ProcessNodeRun).where(
            ProcessNodeRun.run_id == launched.run_id, ProcessNodeRun.node_key == "slow"))
        async def execute():
            async with get_db_session():
                await execute_external_activity(attempt_id)
        worker = asyncio.create_task(execute())
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.wait_for(execute(), 5)
        assert len(requests) == 1
        work = (await human_work(scope, page=1, page_size=50))["items"]
        assert len(work) == 1
        await complete_human_work(UUID(work[0]["attempt_id"]), scope, {})
        await asyncio.wait_for(process_service.refresh_run(launched.run_id), 5)
        run = await db.get(ProcessRun, launched.run_id)
        assert (await read_run_data(run.id, owner.id))["data"] == {"fast": {"type": "bool", "value": True}}
        assert not worker.done()
        release.set()
        await asyncio.wait_for(worker, 5)
        run = await finish_run(db, launched.run_id)
        assert run.status == "success", run.error_message
        assert len(requests) == 1
    finally:
        release.set()
        if worker is not None:
            await worker
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", [False, True])
async def test_wide_frontier_admits_all_humans_even_when_earlier_activities_wait(db, native, typed):
    from core.user import UserModel
    from app.agent import AgentManagementScope
    from app.process.native_actors import human_work
    owner, _ = native
    user = UserModel(email=f"synthetic-frontier-{uuid4().hex}@example.invalid", hashed_password="unused", is_active=True)
    db.add(user); await db.flush()
    scope = AgentManagementScope(user.id, frozenset())
    declarations = {"inputs": [], "outputs": []} if typed else {}
    nodes = [Node(id="start", kind="start"), Node(id="end", kind="end")]
    nodes.extend(Node(id=f"work_{index}", kind="human_task", config={"prompt": "Synthetic wide frontier", "actor": "reviewer"}, **declarations) for index in range(55))
    value = Workflow(schema_version="galaris.bpmn/v2" if typed else "galaris.bpmn/v1", **declarations, nodes=nodes,
        actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)],
        flows=[*[Flow(id=f"start_{index}", source="start", target=f"work_{index}") for index in range(55)],
            *[Flow(id=f"end_{index}", source=f"work_{index}", target="end") for index in range(55)]])
    definition = await create(actor_agent_id=owner.id, title="Synthetic wide frontier", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(5):
        await process_service.refresh_run(launched.run_id)
    assert (await human_work(scope, page=1, page_size=500))["total"] == 55


@pytest.mark.asyncio
async def test_tasks_share_writable_run_json_and_attachments_without_mappings(db, native):
    owner, stranger = native
    value = Workflow(nodes=[Node(id="start", kind="start"),
        Node(id="prepare", kind="task", config={"prompt": "Prepare shared data"}),
        Node(id="review", kind="task", config={"prompt": "Review shared data"}), Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="prepare"), Flow(id="b", source="prepare", target="review"),
            Flow(id="c", source="review", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic shared workspace", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"amount": 3})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(3):
        await process_service.refresh_run(launched.run_id)
    run = await db.get(ProcessRun, launched.run_id)
    document = await read_run_data(run.id, owner.id)
    assert document["can_write"]
    assert document["data"] == {"amount": 3}
    with pytest.raises(PermissionError):
        await read_run_data(run.id, stranger.id)
    from app.file_share import ResourceContext, resource_write, resource_create
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    await resource_write(context, f"galaris://processes/runs/{run.id}/data", b'{"amount": 3, "approved": true}',
        expected_revision=document["revision"])
    attachment = await resource_create(context, f"galaris://processes/runs/{run.id}/attachments/",
        b"Synthetic shared report", name="report.txt")
    await tick_run(db, run.id)
    for _ in range(3):
        await process_service.refresh_run(run.id)
    attempts = list(await db.scalars(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)))
    assert len(attempts) == 2
    assert all(f"galaris://processes/runs/{run.id}/data" in attempt.prompt for attempt in attempts)
    review = next(attempt for attempt in attempts if "Review shared data" in attempt.prompt)
    assert review.input == {"amount": 3, "approved": True}
    assert f"galaris://processes/runs/{run.id}/attachments/" in review.prompt
    assert [item["uri"] for item in await run_files(run.id)] == [attachment.uri]
    finished = await finish_run(db, run.id)
    assert finished.status == "success" and finished.output == {"amount": 3, "approved": True}
    assert (await read_run_data(run.id, owner.id))["data"] == finished.output
    second = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"amount": 9})
    await process_service.process_start_jobs(engine_code="galaris")
    other_run = await db.get(ProcessRun, second.run_id)
    assert other_run.id != run.id
    assert (await read_run_data(other_run.id, owner.id))["data"] == {"amount": 9}
    assert not await run_files(other_run.id)


@pytest.mark.asyncio
async def test_parallel_tasks_merge_disjoint_data_and_wait_for_all(db, native):
    owner, _ = native
    definition_graph = Workflow(nodes=[Node(id="start", kind="start"), Node(id="split", kind="parallel"),
        Node(id="left", kind="task", config={"prompt": "Left"}),
        Node(id="right", kind="task", config={"prompt": "Right"}),
        Node(id="join", kind="parallel"), Node(id="end", kind="end")],
        flows=[Flow(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate([
            ("start", "split"), ("split", "left"), ("split", "right"), ("left", "join"), ("right", "join"), ("join", "end")])])
    definition = await create(actor_agent_id=owner.id, title="Parallel synthetic branches", graph=definition_graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    def write_branch(attempt, data):
        return {**data, **({"left": 1} if attempt.prompt.startswith("Left") else {"right": 2})}
    run = await finish_run(db, launched.run_id, workspace_update=write_branch)
    assert run.status == "success" and run.output == {"left": 1, "right": 2}, run.error_message
    dataset = (await read_run_data(run.id, owner.id))["data"]
    assert dataset == run.output
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) >= 6


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,branch", [(5, "ordinary"), (12, "large")])
@pytest.mark.parametrize("typed", [False, True])
async def test_if_admits_only_the_selected_branch(db, native, amount, branch, typed):
    owner, _ = native
    value = Workflow(nodes=[Node(id="start", kind="start"), Node(id="prepare", kind="task", config={"prompt": "Set decision amount"}), Node(id="choice", kind="if"),
        Node(id="ordinary", kind="task", config={"prompt": "Invent an ordinary outcome"}),
        Node(id="large", kind="task", config={"prompt": "Invent a large outcome"}),
        Node(id="end", kind="end")], flows=[Flow(id="f1", source="start", target="prepare"),
            Flow(id="prepared", source="prepare", target="choice"),
            Flow(id="f2", source="choice", target="large", condition="data.amount >= 10"),
            Flow(id="f3", source="choice", target="ordinary"), Flow(id="f4", source="large", target="end"),
            Flow(id="f5", source="ordinary", target="end")])
    if typed:
        from app.process.values import Variable
        value.schema_version = "galaris.bpmn/v2"
        value.inputs = [Variable(name="amount", type="int", nullable=False)]
        value.outputs = [Variable(name="branch", type="string", nullable=False)]
        for node in value.nodes:
            if node.kind == "task":
                node.inputs = []
                node.outputs = [Variable(name="amount", type="int", nullable=False)] if node.id == "prepare" else value.outputs
        value.flows[2].condition = "data.amount.value >= 10"
    definition = await create(actor_agent_id=owner.id, title="Synthetic conditional workflow", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
        input_data={"amount": {"type": "int", "value": 0}} if typed else {"amount": 0})
    await process_service.process_start_jobs(engine_code="galaris")
    if typed:
        run = await finish_run(db, launched.run_id, result=lambda attempt:
            {"amount": {"type": "int", "value": amount}} if attempt.prompt.startswith("Set decision amount") else {"branch": {"type": "string", "value": branch}})
        assert run.status == "success", run.error_message
        assert run.output == {"branch": {"type": "string", "value": branch}}
    else:
        run = await finish_run(db, launched.run_id, workspace_update=lambda attempt, data:
            {"amount": amount} if attempt.prompt.startswith("Set decision amount") else {**data, "branch": branch})
        assert run.output == {"amount": amount, "branch": branch}
    admitted = list(await db.scalars(select(ProcessNodeRun.node_key).join(ProcessNodeAttempt,
        ProcessNodeAttempt.node_run_id == ProcessNodeRun.id).where(ProcessNodeRun.run_id == run.id)))
    assert sorted(admitted) == sorted(["prepare", branch])


@pytest.mark.asyncio
async def test_shared_files_are_copied_once_and_forwarded_to_child_run_workspaces(db, native):
    from app.memory import document_service
    from app.process import ProcessFileInput
    owner, _ = native
    source = await document_service.create_document(owner_agent_id=owner.id, title="Invented input file",
        content='{"value": 7}', task_id=None, document_type="dataset")
    child_graph = graph()
    child = await create(actor_agent_id=owner.id, title="Synthetic shared child", graph=child_graph)
    reference = ProcessFileInput(uri=f"document://{source.id}")
    parent_graph = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="child", kind="call", config={"process_code": child.code}),
        Node(id="finish", kind="end", config={"output": {"$expr": "results.child"}})],
        flows=[Flow(id="a", source="begin", target="child"), Flow(id="b", source="child", target="finish")])
    parent = await create(actor_agent_id=owner.id, title="Synthetic file forwarding", graph=parent_graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=parent.code, input_data={"value": 7}, files=[reference])
    await process_service.process_start_jobs(engine_code="galaris")
    root = await db.get(ProcessRun, launched.run_id)
    frozen = next(iter(root.execution_state["attachments"].values()))
    assert "workflow_attachments" not in root.data
    assert frozen["origin_uri"] == reference.uri and frozen["uri"].startswith(f"galaris://processes/runs/{root.id}/attachments/")
    from app.file_share import ResourceContext, materialize_resource, resource_list
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    manifest = await resource_list(context, f"galaris://processes/runs/{root.id}/attachments/")
    assert len(manifest.entries) == 1
    # Replay startup after a lost reply: the completed copy receipt is reused.
    from app.process.schemas import ProcessStartPayload
    engine = NativeProcessEngine()
    await engine.start_run(parent.code, process_service._engine_run_reference(root), ProcessStartPayload())
    assert len((await resource_list(context, f"galaris://processes/runs/{root.id}/attachments/")).entries) == 1
    await write_workflow_document(source.id, owner.id, '{"value": 9}', expected_revision=source.revision)
    await process_service.refresh_run(launched.run_id)
    await process_service.refresh_run(launched.run_id)
    nested = await db.scalar(select(ProcessRun).where(ProcessRun.parent_run_id == launched.run_id))
    await process_service.process_start_jobs(engine_code="galaris")
    await finish_run(db, nested.id)
    assert (await finish_run(db, launched.run_id)).output == {"value": 7}
    nested_file = next(iter(nested.execution_state["attachments"].values()))
    assert nested_file["origin_uri"] == manifest.entries[0].uri
    assert nested_file["uri"].startswith(f"galaris://processes/runs/{nested.id}/attachments/")
    assert "download_url" not in nested_file
    prompt = await db.scalar(select(ProcessNodeAttempt.prompt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == nested.id))
    from app.file_share import resource_info
    assert (await resource_info(context, nested_file["uri"])).uri in prompt and nested.callback_token not in prompt
    from pathlib import Path
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        path = Path(directory) / "frozen"
        await materialize_resource(context, nested_file["uri"], path, max_bytes=1000)
        assert json.loads(path.read_text()) == {"value": 7}


@pytest.mark.asyncio
async def test_revoked_source_file_access_prevents_any_node_admission(db, native):
    from app.memory import document_service
    from app.process import ProcessFileInput
    from app.file_share import ResourceContext, resource_list

    owner, reader = native
    source = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic revocable source",
        content='{"value": 7}', task_id=None, document_type="dataset")
    value = graph()
    definition = await create(actor_agent_id=owner.id, title="Synthetic revocable file process", graph=value)
    await memory.set_item_grant(source.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    from app.process.native_sharing import grant_agent
    await grant_agent(definition.code, owner.id, reader.id)
    launched = await process_service.start_process(agent_id=reader.id, workflow_id=definition.code, input_data={},
        files=[ProcessFileInput(uri=f"document://{source.id}", slot="data")])
    await memory.remove_item_grant(source.id, reader.id, actor_agent_id=owner.id)
    await process_service.process_start_jobs(engine_code="galaris")
    run = await db.get(ProcessRun, launched.run_id)
    assert run.execution_state["data_initialized"]
    assert not run.engine_metadata.get("native", {}).get("initialized")
    assert run.status == "error" and run.error_code == "process_start_failed"
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 0
    assert not (await resource_list(ResourceContext(agent_id=reader.id, runtime="internal"),
        f"galaris://processes/runs/{run.id}/attachments/")).entries


@pytest.mark.asyncio
async def test_cancellation_during_file_materialization_prevents_copy_and_node_admission(db, native, monkeypatch):
    from app.memory import document_service
    from app.process import ProcessFileInput
    from app.file_share import ResourceContext, resource_list
    import app.file_share as file_share

    owner, _ = native
    source = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic cancellable source",
        content='{"value": 7}', task_id=None, document_type="dataset")
    value = graph()
    definition = await create(actor_agent_id=owner.id, title="Synthetic cancelled preparation", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={},
        files=[ProcessFileInput(uri=f"document://{source.id}", slot="data")])
    materialize = file_share.materialize_resource

    async def cancel_after_transfer(*args, **kwargs):
        result = await materialize(*args, **kwargs)
        await process_service.cancel_run(launched.run_id)
        return result

    monkeypatch.setattr(file_share, "materialize_resource", cancel_after_transfer)
    await process_service.process_start_jobs(engine_code="galaris")
    run = await db.get(ProcessRun, launched.run_id)
    assert run.status == "cancelled"
    assert not run.engine_metadata.get("native", {}).get("initialized")
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 0
    assert not (await resource_list(ResourceContext(agent_id=owner.id, runtime="internal"),
        f"galaris://processes/runs/{run.id}/attachments/")).entries


@pytest.mark.asyncio
async def test_archiving_removes_native_process_from_agent_discovery_until_reactivated(db, native):
    from app.process.native_definitions import archive
    from app.process.resource_facade import list_process_resources, read_process_resource

    owner, outsider = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic archive lifecycle", graph=graph())

    async def discoverable():
        listed = await process_service.list_for_agent(owner.id)
        resources = await list_process_resources(actor_agent_id=owner.id, query="Synthetic archive")
        return ([item["workflow_id"] for item in listed], [item["workflow_id"] for item in resources])

    assert await discoverable() == ([definition.code], [definition.code])
    assert await read_process_resource(definition.code, actor_agent_id=owner.id) is not None
    await archive(definition.code, owner.id, True)
    assert await discoverable() == ([], [])
    assert await read_process_resource(definition.code, actor_agent_id=owner.id) is None
    with pytest.raises(PermissionError):
        await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})

    await archive(definition.code, owner.id, False)
    assert await discoverable() == ([definition.code], [definition.code])
    assert await read_process_resource(definition.code, actor_agent_id=outsider.id) is None
    assert await process_service.list_for_agent(outsider.id) == []
    assert await list_process_resources(actor_agent_id=outsider.id) == []
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    assert (await db.get(ProcessRun, launched.run_id)).status == "queued"


@pytest.mark.asyncio
async def test_native_admission_recovery_rechecks_human_scope_after_archive(db, native):
    from core.user import UserModel
    from app.agent import AgentManagementScope
    from app.process.native_definitions import archive

    owner, colleague = native
    human = UserModel(email=f"native-recovery-{uuid4().hex}@example.com", hashed_password="synthetic", is_active=True)
    db.add(human)
    await db.flush()
    owner.user_id = human.id
    await db.commit()
    definition = await create(actor_agent_id=owner.id, owner_user_id=human.id,
        title="Synthetic recoverable human process", graph=graph())
    kwargs = dict(agent_id=owner.id, workflow_id=definition.code, input_data={}, requester_user_id=human.id)
    original = await process_service.start_process(**kwargs, idempotency_key="recover-human")
    scope = AgentManagementScope(human.id, frozenset({owner.id}))
    await archive(definition.code, scope, True)
    assert await process_service.delete_definition(definition.id)
    assert definition.archived and definition.deleted_at is None
    recovered = await process_service.start_process(**kwargs, idempotency_key="recover-human", wait_for_completion=True)
    assert recovered.run_id == original.run_id and recovered.deduplicated
    outsider = UserModel(email=f"native-outsider-{uuid4().hex}@example.com", hashed_password="synthetic", is_active=True)
    db.add(outsider)
    await db.commit()
    with pytest.raises(PermissionError, match="management scope"):
        await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
            input_data={}, requester_user_id=outsider.id, idempotency_key="recover-human")
    with pytest.raises(PermissionError, match="archived"):
        await process_service.start_process(**kwargs, idempotency_key="new-human")
    with pytest.raises(PermissionError):
        await process_service.start_process(agent_id=colleague.id, workflow_id=definition.code,
            input_data={}, requester_user_id=human.id)
    human.is_active = False
    await db.commit()
    for key in ("recover-human", "new-human"):
        with pytest.raises(PermissionError, match="active human"):
            await process_service.start_process(**kwargs, idempotency_key=key)
    kwargs["requester_user_id"] = 2_000_000_000
    for key in ("recover-human", "new-human"):
        with pytest.raises(PermissionError, match="active human"):
            await process_service.start_process(**kwargs, idempotency_key=key)
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1


@pytest.mark.asyncio
async def test_managed_human_can_still_launch_an_assigned_external_process(db, native):
    from core.user import UserModel
    from app.tools import ToolModel
    from app.process import FakeProcessEngine
    from app.process.schemas import ProcessDefinitionCreate, ProcessCallbackEvent

    owner, colleague = native
    human = UserModel(email=f"external-launcher-{uuid4().hex}@example.com", hashed_password="synthetic", is_active=True)
    db.add(human)
    await db.flush()
    owner.user_id = human.id
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "fake"))
    if tool is None:
        tool = ToolModel(code="fake", label="Synthetic external engine", connection_schema={})
        db.add(tool)
        await db.flush()
    registry.register(FakeProcessEngine())
    definition = await process_service.create_definition(ProcessDefinitionCreate(agent_id=owner.id, tool_id=tool.id,
        engine_process_id="synthetic-external-" + uuid4().hex, label="Synthetic external process"))
    native_tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
    from app.process.schemas import ProcessDefinitionUpdate
    with pytest.raises(ValueError):
        await process_service.update_definition(definition.id, ProcessDefinitionUpdate(tool_id=native_tool.id))
    saved = await process_service.update_definition(definition.id, ProcessDefinitionUpdate(tool_id=tool.id, label="Synthetic external renamed"))
    assert saved.tool_id == tool.id and saved.document_id is None and saved.label == "Synthetic external renamed"
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.engine_process_id,
        input_data={"synthetic": True}, requester_user_id=human.id)
    run = await db.get(ProcessRun, launched.run_id)
    assert run.engine_code == "fake" and run.requester_user_id == human.id and run.data == {}
    with pytest.raises(PermissionError):
        await process_service.start_process(agent_id=colleague.id, workflow_id=definition.engine_process_id,
            input_data={}, requester_user_id=human.id)
    await process_service.process_start_jobs(engine_code="fake")
    terminal, duplicate = await process_service.receive_callback(run.id, run.callback_token,
        ProcessCallbackEvent(event_id="synthetic-external-success", status="success", output={"synthetic": True}))
    assert not duplicate and terminal.status == "success" and terminal.output == {"synthetic": True}
    repeated, duplicate = await process_service.receive_callback(run.id, run.callback_token,
        ProcessCallbackEvent(event_id="synthetic-external-success", status="success", output={"replacement": True}))
    assert duplicate and repeated.output == {"synthetic": True}


@pytest.mark.asyncio
async def test_task_launched_process_preserves_causality_and_rejects_callbacks_or_legacy_edits(db, native):
    from app.process.schemas import ProcessCallbackEvent, ProcessDefinitionCreate, ProcessDefinitionUpdate
    from app.llm import LLMCall
    from app.process.native_runs import run_metrics
    owner, reader = native
    parent = await create(actor_agent_id=owner.id, title="Synthetic task parent", graph=graph())
    child = await create(actor_agent_id=owner.id, title="Synthetic task child", graph=graph())
    with pytest.raises(ValueError):
        await process_service.create_definition(ProcessDefinitionCreate(agent_id=owner.id, tool_id=parent.tool_id,
            engine_process_id="legacy-native", label="Synthetic bypass"))
    with pytest.raises(ValueError):
        await process_service.update_definition(parent.id, ProcessDefinitionUpdate(label="Synthetic bypass"))
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=parent.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(launched.run_id)
    await process_service.refresh_run(launched.run_id)
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == launched.run_id))
    admitted = await process_service.start_process(agent_id=owner.id, workflow_id=child.code, input_data={}, task_id=attempt.task_id)
    nested = await db.get(ProcessRun, admitted.run_id)
    assert (nested.parent_run_id, nested.root_run_id, nested.caller_node_attempt_id) == (launched.run_id, launched.run_id, attempt.id)
    with pytest.raises(PermissionError, match="fenced engine"):
        await process_service.receive_callback(nested.id, nested.callback_token,
            ProcessCallbackEvent(event_id="synthetic-forged-receipt", status="success", output={}))
    assert nested.status == "queued"
    recovered = await process_service.start_process(agent_id=owner.id, workflow_id=child.code, input_data={},
        task_id=attempt.task_id, idempotency_key=nested.idempotency_key, wait_for_completion=True)
    assert recovered.run_id == nested.id and recovered.deduplicated
    await_task = await task_service.get_by_id(nested.await_task_id)
    assert await_task.data["awaiting_reply"]["deadline"] is None
    await process_service.process_start_jobs(engine_code="galaris")
    await finish_run(db, nested.id)
    await finish_run(db, launched.run_id)
    child_attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == nested.id))
    db.add_all([LLMCall(process_run_id=launched.run_id, task_id=attempt.task_id, status="completed", cost=0.2, inference_cost=0.2, total_tokens=10, cost_estimated=False),
        LLMCall(process_run_id=launched.run_id, task_id=attempt.task_id, status="error", cost=0.1, inference_cost=0.1, total_tokens=5, cost_estimated=False),
        LLMCall(process_run_id=nested.id, task_id=child_attempt.task_id, status="completed", cost=0, inference_cost=0.5, total_tokens=20, cost_estimated=True, is_subscription=True)])
    await db.commit()
    metrics = await run_metrics(launched.run_id, owner.id)
    assert metrics["direct"]["calls"] == 2 and metrics["direct"]["cost"] == pytest.approx(0.3)
    assert metrics["inclusive"]["calls"] == 3 and metrics["inclusive"]["cost"] == pytest.approx(0.3)
    assert metrics["inclusive"]["inference_cost"] == pytest.approx(0.8)
    assert metrics["inclusive"]["tokens"] == 35 and metrics["inclusive"]["estimated_calls"] == 1
    assert metrics["nodes"]["work"]["cost"] == pytest.approx(0.3)
    assert metrics["tasks"][str(attempt.task_id)]["cost"] == pytest.approx(0.3)
    occurrence = metrics["occurrences"][str(attempt.node_run_id)]
    assert occurrence["direct"]["calls"] == 2 and occurrence["inclusive"]["calls"] == 3
    assert occurrence["inclusive"]["inference_cost"] == pytest.approx(0.8)
    assert not metrics["partial"]
    root = await db.get(ProcessRun, launched.run_id)
    with pytest.raises(PermissionError):
        await run_metrics(launched.run_id, reader.id)
    # Sharing the parent does not expose a private child process.
    await set_grant((await db.get(ProcessDefinition, root.process_id)).share_id, "agent", reader.id, False)
    await db.commit()
    restricted = await run_metrics(launched.run_id, reader.id)
    assert restricted["partial"] and restricted["inclusive"]["cost"] == pytest.approx(0.3)
    assert restricted["inclusive"]["inference_cost"] == pytest.approx(0.3)
    from app.process.native_runs import children, inspect_occurrence, inspect_run
    assert (await children(launched.run_id, reader.id))["total"] == 0
    assert all(entry["child_run_id"] is None for entry in
        (await inspect_occurrence(launched.run_id, attempt.node_run_id, reader.id))["attempts"])
    assert (await run_metrics(launched.run_id, reader.id))["partial"]
    await set_grant((await db.get(ProcessDefinition, nested.process_id)).share_id, "agent", reader.id, False)
    await db.commit()
    shared = await run_metrics(launched.run_id, reader.id)
    assert not shared["partial"] and shared["inclusive"]["cost"] == pytest.approx(0.3)
    assert shared["inclusive"]["inference_cost"] == pytest.approx(0.8)
    assert (await children(launched.run_id, reader.id))["total"] == 1
    # Seeing a child does not reveal its unrelated parent.
    await set_grant((await db.get(ProcessDefinition, root.process_id)).share_id, "agent", reader.id, None)
    await db.commit()
    assert (await inspect_run(nested.id, reader.id))["parent_run_id"] is None
    for run_id in (nested.id, launched.run_id):
        with pytest.raises(ValueError, match="ancestry"):
            await process_service.delete_run(run_id)
    # Historical rows may precede the native archive contract. A hidden
    # definition must never turn recovery into a new effect.
    from datetime import datetime, timezone
    parent_run = await db.get(ProcessRun, launched.run_id)
    original_key = parent_run.idempotency_key
    parent.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    db.expunge(parent)
    with pytest.raises(LookupError, match="definition not found"):
        await process_service.start_process(agent_id=owner.id, workflow_id=parent_run.launch_snapshot["workflow_id"],
            input_data={}, idempotency_key=original_key)
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("function_state", ["enabled", "disabled", "denied_resource", "ask_allow", "ask_deny"])
@pytest.mark.parametrize("typed", [False, True])
async def test_tool_activity_uses_live_mcp_rights_and_finishes_its_context(inference_db, committed_native, function_state, typed):
    from app.connection import Connection
    from app.connection.facade import set_connection_function_state
    from app.tools import ToolModel
    db = inference_db
    owner, other = committed_native
    approver = None
    if function_state.startswith("ask"):
        from core.user import UserModel
        approver = UserModel(email=f"process-approver-{uuid4().hex}@example.test", hashed_password="synthetic")
        db.add(approver)
        await db.flush()
        owner.user_id = approver.id
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    state = "ask" if approver else "enabled" if function_state == "denied_resource" else function_state
    await set_connection_function_state(connection.id, "process_definition_read", state)
    target = await create(actor_agent_id=other.id if function_state == "denied_resource" else owner.id,
        title="Synthetic audited process", graph=graph())
    value = Workflow(nodes=[Node(id="start", kind="start"), Node(id="audit", kind="tool_call",
        config={"tool": "process_definition_read", "input": {"process_code": target.code}}),
        Node(id="end", kind="end", config={"output": {"code": {"$expr": "results.audit.code"}}})],
        flows=[Flow(id="a", source="start", target="audit"), Flow(id="b", source="audit", target="end")])
    if typed:
        from app.process.values import Variable
        value.schema_version = "galaris.bpmn/v2"
        value.inputs = []
        value.outputs = [Variable(name="code", type="string", nullable=False)]
        value.nodes[1].inputs = [Variable(name="process_code", type="string", nullable=False,
            default={"type": "string", "value": target.code})]
        value.nodes[1].outputs = value.outputs
        value.nodes[1].config = {"tool": "process_definition_read"}
    definition = await create(actor_agent_id=owner.id, title="Synthetic declared Tool workflow", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    if approver:
        from app.tools.authorization_models import ActionAuthorization
        from app.tools.facade import answer_action
        for _ in range(5):
            await tick_run(db, launched.run_id)
        attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == launched.run_id))
        assert attempt.status == "authorization", (attempt.error, attempt.receipt)
        from app.process.native_runs import inspect_occurrence
        inspected = await inspect_occurrence(launched.run_id, attempt.node_run_id, owner.id)
        assert inspected["attempts"][0]["receipt"]["authorization"]["request_id"] == attempt.receipt["authorization"]["request_id"]
        assert "continuation" not in inspected["attempts"][0]["receipt"]["authorization"]
        assert attempt.receipt["authorization"]["continuation"]
        task = await task_service.get_by_id(attempt.task_id)
        assert task.paused and task.lease_token is None
        from app.task import scheduler
        # Resuming the public Task must not route a non-agent Tool context to an LLM.
        task_service.clear_pauses(task)
        await task_service.save(task)
        assert await scheduler._claim_specific(task.id, priority=0) is None
        task_service.suspend(task, task_service.PAUSE_USER)
        await task_service.save(task)
        authorization = await db.get(ActionAuthorization, UUID(attempt.receipt["authorization"]["request_id"]))
        assert authorization.status == "pending"
        assert await answer_action(authorization.id, user_id=approver.id, approved=function_state == "ask_allow")
        await tick_run(db, launched.run_id)
        await db.refresh(attempt)
        assert attempt.status == "authorization"
        task_service.clear_pauses(task)
        await task_service.save(task)
    run = await finish_run(db, launched.run_id)
    assert run.status == ("success" if function_state in {"enabled", "ask_allow"} else "error")
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id))
    if function_state in {"enabled", "ask_allow"}:
        if typed:
            assert run.output == {"code": {"type": "string", "value": target.code}}
            assert attempt.receipt == run.output
        else:
            assert run.output == {} and attempt.receipt["code"] == target.code
    task = await task_service.get_by_id(attempt.task_id)
    assert not task.ai and task.status in {TaskStatus.SUCCESS, TaskStatus.ERROR}
    assert task.lease_token is None and not task.paused


@pytest.mark.asyncio
async def test_ambiguous_tool_effect_blocks_retries_handlers_and_new_admissions(inference_db, committed_native, monkeypatch):
    import asyncio
    from dataclasses import replace
    from unittest.mock import AsyncMock
    from app.browser import mcp as browser_mcp
    from app.connection import Connection, facade as connections
    from app.tools import ToolModel, mcp_loader
    from app.process.native_runs import control_run
    db = inference_db
    owner, _ = committed_native
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "browser"))
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    await connections.set_connection_function_state(connection.id, "browser_open", "enabled")
    definitions = tuple(replace(item, timeout_seconds=2) if item.name == "browser_open" else item
        for item in mcp_loader.load_mcp_tools())
    monkeypatch.setattr(mcp_loader, "load_mcp_tools", lambda: definitions)
    entered = asyncio.Event()
    async def interrupted_external_operation(**_kwargs):
        entered.set()
        await asyncio.Future()
    dispatch = AsyncMock(side_effect=interrupted_external_operation)
    monkeypatch.setattr(browser_mcp.browser_executor, "open", dispatch)
    value = Workflow(error_handler="handler", nodes=[Node(id="start", kind="start"),
        Node(id="browse", kind="tool_call", config={"tool": "browser_open", "input": {
            "url": "https://example.test/invented", "output": "content"}, "retry": {"attempts": 3}, "catch": "handler"}),
        Node(id="end", kind="end"), Node(id="handler", kind="end", config={"output": {"unsafe": True}})],
        flows=[Flow(id="a", source="start", target="browse"), Flow(id="b", source="browse", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic uncertain external effect", graph=value)
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(5):
        run = await tick_run(db, response.run_id)
    assert entered.is_set() and dispatch.await_count == 1
    assert run.status == "cancelling" and run.engine_metadata["native"]["paused"]
    assert run.error_code == "effect_outcome_unknown"
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id, ProcessNodeRun.node_key == "handler")) == 0
    with pytest.raises(ValueError, match="reconciliation"):
        await control_run(run.id, owner.id, "resume")
    await db.commit()
    await process_service.cancel_run(run.id)
    stopped = await process_service.refresh_run(run.id)
    assert stopped.status == "cancelling"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["for", "while"])
async def test_loops_are_durable_sequential_and_preserve_each_result(db, native, kind):
    owner, _ = native
    body = Workflow(nodes=[Node(id="body_start", kind="start"), Node(id="increment", kind="task", config={
        "prompt": "Synthetic iteration"}), Node(id="body_end", kind="end")],
        flows=[Flow(id="body_a", source="body_start", target="increment"), Flow(id="body_b", source="increment", target="body_end")])
    config = {"items": "input.values"} if kind == "for" else {"condition": "index == null or index < 2"}
    definition_graph = Workflow(nodes=[Node(id="start", kind="start"), Node(id="loop", kind=kind, body=body, config=config),
        Node(id="end", kind="end", config={"output": {"$expr": "results.loop"}})],
        flows=[Flow(id="f1", source="start", target="loop"), Flow(id="f2", source="loop", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic loop", graph=definition_graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"values": [1, 2]})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, workspace_update=lambda attempt, data: {**data, "count": data.get("count", 0) + 1})
    assert run.status == "success" and run.output == {"values": [1, 2], "count": 2}, run.error_message
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [[], ["first", "second"]])
async def test_nested_for_while_keeps_occurrences_separate_after_restart(db, native, values):
    owner, _ = native
    inner = Workflow(nodes=[Node(id="inner_start", kind="start"),
        Node(id="inner_work", kind="task", config={"prompt": "Invent an iteration"}),
        Node(id="inner_end", kind="end")],
        flows=[Flow(id="inner_a", source="inner_start", target="inner_work"),
            Flow(id="inner_b", source="inner_work", target="inner_end")])
    outer = Workflow(nodes=[Node(id="outer_start", kind="start"),
        Node(id="inner_loop", kind="while", body=inner, config={"condition": "index < 2"}),
        Node(id="outer_end", kind="end", config={"output": {"$expr": "results.inner_loop"}})],
        flows=[Flow(id="outer_a", source="outer_start", target="inner_loop"),
            Flow(id="outer_b", source="inner_loop", target="outer_end")])
    definition_graph = Workflow(nodes=[Node(id="start", kind="start"),
        Node(id="outer_loop", kind="for", body=outer, config={"items": "input.values"}),
        Node(id="end", kind="end", config={"output": {"$expr": "results.outer_loop"}})],
        flows=[Flow(id="a", source="start", target="outer_loop"), Flow(id="b", source="outer_loop", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic nested iterations", graph=definition_graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"values": values})
    await process_service.process_start_jobs(engine_code="galaris")
    await tick_run(db, launched.run_id)
    registry.register(NativeProcessEngine())
    db.expire_all()
    run = await finish_run(db, launched.run_id, workspace_update=lambda attempt, data: {**data, "count": data.get("count", 0) + 1})
    assert run.status == "success", run.error_message
    assert run.output == ({"values": values, "count": 2 * len(values)} if values else {"values": []})
    occurrences = list(await db.scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id, ProcessNodeRun.node_key == "inner_work")))
    assert len(occurrences) == 2 * len(values)
    assert all(node.status == "success" and node.context["body_path"] == ["outer_loop", "inner_loop"] for node in occurrences)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_scope", ["activity", "graph"])
@pytest.mark.parametrize("in_loop", [False, True])
async def test_first_failure_stops_run_without_legacy_retry_or_recovery(db, native, handler_scope, in_loop):
    owner, _ = native
    definition_graph = graph()
    definition_graph.nodes[1].config.update(retry={"attempts": 3})
    raw = definition_graph.model_dump()
    if handler_scope == "activity":
        raw["nodes"][1]["config"]["catch"] = "handler"
    else:
        raw["error_handler"] = "handler"
    raw["nodes"].append({"id": "handler", "kind": "task", "config": {"prompt": "Forbidden recovery"}})
    raw["flows"].append({"id": "handled", "source": "handler", "target": "end"})
    definition_graph = Workflow.model_validate(raw)
    assert {node.id for node in definition_graph.nodes} == {"start", "work", "end"}
    if in_loop:
        definition_graph = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="loop", kind="for", body=definition_graph, config={"items": "data.items"}), Node(id="finish", kind="end")],
            flows=[Flow(id="a", source="begin", target="loop"), Flow(id="b", source="loop", target="finish")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic stop on error", graph=definition_graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"items": [1, 2]})
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id, fail_first=True)
    assert run.status == "error" and run.error_code == "node_failed"
    from app.process.native_runs import inspect_run
    inspected = await inspect_run(run.id, owner.id)
    assert inspected["error_code"] == "node_failed" and inspected["error"] == "Synthetic failure"
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id, ProcessNodeRun.node_key == "handler")) == 0
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 1
    assert (await read_run_data(run.id, owner.id))["data"] == {"items": [1, 2]}
    assert (await process_service.refresh_run(run.id)).status == "error"


@pytest.mark.asyncio
async def test_failure_cancels_other_parallel_tasks_and_never_admits_successors(db, native):
    owner, _ = native
    value = Workflow(nodes=[Node(id="start", kind="start"), Node(id="split", kind="parallel"),
        Node(id="fails", kind="task", config={"prompt": "Synthetic failed work"}),
        Node(id="active", kind="task", config={"prompt": "Synthetic active work"}),
        Node(id="forbidden", kind="task", config={"prompt": "Must never execute"}),
        Node(id="join", kind="parallel"), Node(id="end", kind="end")],
        flows=[Flow(id=f"f{i}", source=a, target=b) for i, (a, b) in enumerate([
            ("start", "split"), ("split", "fails"), ("split", "active"), ("fails", "forbidden"),
            ("forbidden", "join"), ("active", "join"), ("join", "end")])])
    definition = await create(actor_agent_id=owner.id, title="Synthetic parallel stop", graph=value)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={"kept": True})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4):
        await process_service.refresh_run(launched.run_id)
    bindings = dict((await db.execute(select(ProcessNodeRun.node_key, ProcessNodeAttempt.task_id)
        .join(ProcessNodeAttempt).where(ProcessNodeRun.run_id == launched.run_id))).all())
    assert set(bindings) == {"fails", "active"}
    failed = await task_service.get_by_id(bindings["fails"])
    transition(failed, TaskEvent.START_EXECUTION)
    failed.execution_result = {"success": False, "result": "", "error": "Synthetic parallel failure"}
    failed.last_error = "Synthetic parallel failure"
    transition(failed, TaskEvent.EXECUTION_FAILED)
    await task_service.update(failed.id, failed)
    for _ in range(4):
        run = await process_service.refresh_run(launched.run_id)
    assert run.status == "error" and run.error_code == "node_failed"
    assert (await task_service.get_by_id(bindings["active"])).status == TaskStatus.ERROR
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(
        ProcessNodeRun.run_id == run.id, ProcessNodeRun.node_key == "forbidden")) == 0
    assert (await read_run_data(run.id, owner.id))["data"] == {"kept": True}


@pytest.mark.asyncio
async def test_native_start_timeout_stops_without_an_automatic_retry(db, native, monkeypatch):
    import asyncio
    import app.file_share as file_share
    from app.process import ProcessFileInput
    from app.process.models import ProcessStartJob
    from app.memory import document_service
    owner, _ = native
    source = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic timeout file", content='{}', task_id=None, document_type="dataset")
    definition = await create(actor_agent_id=owner.id, title="Synthetic timed-out launch", graph=graph())
    async def stalled_transfer(*args, **kwargs):
        await asyncio.Future()
    monkeypatch.setattr(file_share, "materialize_resource", stalled_transfer)
    monkeypatch.setattr(NativeProcessEngine, "start_timeout_seconds", 0.05)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={},
        files=[ProcessFileInput(uri=f"document://{source.id}")])
    await process_service.process_start_jobs(engine_code="galaris")
    run = await db.get(ProcessRun, launched.run_id)
    assert run.status == "error" and run.error_code == "engine_timeout"
    job = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == run.id))
    assert job.status == "failed" and job.attempts == 1
    assert await process_service.process_start_jobs(engine_code="galaris") == 0
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("in_child", [False, True])
@pytest.mark.parametrize("coded", [False, True])
async def test_executor_exception_stops_run_and_preserves_child_error_code(db, native, monkeypatch, in_child, coded):
    from app.process import program_contracts
    from app.process.engine import ProcessEngineError
    owner, _ = native
    class BrokenExecutor:
        async def execute(self, **kwargs):
            if coded:
                raise ProcessEngineError("synthetic_execution_failure", "Invented executor failed")
            raise RuntimeError("Invented executor failed")
    monkeypatch.setattr(program_contracts, "program_executor", lambda: BrokenExecutor())
    value = graph()
    value.nodes[1].kind = "program"
    value.nodes[1].config = {"program_uri": "document://00000000-0000-0000-0000-000000000001"}
    definition = await create(actor_agent_id=owner.id, title="Synthetic throwing executor", graph=value)
    if in_child:
        parent = graph()
        parent.nodes[1].kind = "call"
        parent.nodes[1].config = {"process_code": definition.code}
        definition = await create(actor_agent_id=owner.id, title="Synthetic failed child", graph=parent)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    for _ in range(15):
        await process_service.process_start_jobs(engine_code="galaris")
        for run in list(await db.scalars(select(ProcessRun))):
            if run.status not in process_service.TERMINAL_STATUSES:
                await process_service.refresh_run(run.id)
    root = await db.get(ProcessRun, launched.run_id)
    assert root.status == "error"
    assert root.error_code == ("synthetic_execution_failure" if coded else "node_failed")
    from app.process.native_runs import inspect_run
    assert (await inspect_run(root.id, owner.id))["error_code"] == root.error_code


@pytest.mark.asyncio
async def test_pause_step_breakpoint_resume_and_child_current_definition(db, native):
    from app.process.native_runs import control_run
    owner, _ = native
    child_graph = Workflow(nodes=[Node(id="start", kind="start"), Node(id="end", kind="end", config={"output": {"current": 1}})],
        flows=[Flow(id="f1", source="start", target="end")])
    child = await create(actor_agent_id=owner.id, title="Synthetic child", graph=child_graph)
    parent_graph = Workflow(nodes=[Node(id="start", kind="start"), Node(id="child", kind="call", config={"process_code": child.code}),
        Node(id="end", kind="end", config={"output": {"$expr": "results.child"}})],
        flows=[Flow(id="f1", source="start", target="child"), Flow(id="f2", source="child", target="end")])
    parent = await create(actor_agent_id=owner.id, title="Synthetic parent", graph=parent_graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=parent.code, input_data={})
    pause_key = uuid4()
    receipt = await control_run(launched.run_id, owner.id, "pause", command_key=pause_key, expected_revision=0)
    assert await control_run(launched.run_id, owner.id, "pause", command_key=pause_key, expected_revision=0) == receipt
    from app.memory import MemoryConflictError
    with pytest.raises(MemoryConflictError):
        await control_run(launched.run_id, owner.id, "resume", command_key=uuid4(), expected_revision=0)
    with pytest.raises(ValueError):
        await control_run(launched.run_id, owner.id, "resume", command_key=pause_key)
    from app.process.models import ProcessRunEvent
    assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(
        ProcessRunEvent.run_id == launched.run_id, ProcessRunEvent.event_id == f"debugger:{pause_key}")) == 1
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(launched.run_id)
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == launched.run_id)) == 0
    await control_run(launched.run_id, owner.id, "step")
    await process_service.refresh_run(launched.run_id)
    child_graph.nodes[1].title = "Current child definition"
    await update(child.code, owner.id, expected_revision=1, graph=child_graph)
    await control_run(launched.run_id, owner.id, "breakpoints", ["child"])
    await control_run(launched.run_id, owner.id, "resume")
    await process_service.refresh_run(launched.run_id)
    paused = await db.get(ProcessRun, launched.run_id)
    assert paused.engine_metadata["native"]["paused"]
    await control_run(launched.run_id, owner.id, "resume")
    await process_service.refresh_run(launched.run_id)
    nested = await db.scalar(select(ProcessRun).where(ProcessRun.parent_run_id == launched.run_id))
    assert nested.launch_snapshot["definition"]["revision"] == 2
    await process_service.process_start_jobs(engine_code="galaris")
    await finish_run(db, nested.id)
    run = await finish_run(db, launched.run_id)
    assert run.output == {}
    assert nested.launch_snapshot["definition"]["graph"]["nodes"][1]["title"] == "Current child definition"


@pytest.mark.asyncio
async def test_human_ownership_readonly_sharing_run_dataset_and_orphans(db, native, monkeypatch):
    from datetime import datetime, timezone
    from app.agent import AgentManagementScope
    from app.memory import update_workflow_sharing
    from app.process.native_sharing import read as process_sharing, preview as process_sharing_preview, update as update_process_sharing
    from app.process.native_access import accessible_clause
    from app.memory.schemas import DocumentSharingLevelUpdate
    from app.memory import service as document_service
    from core.user import UserModel
    from core.authorize import Role, Assignment, RolePrivilege, Privilege
    from app.process.native_runs import inspect_run, list_runs
    owner, agent_reader = native
    human = UserModel(email=f"workflow-{uuid4()}@example.invalid", hashed_password="synthetic", is_active=True)
    viewer = UserModel(email=f"workflow-{uuid4()}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add_all([human, viewer])
    await db.flush()
    owner.user_id = human.id
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    viewer_scope = AgentManagementScope(user_id=viewer.id, agent_ids=frozenset())
    process_count = await db.scalar(select(func.count()).select_from(ProcessDefinition))
    preview = await process_sharing_preview(scope, owner_agent_id=None)
    assert preview.owner.kind == "user" and preview.owner.id == human.id
    agent_preview = await process_sharing_preview(scope, owner_agent_id=owner.id)
    assert agent_preview.owner.kind == "agent" and agent_preview.owner.id == owner.id
    assert await db.scalar(select(func.count()).select_from(ProcessDefinition)) == process_count
    with pytest.raises(PermissionError):
        await process_sharing_preview(viewer_scope, owner_agent_id=owner.id)
    definition = await create(actor_agent_id=owner.id, owner_user_id=human.id, title="Synthetic human-owned workflow", graph=graph())
    assert (await process_sharing(definition.code, scope)).options == preview.options
    assert (await read(definition.code, scope))["can_write"]
    item = definition
    await update_process_sharing(definition.code, scope, DocumentSharingLevelUpdate(level="private", expected_lock_version=item.lock_version,
        grants=[{"kind": "user", "id": viewer.id, "can_write": False}]))
    assert not (await read(definition.code, viewer_scope))["can_write"]
    with pytest.raises(PermissionError):
        await update(definition.code, viewer_scope, expected_revision=1, graph=graph("Unauthorized"))
    await update_process_sharing(definition.code, scope, DocumentSharingLevelUpdate(level="private", expected_lock_version=item.lock_version,
        grants=[{"kind": "user", "id": viewer.id, "can_write": True}]))
    assert (await read(definition.code, viewer_scope))["can_write"]
    shared_update = await update(definition.code, viewer_scope, expected_revision=1, graph=graph("Synthetic shared edit"))
    assert shared_update["graph"]["nodes"][1]["config"]["prompt"] == "Synthetic shared edit"
    response = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={}, requester_user_id=human.id)
    await process_service.process_start_jobs(engine_code="galaris")
    run = await db.get(ProcessRun, response.run_id)
    assert (await inspect_run(run.id, viewer_scope))["can_control"]
    await write_run_data(run.id, viewer_scope, {"approved": True}, expected_revision=run.data_revision)
    await update_process_sharing(definition.code, scope, DocumentSharingLevelUpdate(level="private",
        expected_lock_version=definition.lock_version, grants=[{"kind": "user", "id": viewer.id, "can_write": False}]))
    assert (await inspect_run(run.id, viewer_scope))["can_control"] is False
    from app.process import router
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=viewer_scope))
    assert (await router._run_or_404(run.id)).id == run.id
    for operation in (router.cancel_run, router.retry_run, router.delete_run, router.refresh_run):
        with pytest.raises(HTTPException) as denied:
            await operation(run.id)
        assert denied.value.status_code == 404
    observer = UserModel(email=f"workflow-{uuid4()}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add(observer)
    await db.flush()
    observer_scope = AgentManagementScope(user_id=observer.id, agent_ids=frozenset({owner.id}))
    with pytest.raises(PermissionError):
        await inspect_run(run.id, observer_scope)
    assert (await list_runs(observer_scope))["total"] == 0
    assert (await process_service.paginate_runs(agent_ids=observer_scope.agent_ids, native_actor=observer_scope))[1] == 0
    human.is_active = False
    await db.commit()
    for actor in (agent_reader.id, viewer_scope):
        with pytest.raises((PermissionError, LookupError)):
            await read(definition.code, actor)
    assert definition.id not in list(await db.scalars(select(ProcessDefinition.id).where(accessible_clause(viewer_scope))))
    assert (await list_runs(viewer_scope))["total"] == 0
    assert (await process_service.paginate_runs(native_actor=viewer_scope))[1] == 0
    admin_role = Role(code="workflow-admin-" + uuid4().hex)
    db.add(admin_role)
    await db.flush()
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "PROCESS_ADMIN"))
    db.add_all([RolePrivilege(role_id=admin_role.id, privilege_id=privilege.id), Assignment(user_id=viewer.id, role_id=admin_role.id)])
    await db.commit()
    assert (await read(definition.code, viewer_scope))["can_write"]
    assert definition.document_id is None


@pytest.mark.asyncio
async def test_lab_real_campaign_idempotency_exact_evidence_and_private_inputs(db, native):
    from app.lab import process_evaluation as lab
    from app.connection import Connection
    from app.tools import ToolModel
    from app.lab.process_evaluation_models import LabProcessCase
    from uuid import UUID
    owner, stranger = native
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    from app.connection.facade import set_connection_function_state
    await set_connection_function_state(connection.id, "process_start", "enabled")
    await db.commit()
    definition = await create(actor_agent_id=owner.id, title="Synthetic benchmark workflow", graph=Workflow(
        nodes=[Node(id="start", kind="start"), Node(id="end", kind="end", config={"output": {"$expr": "input"}})],
        flows=[Flow(id="f1", source="start", target="end")]))
    dataset = await lab.create_synthetic_dataset(owner.id, agent_id=owner.id, title="Invented cases",
        cases=[lab.ProcessCaseInput(input={"value": 7}, expected={"value": 7})], invocation_key="synthetic-inputs")
    campaign = await lab.start_campaign(owner.id, agent_id=owner.id, code=definition.code,
        dataset_document_id=UUID(dataset["document_id"]), title="Real synthetic benchmark", invocation_key="one-campaign")
    assert (await lab.start_campaign(owner.id, agent_id=owner.id, code=definition.code,
        dataset_document_id=UUID(dataset["document_id"]), title="Real synthetic benchmark", invocation_key="one-campaign")).id == campaign.id
    with pytest.raises(PermissionError):
        await lab.inspect_campaign(campaign.id, stranger.id)
    await lab.tick()
    case = await db.scalar(select(LabProcessCase).where(LabProcessCase.campaign_id == campaign.id))
    run_id = case.run_id
    await lab.tick()  # a replay must not launch another run
    assert case.run_id == run_id
    await process_service.process_start_jobs(engine_code="galaris")
    await finish_run(db, run_id)
    await lab.tick()
    evidence = await lab.inspect_campaign(campaign.id, owner.id)
    assert evidence["status"] == "completed"
    assert evidence["items"][0]["evidence"]["exact_check"] is True
    assert evidence["items"][0]["evidence"]["metrics"]["direct"]["cost"] is None


@pytest.mark.asyncio
async def test_lab_rechecks_launch_rights_and_can_cancel_admitted_runs_after_campaign_failure(db, native):
    from app.lab import process_evaluation as lab
    from app.lab.process_evaluation_models import LabProcessCase
    from app.connection import Connection
    from app.connection.facade import set_connection_function_state
    from app.tools import ToolModel
    from app.process.facade import launch_current
    from uuid import UUID
    owner, _ = native
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    await set_connection_function_state(connection.id, "process_start", "enabled")
    definition = await create(actor_agent_id=owner.id, title="Synthetic revocation workflow", graph=graph())
    dataset = await lab.create_synthetic_dataset(owner.id, agent_id=owner.id, title="Invented revocation cases",
        cases=[lab.ProcessCaseInput(input={"value": 1}), lab.ProcessCaseInput(input={"value": 2})], invocation_key="revocation-inputs")
    campaign = await lab.start_campaign(owner.id, agent_id=owner.id, code=definition.code,
        dataset_document_id=UUID(dataset["document_id"]), title="Synthetic interrupted benchmark", invocation_key="revocation-campaign")
    cases = list(await db.scalars(select(LabProcessCase).where(LabProcessCase.campaign_id == campaign.id).order_by(LabProcessCase.position)))
    # One real admission predates the revocation; the next case is still queued.
    cases[0].run_id = await launch_current(definition.code, owner.id, agent_id=owner.id,
        input_data=cases[0].input, invocation_key=f"lab-process-case:{cases[0].id}")
    cases[0].status = "running"
    await db.commit()
    await process_service.process_start_jobs(engine_code="galaris")
    await process_service.refresh_run(cases[0].run_id)
    await process_service.refresh_run(cases[0].run_id)
    await set_connection_function_state(connection.id, "process_start", "disabled")
    await db.commit()
    owner_id, campaign_id = owner.id, campaign.id
    await lab.tick()
    failed = await lab.inspect_campaign(campaign_id, owner_id)
    assert failed["status"] == "failed"
    assert failed["items"][0]["status"] == "running"
    assert failed["items"][1]["run_id"] is None
    await lab.cancel_campaign(campaign_id, owner_id)
    await lab.tick()
    await process_service.refresh_run(UUID(failed["items"][0]["run_id"]))
    await lab.tick()
    cancelled = await lab.inspect_campaign(campaign_id, owner_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["items"][0]["status"] == "cancelled"
