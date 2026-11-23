from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp.client import Client
from sqlalchemy import select

from app.chat import events
from app.connection import Connection, ConnectionFunctionState, ServiceFunctionState
from app.conversation import ConversationTurn
from app.document import document_service
from app.messenger import create_internal_room
from app.services import ServiceModel
from app.services.agent_registry import build_agent_tool_advertisement
from app.services.mcp_loader import build_agent_galaris_fastmcp
from core.settings import settings


@pytest_asyncio.fixture
async def display_scope(db, agents, memory_storage, monkeypatch):
    agent, other = agents
    conversation_connection = None
    for code in ("chat", "document", "memory"):
        tool = await db.scalar(select(ServiceModel).where(ServiceModel.code == code))
        if tool is None:
            tool = ServiceModel(code=code, label=code, connection_schema={},
                             messenger_config={"service": "internal"} if code == "chat" else None)
            db.add(tool)
            await db.flush()
        connection = Connection(service_id=tool.id, agent_id=agent.id, active=code != "memory")
        db.add(connection)
        if code == "document":
            conversation_connection = connection
    await db.flush()
    room = await create_internal_room(actor_user_id=agent.user_id, agent_id=agent.id)
    from app.conversation.models import ConversationRound
    round_ = ConversationRound(room_id=room.id, requester_user_id=agent.user_id, language="en", status="RUNNING")
    db.add(round_)
    await db.flush()
    turn = ConversationTurn(room_id=room.id, round_id=round_.id, agent_id=agent.id,
                            language="en", objective="Show the document", messages=())
    document = await document_service.create_document(
        owner_agent_id=agent.id, title="Report", content="<p>Report body</p>", task_id=None,
    )
    emit = AsyncMock()
    monkeypatch.setattr(events.websocket, "emit", emit)
    return agent, other, turn, document, conversation_connection, emit


async def server_for(agent, turn, *, conversation_only=True):
    return await build_agent_galaris_fastmcp(
        agent.id, task_id=None if conversation_only else uuid4(),
        resources={"conversation_turn": turn}, conversation_only=conversation_only,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_kind", ["uuid", "uri", "url", "relative_url", "legacy_url", "legacy_relative_url"])
@pytest.mark.parametrize("legacy_function_denials", [False, True])
async def test_show_document_honors_function_policy_without_changing_content_or_sharing(
    display_scope, db, reference_kind, legacy_function_denials,
):
    agent, _, turn, document, connection, emit = display_scope
    if legacy_function_denials:
        # System service connections stay mandatory; function denials apply normally.
        db.add_all([
            ConnectionFunctionState(
                connection_id=connection.id, function_name="document_show", enabled=False,
            ),
            ServiceFunctionState(
                service_id=connection.service_id, function_name="document_show", enabled=False,
            ),
        ])
        await db.flush()
    references = {
        "uuid": str(document.id), "uri": f"document://{document.id}",
        "url": f"{settings.APP_HOST.rstrip('/')}/documents?document_id={document.id}",
        "relative_url": f"/documents?document_id={document.id}",
        "legacy_url": f"{settings.APP_HOST.rstrip('/')}/documents?document_id={document.id}",
        "legacy_relative_url": f"/documents?document_id={document.id}",
    }
    advertisement = await build_agent_tool_advertisement(
        agent.id, runtime="internal", conversation_only=True, resources={"conversation_turn": turn},
    )
    before = (document.revision, document.visibility, document.lock_version)
    if legacy_function_denials:
        assert "document_show" not in advertisement.tool_names
        async with Client(await server_for(agent, turn)) as client:
            result = await client.call_tool("document_show", {"document": references[reference_kind]}, raise_on_error=False)
        assert result.is_error
        assert (document.revision, document.visibility, document.lock_version) == before
        emit.assert_not_awaited()
        return
    assert "document_show" in advertisement.tool_names
    async with Client(await server_for(agent, turn)) as client:
        assert "document_show" in {tool.name for tool in await client.list_tools()}
        result = await client.call_tool("document_show", {"document": references[reference_kind]})
    assert not result.is_error
    assert result.data["status"] == "requested"
    assert (document.revision, document.visibility, document.lock_version) == before
    emit.assert_awaited_once()
    args = emit.call_args.args
    assert args == ("chat", "document_show", {"room_id": str(turn.room_id), "document_id": str(document.id)})
    assert emit.call_args.kwargs["room"].resource_id == turn.room_id


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_context", "voice", "other_agent", "unknown_room", "external",
                                 "task", "inactive", "function_disabled", "memory_only"])
async def test_show_document_is_absent_outside_its_authorized_context(display_scope, db, case):
    from app.messenger.models import Room

    agent, other, turn, _, connection, _ = display_scope
    if case == "no_context":
        turn = None
    elif case == "voice":
        turn = replace(turn, origin="voice")
    elif case == "other_agent":
        turn = replace(turn, agent_id=other.id)
    elif case == "unknown_room":
        turn = replace(turn, room_id=uuid4())
    elif case == "external":
        room = await db.get(Room, turn.room_id)
        chat_connection = await db.get(Connection, room.connection_id)
        tool = await db.get(ServiceModel, chat_connection.service_id)
        tool.code = "external-chat-test"
        tool.messenger_config = {"service": "nextcloud_talk"}
    elif case == "inactive":
        connection.active = False
    elif case == "memory_only":
        connection.active = False
        memory_tool = await db.scalar(select(ServiceModel).where(ServiceModel.code == "memory"))
        memory_connection = await db.scalar(select(Connection).where(
            Connection.service_id == memory_tool.id, Connection.agent_id == agent.id,
        ))
        memory_connection.active = True
    elif case == "function_disabled":
        db.add(ConnectionFunctionState(connection_id=connection.id, function_name="document_show", enabled=False))
    await db.flush()
    async with Client(await server_for(agent, turn, conversation_only=case != "task")) as client:
        assert "document_show" not in {tool.name for tool in await client.list_tools()}
        if case == "task":
            result = await client.call_tool(
                "document_show", {"document": str(uuid4())}, raise_on_error=False,
            )
            assert result.is_error
    advertisement = await build_agent_tool_advertisement(
        agent.id, runtime="internal", conversation_only=case != "task", resources={"conversation_turn": turn},
    )
    assert "document_show" not in advertisement.tool_names


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["private", "missing", "bad_url", "revoked"])
async def test_show_document_rejects_invalid_or_revoked_requests(display_scope, db, case):
    agent, other, turn, document, connection, emit = display_scope
    reference = str(document.id)
    if case == "private":
        private = await document_service.create_document(
            owner_agent_id=other.id, title="Private", content="<p>Secret</p>", task_id=None,
        )
        reference = str(private.id)
    elif case == "missing":
        reference = str(uuid4())
    elif case == "bad_url":
        reference = f"https://untrusted.example/documents?document_id={document.id}"
    server = await server_for(agent, turn)
    if case == "revoked":
        connection.active = False
        await db.flush()
    emit.reset_mock()
    async with Client(server) as client:
        result = await client.call_tool("document_show", {"document": reference}, raise_on_error=False)
    assert result.is_error
    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_show_document_requires_both_local_scope_and_document_read_access(display_scope, db):
    from app.agent.dialogue_service import set_agent_membership
    from app.connection.facade import set_management_scope
    from app.document.item_sharing import update_agent_sharing
    from core.team import TeamModel

    agent, owner, turn, _, connection, emit = display_scope
    document = await document_service.create_document(
        owner_agent_id=owner.id, title="Synthetic shared report", content="<p>Report body</p>", task_id=None,
    )
    team = TeamModel(name="Synthetic document presentation team")
    db.add(team)
    await db.flush()
    for member in (agent, owner):
        await set_agent_membership(team.id, member.id, True)
    args = {"document": str(document.id)}
    async with Client(await server_for(agent, turn)) as client:
        await set_management_scope(connection.id, "team", authorized=True)
        emit.reset_mock()
        assert (await client.call_tool("document_show", args, raise_on_error=False)).is_error
        emit.assert_not_awaited()
        await update_agent_sharing(document.id, agent_id=owner.id, kind="agent", target_id=agent.id, access="read")
        emit.reset_mock()
        assert not (await client.call_tool("document_show", args)).is_error
        emit.assert_awaited_once()
        await set_agent_membership(team.id, owner.id, False)
        emit.reset_mock()
        assert (await client.call_tool("document_show", args, raise_on_error=False)).is_error
        emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_document_presentation_interrupts_before_publication(display_scope):
    from app.conversation.document_display import display_conversation_document
    from app.conversation.preparation import ConversationSuperseded

    _, _, turn, document, _, emit = display_scope
    turn = replace(turn, assert_fresh_before_effect=AsyncMock(return_value=False))
    emit.reset_mock()
    # Freshness is a control signal for the owning conversation, not a retriable tool error.
    with pytest.raises(ConversationSuperseded):
        await display_conversation_document(turn, document.id)
    emit.assert_not_awaited()
