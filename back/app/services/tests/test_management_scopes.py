"""Synthetic persistence journeys for connection-local administration scopes."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.agent.models import Agent, AgentTeam, Title
from app.connection import connection_service as connections
from app.connection.models import Connection, ConnectionFunctionState, ConnectionParam, ServiceFunctionState
from app.goal import mcp as goals, resource_facade as goal_resources
from app.goal.models import GoalStatus
from app.goal.tests.factories import make_goal
from app.llm import mcp as llm
from app.llm.models import LLMCall
from app.process import mcp as processes
from app.process.models import ProcessDefinition, ProcessRun
from app.task.access import agent_task_filter, require_agent_task_access
from app.task.models import Task, TaskStatus
from app.services import admin_service
from app.services.admin_contracts import AdministrationContext, AdministrationError
from app.services.contracts import MANAGEMENT_SCOPE_OPTIONS, default_management_scope
from app.services.facade import administration_scope
from app.services.mandatory_services import sync_integrated_service_connections, sync_mandatory_services
from app.services.mcp_loader import McpToolContext, list_enabled_native_mcp_definitions
from app.services.models import Service
from core.team import TeamModel


@pytest_asyncio.fixture
async def scope_agents(db):
    title = Title(label="Synthetic scope operator", gender="M")
    team = TeamModel(name="Synthetic scope team")
    db.add_all([title, team])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"scope-{uuid4().hex}", first_name=name,
                    last_name="Synthetic", agent_driver="internal") for name in ("Caller", "Peer", "Outsider")]
    db.add_all(agents)
    await db.flush()
    db.add_all([AgentTeam(agent_id=agent.id, team_id=team.id) for agent in agents[:2]])
    await db.commit()
    return agents, team


async def delegate(db, agent, code, level):
    tool = await db.scalar(select(Service).where(Service.code == code))
    connection = await connections.get_or_create_connection(tool.id, agent.id, active=True)
    if not connection.active:
        await connections.set_connection_active(connection.id, True)
    await connections.set_management_scope(connection.id, level, authorized=True)
    return connection


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "legacy_code", "label", "blocked", "asked"), [
    ("process", "process_admin", "Processes", "process_start", "process_get_run"),
    ("goal", "goal_management", "Goals", "goal_run_now", "goal_ask_referrer"),
    ("agent", "agent_admin", "Agent", "agent_list", "agent_get"),
    ("service", "service_admin", "Services", "services_list", "services_list"),
])
async def test_service_upgrade_preserves_connection_identity_and_moves_function_policies(
    db, scope_agents, code, legacy_code, label, blocked, asked,
):
    (caller, peer, outsider), _ = scope_agents
    service = await db.scalar(select(Service).where(Service.code == code))
    original_service_id = service.id
    galaris = await db.scalar(select(Service).where(Service.code == "galaris"))
    service.code = legacy_code
    service.label = "Synthetic legacy service"
    service.global_params = {"synthetic": {"value": "kept", "forced": False}}
    personal = await connections.get_or_create_connection(service.id, caller.id, active=False)
    delegated = await delegate(db, peer, legacy_code, "team")
    dormant = await delegate(db, outsider, legacy_code, "all")
    await connections.set_connection_active(dormant.id, False)
    old_connection = await connections.get_or_create_connection(galaris.id, caller.id, active=True)
    db.add_all([
        ConnectionParam(connection_id=personal.id, param_name="synthetic", param_value="local"),
        ServiceFunctionState(service_id=galaris.id, function_name=blocked, state="disabled", enabled=False),
        ConnectionFunctionState(connection_id=old_connection.id, function_name=asked, state="ask", enabled=False),
    ])
    await db.flush()

    await sync_mandatory_services()
    await db.refresh(service)
    assert (service.id, service.code, service.label) == (original_service_id, code, label)
    assert service.global_params["synthetic"]["value"] == "kept"
    await db.refresh(personal)
    assert personal.active
    assert await db.scalar(select(ConnectionParam.param_value).where(ConnectionParam.connection_id == personal.id,
        ConnectionParam.param_name == "synthetic")) == "local"
    assert (await administration_scope(caller.id, code)).level == ("usage" if code in {"agent", "service"} else "personal")
    assert (await administration_scope(peer.id, code)).agent_ids == ({caller.id} if code == "agent" else {caller.id, peer.id})
    assert (await administration_scope(outsider.id, code)).agent_ids == frozenset()
    assert await db.scalar(select(Connection.id).where(Connection.service_id == service.id,
        Connection.agent_id == peer.id)) == delegated.id
    assert (await connections.resolve_function(delegated, blocked))["effective_state"] == "disabled"
    assert (await connections.resolve_function(personal, asked))["effective_state"] == "ask"

    await connections.set_connection_active(personal.id, False)
    await connections.set_service_function_state(service.id, blocked, "default")
    await sync_mandatory_services()
    await db.refresh(personal)
    assert not personal.active
    policy = await connections.resolve_function(delegated, blocked)
    assert policy["effective_state"] == policy["default_state"]


@pytest.mark.asyncio
async def test_service_policy_conflict_keeps_both_settings(db, scope_agents):
    from app.services.dbadmin import move_galaris_function_policies

    origin = await db.scalar(select(Service.id).where(Service.code == "galaris"))
    destination = await db.scalar(select(Service.id).where(Service.code == "service"))
    db.add_all([
        ServiceFunctionState(service_id=origin, function_name="services_list", state="disabled", enabled=False),
        ServiceFunctionState(service_id=destination, function_name="services_list", state="enabled", enabled=True),
    ])
    await db.flush()
    with pytest.raises(ValueError, match="Conflicting service_id function policies"):
        async with db.begin_nested():
            await move_galaris_function_policies(db)
    states = await db.execute(select(ServiceFunctionState.service_id, ServiceFunctionState.state).where(
        ServiceFunctionState.function_name == "services_list", ServiceFunctionState.service_id.in_((origin, destination)),
    ))
    assert dict(states.all()) == {origin: "disabled", destination: "enabled"}


@pytest.mark.asyncio
async def test_default_agent_and_service_connections_expose_discovery_only(db, scope_agents):
    (caller, _, _), _ = scope_agents
    await sync_integrated_service_connections(caller.id)
    definitions = await list_enabled_native_mcp_definitions(caller.id, runtime="internal")
    assert {item.name for item in definitions if item.service_code in {"agent", "service"}} == {
        "agent_list", "agent_get", "team_list", "team_members", "services_list",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("existing", "active", "conflict"), [
    (None, True, False), ("team", True, False), ("all", True, True), (None, False, True),
])
async def test_galaris_scope_migrates_to_services_without_overwriting_delegations(db, scope_agents, existing, active, conflict):
    from app.services.builtin_merge import merge_builtin_services
    from app.services.facade import service_administration_scope
    from app.services.permission_catalog import agent_permission_catalog

    (caller, peer, _), _ = scope_agents
    await sync_integrated_service_connections(caller.id)
    records = dict((await db.execute(select(Service.code, Connection).join(Connection).where(
        Connection.agent_id == caller.id, Service.code.in_(("galaris", "service")),
    ))).all())
    origin, target = records["galaris"], records["service"]
    name = "services.management_scope"
    target.active = active
    db.add(ConnectionParam(connection_id=origin.id, param_name=name, param_value="team"))
    if existing is not None:
        db.add(ConnectionParam(connection_id=target.id, param_name=name, param_value=existing))
    await db.flush()
    if conflict:
        with pytest.raises(ValueError, match="Conflicting Galaris and Services"):
            async with db.begin_nested():
                await merge_builtin_services(db)
        assert (await connections.get_params_for_api(origin.id))[1][name] == "team"
        assert (await connections.get_params_for_api(target.id))[1].get(name) == existing
        return
    for _ in range(2):
        await merge_builtin_services(db)
    assert (await service_administration_scope(caller.id)).agent_ids == {caller.id, peer.id}
    assert name not in (await connections.get_params_for_api(origin.id))[1]
    assert (await connections.get_params_for_api(target.id))[1][name] == "team"
    with pytest.raises(ValueError, match="Unknown connection parameter"):
        await connections.set_management_scope(origin.id, "all", authorized=True, commit=False)
    for service_code, connection in records.items():
        catalog = await agent_permission_catalog(caller.id, connection_id=connection.id)
        assert (catalog.connections[0].management_scope is not None) == (service_code == "service")


@pytest.mark.asyncio
@pytest.mark.parametrize("code", MANAGEMENT_SCOPE_OPTIONS)
async def test_scope_is_local_live_and_never_granted_by_membership(db, scope_agents, code):
    (caller, peer, outsider), team = scope_agents
    assert (await administration_scope(caller.id, code)).agent_ids == frozenset()
    tool = await db.scalar(select(Service).where(Service.code == code))
    initial = await connections.get_or_create_connection(tool.id, caller.id, active=True)
    default = default_management_scope(code)
    assert await connections.get_management_scope(caller.id, connection_id=initial.id) == default
    assert (await administration_scope(caller.id, code)).level == default
    connection = initial
    if "personal" in MANAGEMENT_SCOPE_OPTIONS[code]:
        await delegate(db, caller, code, "personal")
        assert (await administration_scope(caller.id, code)).agent_ids == {caller.id}
    await delegate(db, caller, code, "team")
    expected = {peer.id} if code == "agent" else {caller.id, peer.id}
    assert (await administration_scope(caller.id, code)).agent_ids == expected
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    assert (await administration_scope(caller.id, code)).agent_ids == expected - {peer.id}
    await delegate(db, caller, code, "all")
    assert (await administration_scope(caller.id, code)).allows(outsider.id)
    # Neither a globally forced parameter nor another administration Service may widen this scope.
    tool = await db.get(Service, connection.service_id)
    tool.global_params = {"services.management_scope": {"value": "all", "forced": True}}
    await delegate(db, caller, "service" if code != "service" else "process", "all")
    await connections.set_management_scope(connection.id, None, authorized=True)
    scope = await administration_scope(caller.id, code)
    assert scope.level == default
    assert not scope.allows(outsider.id)


@pytest.mark.asyncio
async def test_native_tool_policies_are_local_to_the_registered_service(db, scope_agents):
    from app.services.mcp_loader import get_disabled_internal_function_names, load_mcp_tools

    (caller, _, _), _ = scope_agents
    await sync_integrated_service_connections(caller.id)
    records = dict((await db.execute(select(Service.code, Connection).join(Connection).where(
        Connection.agent_id == caller.id,
    ))).all())
    assert await connections.has_active_service_function(caller.id, "service", "services_list")
    assert not await connections.has_active_service_function(caller.id, "memory", "services_list")
    assert not await connections.has_active_service_function(caller.id, "service", "synthetic_unregistered_function")
    definitions = [definition for definition in load_mcp_tools() if definition.management_scope_service]
    foreign = records["memory"]
    # Exercise the stored shape an old or incorrectly imported policy can leave.
    db.add_all([
        ConnectionFunctionState(connection_id=foreign.id, function_name=d.name, state="disabled", enabled=False)
        for d in definitions
    ])
    await db.flush()
    for definition in definitions:
        if definition.default_blocked:
            await connections.set_connection_function_state(
                records[definition.service_code].id, definition.name, "enabled", commit=False,
            )
    names = {definition.name for definition in definitions}
    assert names.isdisjoint(await get_disabled_internal_function_names(caller.id))

    for definition in definitions:
        await connections.set_connection_function_state(
            records[definition.service_code].id, definition.name, "disabled", commit=False,
        )
    assert names <= await get_disabled_internal_function_names(caller.id)


@pytest.mark.asyncio
async def test_peer_communication_does_not_grant_management(db, scope_agents):
    (caller, _, outsider), _ = scope_agents
    await sync_integrated_service_connections(caller.id)
    await delegate(db, caller, "chat", "all")
    scope = await administration_scope(caller.id, "chat")
    assert scope.level == "usage"
    assert not scope.allows(outsider.id)


@pytest.mark.asyncio
async def test_goal_scope_covers_file_reads_lifecycle_and_reassignment(db, scope_agents):
    (caller, peer, outsider), _ = scope_agents
    records = [await make_goal(title=f"Synthetic goal {index}", description="<p>Synthetic goal.</p>",
        agent_id=agent.id, status=GoalStatus.ACTIVE) for index, agent in enumerate((caller, peer, outsider))]
    db.add_all(records)
    await db.commit()
    ctx = McpToolContext(caller.id, "internal")
    await sync_integrated_service_connections(caller.id)
    assert (await administration_scope(caller.id, "goal")).agent_ids == {caller.id}
    assert {item["id"] for item in await goal_resources.list_goal_resources(actor_agent_id=caller.id)} == {str(records[0].id)}
    await goals.mcp_goal_pause(ctx, str(records[0].id), records[0].revision)
    with pytest.raises(PermissionError):
        await goals.mcp_goal_pause(ctx, str(records[1].id), records[1].revision)
    await delegate(db, caller, "goal", "team")
    page = await goal_resources.list_goal_resources(actor_agent_id=caller.id, limit=500)
    assert {item["id"] for item in page} == {str(record.id) for record in records[:2]}
    await goals.mcp_goal_pause(ctx, str(records[1].id), records[1].revision)
    assert records[1].status == GoalStatus.PAUSED
    with pytest.raises(PermissionError):
        await goals.mcp_goal_update(ctx, str(records[1].id), records[1].revision, agent_id=outsider.id)
    assert await goal_resources.read_goal_resource(records[2].id, actor_agent_id=caller.id) is None
    await delegate(db, caller, "goal", "usage")
    with pytest.raises(PermissionError):
        await goals.mcp_goal_delete(ctx, str(records[0].id))


@pytest.mark.asyncio
async def test_process_scope_filters_before_limit_and_checks_new_assignment(db, scope_agents):
    (caller, peer, outsider), _ = scope_agents
    tool = await db.scalar(select(Service).where(Service.code == "galaris"))
    records = [ProcessDefinition(agent_id=agent.id, service_id=tool.id, engine_process_id=f"scope-{uuid4().hex}",
        label=f"{index} Synthetic process") for index, agent in enumerate((outsider, peer, caller))]
    db.add_all(records)
    await db.flush()
    runs = [ProcessRun(process_id=record.id, launcher_agent_id=record.agent_id, engine_code="external",
                       status="success", launch_snapshot={}, correlation_id=uuid4().hex,
                       callback_token=uuid4().hex) for record in records]
    db.add_all(runs)
    await db.commit()
    ctx = McpToolContext(caller.id, "internal")
    await sync_integrated_service_connections(caller.id)
    assert (await administration_scope(caller.id, "process")).agent_ids == {caller.id}
    assert [item["id"] for item in await processes.process_admin_list(ctx)] == [records[2].id]
    assert [item["id"] for item in await processes.process_admin_list_runs(ctx)] == [str(runs[2].id)]
    with pytest.raises(PermissionError):
        await processes.process_admin_get(ctx, records[1].id)
    with pytest.raises(PermissionError):
        await processes.process_admin_get_run(ctx, str(runs[1].id), refresh_if_stale=False)
    with pytest.raises(PermissionError):
        await processes.process_admin_create(ctx, caller.id, "unassigned-external-workflow", "Synthetic")
    with pytest.raises(PermissionError):
        await processes.process_admin_update(ctx, records[2].id, workflow_id="unassigned-external-workflow")
    await delegate(db, caller, "process", "team")
    page = await processes.process_admin_list(ctx, limit=1)
    assert len(page) == 1 and page[0]["id"] == records[1].id
    with pytest.raises(PermissionError):
        await processes.process_admin_get(ctx, records[0].id)
    with pytest.raises(PermissionError):
        await processes.process_admin_update(ctx, records[1].id, agent_id=outsider.id)
    with pytest.raises(PermissionError):
        await processes.process_admin_get_run(ctx, str(runs[0].id), refresh_if_stale=False)
    detail = await processes.process_admin_get_run(ctx, str(runs[1].id), refresh_if_stale=False)
    assert detail["id"] == str(runs[1].id)
    with pytest.raises(PermissionError):
        await processes.process_admin_sync(ctx)


@pytest.mark.asyncio
async def test_native_process_administration_keeps_definition_and_launcher_scopes_distinct(db, scope_agents):
    from app.process import native_definitions, native_runs, resource_facade
    from app.process.bpmn import Workflow, Node, Flow
    (caller, peer, outsider), team = scope_agents
    workflow = Workflow(nodes=[Node(id="start", kind="start"), Node(id="end", kind="end")],
                        flows=[Flow(id="done", source="start", target="end")])
    definitions = [await native_definitions.create(actor_agent_id=agent.id, title="Synthetic scoped native workflow",
        code=f"scope-{uuid4().hex}", graph=workflow) for agent in (peer, outsider)]
    runs = [ProcessRun(process_id=definition.id, launcher_agent_id=launcher.id, engine_code="galaris",
        status="success", correlation_id=uuid4().hex, callback_token=uuid4().hex,
        launch_snapshot={"definition": {"graph": workflow.model_dump(mode="json")}})
        for definition, launcher in ((definitions[1], peer), (definitions[0], outsider), (definitions[1], caller))]
    db.add_all(runs)
    await db.commit()
    await delegate(db, caller, "process", "personal")
    with pytest.raises(PermissionError):
        await native_definitions.read(definitions[0].code, caller.id)
    with pytest.raises(PermissionError):
        await processes.process_admin_get_run(McpToolContext(caller.id, "internal"), str(runs[2].id))
    assert (await native_runs.list_runs(caller.id))["items"] == []
    await delegate(db, caller, "process", "team")
    assert (await native_definitions.read(definitions[0].code, caller.id))["can_write"] is True
    assert [item["id"] for item in await native_definitions.list_for(caller.id)] == [definitions[0].id]
    page = await native_runs.list_runs(caller.id)
    assert {item["id"] for item in page["items"]} == {str(runs[0].id), str(runs[2].id)}
    assert (await resource_facade.read_process_run_resource(runs[0].id, actor_agent_id=caller.id))["id"] == str(runs[0].id)
    with pytest.raises(PermissionError):
        await native_runs.require_run(runs[1].id, caller.id, control=True)
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    with pytest.raises(PermissionError):
        await native_runs.require_run(runs[0].id, caller.id, control=True)


@pytest.mark.asyncio
async def test_tool_scope_filters_connections_and_protects_global_settings(db, scope_agents):
    (caller, peer, outsider), _ = scope_agents
    grant = await delegate(db, caller, "service", "team")
    for name in ("service_admin_connection_list", "service_admin_global_params_set"):
        await connections.set_connection_function_state(grant.id, name, "enabled")
    tool = Service(code=f"synthetic_scope_{uuid4().hex}", label="Synthetic shared tool")
    db.add(tool)
    await db.flush()
    db.add_all([Connection(service_id=tool.id, agent_id=agent.id, active=False) for agent in (caller, peer, outsider)])
    await db.commit()
    actor = AdministrationContext(agent_id=caller.id, function_name="service_admin_connection_list")
    page = await admin_service.connection_list(actor, service_id=tool.id, limit=500)
    assert page["total"] == 2
    assert {item["agent_id"] for item in page["items"]} == {caller.id, peer.id}
    with pytest.raises(AdministrationError):
        await admin_service.connection_list(actor, agent_id=outsider.id)
    actor = AdministrationContext(agent_id=caller.id, function_name="service_admin_global_params_set")
    with pytest.raises(AdministrationError):
        await admin_service.global_params_set(actor, tool.id, {}, await admin_service.fingerprint(tool))


@pytest.mark.asyncio
async def test_services_and_task_scopes_are_independent_and_filter_before_pagination(db, scope_agents):
    (caller, peer, outsider), team = scope_agents
    now = datetime.now(timezone.utc)
    calls = [LLMCall(agent_id=agent.id, started_at=now + timedelta(seconds=index))
             for index, agent in enumerate((caller, peer, outsider))]
    tasks = [Task(agent_id=agent.id, label="Synthetic scope task", objective="<p>Synthetic task.</p>",
                  status=TaskStatus.CREATE) for agent in (caller, peer, outsider)]
    db.add_all([*calls, *tasks])
    await db.commit()
    await delegate(db, caller, "service", "team")
    ctx = McpToolContext(caller.id, "internal")
    ids = json.loads(await llm.mcp_llm_calls(ctx, now - timedelta(seconds=1), now + timedelta(seconds=5), limit=1))
    assert ids == [str(calls[1].id)]
    with pytest.raises(ValueError, match="not found"):
        await llm.mcp_llm_call(ctx, str(calls[2].id))
    assert json.loads(await llm.mcp_llm_call(ctx, str(calls[1].id)))["id"] == str(calls[1].id)
    assert set(await db.scalars(select(Task.id).where(await agent_task_filter(caller.id)))) == {tasks[0].id}
    await delegate(db, caller, "task", "team")
    visible = set(await db.scalars(select(Task.id).where(await agent_task_filter(caller.id))))
    assert {task.id for task in tasks[:2]} <= visible and tasks[2].id not in visible
    await require_agent_task_access(tasks[1], caller.id, manage=True)
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    with pytest.raises(PermissionError):
        await require_agent_task_access(tasks[1], caller.id, manage=True)


@pytest.mark.asyncio
async def test_conversation_task_commands_use_tasks_delegation(db, scope_agents, monkeypatch):
    from app.conversation import ConversationTurn, mcp as conversation

    (caller, peer, _), team = scope_agents
    await sync_integrated_service_connections(caller.id)
    await delegate(db, caller, "service", "all")
    task_grant = await delegate(db, caller, "task", "personal")
    chat = await db.scalar(select(Connection).join(Service).where(
        Connection.agent_id == caller.id, Service.code == "chat",
    ))
    room = str(uuid4())
    task = Task(agent_id=peer.id, label="Synthetic scoped Task", status=TaskStatus.EXEC,
                messenger_connection_id=chat.id, message_group_id=room)
    db.add(task)
    await db.commit()
    turn = ConversationTurn(
        room_id=uuid4(), round_id=uuid4(), agent_id=caller.id, language="en",
        objective="Manage the Task", messages=(), messaging_context={"connection_id": chat.id, "room_id": room},
    )
    ctx = McpToolContext(caller.id, "internal", resources={"conversation_turn": turn})
    uri = f"galaris://task/{task.id}"
    commands = (conversation.conversation_task_pause, conversation.conversation_task_resume,
                conversation.conversation_task_stop, conversation.conversation_task_retry)
    monkeypatch.setattr("app.task.runner.go_next", lambda *_args, **_kwargs: None)

    async def assert_out_of_scope():
        assert await conversation.conversation_task_list(ctx) == []
        for command in commands:
            with pytest.raises(ValueError, match="Task not found"):
                await command(ctx, task_id=uri)

    await assert_out_of_scope()
    assert task.status == TaskStatus.EXEC
    await connections.set_management_scope(task_grant.id, "team", authorized=True)
    assert [row["id"] for row in await conversation.conversation_task_list(ctx)] == [str(task.id)]
    for command in commands:
        assert (await command(ctx, task_id=uri))["id"] == str(task.id)
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    await assert_out_of_scope()


@pytest.mark.asyncio
async def test_incident_inspection_scopes_pagination_traces_and_live_revocation(db, scope_agents):
    from app.incident import mcp as incidents, service
    from app.incident.contracts import FailureEvent
    from app.incident.models import FailurePattern
    from app.incident.schemas import FailurePatternUpdate

    (caller, peer, outsider), team = scope_agents
    now = datetime.now(timezone.utc)
    records = [await service.record_failure(db, FailureEvent(
        idempotency_key=f"synthetic-scoped-incident:{uuid4()}", kind="tool", phase="execute",
        agent_id=agent.id if agent else None, tool_name="synthetic_read",
        error_type="SyntheticError", error_message="Synthetic shared failure",
        occurred_at=now + timedelta(seconds=index),
        trace={"diagnostic": f"Synthetic trace {index}", "password": "synthetic-hidden-secret"},
    )) for index, agent in enumerate((caller, peer, outsider, None))]
    await db.commit()
    assert len({record.pattern_id for record in records}) == 1
    await service.update_pattern(records[0].pattern_id, FailurePatternUpdate(
        status="triaged", diagnosis="Synthetic global diagnostic from outside the delegated scope",
    ))
    ctx = McpToolContext(caller.id, "internal")
    for operation in (lambda: incidents.incidents_list(ctx),
                      lambda: incidents.incident_get(ctx, records[0].id)):
        with pytest.raises(PermissionError):
            await operation()
    grant = await delegate(db, caller, "service", "personal")
    page = await incidents.incidents_list(ctx)
    assert page["page_size"] == 50 and page["total"] == 1
    assert [item["id"] for item in page["items"]] == [str(records[0].id)]
    assert "trace" not in page["items"][0]
    assert "pattern_occurrence_count" not in page["items"][0]
    await delegate(db, caller, "service", "team")
    page = await incidents.incidents_list(ctx, page_size=1)
    assert page["total"] == 2
    assert page["items"][0]["id"] == str(records[1].id)
    assert (await incidents.incidents_list(ctx, page=2, page_size=1))["items"][0]["id"] == str(records[0].id)
    detail = await incidents.incident_get(ctx, records[1].id)
    assert detail["trace"]["diagnostic"] == "Synthetic trace 1"
    assert detail["trace"]["password"] == "[REDACTED]"
    assert detail["redacted_fields"] and detail["trace_content_hash"]
    assert {"pattern", "pattern_status", "pattern_occurrence_count"}.isdisjoint(detail)
    for missing in (records[2].id, records[3].id, uuid4()):
        with pytest.raises(ValueError, match="not found"):
            await incidents.incident_get(ctx, missing)
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    with pytest.raises(ValueError, match="not found"):
        await incidents.incident_get(ctx, records[1].id)
    assert (await incidents.incidents_list(ctx))["total"] == 1
    await delegate(db, caller, "service", "all")
    page = await incidents.incidents_list(ctx, page_size=500)
    assert page["total"] == 4 and page["items"][0]["id"] == str(records[3].id)
    detail = await incidents.incident_get(ctx, records[2].id)
    pattern = await db.get(FailurePattern, records[2].pattern_id)
    assert detail["pattern"]["diagnosis"] == pattern.diagnosis
    assert detail["pattern_occurrence_count"] == 4
    # The same filters bound rows and totals before pagination, including inclusive dates.
    filtered = await incidents.incidents_list(ctx, occurred_from=now, occurred_until=now,
        kind="tool", category=records[0].category, search="shared failure", recovered=False)
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == str(records[0].id)
    assert (await incidents.incidents_list(ctx, recovered=True))["total"] == 0
    assert (await incidents.incidents_list(ctx, kind="llm"))["total"] == 0
    assert (await incidents.incidents_list(ctx, search="synthetic-absent"))["total"] == 0
    for arguments in ({"page": 0}, {"page_size": 0}, {"page_size": 501},
                      {"occurred_from": now.replace(tzinfo=None)},
                      {"occurred_until": now.replace(tzinfo=None)},
                      {"occurred_from": now + timedelta(seconds=1), "occurred_until": now}):
        with pytest.raises(ValueError):
            await incidents.incidents_list(ctx, **arguments)
    await delegate(db, caller, "service", "usage")
    for operation in (lambda: incidents.incidents_list(ctx),
                      lambda: incidents.incident_get(ctx, records[2].id)):
        with pytest.raises(PermissionError):
            await operation()


@pytest.mark.asyncio
async def test_incident_tools_work_over_mcp_and_recheck_function_permissions(db, scope_agents):
    from fastmcp import Client
    from app.incident import service
    from app.incident.contracts import FailureEvent
    from app.services import build_galaris_fastmcp

    (caller, _, _), _ = scope_agents
    record = await service.record_failure(db, FailureEvent(
        idempotency_key=f"synthetic-mcp-incident:{uuid4()}", kind="llm", agent_id=caller.id,
        error_type="SyntheticProviderError", error_message="Synthetic provider unavailable",
        trace={"diagnostic": "Synthetic transport trace"},
    ))
    await db.commit()
    await sync_integrated_service_connections(caller.id)
    await delegate(db, caller, "service", "personal")
    grant = await db.scalar(select(Connection).join(Service).where(
        Connection.agent_id == caller.id, Service.code == "galaris",
    ))
    for name in ("incidents_list", "incident_get"):
        await connections.set_connection_function_state(grant.id, name, "enabled")
    server = build_galaris_fastmcp(caller.id, runtime="internal", enabled_service_codes={"galaris"})
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert {"incidents_list", "incident_get"} <= tools.keys()
        assert tools["incidents_list"].input_schema["properties"]["page_size"]["maximum"] == 500
        listing = await client.call_tool("incidents_list", {"page_size": 500})
        assert listing.structured_content["items"][0]["id"] == str(record.id)
        detail = await client.call_tool("incident_get", {"incident_id": str(record.id)})
        assert detail.structured_content["trace"]["diagnostic"] == "Synthetic transport trace"
        invalid = await client.call_tool("incidents_list", {"page_size": 501}, raise_on_error=False)
        assert invalid.is_error
        invalid = await client.call_tool("incident_get", {"incident_id": "not-a-uuid"}, raise_on_error=False)
        assert invalid.is_error
        await connections.set_connection_function_state(grant.id, "incident_get", "disabled")
        denied = await client.call_tool("incident_get", {"incident_id": str(record.id)}, raise_on_error=False)
        assert denied.is_error
