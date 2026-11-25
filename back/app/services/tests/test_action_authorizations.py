"""Approval protects the actual dispatch across retries and concurrent decisions."""

import asyncio
import json
from unittest.mock import AsyncMock
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent import Agent, Title
from app.harnesses.registry import all_providers
from app.services.authorization import (
    AuthorizationAction, AuthorizationClosed, AuthorizationRequired,
    answer_action, claim_action, finish_action,
)
from app.services.authorization_models import ActionAuthorization
from core.database import get_db_session
from core.user import UserModel


@pytest_asyncio.fixture
async def action(committed_database):
    async with get_db_session() as db:
        user = UserModel(email=f"approver-{uuid4().hex}@example.test", hashed_password="synthetic")
        title = Title(label="Synthetic", gender="X")
        db.add_all([user, title])
        await db.flush()
        from core.authorize import Assignment, Privilege, Role
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))
        role = Role(code=f"synthetic-approver-{uuid4().hex}", privileges=[privilege])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
        agent = Agent(user_id=user.id, title_id=title.id, code=f"approval-{uuid4().hex}", first_name="Synthetic", last_name="Agent")
        db.add(agent)
        await db.flush()
        return AuthorizationAction(agent_id=agent.id, runtime="internal", context_key="principal:synthetic-run",
                                   callback_key=str(uuid4()), source="runtime", name="command",
                                   arguments={"command": "echo synthetic", "cwd": "/workspace"},
                                   configuration={"session": "synthetic-session"})


async def pending(action):
    with pytest.raises(AuthorizationRequired) as caught:
        await claim_action(action)
    return caught.value.request_id


@pytest.mark.asyncio
@pytest.mark.parametrize("readable", [True, False])
async def test_task_approval_resolves_only_targets_the_reviewer_can_read(action, readable):
    from app.connection import facade as connections
    from app.messenger import read_internal_interaction
    from app.messenger.models import Interaction
    from app.services.authorization_notifications import deliver_authorization_notifications
    from app.services.authorization_router import get_request
    from app.services.models import Service
    from app.task import Task
    from core.authorize import Assignment, Privilege, Role
    from core.user import user_identity_context

    title = "Synthetic task <2026>"
    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        if readable:
            privilege = await db.scalar(select(Privilege).where(Privilege.code == "TASK_ACCESS"))
            role = Role(code=f"synthetic-task-reader-{uuid4().hex}", privileges=[privilege])
            db.add(role)
            await db.flush()
            db.add(Assignment(user_id=agent.user_id, role_id=role.id))
        target = Task(agent_id=agent.id, label=title, objective="<p>Synthetic work</p>")
        db.add(target)
        await db.flush()
        task_id = str(target.id)
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        service = await db.scalar(select(Service).where(Service.code == "task"))
        await connections.get_or_create_connection(chat.id, agent.id)
        connection = await connections.get_or_create_connection(service.id, agent.id)
        await connections.set_connection_function_state(connection.id, "task_cancel", "ask")
        request = replace(action, source="mcp", name="task_cancel", arguments={"task_id": task_id},
                          service_id=service.id, connection_id=connection.id)

    identifier = await pending(request)
    await deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        choice = await db.get(Interaction, row.interaction_id)
        choice_view = await read_internal_interaction(row.approver_user_id, UUID(choice.room_id), choice.id)
        with user_identity_context(await db.get(UserModel, row.approver_user_id)):
            review = await get_request(identifier)
        field, = review["presentation"]["fields"]
        assert review["arguments"]["task_id"] == task_id
        assert task_id not in choice_view.body
        assert choice_view.body_html is not None
        if readable:
            assert field["value"] == title
            assert field["resource_uri"] == f"galaris://task/{task_id}"
            assert f'href="galaris://task/{task_id}">Synthetic task &lt;2026&gt;</a>' in choice_view.body_html
        else:
            assert field["value"] != task_id
            assert "resource_uri" not in field
            assert task_id not in choice_view.body_html and "Synthetic task" not in choice_view.body_html


@pytest.mark.asyncio
async def test_streamable_http_mcp_app_captures_and_filters_only_an_enabled_read_tool(action, monkeypatch):
    from contextlib import asynccontextmanager
    import httpx
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    from app.connection import facade as connections
    from app.connection.models import Connection
    from app.services import mcp_loader, service as services
    from app.services.contracts import ToolCallRejectedError
    from app.services.models import Service
    from core.api import create_app
    from plugins.sample.fixtures import mount
    from plugins.sample.mcp_inventory import APP_URI

    @asynccontextmanager
    async def lifespan(_app):
        yield

    application = create_app(lifespan)
    mount(application)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), **kwargs)

    endpoint = "http://localhost/api/plugin-samples/mcp/"
    transport = StreamableHttpTransport(endpoint, httpx_client_factory=client_factory)
    monkeypatch.setattr(mcp_loader, "_external_transport", lambda *_args: transport)
    presentations = []
    room_id = uuid4()
    async with get_db_session() as db:
        service = Service(code="test_inventory", label="Inventory",
            mcp_config={"type": "http", "url": endpoint})
        db.add(service)
        await db.flush()
        service_id = service.id
        assert service.conversation_tools == {}
        connection = Connection(service_id=service.id, agent_id=action.agent_id, active=True)
        db.add(connection)
        await db.flush()
        connection_id = connection.id
        await connections.set_connection_function_state(connection_id, "sample_inventory", "enabled")
        await connections.set_connection_function_state(connection_id, APP_URI, "enabled", capability_kind="resource")
        await services.set_conversation_tool(service_id, "sample_inventory", source="external", enabled=True)
        owner = await db.get(Agent, action.agent_id)
        restricted_agent = Agent(
            code=f"inventory-{uuid4().hex}", title_id=owner.title_id, user_id=owner.user_id,
            first_name="Restricted", last_name="Inventory Agent",
        )
        db.add(restricted_agent)
        await db.flush()
        restricted_connection = await connections.get_or_create_connection(service_id, restricted_agent.id)
        await connections.set_connection_function_state(restricted_connection.id, "sample_inventory", "disabled")
        restricted_server = await mcp_loader.build_agent_mcp(restricted_agent.id, conversation_only=True)
        server = await mcp_loader.build_agent_mcp(
            action.agent_id, conversation_only=True, resources={"mcp_presentation_sink": presentations.append},
        )

    async with application.router.lifespan_context(application):
        async with Client(restricted_server) as client:
            assert "test_inventory_sample_inventory" not in {tool.name for tool in await client.list_tools()}
            assert (await client.call_tool("test_inventory_sample_inventory", raise_on_error=False)).is_error
        async with Client(server) as client:
            visible = {tool.name for tool in await client.list_tools()}
            assert "test_inventory_sample_inventory" in visible
            assert "test_inventory_sample_value" not in visible
            assert (await client.call_tool("test_inventory_sample_value", raise_on_error=False)).is_error
            result = await client.call_tool("test_inventory_sample_inventory")
            assert len(result.structured_content["table"]["rows"]) == 4
        presentation, = presentations
        assert presentation.table.rows == result.structured_content["table"]["rows"]
        assert presentation.resource_uri == APP_URI
        params = dict(agent_id=action.agent_id, user_id=action.approver_user_id or 0, room_id=room_id)
        async with get_db_session() as db:
            params["user_id"] = (await db.get(Agent, action.agent_id)).user_id
        html = await mcp_loader.request_mcp_presentation(presentation, **params)
        assert '<select name="site">' in html
        filtered = await mcp_loader.request_mcp_presentation(presentation, **params, arguments={"site": "Lyon"})
        assert [row[-1] for row in filtered.rows] == [18, 7]
        async with get_db_session():
            await connections.set_connection_function_state(connection_id, "sample_inventory", "ask")
        with pytest.raises(ToolCallRejectedError):
            await mcp_loader.request_mcp_presentation(presentation, **params, arguments={"site": "Lille"})
        async with get_db_session():
            await services.set_conversation_tool(service_id, "sample_inventory", source="external", enabled=False)
            task_server = await mcp_loader.build_agent_mcp(action.agent_id)
        async with Client(server) as client:
            assert "test_inventory_sample_inventory" not in {tool.name for tool in await client.list_tools()}
            assert (await client.call_tool("test_inventory_sample_inventory", raise_on_error=False)).is_error
        with pytest.raises(PermissionError):
            await mcp_loader.request_mcp_presentation(presentation, **params)
        async with Client(task_server) as client:
            assert {"test_inventory_sample_inventory", "test_inventory_sample_value"} <= {
                tool.name for tool in await client.list_tools()
            }


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "service_code", "field", "label"), [
    ("goal_create", "goal", "description", "Description"),
    ("goal_update", "goal", "description", "Description"),
    ("goal_update_suivi", "goal", "tracking_content", "Tracking"),
    ("task_run", "task", "objective", "Task objective"),
    ("agent_create", "agent", "job_description", "Job description"),
    ("agent_update", "agent", "personality", "Personality"),
])
async def test_approval_projects_editorial_fields_to_the_recipient_chat(action, name, service_code, field, label):
    from app.connection import facade as connections
    from app.messenger import read_internal_interaction
    from app.messenger.models import Interaction
    from app.services.authorization_notifications import deliver_authorization_notifications
    from app.services.authorization_presentation import present_authorization
    from app.services.mcp_authorization import bind_native_action
    from app.services.mcp_loader import McpToolContext, load_mcp_tools
    from app.services.models import Service

    html = "<h2>Planned work</h2><ul><li>Review the result</li></ul>"
    arguments = {field: html}
    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        if name == "agent_create":
            arguments = {"configuration": {field: html, "first_name": "Synthetic", "last_name": "<Example>",
                "code": "synthetic-review", "title_id": agent.title_id, "user_id": agent.user_id}}
        elif name == "agent_update":
            arguments = {"agent_id": action.agent_id, "changes": {field: html, "job_description": None, "team_ids": []}}
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        tool = await db.scalar(select(Service).where(Service.code == service_code))
        await connections.get_or_create_connection(chat.id, action.agent_id)
        connection = await connections.get_or_create_connection(tool.id, action.agent_id)
        await connections.set_connection_function_state(connection.id, name, "ask")
        definition = next(item for item in load_mcp_tools() if item.name == name)
        native_action = await bind_native_action(
            McpToolContext(agent_id=action.agent_id, runtime="internal", conversation_only=name == "task_run"),
            definition, arguments,
        )
    identifier = await pending(native_action)
    await deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        choice = await db.get(Interaction, row.interaction_id)
        assert choice is not None and choice.room_id is not None
        review = await present_authorization(row, arguments=arguments, language="en")
        assert [item for item in review["fields"] if item.get("format") == "html"] == [
            {"label": label, "value": html, "format": "html"},
        ]
        choice_view = await read_internal_interaction(row.approver_user_id, UUID(choice.room_id), choice.id)
        assert choice_view.can_answer and choice_view.is_authorization
        assert choice_view.body_html is not None and html in choice_view.body_html
        assert "Review the result" in choice_view.body and "<h2>" not in choice_view.body
        if name == "agent_create":
            assert review["title"] == "Create an agent"
            assert {"label": "Last name", "value": "<Example>"} in review["fields"]
            assert "&lt;Example&gt;" in choice_view.body_html
        if name == "agent_update":
            assert {"label": "Job description", "value": "—"} in review["fields"]
            assert {"label": "Team IDs", "value": "[]"} in review["fields"]


@pytest.mark.asyncio
async def test_authorization_policy_lock_does_not_wait_for_unrelated_agent_foreign_keys(action):
    from sqlalchemy import text
    from app.agent import authorization_policy
    from app.task import Task

    async with get_db_session() as caller:
        caller.add(Task(label="Synthetic admitted work", agent_id=action.agent_id))
        await caller.flush()
        # The outer admission owns a KEY SHARE FK lock on Agent until commit.
        # Authorization must serialize policy changes without waiting on that FK.
        async with get_db_session() as authorization:
            await authorization.execute(text("SET LOCAL lock_timeout = '100ms'"))
            policy = await authorization_policy(action.agent_id, lock=True)
            assert policy.manager_user_id > 0
            from sqlalchemy import update
            from sqlalchemy.exc import DBAPIError

            async with get_db_session() as editor:
                await editor.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(DBAPIError):
                    await editor.execute(update(Agent).where(Agent.id == action.agent_id).values(
                        authorization_version=Agent.authorization_version + 1))
                await editor.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
@pytest.mark.parametrize("state", ["default", "ask", "disabled"])
async def test_goal_question_needs_no_approval_by_default_but_preserves_explicit_policy(action, runtime, state):
    from app.connection import facade as connections
    from app.services.contracts import ToolCallRejectedError
    from app.services.mcp_authorization import bind_native_action
    from app.services.mcp_loader import McpToolContext, load_mcp_tools
    from app.services.models import Service

    async with get_db_session() as db:
        tool = await db.scalar(select(Service).where(Service.code == "goal"))
        connection = await connections.get_or_create_connection(tool.id, action.agent_id)
        await connections.set_connection_function_state(connection.id, "goal_ask_referrer", state)
        policy = await connections.resolve_function(connection, "goal_ask_referrer")
        assert policy["default_state"] == "enabled"
        assert policy["effective_state"] == ("enabled" if state == "default" else state)
        definition = next(item for item in load_mcp_tools() if item.name == "goal_ask_referrer")
        question = await bind_native_action(
            McpToolContext(agent_id=action.agent_id, runtime=runtime),
            definition, {"question": "Which delivery option should I use?"},
        )

    if state == "ask":
        await pending(question)
    elif state == "disabled":
        with pytest.raises(ToolCallRejectedError, match="disabled"):
            await claim_action(question)
    else:
        assert await claim_action(question) is None
        async with get_db_session() as db:
            assert await db.scalar(select(ActionAuthorization.id).where(
                ActionAuthorization.agent_id == action.agent_id,
                ActionAuthorization.capability_name == "goal_ask_referrer",
            )) is None


@pytest.mark.asyncio
async def test_permission_catalog_keeps_saved_rules_and_reports_offline_sources_without_secrets(action, monkeypatch):
    from app.connection import Connection, facade as connections
    from app.services.models import Service
    from app.services.permission_catalog import agent_permission_catalog
    calls = []
    async def unavailable(tool, params, *, include_resources=True):
        calls.append(include_resources)
        raise TimeoutError("Synthetic unreachable MCP service")
    monkeypatch.setattr("app.services.permission_catalog.list_external_mcp_capabilities", unavailable)
    async with get_db_session() as db:
        tool = Service(code=f"offline-{uuid4().hex}", label="Synthetic offline catalog",
            mcp_config={"type": "http", "url": "https://synthetic.example.test/mcp"},
            connection_schema={"params": {"network_filter": {"type": "password"}, "api_key": {"type": "password"}}})
        db.add(tool); await db.flush()
        connection = Connection(agent_id=action.agent_id, service_id=tool.id, active=True)
        db.add(connection); await db.flush()
        await connections.set_connection_function_state(connection.id, "saved_external_function", "disabled")
        await connections.set_params_bulk(connection.id, {"network_filter": "synthetic-secret", "api_key": "synthetic-token"})
        catalogue = await agent_permission_catalog(action.agent_id)
        entry = next(row for row in catalogue.capabilities if row.name == "saved_external_function")
        assert entry.effective_state == "disabled" and not entry.available
        assert "Synthetic offline catalog" in catalogue.unavailable_catalogs
        assert calls == [False]
        assert "synthetic-secret" not in catalogue.model_dump_json()
        assert "synthetic-token" not in catalogue.model_dump_json()



async def approve_and_claim(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    return await claim_action(action)


@pytest.mark.asyncio
@pytest.mark.parametrize("pin_storage", ["column", "data", "default"])
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
@pytest.mark.parametrize("state", ["enabled", "disabled"])
async def test_goal_message_authorizes_and_delivers_on_its_internal_connection(action, pin_storage, runtime, state):
    """An enabled external Messenger cannot make a Goal's exact Chat route ambiguous."""
    from fastmcp import Client
    from app.connection import Connection, facade as connections
    from app.messenger import create_internal_room
    from app.messenger.models import Message
    from app.task.models import Task, TaskStatus
    from app.services import ServiceModel, build_agent_galaris_fastmcp

    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        chat = await db.scalar(select(ServiceModel).where(ServiceModel.code == "chat"))
        talk = ServiceModel(code=f"synthetic-talk-{uuid4().hex}", label="Synthetic Talk",
                         messenger_config={"service": "nextcloud_talk"})
        db.add(talk)
        await db.flush()
        connection = Connection(agent_id=agent.id, service_id=chat.id, active=True)
        db.add_all([connection, Connection(agent_id=agent.id, service_id=talk.id, active=True)])
        await db.flush()
        assert await create_internal_room(actor_user_id=agent.user_id, agent_id=agent.id) is not None
        task = Task(label="Synthetic goal cycle", objective="<p>Send a progress update.</p>",
                    agent_id=agent.id, status=TaskStatus.EXEC,
                    messenger_connection_id=connection.id if pin_storage == "column" else None,
                    data={"goal_referrer_type": "MESSENGER", "goal_referrer_platform": "internal",
                          "goal_referrer_user_id": f"user:{agent.user_id}",
                          "messenger_connection_id": connection.id})
        db.add(task)
        await db.flush()
        task_id, chat_connection_id, user_id = task.id, connection.id, agent.user_id
        await connections.set_connection_function_state(connection.id, "messenger_send_message_to_user", state)

    async with get_db_session():
        server = await build_agent_galaris_fastmcp(action.agent_id, runtime=runtime,
            task_id=None if pin_storage == "default" else task_id,
            allowed_tool_names={"messenger_send_message_to_user", "messenger_list_rooms"})
    async with Client(server) as client:
        rooms = await client.call_tool("messenger_list_rooms", {}, raise_on_error=False)
        assert not rooms.is_error
        result = await client.call_tool("messenger_send_message_to_user",
            {"user": f"user:{user_id}", "message": "Synthetic progress update."}, raise_on_error=False)
        assert result.is_error is (state == "disabled")
    async with get_db_session() as db:
        receipts = list(await db.scalars(select(Message).where(Message.direction == "outbound",
            Message.connection_id == chat_connection_id)))
        assert [row.text for row in receipts] == (["Synthetic progress update."] if state == "enabled" else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize("processing", [False, True])
async def test_api_decision_resolves_chat_choice_without_dispatch(action, monkeypatch, approved, processing):
    import app.services.authorization_notifications as outbox
    from app.connection import Connection
    from app.messenger import (
        ChoiceOption, ChoiceRequest, chat_pending_question_summary, list_chat_rooms,
        mark_chat_room_read, request_user_choice,
    )
    from app.messenger.models import Interaction
    from app.services.models import Service
    from core.authorize import Assignment, Privilege, Role
    from core.authorize.context import role_id_ctx

    async with get_db_session() as db:
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        db.add(Connection(agent_id=action.agent_id, service_id=chat.id, active=True))
    identifier = await pending(action)
    await outbox.deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        interaction_id = row.interaction_id
        assert interaction_id is not None
        choice = await db.get(Interaction, interaction_id)
        assert choice is not None and choice.room_id is not None
        room_id = UUID(choice.room_id)
        approver = row.approver_user_id
        assert await mark_chat_room_read(approver, room_id)
        assert await chat_pending_question_summary(approver) == (1, choice.expires_at)
        rooms = await list_chat_rooms(approver)
        assert {room.id: room.pending_question_until for room in rooms.items} == {room_id: choice.expires_at}
        assert rooms.items[0].unread_count == 0

        chat_access = await db.scalar(select(Privilege).where(Privilege.code == "CHAT_ACCESS"))
        assert chat_access is not None
        chat_only_role = Role(code=f"synthetic-chat-only-{uuid4().hex}", privileges=[chat_access])
        db.add(chat_only_role)
        await db.flush()
        db.add(Assignment(user_id=approver, role_id=chat_only_role.id))
        await db.commit()
        token = role_id_ctx.set(chat_only_role.id)
        try:
            assert await chat_pending_question_summary(approver) == (0, None)
            rooms = await list_chat_rooms(approver)
            assert {room.id: room.pending_question_until for room in rooms.items} == {room_id: None}
        finally:
            role_id_ctx.reset(token)

        question = await request_user_choice(
            agent_id=action.agent_id, user_id=approver, idempotency_key="synthetic-follow-up",
            request=ChoiceRequest(
                kind="synthetic-follow-up", title="Continue the review?",
                options=[ChoiceOption(id="yes", label="Yes")],
            ),
        )
        assert question.room_id == choice.room_id
        assert await chat_pending_question_summary(approver) == (2, min(choice.expires_at, question.expires_at))
        rooms = await list_chat_rooms(approver)
        assert rooms.items[0].pending_question_until == max(choice.expires_at, question.expires_at)
        if processing:
            choice.status = "PROCESSING"
            choice.processing_token = uuid4()
            choice.resolution = {"option_id": "deny" if approved else "allow"}
            await db.commit()
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=approved)
        await db.refresh(choice)
        assert choice.status == "RESOLVED"
        assert choice.resolution["option_id"] == ("allow" if approved else "deny")
        assert await chat_pending_question_summary(approver) == (1, question.expires_at)
        rooms = await list_chat_rooms(approver)
        assert {room.id: room.pending_question_until for room in rooms.items} == {room_id: question.expires_at}
    monkeypatch.setattr(outbox, "wake_authorization_context", AsyncMock(return_value=True))
    await outbox.reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        choice = await db.get(Interaction, interaction_id)
        assert choice.status == "RESOLVED"
        assert choice.resolution["option_id"] == ("allow" if approved else "deny")
        assert row.status == ("approved" if approved else "denied")
        assert row.claimed_at is None


@pytest.mark.asyncio
async def test_deleted_agent_cannot_answer_or_resume_but_keeps_the_audit(action):
    from app.services.authorization_notifications import reconcile_authorizations
    identifier = await pending(action)
    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        agent.soft_delete()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True) is False
    with pytest.raises(PermissionError, match="unavailable"):
        await claim_action(action)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "invalidated" and row.encrypted_arguments is None
        assert row.agent_id == action.agent_id and row.approver_user_id is not None


@pytest.mark.asyncio
async def test_refused_arguments_cannot_create_a_new_question_under_a_new_callback(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=False)
    with pytest.raises(AuthorizationClosed, match="denied") as refused:
        await claim_action(replace(action, callback_key=str(uuid4())))
    assert refused.value.request_id == identifier


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_action", ["openai_messages", "codex", "claude_agent", "deepseek_harness"], indirect=True)
@pytest.mark.parametrize("approved", [True, False])
async def test_managed_approval_waits_for_the_resumed_task_attempt(action, runtime_action, approved):
    from datetime import datetime, timedelta, timezone
    from httpx import ASGITransport, AsyncClient
    from app.agent import AgentSnapshot, ResolvedExecutionTarget
    from app.agent.tests.test_driver_testkit import _request
    from app.harnesses.models import AgentHarness
    from app.mcp.service import ensure_system_token
    from app.task import task_service
    from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter, _wake_authorization_context
    from app.task.models import Task, TaskAttempt, TaskStatus
    from app.services.runtime_authorization import issue_runtime_run_grant, renew_runtime_run_grant, runtime_authorizations_ready
    from main import app

    lease = uuid4()
    async with get_db_session() as db:
        assignment = await db.scalar(select(AgentHarness).where(AgentHarness.agent_id == action.agent_id))
        task = Task(agent_id=action.agent_id, label="Synthetic approved effect", objective="<p>Write once.</p>",
                    status=TaskStatus.EXEC, lease_token=lease,
                    lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add(task)
        await db.flush()
        attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH", status="CLAIMED",
                              worker_id="synthetic-first-worker", lease_token=lease)
        db.add(attempt)
        await db.flush()
        task_id, attempt_id, assignment_id = task.id, attempt.id, assignment.id
        bearer = await ensure_system_token(action.agent_id)
    request = replace(_request(), task_id=task_id, attempt_id=attempt_id, driver_code="openai_messages",
        agent=AgentSnapshot(id=action.agent_id, code="synthetic", first_name="Synthetic", last_name="Runtime", driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code=runtime_action.runtime, target_ref=f"harness:{assignment_id}", revision="1"))
    credential = await issue_runtime_run_grant(request)
    headers = {"Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": credential}
    endpoint = "/api/services/runtime-authorizations"
    payload = {"callback_key": "same-effect", "name": "write_file", "session": "synthetic", "arguments": {"content": "write once"}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 200 and response.json()["status"] == "pending"
        identifier = UUID(response.json()["request_id"])
        assert not await runtime_authorizations_ready(credential, agent_id=action.agent_id, identifiers=[identifier])
        # Even an immediate answer must wait for the first attempt to settle.
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=approved)
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "pending"
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["status"] == "pending"
        assert not await runtime_authorizations_ready(credential, agent_id=action.agent_id, identifiers=[identifier])
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            SqlAlchemyAgentTaskAdapter().suspend(task, task_service.PAUSE_APPROVAL)
            task.data = {**(task.data or {}), "authorization_requests": [str(identifier)]}
            task.lease_token = task.lease_expires_at = None
            (await db.get(TaskAttempt, attempt_id)).status = "WAITING_APPROVAL"
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "pending"
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["status"] == "pending"
        async with get_db_session() as db:
            assert (await db.get(ActionAuthorization, identifier)).status == ("approved" if approved else "denied")
        assert await _wake_authorization_context(action.agent_id, f"task:{task_id}")
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            assert task.status == TaskStatus.DISPATCH and not task.paused
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "pending"

        resumed_lease = uuid4()
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            task.status = TaskStatus.EXEC
            task.lease_token, task.lease_expires_at = resumed_lease, datetime.now(timezone.utc) + timedelta(minutes=5)
            attempt = TaskAttempt(task_id=task_id, attempt_number=2, phase="DISPATCH", status="CLAIMED",
                                  worker_id="synthetic-resumed-worker", lease_token=resumed_lease)
            db.add(attempt)
            await db.flush()
            resumed_attempt_id = attempt.id
        # A new lease alone cannot release an actor still bound to the old attempt.
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "pending"
        await renew_runtime_run_grant(credential, replace(request, run_id=uuid4(), attempt_id=resumed_attempt_id))
        assert await runtime_authorizations_ready(credential, agent_id=action.agent_id, identifiers=[identifier])
        assert not await runtime_authorizations_ready(credential, agent_id=action.agent_id + 100000, identifiers=[identifier])
        assert not await runtime_authorizations_ready(credential, agent_id=action.agent_id, identifiers=[identifier, uuid4()])
        async with get_db_session() as db:
            (await db.get(Task, task_id)).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "pending"
        assert not await runtime_authorizations_ready(credential, agent_id=action.agent_id, identifiers=[identifier])
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            task.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            task_service.suspend(task, task_service.PAUSE_USER)
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "pending"
        async with get_db_session() as db:
            task_service.release(await db.get(Task, task_id), task_service.PAUSE_USER)
        # The driver observes the old waiting snapshot before the actor's next
        # authorization poll. Returning WAITING here would release the lease again
        # and strand the already answered request after its wake was consumed.
        import httpx
        from app.harnesses.openai_client import OpenAIHarnessClient
        state = {"status": "waiting_for_authorization", "authorization_requests": [str(identifier)]}
        observed = asyncio.Event()

        def runtime_snapshot(_request):
            observed.set()
            return httpx.Response(200, json=dict(state))

        async def delayed_actor_poll():
            await observed.wait()
            await asyncio.sleep(0.35)
            assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == ("approved" if approved else "denied")
            async with get_db_session():
                scope = await SqlAlchemyAgentTaskAdapter().record_scope_preflight(task_id, agent_id=action.agent_id,
                    descriptor=None, tool_name="synthetic_write", arguments={})
                assert scope.decision == "allow_and_record"
            assert (await client.post(endpoint, headers=headers, json=payload)).json()["claimed"] is approved
            assert (await client.post(endpoint, headers=headers, json=payload)).json()["claimed"] is False
            async with get_db_session():
                if approved:
                    await finish_action(identifier, receipt={"synthetic_effect": "completed"})
            state.update(status="completed", authorization_requests=[])

        runtime_client = OpenAIHarnessClient(base_url="http://runtime.example.test/v1", token="synthetic",
            run_context=credential, transport=httpx.MockTransport(runtime_snapshot))
        result, _ = await asyncio.wait_for(asyncio.gather(
            runtime_client.control_run(request.to_envelope(), runtime_run_id="synthetic-actor", start=False),
            delayed_actor_poll()), timeout=5)
        assert result.disposition == "completed" and result.success
        async with get_db_session() as db:
            if not approved:
                assert (await db.get(ActionAuthorization, identifier)).claimed_at is None
                return
            task_service.suspend(await db.get(Task, task_id), task_service.PAUSE_USER)
        assert (await client.get(f"{endpoint}/{identifier}", headers=headers)).json()["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_action", ["openai_messages", "codex", "claude_agent", "deepseek_harness"], indirect=True)
async def test_runtime_run_grant_is_scoped_renewable_and_revoked_by_assignment_changes(action, runtime_action, monkeypatch):
    from app.agent import AgentSnapshot, ResolvedExecutionTarget, AgentRunCheckpoint
    from app.agent.tests.test_driver_testkit import _request
    from app.harnesses.models import Harness, AgentHarness
    from app.services.runtime_authorization import issue_runtime_run_grant, resolve_runtime_run_grant, renew_runtime_run_grant, revoke_runtime_run_grant
    from app.services.runtime_principals import runtime_principal_port
    from app.mcp.service import rotate_system_token
    from app.mcp.service import create_token_for_agent
    from app.mcp.schemas import AgentMcpTokenCreate
    from app.harnesses.registry import get_provider
    from core.params import params_service
    provider = runtime_action.runtime
    provider_spec = get_provider(provider)
    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        assignment = await db.scalar(select(AgentHarness).where(AgentHarness.agent_id == agent.id))
        agent_id, assignment_id, harness_id = agent.id, assignment.id, assignment.harness_id
        bearer = await rotate_system_token(agent_id)
        _, visible_bearer = await create_token_for_agent(agent_id, AgentMcpTokenCreate(label="Synthetic external client"))
        principal = await runtime_principal_port().for_agent(agent_id)
    request = replace(_request(), task_id=None, driver_code="openai_messages",
        agent=AgentSnapshot(id=agent_id, code="synthetic", first_name="Synthetic", last_name="Runtime", driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code=provider, target_ref=f"harness:{assignment_id}", revision="1"))
    credential = await issue_runtime_run_grant(request)
    grant = await resolve_runtime_run_grant(credential, principal=principal)
    from httpx import ASGITransport, AsyncClient
    from main import app
    headers = {"Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": credential}
    endpoint = "/api/services/runtime-authorizations"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 401
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={**headers, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 200
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={"Authorization": f"Bearer {visible_bearer}", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 200
        assert (await client.get(endpoint + "/context", headers={"Authorization": f"Bearer {bearer}"})).status_code == 401
        assert (await client.get(endpoint + "/context", headers={**headers, "Authorization": "Bearer invalid-synthetic-principal"})).status_code == 401
        assert (await client.get(endpoint + "/context", headers={**headers, "X-Galaris-Run-Context": "foreign-synthetic-context"})).status_code == 403
        assert (await client.get(endpoint + "/context", headers=headers)).json()["active"] is True
        payload = {"callback_key": "one-call", "name": "write_file", "session": "synthetic",
            "arguments": {"path": "synthetic.txt", "content": "approved"}}
        response = await client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 200 and response.json()["status"] == "pending"
        identifier = UUID(response.json()["request_id"])
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["request_id"] == str(identifier)
        assert (await client.get(endpoint + f"/{uuid4()}", headers=headers)).status_code == 404
        assert (await client.get(endpoint + f"/{identifier}", headers=headers)).json()["status"] == "pending"
        assert (await client.post(f"/api/services/action-authorizations/{identifier}/answer", headers=headers,
            json={"approved": True})).status_code in (401, 403)
        assert (await client.get("/api/services/action-authorizations/runtime-permissions", headers=headers)).status_code in (401, 403)
        assert (await client.delete(f"/api/services/action-authorizations/runtime-permissions/{uuid4()}", headers=headers)).status_code in (401, 403)
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["claimed"] is True
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["claimed"] is False
        receipt = {"request_id": str(identifier), "outcome": "completed", "receipt": {"written": True}}
        assert (await client.post(endpoint + "/receipt", headers=headers,
            json={**receipt, "request_id": str(uuid4())})).status_code == 404
        assert (await client.post(endpoint + "/receipt", headers=headers, json=receipt)).status_code == 200
        assert (await client.get(endpoint + f"/{identifier}", headers=headers)).json()["status"] == "completed"
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=replace(principal, agent_id=agent_id + 100000))
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=replace(principal, enabled=False))
    resumed = replace(request, run_id=uuid4(), attempt_id=uuid4(), resume_checkpoint=AgentRunCheckpoint(
        driver_code="openai_messages", runtime_run_id=grant.actor_key, status="waiting_for_authorization"))
    assert await renew_runtime_run_grant(credential, resumed) == credential
    from datetime import datetime, timedelta, timezone
    from app.services.authorization_models import RuntimeRunGrant
    async with get_db_session() as db:
        row = await db.get(RuntimeRunGrant, grant.id)
        original_expiry = row.expires_at
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(PermissionError, match="authority expired"):
        await renew_runtime_run_grant(credential, resumed)
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=principal)
    async with get_db_session() as db:
        row = await db.get(RuntimeRunGrant, grant.id)
        assert row.expires_at < datetime.now(timezone.utc)
        row.expires_at = original_expiry
    with pytest.raises(PermissionError):
        await renew_runtime_run_grant(credential, replace(resumed, resume_checkpoint=None))
    from app.services import runtime_authorization
    changed_configuration = AsyncMock(return_value={"terminal_signature": "changed-governed-connection"})
    monkeypatch.setitem(runtime_authorization._runtime_configurations, provider, changed_configuration)
    with pytest.raises(PermissionError, match="context changed"):
        await resolve_runtime_run_grant(credential, principal=principal)
    with pytest.raises(PermissionError, match="context changed"):
        await renew_runtime_run_grant(credential, resumed)
    monkeypatch.delitem(runtime_authorization._runtime_configurations, provider)
    if harness_id is not None:
        async with get_db_session() as db:
            (await db.get(Harness, harness_id)).enabled = False
    else:
        monkeypatch.setitem(params_service._params_cache, provider_spec.enabled_param, "false")
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=principal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get(endpoint + "/context", headers=headers)).status_code == 403
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={**headers, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 403
    if harness_id is not None:
        async with get_db_session() as db:
            (await db.get(Harness, harness_id)).enabled = True
    else:
        monkeypatch.setitem(params_service._params_cache, provider_spec.enabled_param, "true")
    async with get_db_session() as db:
        (await db.get(AgentHarness, assignment_id)).revision += 1
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=principal)
    revoked = await revoke_runtime_run_grant(resumed.run_id)
    assert revoked is not None and not revoked.active
    with pytest.raises(PermissionError, match="authority was revoked"):
        await renew_runtime_run_grant(credential, resumed)
    async with get_db_session() as db:
        await db.delete(await db.get(RuntimeRunGrant, grant.id))
    with pytest.raises(PermissionError, match="authority is missing"):
        await renew_runtime_run_grant(credential, resumed)


@pytest.mark.asyncio
async def test_user_pause_preserves_agreement_until_resume_but_amendment_invalidates_it(action):
    from app.task.models import Task, TaskStatus
    from app.task import task_service
    async with get_db_session() as db:
        task = Task(agent_id=action.agent_id, label="Synthetic authorization", objective="<p>Synthetic objective</p>", status=TaskStatus.EXEC)
        db.add(task)
        await db.flush()
        identifier = task.id
    scoped = replace(action, context_key=f"task:{identifier}")
    request_id = await pending(scoped)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, request_id)
        assert await answer_action(request_id, user_id=row.approver_user_id, approved=True)
        task = await db.get(Task, identifier)
        task_service.suspend(task, task_service.PAUSE_USER)
    assert await pending(scoped) == request_id
    async with get_db_session() as db:
        assert (await db.get(ActionAuthorization, request_id)).status == "approved"
        task = await db.get(Task, identifier)
        task_service.release(task, task_service.PAUSE_USER)
        task.objective = "<p>Changed synthetic objective</p>"
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(scoped)


@pytest.mark.asyncio
async def test_reconciler_invalidates_a_revoked_approver_and_wakes_without_dispatch(action, monkeypatch):
    from app.services.authorization_notifications import reconcile_authorizations
    import app.services.authorization_notifications as outbox
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        (await db.get(UserModel, row.approver_user_id)).is_active = False
    wake = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "wake_authorization_context", wake)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "invalidated" and row.encrypted_arguments is None and row.wake_due_at is None
    wake.assert_awaited_once_with(action.agent_id, action.context_key)


@pytest.mark.asyncio
@pytest.mark.parametrize("expiry_path", ["answer", "claim", "reconciler"])
async def test_expired_approval_releases_waiting_task_without_dispatch(action, monkeypatch, expiry_path):
    from datetime import datetime, timedelta, timezone
    from unittest.mock import Mock
    from app.task import runner, task_service
    from app.task.models import Task, TaskStatus
    from app.services.authorization_notifications import reconcile_authorizations

    async with get_db_session() as db:
        task = Task(agent_id=action.agent_id, label="Synthetic expired approval",
                    objective="<p>Review the synthetic action.</p>", status=TaskStatus.EXEC)
        db.add(task)
        await db.flush()
        task_id = task.id
    scoped = replace(action, context_key=f"task:{task_id}")
    identifier = await pending(scoped)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        approver = row.approver_user_id
        task = await db.get(Task, task_id)
        task.data = {"authorization_requests": [str(identifier)]}
        task_service.suspend(task, task_service.PAUSE_APPROVAL)
    schedule = Mock()
    monkeypatch.setattr(runner, "go_next", schedule)
    if expiry_path == "answer":
        async with get_db_session():
            assert not await answer_action(identifier, user_id=approver, approved=True)
    elif expiry_path == "claim":
        with pytest.raises(AuthorizationClosed, match="expired"):
            await claim_action(scoped)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "expired"
        assert row.claimed_at is None and row.encrypted_arguments is None
        assert row.finished_at is not None and row.wake_due_at is None
        task = await db.get(Task, task_id)
        assert not task_service.is_paused_for(task, task_service.PAUSE_APPROVAL)
        # The continuation must be schedulable without orphan recovery.
        assert task.status == TaskStatus.DISPATCH
    schedule.assert_called_once_with(task_id, fast=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancel", "timeout"])
async def test_interrupted_native_dispatch_preserves_unknown_outcome_without_replay(action, monkeypatch, interruption):
    from app.browser import mcp as browser_mcp
    from app.connection import Connection, facade as connections
    from app.services import mandatory_services, mcp_loader
    from app.services.authorization import AUTHORIZATION_META_KEY
    from app.services.contracts import ToolExecutionContext, tool_execution
    from app.services.models import Service

    async with get_db_session() as db:
        await mandatory_services.sync_integrated_service_connections(action.agent_id)
        connection = await db.scalar(select(Connection).join(Service).where(
            Connection.agent_id == action.agent_id, Service.code == "browser"))
        await connections.set_connection_function_state(connection.id, "browser_open", "ask")
    definition = next(item for item in mcp_loader.load_mcp_tools() if item.name == "browser_open")
    wrapper = mcp_loader._wrap_tool(definition, mcp_loader.McpToolContext(
        agent_id=action.agent_id, runtime="internal", resources={"authorization_context": action.context_key}))
    operation = uuid4()
    entered = asyncio.Event()

    async def stalled_executor(*_args, **_kwargs):
        entered.set()
        await asyncio.Future()

    dispatch = AsyncMock(side_effect=stalled_executor)
    monkeypatch.setattr(browser_mcp.browser_executor, "open", dispatch)

    async def invoke():
        with tool_execution(ToolExecutionContext(operation, "browser_open")):
            return await wrapper(url="https://example.test/synthetic", output="content")

    control = (await invoke()).meta[AUTHORIZATION_META_KEY]
    identifier = UUID(control["request_id"])
    dispatch.assert_not_awaited()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    if interruption == "timeout":
        # Exercise interruption after admission, not a 100 ms race against
        # permission/catalog SQL before the executor was ever reached.
        wrapper = mcp_loader._wrap_tool(replace(definition, timeout_seconds=2), mcp_loader.McpToolContext(
            agent_id=action.agent_id, runtime="internal", resources={"authorization_context": action.context_key}))
    running = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if interruption == "cancel":
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            assert (await running).is_error
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "outcome_unknown"
        assert row.finished_at is not None and row.encrypted_arguments is not None
    replay = await invoke()
    assert replay.is_error and replay.meta[AUTHORIZATION_META_KEY]["status"] == "outcome_unknown"
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_payload_is_encrypted_and_not_copied_into_secret_key_previews(action):
    from app.services.authorization import redacted_action_arguments
    from core.util import get_encryption_service
    import json
    url = "https://synthetic-user:synthetic-url-password@example.test/resource?signature=synthetic-signed-secret#synthetic-fragment"
    arguments = {"token": "synthetic-private-token", "nested": {"password": "synthetic-password"}, "url": url}
    identifier = await pending(replace(action, arguments=arguments))
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert "synthetic-private-token" not in row.preview and "synthetic-password" not in row.preview
        assert "synthetic-private-token" not in row.encrypted_arguments
        assert "https://example.test/resource" in row.preview
        for private_value in ("synthetic-user", "synthetic-url-password", "synthetic-signed-secret", "synthetic-fragment"):
            assert private_value not in row.preview
            assert private_value not in str(redacted_action_arguments(arguments))
        assert json.loads(get_encryption_service().decrypt(row.encrypted_arguments))["url"] == url


@pytest.mark.asyncio
async def test_notification_failure_stays_visible_and_retries_without_dispatch(action, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import app.services.authorization_notifications as outbox
    from app.connection import Connection
    from app.services.models import Service
    async with get_db_session() as db:
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        db.add(Connection(agent_id=action.agent_id, service_id=chat.id, active=True))
    identifier = await pending(action)
    monkeypatch.setattr(outbox, "request_user_choice", AsyncMock(side_effect=RuntimeError("Synthetic delivery failure")))
    await outbox.deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "pending" and row.claimed_at is None
        assert row.notification_failed_at is not None and row.interaction_id is None
        assert row.notification_due_at > datetime.now(timezone.utc)
        row.notification_due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    from app.messenger import request_user_choice
    monkeypatch.setattr(outbox, "request_user_choice", request_user_choice)
    await outbox.deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "pending" and row.claimed_at is None
        assert row.notification_failed_at is None and row.interaction_id is not None


@pytest.mark.asyncio
async def test_retention_preserves_unknown_evidence_and_accepts_late_authoritative_receipt(action):
    from datetime import datetime, timedelta, timezone
    from app.services.authorization_notifications import reconcile_authorizations
    unknown = await approve_and_claim(action)
    closed = await approve_and_claim(replace(action, callback_key=str(uuid4()), arguments={"command": "other synthetic command"}))
    await finish_action(unknown, outcome="outcome_unknown", receipt={"delivery": "unknown"})
    await finish_action(closed, receipt={"delivery": "confirmed"})
    async with get_db_session() as db:
        for identifier in (unknown, closed):
            (await db.get(ActionAuthorization, identifier)).finished_at = datetime.now(timezone.utc) - timedelta(days=91)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, unknown)
        assert row.status == "outcome_unknown" and row.encrypted_arguments and row.encrypted_receipt
        row = await db.get(ActionAuthorization, closed)
        assert row.status == "completed" and row.encrypted_arguments is None and row.encrypted_receipt is None and row.preview == ""
    await finish_action(unknown, outcome="completed", receipt={"external_receipt": "synthetic-proof"})
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(action)
    # A late conflicting callback cannot rewrite a reconciled terminal result.
    await finish_action(unknown, outcome="failed", receipt={"external_receipt": "conflicting-proof"})
    async with get_db_session() as db:
        assert (await db.get(ActionAuthorization, unknown)).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en-US", "fr", "zh-CN"])
@pytest.mark.parametrize("approved", [True, False])
async def test_remembered_approval_enables_only_this_connection_function_and_preserves_resume(action, monkeypatch, language, approved):
    from app.connection import Connection, facade as connections
    from app.messenger import answer_internal_interaction
    from app.messenger.models import Interaction, Message
    from app.services.authorization_notifications import deliver_authorization_notifications
    from app.services.models import Service
    from core.i18n import normalize_language, render_prompt, t
    from core.params.runtime_settings import runtime_settings
    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "fr" if language == "en-US" else "en")
    async with get_db_session() as db:
        tool = await db.scalar(select(Service).where(Service.code == "topic"))
        connection = Connection(agent_id=action.agent_id, service_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        await connections.set_connection_function_state(connection.id, "topic_create", "ask")
        action = replace(action, source="mcp", service_id=tool.id, connection_id=connection.id,
                         name="topic_create", arguments={"title": "Synthetic topic"})
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        db.add(Connection(agent_id=action.agent_id, service_id=chat.id, active=True))
        manager = await db.get(UserModel, (await db.get(Agent, action.agent_id)).user_id)
        manager.language = language
    with pytest.raises(AuthorizationRequired) as caught:
        await claim_action(action)
    identifier = caught.value.request_id
    await deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert not await answer_action(identifier, user_id=row.approver_user_id + 100000, approved=True, remember=True)
        interaction = await db.get(Interaction, row.interaction_id)
        expected = {
            "en-US": ["Allow this action", "Deny this action", "Always allow this function", "Always deny this function"],
            "fr": ["Autoriser cette action", "Refuser cette action", "Toujours autoriser cette fonction", "Toujours interdire cette fonction"],
            "zh-CN": ["允许此操作", "拒绝此操作", "始终允许此功能", "始终禁止此功能"],
        }[language]
        selected_language = normalize_language(language)
        assert interaction.title == t("permissions.title", selected_language)
        assert [option["label"] for option in interaction.options] == expected
        assert interaction.metadata_["language"] == selected_language
        assert "Synthetic topic" in interaction.body
        assert t("approval_preview.actions.topic_create", selected_language) in interaction.body
        assert "topic_create" not in interaction.body
        assert '{"title":' not in interaction.body
        assert render_prompt(t("permissions.function_scope", selected_language), function="topic_create") in interaction.body
        prompt = await db.get(Message, UUID(interaction.prompt_message_id))
        assert interaction.title in prompt.text
        assert t("messenger_interactions.choose", selected_language) in prompt.text
        assert t("messenger_interactions.reference", selected_language).replace("${reference}", interaction.reference) in prompt.text
        decision = await answer_internal_interaction(row.approver_user_id, UUID(interaction.room_id), interaction.id,
            option_id="allow_always" if approved else "deny_always")
        assert decision.selected_option_id == ("allow_always" if approved else "deny_always")
        assert decision.is_authorization and not decision.can_answer
        response = await db.scalar(select(Message).where(
            Message.remote_message_id == f"interaction:{interaction.id}:answer",
            Message.connection_id == interaction.connection_id,
        ))
        assert response.text == render_prompt(t("messenger_interactions.answer", selected_language),
            title=interaction.title, reference=interaction.reference, answer=expected[2 if approved else 3])
        assert (await connections.resolve_function(connection, "topic_create"))["effective_state"] == ("enabled" if approved else "disabled")
        assert (await connections.resolve_function(connection, "topic_update"))["effective_state"] == "ask"
    if approved:
        assert await claim_action(replace(action, continuation=caught.value.continuation)) == identifier
        await finish_action(identifier)
        assert await claim_action(replace(action, callback_key=str(uuid4()), arguments={"title": "Another synthetic topic"})) is None
        with pytest.raises(AuthorizationClosed, match="completed"):
            await claim_action(action)
    else:
        from app.services.contracts import ToolCallRejectedError
        with pytest.raises(ToolCallRejectedError, match="disabled"):
            await claim_action(replace(action, callback_key=str(uuid4()), context_key="principal:new-task"))
    async with get_db_session():
        await connections.set_connection_function_state(connection.id, "topic_create", "ask")
    await pending(replace(action, callback_key=str(uuid4())))


@pytest.mark.asyncio
async def test_runtime_approval_cannot_be_made_permanent(action):
    """An unconfigured runtime cannot acquire reusable authority (retired blanket ban)."""
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert not await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=True)
        assert row.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_function_permissions_list_only_reusable_grants_and_revoke_to_ask(action, client, approved):
    from app.connection import Connection, facade as connections
    from app.services.models import Service
    from core.authorize.models import Assignment, Role, Privilege
    from core.user import auth_service, refresh_session_service as sessions
    async with get_db_session() as db:
        tool = await db.scalar(select(Service).where(Service.code == "topic"))
        connection = Connection(agent_id=action.agent_id, service_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        await connections.set_connection_function_state(connection.id, "topic_create", "ask")
        action = replace(action, source="mcp", service_id=tool.id, connection_id=connection.id,
            name="topic_create", arguments={"title": "Synthetic topic"})
        manager = await db.get(UserModel, (await db.get(Agent, action.agent_id)).user_id)
        manager.language = "fr"
        other = UserModel(email=f"scope-{uuid4().hex}@example.test", hashed_password="synthetic")
        role = Role(code=f"permissions-{uuid4().hex}", display_name="Synthetic permission manager")
        role.privileges = list(await db.scalars(select(Privilege).where(
            Privilege.code.in_(["PERMISSION_ACCESS", "PERMISSION_DECIDE", "PERMISSION_REVOKE"]))))
        db.add_all([other, role])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in (manager, other)])
        tokens = []
        for user in (manager, other):
            refresh = await sessions.create_refresh_session(user.id)
            tokens.append(await auth_service.create_access_token_for_user(user, session_family=await sessions.family_for_token(refresh)))
    headers, other_headers = [{"Authorization": f"Bearer {token}"} for token in tokens]
    path = "/api/connections/function-permissions"
    assert (await client.get(path)).status_code == 401
    once = await pending(action)
    approvals_path = "/api/services/action-authorizations"
    listed = await client.get(approvals_path, headers=headers, params={"q": "dossier thématique", "status": "pending"})
    assert listed.status_code == 200
    assert [(item["id"], item["title"]) for item in listed.json()["items"]] == [(str(once), "Créer un dossier thématique")]
    assert (await client.get(path, headers=headers)).json()["total"] == 0
    async with get_db_session() as db:
        assert await answer_action(once, user_id=manager.id, approved=True)
    detail = (await client.get(f"{approvals_path}/{once}", headers=headers)).json()
    assert detail["remembered"] is False and detail["selected_option_id"] == "allow"
    assert (await client.get(path, headers=headers)).json()["total"] == 0
    permanent = replace(action, callback_key=str(uuid4()))
    identifier = await pending(permanent)
    async with get_db_session():
        assert await answer_action(identifier, user_id=manager.id, approved=approved, remember=True)
    detail = (await client.get(f"{approvals_path}/{identifier}", headers=headers)).json()
    assert detail["remembered"] is True and detail["selected_option_id"] == ("allow_always" if approved else "deny_always")
    result = await client.get(path, headers=headers, params={"limit": 500})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["capability_name"] == "topic_create"
    assert result.json()["items"][0]["connection_id"] == connection.id
    assert result.json()["items"][0]["allowed"] is approved
    catalog_path = f"/api/services/agents/{action.agent_id}/permissions"
    assert (await client.get(catalog_path)).status_code == 401
    assert (await client.get(catalog_path, headers=other_headers)).status_code == 404
    catalogue = (await client.get(catalog_path, headers=headers)).json()
    functions = {row["name"]: row for row in catalogue["capabilities"] if row["service_id"] == tool.id}
    assert functions["topic_create"]["effective_state"] == ("enabled" if approved else "disabled")
    assert functions["topic_update"]["effective_state"] == "ask"
    assert functions["topic_update"]["policy_source"] == "software"
    assert all(row["connection_id"] is not None for row in catalogue["connections"])
    assert "global_params" not in catalogue["connections"][0]
    if not approved:
        from app.services.contracts import ToolCallRejectedError
        with pytest.raises(ToolCallRejectedError, match="disabled"):
            await claim_action(replace(permanent, callback_key=str(uuid4())))
    assert (await client.get(path, headers=other_headers)).json()["total"] == 0
    revoke = f"/api/connections/{connection.id}/functions/topic_create"
    assert (await client.put(revoke, headers=other_headers, json={"state": "ask"})).status_code == 404
    assert (await client.put(revoke, headers=headers, json={"state": "ask"})).status_code == 200
    assert (await client.get(path, headers=headers)).json()["total"] == 0
    async with get_db_session():
        assert (await connections.resolve_function(connection, "topic_create"))["effective_state"] == "ask"
    async with get_db_session() as db:
        (await db.get(Connection, connection.id)).active = False
        # Runtime consumers keep their active-only default; only the dashboard
        # explicitly inventories inactive connections for human reactivation.
        assert not any(row.id == connection.id for row in await connections.get_connections_by_agent(action.agent_id))
    inactive = (await client.get(catalog_path, headers=headers)).json()
    assert any(row["service_id"] == tool.id and not row["active"] for row in inactive["connections"])
    assert all(row["effective_state"] == "disabled" for row in inactive["capabilities"] if row["service_id"] == tool.id)
    async with get_db_session() as db:
        (await db.get(Connection, connection.id)).active = True
    await pending(replace(permanent, callback_key=str(uuid4())))


@pytest_asyncio.fixture(params=[provider.code for provider in all_providers()])
async def runtime_action(action, request, monkeypatch):
    from app.harnesses.models import AgentHarness, Harness
    from app.harnesses.registry import get_provider
    from core.params import params_service
    runtime = request.param
    provider = get_provider(runtime)
    if provider.enabled_param is not None:
        await params_service.get_all()
        monkeypatch.setitem(params_service._params_cache, provider.enabled_param, "true")
    async with get_db_session() as db:
        harness_id = None
        if runtime == "openai_messages":
            harness = Harness(name="Synthetic consent harness", provider_code=runtime,
                driver_code=provider.driver_code, enabled=True,
                base_url="http://synthetic-harness.example.test/v1", model="synthetic",
                capabilities=["execute", "stream"])
            db.add(harness)
            await db.flush()
            harness_id = harness.id
            (await db.get(Agent, action.agent_id)).task_harness_id = harness_id
        db.add(AgentHarness(agent_id=action.agent_id, provider_code=runtime, harness_id=harness_id, lifecycle_status="ready",
            runtime_base_url="http://synthetic-harness.example.test/v1", runtime_model="synthetic"))
    return replace(action, runtime=runtime, name="write_file")


@pytest.mark.asyncio
@pytest.mark.parametrize(("runtime_action", "paths"), [
    ("codex", ("/api/llm/openai/responses", "/api/llm/openai/responses/compact")),
    ("claude_agent", ("/api/llm/anthropic/v1/messages", "/api/llm/openai/chat/completions")),
    ("deepseek_harness", ("/api/llm/openai/chat/completions", "/api/llm/openai/chat/completions")),
], indirect=["runtime_action"])
async def test_parallel_runtime_llm_calls_keep_their_task_and_attempt(
    runtime_action, paths, committed_database, monkeypatch,
):
    from datetime import datetime, timedelta, timezone

    from fastapi.responses import JSONResponse
    from httpx import ASGITransport, AsyncClient

    from app.agent import AgentSnapshot, ResolvedExecutionTarget, max_parallel_tasks_for_agent
    from app.agent.tests.test_driver_testkit import _request
    from app.harnesses.models import AgentHarness
    from app.llm import anthropic_router, call_router
    from app.mcp.service import rotate_system_token
    from app.services.facade import issue_runtime_run_grant, revoke_runtime_run_grant
    from app.task.models import Task, TaskAttempt, TaskStatus
    from core.database import middleware as database_middleware
    from main import app

    monkeypatch.setattr(database_middleware, "AsyncSessionLocal", committed_database)
    agent_id = runtime_action.agent_id
    async with get_db_session() as db:
        assignment = await db.scalar(select(AgentHarness).where(AgentHarness.agent_id == agent_id))
        assert assignment is not None
        assert await max_parallel_tasks_for_agent(agent_id) == 1
        assignment.provider_metadata = {"run_scoped_llm": True}
        target = ResolvedExecutionTarget(provider_code=runtime_action.runtime,
            target_ref=f"harness:{assignment.id}", revision=str(assignment.revision))
        bearer = await rotate_system_token(agent_id)
        snapshot = AgentSnapshot(id=agent_id, code="synthetic", first_name="Synthetic",
            last_name="Agent", driver_code="openai_messages")
        requests = []
        for index in range(5):
            label = f"Concurrent task {index}"
            task = Task(agent_id=agent_id, label=label, objective=f"<p>{label}</p>",
                status=TaskStatus.EXEC, lease_token=uuid4(),
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
            db.add(task)
            await db.flush()
            attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC",
                worker_id="synthetic", lease_token=task.lease_token)
            db.add(attempt)
            await db.flush()
            requests.append(replace(_request(), task_id=task.id, attempt_id=attempt.id, run_id=uuid4(),
                agent=snapshot, target=target, driver_code="openai_messages"))
        assert await max_parallel_tasks_for_agent(agent_id) is None

    credentials = [await issue_runtime_run_grant(item) for item in requests]
    arrived = asyncio.Event()
    observed = []

    async def provider(_payload, **options):
        observed.append((options["task_id"], options["agent_run_id"], options["task_attempt_id"]))
        if len(observed) >= len(requests):
            arrived.set()
        await asyncio.wait_for(arrived.wait(), timeout=5)
        return JSONResponse({"choices": [{"message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(call_router, "proxy_chat_completion", provider)
    monkeypatch.setattr(call_router, "proxy_responses", provider)
    monkeypatch.setattr(anthropic_router, "call_proxy", provider)
    body = {"model": "synthetic", "max_tokens": 10, "messages": [{"role": "user", "content": "Synthetic"}]}
    headers = {"Authorization": f"Bearer {bearer}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        async def run(index, **extra_headers):
            return await client.post(paths[index % len(paths)], json=body, headers={
                **headers, "X-Galaris-Run-Context": credentials[index], **extra_headers,
            })

        missing = await client.post(paths[0], json=body, headers=headers)
        assert missing.status_code == 401, missing.text
        conflict = await run(0, **{"X-Galaris-Task-Id": str(requests[1].task_id)})
        assert conflict.status_code == 403, conflict.text
        assert not observed
        responses = await asyncio.gather(*(run(index) for index in range(len(requests))))
        assert all(response.status_code == 200 for response in responses)
        assert set(observed) == {(item.task_id, item.run_id, item.attempt_id) for item in requests}

        await revoke_runtime_run_grant(requests[0].run_id)
        assert (await run(0)).status_code == 403
        assert (await run(1)).status_code == 200
        assert len(observed) == len(requests) + 1


@pytest.mark.asyncio
async def test_internal_runtime_is_excluded_from_external_action_type_consent(runtime_action):
    from app.services.authorization import can_remember_action
    from app.services.runtime_permissions import configuration_fingerprint
    internal = replace(runtime_action, runtime="internal")
    identifier = await pending(internal)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await configuration_fingerprint(internal.agent_id, "internal") is None
        assert not await can_remember_action(row)
        assert not await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=True)
        assert row.status == "pending"


@pytest.mark.asyncio
async def test_runtime_type_consent_survives_new_tasks_and_is_revocable(runtime_action):
    from app.services.authorization import can_remember_action
    from app.services.authorization_notifications import deliver_authorization_notifications
    from app.services.authorization_presentation import runtime_label
    from app.services.runtime_permissions import revoke_permission
    from app.connection import Connection
    from app.messenger import answer_internal_interaction
    from app.messenger.models import Interaction
    from app.services.models import Service
    async with get_db_session() as db:
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        db.add(Connection(agent_id=runtime_action.agent_id, service_id=chat.id, active=True))
    identifier = await pending(runtime_action)
    await deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        manager_id = row.approver_user_id
        assert await can_remember_action(row)
        assert not await answer_action(identifier, user_id=manager_id + 100000, approved=True, remember=True)
        interaction = await db.get(Interaction, row.interaction_id)
        assert "allow_always" in [option["id"] for option in interaction.options]
        assert runtime_label(runtime_action.runtime, "en") in interaction.body
        assert runtime_action.arguments["command"] in interaction.body
        await answer_internal_interaction(manager_id, UUID(interaction.room_id), interaction.id, option_id="allow_always")
        await db.refresh(row)
        permission_id = row.runtime_permission_id
        assert permission_id is not None
    assert await claim_action(runtime_action) == identifier
    await finish_action(identifier)
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(runtime_action)
    # New callbacks, arguments, sessions and execution contexts still produce distinct one-use claims.
    later = replace(runtime_action, callback_key=str(uuid4()), context_key="principal:another-synthetic-task",
        arguments={"path": "another.txt", "content": "different synthetic content"},
        configuration={"session": "another-session"})
    auto = await claim_action(later)
    assert auto is not None
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, auto)
        assert row.status == "executing" and row.decision_source == "runtime_policy"
        assert row.runtime_permission_id == permission_id
    await finish_action(auto)
    await pending(replace(later, callback_key=str(uuid4()), name="execute_command"))
    await pending(replace(later, callback_key=str(uuid4()), runtime="other-runtime"))
    await pending(replace(later, callback_key=str(uuid4()), source="domain"))
    await pending(replace(later, callback_key=str(uuid4()), kind="resource"))
    async with get_db_session():
        assert not await revoke_permission(permission_id, user_id=manager_id + 100000)
        assert await revoke_permission(permission_id, user_id=manager_id)
    await pending(replace(later, callback_key=str(uuid4())))


@pytest.mark.asyncio
async def test_runtime_permanent_denial_blocks_new_and_pending_actions_until_removed(runtime_action, monkeypatch):
    from app.services.contracts import ToolCallRejectedError
    from app.services.runtime_permissions import list_permissions, revoke_permission
    from app.agent import AgentManagementScope
    from app.connection import Connection
    from app.messenger.models import Interaction
    from app.services.models import Service
    from app.services.authorization_notifications import deliver_authorization_notifications
    async with get_db_session() as db:
        chat = await db.scalar(select(Service).where(Service.code == "chat"))
        db.add(Connection(agent_id=runtime_action.agent_id, service_id=chat.id, active=True))
    first = await pending(runtime_action)
    older = replace(runtime_action, callback_key=str(uuid4()), arguments={"path": "older.txt"})
    older_id = await pending(older)
    approved_call = replace(runtime_action, callback_key=str(uuid4()), arguments={"path": "approved.txt"})
    approved_id = await pending(approved_call)
    await deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, first)
        manager = row.approver_user_id
        assert await answer_action(approved_id, user_id=manager, approved=True)
        # A pending Chat question from before this feature has no permanent-denial option.
        interaction = await db.get(Interaction, row.interaction_id)
        interaction.options = [option for option in interaction.options if option["id"] != "deny_always"]
        await db.commit()
        assert await answer_action(first, user_id=manager, approved=False, remember=True)
        await db.refresh(interaction)
        assert interaction.status == "RESOLVED" and interaction.resolution["option_id"] == "deny_always"
        permission_id = row.runtime_permission_id
        assert permission_id is not None and row.status == "denied" and row.encrypted_arguments is None
    for call in [older, approved_call, replace(runtime_action, callback_key=str(uuid4()),
            context_key="principal:another-synthetic-task", arguments={"path": "later.txt"})]:
        with pytest.raises(ToolCallRejectedError, match="disabled"):
            await claim_action(call)
    async with get_db_session() as db:
        # The old question cannot turn an effective permanent denial into an approval.
        assert not await answer_action(older_id, user_id=manager, approved=True, remember=True)
        assert not await answer_action(older_id, user_id=manager, approved=True)
    from app.services.authorization_notifications import reconcile_authorizations
    woken = set()
    async def wake(agent_id, context_key):
        woken.add((agent_id, context_key))
        return True
    # Replace the scheduling boundary, preserving real policy resolution and SQL transitions.
    monkeypatch.setattr("app.services.authorization_notifications.wake_authorization_context", wake)
    await reconcile_authorizations()
    async with get_db_session() as db:
        # Reconciliation closes and wakes other waiters rather than leaving them suspended.
        for waiting_id in (older_id, approved_id):
            waiting = await db.get(ActionAuthorization, waiting_id)
            assert waiting.status == "invalidated" and waiting.encrypted_arguments is None
            assert (waiting.agent_id, waiting.context_key) in woken
        scope = AgentManagementScope(user_id=manager, agent_ids=frozenset({runtime_action.agent_id}))
        page = await list_permissions(scope, agent_id=runtime_action.agent_id, offset=0, limit=50)
        assert page["total"] == 1
        assert page["items"][0]["allowed"] is False and page["items"][0]["active"]
        assert not await revoke_permission(permission_id, user_id=manager + 100000)
        assert await revoke_permission(permission_id, user_id=manager)
        assert (await db.get(ActionAuthorization, first)).status == "denied"
    await pending(replace(runtime_action, callback_key=str(uuid4()), context_key="principal:after-removal"))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["configuration", "assignment", "manager", "policy"])
@pytest.mark.parametrize("approved", [True, False])
async def test_runtime_consent_rejects_changes_before_review_and_before_reuse(runtime_action, monkeypatch, change, approved):
    from app.harnesses.models import AgentHarness
    from app.services.authorization import can_remember_action
    from app.services import runtime_authorization
    config = {"terminal_signature": "synthetic-original"}
    async def snapshot(agent_id):
        return dict(config)
    monkeypatch.setitem(runtime_authorization._runtime_configurations, runtime_action.runtime, snapshot)
    first = await pending(runtime_action)
    second_action = replace(runtime_action, callback_key=str(uuid4()))
    second = await pending(second_action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, first)
        assert await answer_action(first, user_id=row.approver_user_id, approved=approved, remember=True)
    if change == "configuration":
        config["terminal_signature"] = "synthetic-changed"
    else:
        async with get_db_session() as db:
            agent = await db.get(Agent, runtime_action.agent_id)
            if change == "assignment":
                assignment = await db.scalar(select(AgentHarness).where(AgentHarness.agent_id == agent.id))
                assignment.revision += 1
            elif change == "policy":
                agent.authorization_version += 1
            else:
                user = UserModel(email=f"new-manager-{uuid4().hex}@example.test", hashed_password="synthetic")
                db.add(user)
                await db.flush()
                agent.user_id = user.id
                agent.authorization_version += 1
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, second)
        assert not await can_remember_action(row)
        assert not await answer_action(second, user_id=row.approver_user_id, approved=True, remember=True)
    with pytest.raises(AuthorizationClosed, match="invalidated" if approved else "denied"):
        await claim_action(runtime_action)
    # A new task asks again; the exact denied operation in the old task stays closed.
    await pending(replace(runtime_action, callback_key=str(uuid4()), context_key="principal:changed-harness-task"))


@pytest.mark.asyncio
async def test_human_runtime_permission_api_revokes_unconsumed_consent_and_preserves_other_questions(runtime_action, client):
    from core.authorize.models import Assignment, Role
    from core.user import auth_service, refresh_session_service as sessions
    from app.services.authorization_models import RuntimeActionPermission
    identifier = await pending(runtime_action)
    already_pending = replace(runtime_action, callback_key=str(uuid4()), arguments={"path": "other.txt"})
    second = await pending(already_pending)
    async with get_db_session() as db:
        agent = await db.get(Agent, runtime_action.agent_id)
        manager = await db.get(UserModel, agent.user_id)
        other = UserModel(email=f"other-reviewer-{uuid4().hex}@example.test", hashed_password="synthetic")
        db.add(other)
        await db.flush()
        admin = await db.scalar(select(Role).where(Role.code == "admin"))
        db.add_all([Assignment(user_id=user.id, role_id=admin.id, is_default=True) for user in (manager, other)])
        await db.commit()
        tokens = []
        for user in (manager, other):
            refresh = await sessions.create_refresh_session(user.id)
            tokens.append(await auth_service.create_access_token_for_user(user, session_family=await sessions.family_for_token(refresh)))
    headers, other_headers = [{"Authorization": f"Bearer {token}"} for token in tokens]
    review_path = f"/api/services/action-authorizations/{identifier}"
    from datetime import datetime, timedelta, timezone
    expired = await pending(replace(runtime_action, callback_key=str(uuid4())))
    async with get_db_session() as db:
        (await db.get(ActionAuthorization, expired)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    pending_path = "/api/services/action-authorizations"
    requests = await client.get(pending_path, headers=headers,
        params={"status": "pending", "agent_id": runtime_action.agent_id, "limit": 500})
    assert {item["id"] for item in requests.json()["items"]} == {str(identifier), str(second)}
    review = await client.get(review_path, headers=headers)
    assert review.status_code == 200
    assert review.json()["remembered"] is False
    assert review.json()["presentation"]["fields"]
    other_review = await client.get(review_path, headers=other_headers)
    assert other_review.status_code == 200
    assert "presentation" not in other_review.json() and "arguments" not in other_review.json()
    answer = await client.post(f"/api/services/action-authorizations/{identifier}/answer", headers=headers,
        json={"approved": True, "remember": True})
    assert answer.status_code == 200
    assert (await client.get(review_path, headers=headers)).json()["remembered"] is True
    requests = await client.get(pending_path, headers=headers,
        params={"status": "pending", "agent_id": runtime_action.agent_id})
    assert [item["id"] for item in requests.json()["items"]] == [str(second)]
    with pytest.raises(AuthorizationRequired) as waiting:
        await claim_action(already_pending)
    assert waiting.value.request_id == second
    path = "/api/services/action-authorizations/runtime-permissions"
    response = await client.get(path, headers=headers, params={"agent_id": runtime_action.agent_id, "limit": 500})
    assert response.status_code == 200
    rows = response.json()["items"]
    assert response.json()["total"] == 1
    assert rows[0]["runtime"] == runtime_action.runtime and rows[0]["capability_name"] == runtime_action.name
    assert rows[0]["active"] and rows[0]["can_revoke"]
    permission_id = rows[0]["id"]
    assert (await client.delete(f"{path}/{permission_id}", headers=other_headers)).status_code == 404
    assert (await client.delete(f"{path}/{permission_id}", headers=headers)).status_code == 200
    assert (await client.delete(f"{path}/{permission_id}", headers=headers)).status_code == 200
    assert (await client.get(path, headers=headers)).json()["items"] == []
    async with get_db_session() as db:
        assert (await db.get(RuntimeActionPermission, UUID(permission_id))).revoked_at is not None
        assert (await db.get(ActionAuthorization, identifier)).status == "invalidated"
        assert (await db.get(ActionAuthorization, second)).status == "pending"
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(runtime_action)
    await pending(replace(runtime_action, callback_key=str(uuid4())))
    policies = "/api/services/action-authorizations/runtime-policies"
    observed = (await client.get(policies, headers=headers, params={"agent_id": runtime_action.agent_id})).json()
    assert len(observed) == 1 and observed[0]["allowed"] is None and not observed[0]["remembered"]
    update = {"agent_id": runtime_action.agent_id, "runtime": runtime_action.runtime,
              "capability_name": runtime_action.name, "allowed": False}
    assert (await client.put(policies, headers=other_headers, json=update)).status_code == 409
    assert (await client.put(policies, headers=headers, json={**update, "capability_name": "unobserved_action"})).status_code == 409
    assert (await client.put(policies, headers=headers, json=update)).status_code == 200
    denied = (await client.get(policies, headers=headers, params={"agent_id": runtime_action.agent_id})).json()
    assert denied[0]["allowed"] is False and denied[0]["active"]
    from app.services.contracts import ToolCallRejectedError
    with pytest.raises(ToolCallRejectedError, match="disabled"):
        await claim_action(replace(runtime_action, callback_key=str(uuid4()), context_key="principal:dashboard-denied"))
    assert (await client.put(policies, headers=headers, json={**update, "allowed": True})).status_code == 200
    claim = await claim_action(replace(runtime_action, callback_key=str(uuid4()), context_key="principal:dashboard-allowed"))
    assert claim is not None
    await finish_action(claim)
    assert (await client.put(policies, headers=headers, json={**update, "allowed": None})).status_code == 200
    await pending(replace(runtime_action, callback_key=str(uuid4()), context_key="principal:dashboard-ask"))


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_before_question", [False, True])
async def test_permanent_function_choice_rejects_a_changed_remote_configuration(action, changed_before_question):
    from app.connection import Connection
    from app.connection import facade as connections
    from app.services import ServiceModel
    from app.services.authorization import can_remember_action, tool_authorization_configuration
    from app.services.service import get_service_by_id
    async with get_db_session() as db:
        tool = ServiceModel(code=f"remote-{uuid4().hex}", label="Synthetic remote service",
            mcp_config={"type": "http", "url": "https://original.example.test/mcp"})
        db.add(tool)
        await db.flush()
        connection = Connection(agent_id=action.agent_id, service_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        service_id, connection_id = tool.id, connection.id
        await connections.set_connection_function_state(connection_id, "publish", "ask")
    async with get_db_session() as db:
        configuration = {"tool": tool_authorization_configuration(await get_service_by_id(service_id)), "params": {}}
        if changed_before_question:
            (await db.get(ServiceModel, service_id)).mcp_config = {"type": "http", "url": "https://changed.example.test/mcp"}
    action = replace(action, source="mcp", service_id=service_id, connection_id=connection_id,
                     name="publish", configuration=configuration)
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await can_remember_action(row) is (not changed_before_question)
        if not changed_before_question:
            (await db.get(ServiceModel, service_id)).mcp_config = {"type": "http", "url": "https://changed.example.test/mcp"}
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert not await can_remember_action(row)
        assert not await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=True)
        assert (await connections.resolve_function(await connections.get_connection(connection_id), "publish"))["effective_state"] == "ask"
        assert row.status == "pending"


@pytest.mark.asyncio
async def test_pending_is_durable_and_approval_dispatches_exactly_once(action):
    identifiers = await asyncio.gather(pending(action), pending(action))
    assert identifiers[0] == identifiers[1]
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifiers[0])
        assert row.status == "pending"
        assert "echo synthetic" not in row.encrypted_arguments
        assert not await answer_action(row.id, user_id=row.approver_user_id + 100000, approved=True)
        assert await answer_action(row.id, user_id=row.approver_user_id, approved=True)
    dispatched = []

    async def dispatch():
        try:
            receipt = await claim_action(action)
        except AuthorizationClosed:
            return
        dispatched.append("effect")
        await finish_action(receipt, receipt={"delivered": True})

    await asyncio.gather(dispatch(), dispatch())
    assert dispatched == ["effect"]
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(action)


@pytest.mark.asyncio
async def test_approval_cannot_execute_changed_arguments(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(replace(action, arguments={"command": "different"}))
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(action)


@pytest.mark.asyncio
async def test_each_new_action_requires_explicit_approval_and_effects_are_audited(action):
    identifier = await pending(action)
    assert await pending(action) == identifier
    receipt = await approve_and_claim(replace(action, callback_key=str(uuid4())))
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, receipt)
        assert row.status == "executing"
        assert row.decision_source == "human"
    assert await pending(action) == identifier
    await finish_action(receipt, outcome="outcome_unknown")
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, receipt)
        assert row.encrypted_arguments is not None


@pytest.mark.asyncio
async def test_refusal_and_unknown_outcome_never_replay(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=False)
    with pytest.raises(AuthorizationClosed, match="denied"):
        await claim_action(action)
    unknown = replace(action, callback_key=str(uuid4()), arguments={"command": "another synthetic command"})
    receipt = await approve_and_claim(unknown)
    await finish_action(receipt, outcome="outcome_unknown")
    with pytest.raises(AuthorizationClosed, match="outcome_unknown"):
        await claim_action(unknown)


@pytest.mark.asyncio
@pytest.mark.parametrize("reconcile", [False, True])
async def test_retired_automatic_approval_cannot_dispatch(action, reconcile):
    from datetime import datetime, timezone
    from app.services.authorization_notifications import reconcile_authorizations
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        row.status = "approved"
        row.decision_source = "agent_yolo"
        row.decided_at = datetime.now(timezone.utc)
    if reconcile:
        await reconcile_authorizations()
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(action)


@pytest.mark.asyncio
async def test_opaque_continuation_survives_new_callback_but_is_bound_to_identity_and_arguments(action):
    with pytest.raises(AuthorizationRequired) as caught:
        await claim_action(action)
    identifier, continuation = caught.value.request_id, caught.value.continuation
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    from app.services.contracts import ToolCallRejectedError
    with pytest.raises(ToolCallRejectedError, match="continuation is invalid"):
        await claim_action(replace(action, arguments={"command": "changed"}, continuation=continuation))
    assert await claim_action(replace(action, callback_key=str(uuid4()), continuation=continuation)) == identifier
    await finish_action(identifier)
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(replace(action, callback_key=str(uuid4()), continuation=continuation))


def test_every_declared_native_function_has_explicit_approval_metadata():
    from app.services.mcp_loader import load_mcp_tools
    definitions = load_mcp_tools()
    assert len(definitions) > 100
    unclassified = [
        definition.name for definition in definitions
        if not definition.approval_reason.strip()
        or definition.approval_reason == "Unclassified native action"
    ]
    assert not unclassified, f"Native functions need explicit approval metadata: {unclassified}"
    assert {definition.name: definition.approval for definition in definitions}["file_create"] == "ask"


def test_native_function_software_defaults():
    from app.services.legacy_names import canonical_service_call
    from app.services.mcp_loader import load_mcp_tools

    defaults = {definition.name: definition.default_state for definition in load_mcp_tools()}
    enabled = {
        "calendar_create_event", "messenger_room_send_file", "messenger_room_send_message",
        "messenger_send_file_to_user", "messenger_send_message_to_user", "voice_call_list",
        "voice_call_start", "voice_call_stop", "contact_create", "documentation_catalog",
        "documentation_search", "memory_forget", "memory_remember", "memory_summarize",
        "audio_read", "audio_transcribe", "image_read", "video_read", "file_to_pdf",
        "topic_create", "task_pause", "task_resume", "task_update", "task_cancel",
    }
    ask = {"chat_round_get", "chat_screenshot", "voice_turn_get", "browser_navigate", "browser_open", "task_run"}
    assert {name: defaults[name] for name in enabled | ask} == dict.fromkeys(enabled, "enabled") | dict.fromkeys(ask, "ask")
    assert canonical_service_call("task_stop", {})[0] == "task_cancel"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("remember", [False, True])
@pytest.mark.parametrize("internal_harness", [False, True])
async def test_file_copy_approval_is_bound_to_the_observed_source_bytes(action, tmp_path, monkeypatch, changed, remember, internal_harness):
    from fastmcp import Client
    from app.file_share import resource_service
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.connection import Connection
    from app.services import ServiceModel, build_agent_galaris_fastmcp
    transport = TemporaryFileTransport(tmp_path / "console")
    source = transport.resolve_path("source.txt")
    source.write_text("approved source")
    async def resolve(_context):
        return transport
    monkeypatch.setattr(resource_service, "_console_transport", resolve)
    async with get_db_session() as db:
        tool = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
        db.add(Connection(agent_id=action.agent_id, service_id=tool.id, active=True))
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(action.agent_id, allowed_tool_names={"file_copy"},
            resources={"console": object()})
    arguments = {"source": "console://source.txt", "destination": "console://destination.txt", "unused": "private"}
    operation = str(uuid4())
    meta = {"galaris.execution/v1": {"operation_id": operation}}
    if internal_harness:
        from types import SimpleNamespace
        from pydantic_ai import ApprovalRequired
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from app.agent.contracts import AgentRunRequest, AgentRunControl, AgentSnapshot, ResolvedModel
        from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
        from app.harness.mcp_toolset import ExecutionEvidenceClient

        save = AsyncMock()
        request = AgentRunRequest(run_id=uuid4(), task_id=None,
            agent=AgentSnapshot(id=action.agent_id, code="synthetic", first_name="Synthetic",
                last_name="Agent", driver_code="internal"),
            driver_code="internal", effort="standard", objective="Copy an approved resource",
            model=ResolvedModel(id=1, code="synthetic", model_name="synthetic/model", label="Synthetic",
                requested_effort="standard"), control=AgentRunControl(save_checkpoint=save))
        journal = HarnessRunCheckpoint(request)
        history = [ModelResponse(parts=[ToolCallPart("file_copy", arguments, "copy-call")])]
        context = SimpleNamespace(messages=history, tool_call_id="copy-call")
        async with ExecutionEvidenceClient(server) as client:
            async def dispatch(name, values, _context, _tool):
                return (await client.call_tool(name, values)).data

            boundary = SimpleNamespace(call_tool=AsyncMock(side_effect=dispatch))
            wrapped = wrap_toolsets([boundary], journal)[0]
            with pytest.raises(ApprovalRequired):
                await wrapped.call_tool("file_copy", arguments, context, None)
            checkpoint = save.await_args.args[0]
            identifier = UUID(checkpoint.data["effects"][0]["authorization_request_id"])
            continuation = checkpoint.data["effects"][0]["authorization_continuation"]
            assert continuation and continuation not in json.dumps(checkpoint.data["message_history"])
            if changed:
                source.write_text("changed source")
            async with get_db_session() as db:
                row = await db.get(ActionAuthorization, identifier)
                assert await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=remember)
            resumed = HarnessRunCheckpoint(replace(request, resume_checkpoint=checkpoint))
            await resumed.prepare_resume()
            approvals = await resumed.deferred_results()
            assert approvals is not None and approvals.approvals["copy-call"] is True
            context.messages = resumed.restored_messages()
            result = await wrap_toolsets([boundary], resumed)[0].call_tool("file_copy", arguments, context, None)
            destination = transport.resolve_path("destination.txt")
            assert destination.exists() is (not changed)
            if changed:
                assert result["authorization_status"] == "invalidated"
            else:
                assert destination.read_text() == "approved source"
            assert "authorization_continuation" not in save.await_args.args[0].data["effects"][0]
            # A later recovery must reuse the receipt, never dispatch the copy twice.
            recovered = HarnessRunCheckpoint(replace(request, resume_checkpoint=save.await_args.args[0]))
            await recovered.prepare_resume()
            await wrap_toolsets([boundary], recovered)[0].call_tool("file_copy", arguments, context, None)
            assert boundary.call_tool.await_count == 2
        return
    async with Client(server) as client:
        result = await client.call_tool("file_copy", arguments, meta=meta, raise_on_error=False)
        control = result.meta["galaris.authorization/v1"]
        assert control["disposition"] == "authorization_required"
        identifier = UUID(control["request_id"])
        if changed:
            source.write_text("changed source")
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=remember)
        meta["galaris.authorization/v1"] = {"continuation": control["continuation"]}
        # Approval remains bound to the effective call, not discarded arguments.
        arguments["unused"] = "different-private-value"
        result = await client.call_tool("file_copy", arguments, meta=meta, raise_on_error=False)
        destination = transport.resolve_path("destination.txt")
        assert destination.exists() is (not changed)
        if changed:
            assert result.is_error and result.meta["galaris.authorization/v1"]["status"] == "invalidated"
        else:
            assert not result.is_error and destination.read_text() == "approved source"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "ask", "disabled"])
async def test_realtime_hangup_uses_conversation_function_policy(action, mode):
    import json
    from app.connection import facade as connections
    from app.services.models import Service
    from app.voice.realtime_tools import realtime_tools, execute_realtime_tool
    async with get_db_session() as db:
        tool = await db.scalar(select(Service).where(Service.code == "chat"))
        connection = await connections.get_or_create_connection(tool.id, action.agent_id, active=True)
        await connections.set_connection_function_state(connection.id, "voice_call_stop", mode or "enabled")
        await db.commit()
    hangup = asyncio.Event()
    tools = realtime_tools(agent_id=action.agent_id, conversation_id="synthetic-room", transport_kind="synthetic",
        language="en", hangup_requested=hangup)
    operation = uuid4()
    first = json.loads(await execute_realtime_tool(tools, name="voice_call_stop", arguments="{}", operation_id=operation))
    if mode != "ask":
        assert hangup.is_set() is (mode is None)
        assert first["ok"] is (mode is None)
        assert "authorization_required" not in first
        async with get_db_session() as db:
            assert await db.scalar(select(ActionAuthorization).where(
                ActionAuthorization.agent_id == action.agent_id,
                ActionAuthorization.capability_name == "voice_call_stop",
            )) is None
        return
    assert not hangup.is_set()
    identifier = UUID(first["authorization_required"])
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "pending" and row.capability_name == "voice_call_stop"
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    result = json.loads(await execute_realtime_tool(tools, name="voice_call_stop", arguments="{}", operation_id=operation))
    assert result["ok"] is True and hangup.is_set()
    replay = json.loads(await execute_realtime_tool(tools, name="voice_call_stop", arguments="{}", operation_id=operation))
    assert replay["authorization_status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_pydantic_deferred_call_resumes_the_same_operation_without_a_new_model_decision(action, approved):
    """Pending human approval stops inference, including a premature runtime resume."""
    from fastmcp import FastMCP
    from pydantic_ai import Agent as PydanticAgent, DeferredToolRequests
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.mcp import MCPToolset
    from fastmcp.tools import ToolResult
    from app.agent import AgentSnapshot
    from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
    from app.harness.mcp_toolset import ExecutionEvidenceClient
    from app.harness.runtime import Agent as HarnessAgent
    from app.harness.tests.test_checkpoint import _request
    from app.services.authorization import AUTHORIZATION_META_KEY
    from app.services.contracts import current_tool_execution
    from app.services.execution_evidence import ExecutionEvidenceMiddleware

    server = FastMCP("synthetic-deferred-effect")
    server.add_middleware(ExecutionEvidenceMiddleware({"synthetic_write"}))
    effects = []
    dispatch_attempts = []
    model_calls = 0

    @server.tool()
    async def synthetic_write(content: str) -> ToolResult:
        dispatch_attempts.append(content)
        operation = current_tool_execution()
        assert operation is not None
        try:
            permit = await claim_action(replace(action, callback_key=str(operation.operation_id), arguments={"content": content}))
        except AuthorizationRequired as exc:
            return ToolResult(content=str(exc), is_error=True, meta={AUTHORIZATION_META_KEY: {
                "disposition": "authorization_required", "status": "pending", "request_id": str(exc.request_id)}})
        effects.append(content)
        await finish_action(permit, receipt={"written": content})
        return ToolResult(content="written")

    def model(messages, _info):
        nonlocal model_calls
        model_calls += 1
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("synthetic_write", {"content": "approved bytes"}, tool_call_id="synthetic-call")])
        return ModelResponse(parts=[TextPart("The action has been resolved")])

    save = AsyncMock()
    request = replace(_request(save_checkpoint=save), agent=AgentSnapshot(
        id=action.agent_id, code="synthetic", first_name="Synthetic", last_name="Agent", driver_code="internal"))
    journal = HarnessRunCheckpoint(request)
    toolset = MCPToolset(ExecutionEvidenceClient(server))
    agent = PydanticAgent(FunctionModel(model), output_type=[str, DeferredToolRequests], retries=0,
        toolsets=wrap_toolsets([toolset], journal))
    result = await agent.run("Write the synthetic content")
    assert isinstance(result.output, DeferredToolRequests)
    assert effects == []
    assert model_calls == 1
    assert dispatch_attempts == ["approved bytes"]
    await journal.interrupted(result.all_messages())
    snapshot = save.await_args.args[0]
    identifier = UUID(str(snapshot.data["effects"][0]["authorization_request_id"]))
    # A premature scheduler wake must stop before consulting the model or MCP again.
    waiting = HarnessRunCheckpoint(replace(request, resume_checkpoint=snapshot))
    from types import SimpleNamespace
    runtime = HarnessAgent(SimpleNamespace(), checkpoint=waiting)
    runtime._agent = agent
    assert [message async for message in runtime.run("Continue the work")] == []
    assert runtime.authorization_requests == [identifier]
    assert runtime.error == ""
    assert effects == []
    assert model_calls == 1
    assert dispatch_attempts == ["approved bytes"]
    async with get_db_session() as db:
        assert list(await db.scalars(select(ActionAuthorization.id).where(
            ActionAuthorization.agent_id == action.agent_id))) == [identifier]
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=approved)
    resumed = HarnessRunCheckpoint(replace(request, resume_checkpoint=snapshot))
    await resumed.prepare_resume()
    history = resumed.restored_messages()
    deferred = await resumed.deferred_results()
    continued = PydanticAgent(FunctionModel(model), output_type=[str, DeferredToolRequests], retries=0,
        toolsets=wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], resumed))
    final = await continued.run(None, message_history=history, deferred_tool_results=deferred)
    assert final.output == "The action has been resolved"
    assert effects == (["approved bytes"] if approved else [])
    assert len(resumed.effects) == 1
    assert model_calls == 2
    assert dispatch_attempts == ["approved bytes"] * (2 if approved else 1)


@pytest.mark.asyncio
async def test_native_system_mutation_has_no_effect_until_exact_approval(action, tmp_path, monkeypatch):
    from fastmcp import Client
    from app.connection import facade as connections
    from app.file_share import mcp, resource_service
    from app.file_share.resource_contracts import ResourceContext
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.services import mandatory_services, mcp_loader
    from app.services.contracts import EXECUTION_META_KEY
    from app.services.authorization import AUTHORIZATION_META_KEY
    from app.services.models import Service
    from app.connection.models import Connection
    transport = TemporaryFileTransport(tmp_path / "console")
    monkeypatch.setattr(resource_service, "_console_transport", AsyncMock(return_value=transport))
    monkeypatch.setattr(mcp, "_resource_context", AsyncMock(return_value=ResourceContext(
        agent_id=action.agent_id, runtime="internal", console_resource=transport)))
    async with get_db_session() as db:
        await mandatory_services.sync_integrated_service_connections(action.agent_id)
        connection = await db.scalar(select(Connection).join(Service).where(Connection.agent_id == action.agent_id, Service.code == "file_sharing"))
        connection_id = connection.id
        await connections.set_connection_function_state(connection_id, "file_create", "ask")
        server = await mcp_loader.build_agent_galaris_fastmcp(action.agent_id, runtime="internal")
    operation = str(uuid4())
    arguments = {"path": "console://approved.txt", "content": "synthetic"}
    async with Client(server) as client:
        result = await client.call_tool("file_create", arguments, raise_on_error=False,
            meta={EXECUTION_META_KEY: {"operation_id": operation}})
        assert result.is_error
        control = result.meta[AUTHORIZATION_META_KEY]
        identifier = UUID(control["request_id"])
        assert not (transport.root_path() / "approved.txt").exists()
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
        approved = await client.call_tool("file_create", arguments, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert not approved.is_error
        assert (transport.root_path() / "approved.txt").read_text() == "synthetic"
        replay = await client.call_tool("file_create", arguments, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert replay.is_error and replay.meta[AUTHORIZATION_META_KEY]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("remember", [False, True])
async def test_external_proxy_guards_dispatch_and_keeps_capability_kinds_separate(action, tmp_path, monkeypatch, remember):
    from fastmcp import Client, FastMCP
    from app.connection import facade as connections
    from app.connection.models import Connection
    from app.services import mcp_loader
    from app.services.models import Service
    from app.services.authorization import AUTHORIZATION_META_KEY
    remote = FastMCP("Synthetic external boundary")
    effects = []

    @remote.tool(name="same")
    def mutate(value: str) -> str:
        effects.append(value)
        return value

    @remote.resource("synthetic://same")
    def read_resource() -> str:
        return "resource"

    @remote.prompt(name="same")
    def prompt() -> str:
        return "prompt"

    monkeypatch.setattr(mcp_loader, "_external_transport", lambda *_args: remote)
    async with get_db_session() as db:
        tool = Service(code=f"external_{uuid4().hex}", label="Synthetic MCP", mcp_config={"type": "http", "url": "https://mcp.example.test/mcp"})
        db.add(tool)
        await db.flush()
        connection = Connection(service_id=tool.id, agent_id=action.agent_id, active=True)
        db.add(connection)
        await db.flush()
        connection_id, code = connection.id, tool.code
        await connections.set_connection_function_state(connection_id, "same", "ask")
        await connections.set_connection_function_state(connection_id, "same", "disabled", capability_kind="prompt")
        server = await mcp_loader.build_agent_mcp(action.agent_id, resources={"mcp_principal": "synthetic-caller"})
    async with Client(server) as client:
        assert not await client.list_prompts()
        assert len(await client.list_resources()) == 1
        pending_result = await client.call_tool(f"{code}_same", {"value": "once"}, raise_on_error=False)
        assert pending_result.is_error and effects == []
        control = pending_result.meta[AUTHORIZATION_META_KEY]
        identifier = UUID(control["request_id"])
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=remember)
        result = await client.call_tool(f"{code}_same", {"value": "once"}, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert not result.is_error and effects == ["once"]
        replay = await client.call_tool(f"{code}_same", {"value": "once"}, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert replay.is_error and effects == ["once"]
        if remember:
            subsequent = await client.call_tool(f"{code}_same", {"value": "future"}, raise_on_error=False)
            assert not subsequent.is_error and effects == ["once", "future"]
