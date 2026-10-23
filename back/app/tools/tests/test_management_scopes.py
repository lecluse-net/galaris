"""Synthetic persistence journeys for connection-local administration scopes."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.agent.models import Agent, AgentTeam, Title
from app.connection import connection_service as connections
from app.connection.models import Connection
from app.goal import mcp as goals, resource_facade as goal_resources
from app.goal.models import GoalStatus
from app.goal.tests.factories import make_goal
from app.llm import mcp as llm
from app.llm.models import LLMCall
from app.process import mcp as processes
from app.process.models import ProcessDefinition, ProcessRun
from app.task.access import agent_task_filter, require_agent_task_access
from app.task.models import Task, TaskStatus
from app.tools import admin_service
from app.tools.admin_contracts import AdministrationContext, AdministrationError
from app.tools.facade import administration_scope
from app.tools.mcp_loader import McpToolContext
from app.tools.models import Tool
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
    tool = await db.scalar(select(Tool).where(Tool.code == code))
    connection = await connections.get_or_create_connection(tool.id, agent.id, active=True)
    await connections.set_connection_active(connection.id, True)
    await connections.set_param(connection.id, "tools.management_scope", level, scope_edit_authorized=True)
    return connection


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["process_admin", "tool_admin", "goal_management", "galaris_admin"])
async def test_scope_is_local_live_and_never_granted_by_membership(db, scope_agents, code):
    (caller, peer, outsider), team = scope_agents
    assert (await administration_scope(caller.id, code)).agent_ids == frozenset()
    connection = await delegate(db, caller, code, "personal")
    assert (await administration_scope(caller.id, code)).agent_ids == {caller.id}
    await delegate(db, caller, code, "team")
    assert (await administration_scope(caller.id, code)).agent_ids == {caller.id, peer.id}
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    assert (await administration_scope(caller.id, code)).agent_ids == {caller.id}
    await delegate(db, caller, code, "all")
    assert (await administration_scope(caller.id, code)).allows(outsider.id)
    # Neither a globally forced parameter nor another administration Tool may widen this scope.
    tool = await db.get(Tool, connection.tool_id)
    tool.global_params = {"tools.management_scope": {"value": "all", "forced": True}}
    await delegate(db, caller, "galaris_admin" if code != "galaris_admin" else "tool_admin", "all")
    await connections.set_connection_active(connection.id, False)
    assert (await administration_scope(caller.id, code)).agent_ids == frozenset()


@pytest.mark.asyncio
async def test_goal_scope_covers_file_reads_lifecycle_and_reassignment(db, scope_agents):
    (caller, peer, outsider), _ = scope_agents
    records = [await make_goal(title=f"Synthetic goal {index}", description="<p>Synthetic goal.</p>",
        agent_id=agent.id, status=GoalStatus.ACTIVE) for index, agent in enumerate((caller, peer, outsider))]
    db.add_all(records)
    await db.commit()
    ctx = McpToolContext(caller.id, "internal")
    await delegate(db, caller, "goal_management", "personal")
    with pytest.raises(PermissionError):
        await goals.mcp_goal_pause(ctx, str(records[1].id), records[1].revision)
    await delegate(db, caller, "goal_management", "team")
    page = await goal_resources.list_goal_resources(actor_agent_id=caller.id, limit=500)
    assert {item["id"] for item in page} == {str(record.id) for record in records[:2]}
    await goals.mcp_goal_pause(ctx, str(records[1].id), records[1].revision)
    assert records[1].status == GoalStatus.PAUSED
    with pytest.raises(PermissionError):
        await goals.mcp_goal_update(ctx, str(records[1].id), records[1].revision, agent_id=outsider.id)
    assert await goal_resources.read_goal_resource(records[2].id, actor_agent_id=caller.id) is None
    await delegate(db, caller, "goal_management", "usage")
    with pytest.raises(PermissionError):
        await goals.mcp_goal_delete(ctx, str(records[0].id))


@pytest.mark.asyncio
async def test_process_scope_filters_before_limit_and_checks_new_assignment(db, scope_agents):
    (caller, peer, outsider), _ = scope_agents
    tool = await db.scalar(select(Tool).where(Tool.code == "galaris"))
    records = [ProcessDefinition(agent_id=agent.id, tool_id=tool.id, engine_process_id=f"scope-{uuid4().hex}",
        label=f"{index} Synthetic process") for index, agent in enumerate((outsider, peer, caller))]
    db.add_all(records)
    await db.flush()
    runs = [ProcessRun(process_id=record.id, launcher_agent_id=record.agent_id, engine_code="external",
                       status="success", launch_snapshot={}, correlation_id=uuid4().hex,
                       callback_token=uuid4().hex) for record in records]
    db.add_all(runs)
    await db.commit()
    await delegate(db, caller, "process_admin", "team")
    ctx = McpToolContext(caller.id, "internal")
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
        for definition, launcher in ((definitions[1], peer), (definitions[0], outsider))]
    db.add_all(runs)
    await db.commit()
    await delegate(db, caller, "process_admin", "personal")
    with pytest.raises(PermissionError):
        await native_definitions.read(definitions[0].code, caller.id)
    await delegate(db, caller, "process_admin", "team")
    assert (await native_definitions.read(definitions[0].code, caller.id))["can_write"] is True
    assert [item["id"] for item in await native_definitions.list_for(caller.id)] == [definitions[0].id]
    page = await native_runs.list_runs(caller.id)
    assert [item["id"] for item in page["items"]] == [str(runs[0].id)]
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
    grant = await delegate(db, caller, "tool_admin", "team")
    for name in ("tool_admin_connection_list", "tool_admin_global_params_set"):
        await connections.set_connection_function_state(grant.id, name, "enabled")
    tool = Tool(code=f"synthetic_scope_{uuid4().hex}", label="Synthetic shared tool")
    db.add(tool)
    await db.flush()
    db.add_all([Connection(tool_id=tool.id, agent_id=agent.id, active=False) for agent in (caller, peer, outsider)])
    await db.commit()
    actor = AdministrationContext(agent_id=caller.id, function_name="tool_admin_connection_list")
    page = await admin_service.connection_list(actor, tool_id=tool.id, limit=500)
    assert page["total"] == 2
    assert {item["agent_id"] for item in page["items"]} == {caller.id, peer.id}
    with pytest.raises(AdministrationError):
        await admin_service.connection_list(actor, agent_id=outsider.id)
    actor = AdministrationContext(agent_id=caller.id, function_name="tool_admin_global_params_set")
    with pytest.raises(AdministrationError):
        await admin_service.global_params_set(actor, tool.id, {}, await admin_service.fingerprint(tool))


@pytest.mark.asyncio
async def test_galaris_scope_protects_tasks_and_llm_ids_before_pagination(db, scope_agents):
    (caller, peer, outsider), team = scope_agents
    now = datetime.now(timezone.utc)
    calls = [LLMCall(agent_id=agent.id, started_at=now + timedelta(seconds=index))
             for index, agent in enumerate((caller, peer, outsider))]
    tasks = [Task(agent_id=agent.id, label="Synthetic scope task", objective="<p>Synthetic task.</p>",
                  status=TaskStatus.CREATE) for agent in (caller, peer, outsider)]
    db.add_all([*calls, *tasks])
    await db.commit()
    await delegate(db, caller, "galaris_admin", "team")
    ctx = McpToolContext(caller.id, "internal")
    ids = json.loads(await llm.mcp_llm_calls(ctx, now - timedelta(seconds=1), now + timedelta(seconds=5), limit=1))
    assert ids == [str(calls[1].id)]
    with pytest.raises(ValueError, match="not found"):
        await llm.mcp_llm_call(ctx, str(calls[2].id))
    assert json.loads(await llm.mcp_llm_call(ctx, str(calls[1].id)))["id"] == str(calls[1].id)
    visible = set(await db.scalars(select(Task.id).where(await agent_task_filter(caller.id))))
    assert {task.id for task in tasks[:2]} <= visible and tasks[2].id not in visible
    await require_agent_task_access(tasks[1], caller.id, manage=True)
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id, AgentTeam.team_id == team.id))
    await db.commit()
    with pytest.raises(PermissionError):
        await require_agent_task_access(tasks[1], caller.id, manage=True)
