from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp.client import Client
from sqlalchemy import select

from app.chat import events
from app.connection import Connection, ConnectionFunctionState, ToolFunctionState
from app.conversation import ConversationTurn
from app.memory import document_service
from app.messenger import create_internal_room
from app.tools import ToolModel
from app.tools.agent_registry import build_agent_tool_advertisement
from app.tools.mcp_loader import build_agent_galaris_fastmcp
from core.settings import settings


@pytest_asyncio.fixture
async def display_scope(db, agents, memory_storage, monkeypatch):
    agent, other = agents
    conversation_connection = None
    for code in ("chat", "conversation", "memory"):
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == code))
        if tool is None:
            tool = ToolModel(code=code, label=code, connection_schema={},
                             messenger_config={"service": "internal"} if code == "chat" else None)
            db.add(tool)
            await db.flush()
        tool.conversation_enabled = code != "memory"
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=code != "memory")
        db.add(connection)
        if code == "conversation":
            conversation_connection = connection
    await db.flush()
    room = await create_internal_room(actor_user_id=agent.user_id, agent_id=agent.id)
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=agent.id,
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
@pytest.mark.parametrize("reference_kind", ["uuid", "uri", "url", "relative_url"])
@pytest.mark.parametrize("legacy_function_denials", [False, True])
async def test_show_document_uses_current_room_without_changing_content_or_sharing(
    display_scope, db, reference_kind, legacy_function_denials,
):
    agent, _, turn, document, connection, emit = display_scope
    if legacy_function_denials:
        # ADR 0105: historical function denials cannot disable a system service.
        db.add_all([
            ConnectionFunctionState(
                connection_id=connection.id, function_name="document_show", enabled=False,
            ),
            ToolFunctionState(
                tool_id=connection.tool_id, function_name="document_show", enabled=False,
            ),
        ])
        await db.flush()
    references = {
        "uuid": str(document.id), "uri": f"document://{document.id}",
        "url": f"{settings.APP_HOST.rstrip('/')}/memory/documents?document_id={document.id}",
        "relative_url": f"/memory/documents?document_id={document.id}",
    }
    advertisement = await build_agent_tool_advertisement(
        agent.id, runtime="internal", conversation_only=True, resources={"conversation_turn": turn},
    )
    assert "document_show" in advertisement.tool_names
    before = (document.revision, document.visibility, document.lock_version)
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
                                 "task", "inactive", "conversation_disabled", "memory_only"])
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
        tool = await db.get(ToolModel, chat_connection.tool_id)
        tool.code = "external-chat-test"
        tool.messenger_config = {"service": "nextcloud_talk"}
    elif case == "inactive":
        connection.active = False
    elif case == "memory_only":
        connection.active = False
        memory_tool = await db.scalar(select(ToolModel).where(ToolModel.code == "memory"))
        memory_tool.conversation_enabled = True
        memory_connection = await db.scalar(select(Connection).where(
            Connection.tool_id == memory_tool.id, Connection.agent_id == agent.id,
        ))
        memory_connection.active = True
    elif case == "conversation_disabled":
        tool = await db.get(ToolModel, connection.tool_id)
        tool.conversation_enabled = False
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
        reference = f"https://untrusted.example/memory/documents?document_id={document.id}"
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
