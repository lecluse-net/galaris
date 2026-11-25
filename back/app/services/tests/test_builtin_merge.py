"""Qualify retirement on populated PostgreSQL connections and live tool policies."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionFunctionState, ConnectionParam, ServiceFunctionState, facade as connections
from app.services.authorization_models import ActionAuthorization
from app.services.builtin_merge import merge_builtin_services, merge_media_and_search_services, rename_chat_tools
from app.services.contracts import CHAT_CHANNEL_PARAM, VOICE_AUTO_ANSWER_PARAM
from app.services.dbadmin import move_galaris_function_policies
from app.services.facade import administration_scope
from app.services.mandatory_services import sync_integrated_service_connections, sync_mandatory_services
from app.services.models import Service
from core.user import UserModel


async def _legacy(db):
    title = Title(label="Synthetic migration", gender="X")
    admin = Service(code="platform_admin", label="Synthetic administration")
    voice = Service(code="voice", label="Synthetic voice")
    db.add_all([title, admin, voice])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"synthetic-merge-{index}", first_name="Synthetic", last_name="Owner")
              for index in range(2)]
    db.add_all(agents)
    await db.flush()
    await sync_integrated_service_connections()
    rows = [Connection(service_id=service.id, agent_id=agent.id, active=index == 0)
            for service in (admin, voice) for index, agent in enumerate(agents)]
    db.add_all(rows)
    await db.flush()
    return agents, rows


async def _completed_action(db, origin, name):
    owner = UserModel(email=f"{name}@example.test", hashed_password="synthetic")
    db.add(owner)
    await db.flush()
    result = ActionAuthorization(operation_key=f"synthetic-{name}", agent_id=origin.agent_id,
        approver_user_id=owner.id, service_id=origin.service_id, connection_id=origin.id, source="mcp",
        capability_kind="tool", capability_name=name, runtime="internal", context_key="principal:synthetic",
        fingerprint="synthetic", configuration_fingerprint="synthetic", mode="ask", policy_source="tool",
        status="completed", policy_version=1, preview="Synthetic action",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1))
    db.add(result)
    await db.flush()
    return result


@pytest.mark.asyncio
async def test_chat_merge_keeps_transport_and_voice_independent(db):
    from app.messenger import internal_connection
    from app.services.mcp_loader import list_enabled_native_mcp_definitions
    from app.voice.facade import voice_auto_answer_agents

    title = Title(label="Synthetic Chat", gender="X")
    legacy = Service(code="conversation", label="Conversation", can_disable=False)
    db.add_all([title, legacy])
    await db.flush()
    agent = Agent(title_id=title.id, code="chat-merge", first_name="Synthetic", last_name="Agent")
    db.add(agent)
    await db.flush()
    await sync_integrated_service_connections(agent.id)
    chat = await db.scalar(select(Service).where(Service.code == "chat"))
    target = await db.scalar(select(Connection).where(Connection.service_id == chat.id, Connection.agent_id == agent.id))
    target.active = False
    origin = Connection(service_id=legacy.id, agent_id=agent.id, active=True)
    db.add(origin)
    await db.flush()
    db.add_all([
        ConnectionParam(connection_id=origin.id, param_name=VOICE_AUTO_ANSWER_PARAM, param_value="true"),
        ConnectionFunctionState(connection_id=origin.id, function_name="voice_call_stop", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=origin.id, function_name="conversation_choice_resolve", state="ask", enabled=False),
        ServiceFunctionState(service_id=legacy.id, function_name="conversation_round_get", state="disabled", enabled=False),
        ConnectionParam(connection_id=target.id, param_name="services.management_scope", param_value="none"),
    ])
    action = await _completed_action(db, origin, "voice_call_stop")
    for _ in range(2):
        await sync_mandatory_services()

    assert await db.scalar(select(Service.id).where(Service.code == "conversation")) is None
    assert target.active and not (await internal_connection(target.id)).active
    assert agent.id in await voice_auto_answer_agents()
    assert (await connections.resolve_function(target, "voice_call_stop"))["effective_state"] == "ask"
    assert (await connections.resolve_function(target, "chat_choice_resolve"))["effective_state"] == "ask"
    assert (await connections.resolve_function(target, "chat_round_get"))["effective_state"] == "disabled"
    assert await connections.get_management_scope(agent.id, connection_id=target.id) == "none"
    await db.refresh(action)
    assert (action.service_id, action.connection_id, action.status) == (chat.id, target.id, "completed")
    names = {item.name for item in await list_enabled_native_mcp_definitions(agent.id, runtime="internal", conversation_only=True)}
    assert "voice_call_stop" in names and "messenger_list_rooms" not in names

    await connections.set_params_bulk(target.id, {CHAT_CHANNEL_PARAM: "true"}, commit=False)
    assert (await internal_connection(target.id)).active


@pytest.mark.asyncio
async def test_chat_tool_rename_keeps_global_and_local_policies(db):
    agents, _ = await _legacy(db)
    chat_id = await db.scalar(select(Service.id).where(Service.code == "chat"))
    target = await db.scalar(select(Connection).where(Connection.service_id == chat_id, Connection.agent_id == agents[0].id))
    db.add_all([
        ServiceFunctionState(service_id=chat_id, function_name="conversation_round_get", enabled=False),
        ServiceFunctionState(service_id=chat_id, function_name="repository_show", state="disabled", enabled=False),
        ConnectionFunctionState(connection_id=target.id, function_name="conversation_choice_resolve", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=target.id, function_name="chat_choice_resolve", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=target.id, function_name="repository_show", state="enabled", enabled=True),
        ServiceFunctionState(service_id=chat_id, function_name="conversation_round_get", capability_kind="resource", enabled=True),
    ])
    history = await _completed_action(db, target, "conversation_choice_resolve")
    pending = await _completed_action(db, target, "conversation_round_get")
    pending.status = "approved"
    repository_pending = await _completed_action(db, target, "repository_show")
    repository_pending.status = "pending"
    await db.flush()

    for _ in range(2):
        await rename_chat_tools(db)

    assert (await connections.resolve_function(target, "chat_round_get"))["effective_state"] == "disabled"
    assert (await connections.resolve_function(target, "chat_choice_resolve"))["effective_state"] == "ask"
    assert (await connections.resolve_function(target, "chat_repository_show"))["effective_state"] == "enabled"
    assert set((await db.execute(select(ServiceFunctionState.capability_kind, ServiceFunctionState.function_name)
        .where(ServiceFunctionState.service_id == chat_id))).all()) == {
            ("tool", "chat_round_get"), ("resource", "conversation_round_get"), ("tool", "chat_repository_show"),
        }
    assert set(await db.scalars(select(ConnectionFunctionState.function_name).where(
        ConnectionFunctionState.connection_id == target.id,
    ))) == {"chat_choice_resolve", "chat_repository_show"}
    assert (history.status, history.capability_name) == ("completed", "conversation_choice_resolve")
    assert (pending.status, pending.capability_name) == ("invalidated", "conversation_round_get")
    assert (repository_pending.status, repository_pending.capability_name) == ("invalidated", "repository_show")


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "old", "new"), [
    ("service", "service_admin_connection_list", "service_connection_list"),
    ("process", "conversation_process_start", "process_start_conversation"),
    ("task", "conversation_task_submit", "task_run"),
    ("task", "task_work_update", "task_update"),
])
async def test_domain_tool_rename_preserves_policies_and_invalidates_pending_approval(db, code, old, new):
    agents, _ = await _legacy(db)
    service_id = await db.scalar(select(Service.id).where(Service.code == code))
    connection = await db.scalar(select(Connection).where(
        Connection.service_id == service_id, Connection.agent_id == agents[0].id))
    db.add_all([
        ServiceFunctionState(service_id=service_id, function_name=old, state="disabled", enabled=False),
        ConnectionFunctionState(connection_id=connection.id, function_name=old, state="ask", enabled=False),
    ])
    pending = await _completed_action(db, connection, old)
    pending.status = "pending"
    await db.flush()
    for _ in range(2):
        await sync_mandatory_services()
    assert list(await db.scalars(select(ServiceFunctionState.function_name).where(
        ServiceFunctionState.service_id == service_id))) == [new]
    assert (await connections.resolve_function(connection, new))["effective_state"] == "ask"
    assert (pending.status, pending.capability_name) == ("invalidated", old)


@pytest.mark.asyncio
async def test_task_run_merge_intersects_permissions_and_respects_new_grants(db):
    from core.params import Param, Params

    agents, _ = await _legacy(db)
    service_id = await db.scalar(select(Service.id).where(Service.code == "task"))
    first, second = (await db.scalars(select(Connection).where(
        Connection.service_id == service_id, Connection.agent_id.in_([agent.id for agent in agents]),
    ).order_by(Connection.agent_id))).all()
    marker = await db.get(Param, Params.TASK_RUN_POLICIES_MERGED)
    marker.value = None
    db.add_all([
        ConnectionFunctionState(connection_id=first.id, function_name="task_run", state="enabled", enabled=True),
        ConnectionFunctionState(connection_id=second.id, function_name="task_submit", state="disabled", enabled=False),
    ])
    old = await _completed_action(db, first, "task_run")
    old.status = "approved"
    await db.flush()

    await sync_mandatory_services()
    assert (await connections.resolve_function(first, "task_run"))["effective_state"] == "ask"
    assert (await connections.resolve_function(second, "task_run"))["effective_state"] == "disabled"
    assert old.status == "invalidated"
    assert marker.value == "true"
    await connections.set_connection_function_state(first.id, "task_run", "enabled", commit=False)
    await sync_mandatory_services()
    assert (await connections.resolve_function(first, "task_run"))["effective_state"] == "enabled"
    assert (await connections.resolve_function(second, "task_run"))["effective_state"] == "disabled"


@pytest.mark.asyncio
async def test_task_tool_merge_retains_stricter_effective_policies_on_replay(db):
    agents, _ = await _legacy(db)
    service_id = await db.scalar(select(Service.id).where(Service.code == "task"))
    first, second = (await db.scalars(select(Connection).where(
        Connection.service_id == service_id, Connection.agent_id.in_([agent.id for agent in agents]),
    ).order_by(Connection.agent_id))).all()
    db.add_all([
        ServiceFunctionState(service_id=service_id, function_name="task_status", state="disabled", enabled=False),
        ServiceFunctionState(service_id=service_id, function_name="task_retry", state="ask", enabled=False),
        ServiceFunctionState(service_id=service_id, function_name="task_stop", state="enabled", enabled=True),
        ServiceFunctionState(service_id=service_id, function_name="task_stop_conversation", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=first.id, function_name="task_get", state="enabled", enabled=True),
        ConnectionFunctionState(connection_id=first.id, function_name="task_resume", state="disabled", enabled=False),
        ConnectionFunctionState(connection_id=second.id, function_name="task_get", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=second.id, function_name="task_status", state="enabled", enabled=True),
        ConnectionFunctionState(connection_id=second.id, function_name="task_stop_conversation", state="enabled", enabled=True),
    ])
    old_stop = await _completed_action(db, first, "task_stop")
    old_stop.status = "approved"
    await db.flush()

    for _ in range(2):
        await sync_mandatory_services()
        assert (await connections.resolve_function(first, "task_get"))["effective_state"] == "disabled"
        assert (await connections.resolve_function(second, "task_get"))["effective_state"] == "ask"
        assert (await connections.resolve_function(first, "task_cancel"))["effective_state"] == "ask"
        assert (await connections.resolve_function(second, "task_cancel"))["effective_state"] == "enabled"
        assert (await connections.resolve_function(first, "task_resume"))["effective_state"] == "disabled"
        assert (await connections.resolve_function(second, "task_resume"))["effective_state"] == "ask"
    assert set(await db.scalars(select(ServiceFunctionState.function_name).where(
        ServiceFunctionState.service_id == service_id,
    ))) == {"task_get", "task_cancel", "task_resume"}
    assert (old_stop.status, old_stop.capability_name) == ("invalidated", "task_stop")


@pytest.mark.asyncio
async def test_chat_tool_rename_rejects_conflicting_policies(db):
    chat_id = await db.scalar(select(Service.id).where(Service.code == "chat"))
    db.add_all([
        ServiceFunctionState(service_id=chat_id, function_name="conversation_round_get", state="disabled", enabled=False),
        ServiceFunctionState(service_id=chat_id, function_name="chat_round_get", state="enabled", enabled=True),
    ])
    await db.flush()
    with pytest.raises(ValueError, match="Conflicting .* policies"):
        async with db.begin_nested():
            await rename_chat_tools(db)
    assert set((await db.execute(select(ServiceFunctionState.function_name, ServiceFunctionState.state)
        .where(ServiceFunctionState.service_id == chat_id))).all()) == {
            ("conversation_round_get", "disabled"), ("chat_round_get", "enabled"),
        }


@pytest.mark.asyncio
async def test_merge_preserves_scope_and_exact_effective_policy(db):
    agents, (old_admin, _, old_voice, _) = await _legacy(db)
    db.add_all([
        ConnectionParam(connection_id=old_admin.id, param_name="services.management_scope", param_value="all"),
        ConnectionFunctionState(connection_id=old_voice.id, function_name="voice_call_stop", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=old_admin.id, function_name="llm_call", state="disabled", enabled=False),
    ])
    await db.flush()
    for _ in range(2):
        await merge_builtin_services(db)
        await rename_chat_tools(db)
    remaining = await db.scalars(select(Service.id).where(Service.code.in_(("platform_admin", "voice"))))
    assert not remaining.all()
    assert (await administration_scope(agents[0].id, "service")).is_global
    assert (await administration_scope(agents[1].id, "service")).level == "usage"
    assert (await administration_scope(agents[0].id, "galaris")).level == "usage"
    from app.voice.facade import voice_auto_answer_agents

    assert await voice_auto_answer_agents() == {agents[0].id}
    for code, name, expected in (
        ("galaris", "documentation_catalog", "enabled"), ("galaris", "llm_call", "disabled"),
        ("chat", "voice_turn_get", "ask"), ("chat", "chat_round_get", "ask"),
        ("chat", "voice_call_stop", "ask"), ("chat", "voice_call_list", "enabled"),
        ("chat", "voice_call_start", "ask"),
    ):
        tool = await db.scalar(select(Service).where(Service.code == code))
        for index, agent in enumerate(agents):
            target = await db.scalar(select(Connection).where(Connection.service_id == tool.id, Connection.agent_id == agent.id))
            state = expected if index == 0 else "disabled"
            assert (await connections.resolve_function(target, name))["effective_state"] == state
            assert (name in (await connections.get_disabled_function_names_many([target]))[target.id]) is (state == "disabled")


@pytest.mark.asyncio
async def test_migration_retains_policies_for_a_soft_deleted_agent(db):
    agents, (_, old_admin, _, _) = await _legacy(db)
    archived = agents[1]
    galaris = await db.scalar(select(Service.id).where(Service.code == "galaris"))
    await db.execute(delete(Connection).where(Connection.service_id == galaris, Connection.agent_id == archived.id))
    archived.soft_delete()
    db.add(ConnectionFunctionState(connection_id=old_admin.id, function_name="llm_call", state="disabled", enabled=False))
    await db.flush()

    await merge_builtin_services(db)

    connection = await db.scalar(select(Connection).where(Connection.service_id == galaris, Connection.agent_id == archived.id))
    assert connection is not None and not connection.active
    assert (await connections.resolve_function(connection, "llm_call"))["connection_state"] == "disabled"


@pytest.mark.asyncio
async def test_merge_refuses_to_erase_an_unmapped_connection_setting(db):
    _, (_, _, voice, _) = await _legacy(db)
    db.add(ConnectionParam(connection_id=voice.id, param_name="synthetic", param_value="keep"))
    await db.flush()
    with pytest.raises(ValueError, match="connection parameter requires"):
        async with db.begin_nested():
            await merge_builtin_services(db)
    assert await db.scalar(select(Service.id).where(Service.code == "voice")) is not None
    assert await db.scalar(select(ConnectionParam.param_value).where(ConnectionParam.connection_id == voice.id)) == "keep"


@pytest.mark.asyncio
async def test_catalogue_merge_preserves_independent_media_and_search_access(db):
    agents, _ = await _legacy(db)
    destinations = {row.code: row.id for row in await db.scalars(select(Service).where(
        Service.code.in_(("multimedia", "browser")),
    ))}
    for code, state in (("audio", True), ("image", False), ("search", True)):
        service = Service(code=code, label=code)
        db.add(service)
        await db.flush()
        db.add_all(Connection(service_id=service.id, agent_id=agent.id, active=active)
                   for agent, active in zip(agents, (state, not state), strict=True))
        if code == "audio":
            db.add(ServiceFunctionState(service_id=service.id, function_name="audio_transcribe", state="enabled", enabled=True))
        if code == "search":
            await db.flush()
            origin = await db.scalar(select(Connection).where(Connection.service_id == service.id,
                                                               Connection.agent_id == agents[0].id))
            history = await _completed_action(db, origin, "search_web")
    for code in ("multimedia", "browser"):
        target = await db.scalar(select(Connection).where(Connection.service_id == destinations[code],
                                                          Connection.agent_id == agents[0].id))
        target.active = False
    await db.flush()

    for _ in range(2):
        await merge_media_and_search_services(db)

    assert not (await db.scalars(select(Service.id).where(Service.code.in_(("audio", "image", "search"))))).all()
    await db.refresh(history)
    assert history.status == "completed" and history.service_id == destinations["browser"]
    assert (await db.get(Connection, history.connection_id)).service_id == destinations["browser"]
    for code, name, expected in (
        ("multimedia", "audio_transcribe", ["enabled", "disabled"]),
        ("multimedia", "image_read", ["disabled", "ask"]),
        ("multimedia", "audio_read", ["disabled", "enabled"]),
        ("browser", "search_web", ["ask", "disabled"]),
        ("browser", "browser_open", ["disabled", "ask"]),
    ):
        for agent, state in zip(agents, expected, strict=True):
            target = await db.scalar(select(Connection).where(Connection.service_id == destinations[code],
                                                              Connection.agent_id == agent.id))
            assert target.active
            assert (await connections.resolve_function(target, name))["effective_state"] == state
    new_agent = Agent(title_id=agents[0].title_id, code="post-merge", first_name="Synthetic", last_name="Newcomer")
    db.add(new_agent)
    await db.flush()
    await sync_integrated_service_connections(new_agent.id)
    target = await db.scalar(select(Connection).where(Connection.service_id == destinations["multimedia"],
                                                     Connection.agent_id == new_agent.id))
    assert (await connections.resolve_function(target, "audio_transcribe"))["effective_state"] == "enabled"


@pytest.mark.asyncio
async def test_split_transfers_function_overrides_without_changing_other_functions(db):
    agents, _ = await _legacy(db)
    legacy = Service(code="conversation", label="Conversation", can_disable=False)
    db.add(legacy)
    await db.flush()
    db.add(Connection(service_id=legacy.id, agent_id=agents[0].id, active=True))
    await db.flush()
    services = {row.code: row.id for row in await db.scalars(select(Service))}
    targets = [("galaris", "agent", "team_members"), ("galaris", "contact", "contact_update"),
               ("galaris", "document", "document_analysis_get"), ("galaris", "task", "task_run"),
               ("conversation", "process", "process_pending"),
               ("conversation", "task", "task_list"), ("conversation", "document", "document_show")]
    for source, _, name in targets:
        origin = await db.scalar(select(Connection).where(Connection.service_id == services[source],
                                                          Connection.agent_id == agents[0].id))
        db.add(ConnectionFunctionState(connection_id=origin.id, function_name=name, state="disabled", enabled=False))
        if name == "task_list":
            history = await _completed_action(db, origin, name)
    await db.flush()

    for _ in range(2):
        await move_galaris_function_policies(db)
    await db.refresh(history)
    assert history.status == "completed" and history.service_id == services["task"]

    for _, code, name in targets:
        for agent, expected in zip(agents, ("disabled", "default"), strict=True):
            connection = await db.scalar(select(Connection).where(Connection.agent_id == agent.id,
                                                                  Connection.service_id == services[code]))
            assert connection.active
            assert (await connections.resolve_function(connection, name))["connection_state"] == expected
