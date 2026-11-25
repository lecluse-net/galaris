from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.conversation import mcp as conversation_mcp
from app.services import McpToolContext
from app.services.facade import AdministrationScope
from app.voice import mcp as voice_mcp
from core.database import database


@asynccontextmanager
async def _session() -> AsyncIterator[None]:
    yield


@pytest.mark.asyncio
async def test_text_round_admin_tool_maps_uuid_to_complete_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    authorize = AsyncMock(return_value=AdministrationScope("personal", frozenset({7})))
    inspect = AsyncMock(return_value={"round": {"id": str(identifier)}})
    monkeypatch.setattr(database, "get_db_session", _session)
    monkeypatch.setattr("app.services.management_scope.administration_scope", authorize)
    monkeypatch.setattr(conversation_mcp, "inspect_round", inspect)

    result = await conversation_mcp.chat_round_get(
        McpToolContext(agent_id=7, runtime="internal"),
        round_id=str(identifier),
    )

    assert result == {"round": {"id": str(identifier)}}
    authorize.assert_awaited_once_with(7, "service")
    inspect.assert_awaited_once_with(identifier, agent_ids=frozenset({7}))


@pytest.mark.asyncio
async def test_voice_turn_admin_tool_maps_uuid_to_complete_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    authorize = AsyncMock(return_value=AdministrationScope("personal", frozenset({7})))
    inspect = AsyncMock(return_value={"turn": {"id": str(identifier)}})
    monkeypatch.setattr(database, "get_db_session", _session)
    monkeypatch.setattr("app.services.management_scope.administration_scope", authorize)
    monkeypatch.setattr("app.voice.inspection_service.inspect_turn", inspect)

    result = await voice_mcp.voice_turn_get(
        McpToolContext(agent_id=7, runtime="internal"),
        turn_id=str(identifier),
    )

    assert result == {"turn": {"id": str(identifier)}}
    authorize.assert_awaited_once_with(7, "service")
    inspect.assert_awaited_once_with(identifier, agent_ids=frozenset({7}))


@pytest.mark.asyncio
async def test_admin_tools_reject_non_uuid_identifiers() -> None:
    ctx = McpToolContext(agent_id=7, runtime="internal")

    with pytest.raises(ValueError, match="conversation round UUID"):
        await conversation_mcp.chat_round_get(ctx, round_id="not-an-id")
    with pytest.raises(ValueError, match="voice conversation turn UUID"):
        await voice_mcp.voice_turn_get(ctx, turn_id="not-an-id")


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "argument", "key"), [
    ("chat_round_get", "round_id", "round"),
    ("voice_turn_get", "turn_id", "turn"),
])
async def test_chat_inspections_recheck_services_scope_and_chat_permission(db, name, argument, key):
    from datetime import datetime, timezone
    from fastmcp import Client
    from sqlalchemy import select
    from app.agent.models import AgentTeam
    from app.connection import Connection, facade as connections
    from app.conversation.tests.test_resource_facade import _round_scope
    from app.messenger import Room
    from app.services import build_galaris_fastmcp
    from app.services.mandatory_services import sync_integrated_service_connections
    from app.services.models import Service
    from app.voice.models import VoiceConversationSession
    from core.team import TeamModel

    caller, _ = await _round_scope(db, "Synthetic inspector")
    target, record = await _round_scope(db, "Synthetic inspected round")
    if key == "turn":
        room = await db.get(Room, record.room_id)
        room.conversation_type = "audio"
        session = VoiceConversationSession(
            messenger_room_id=room.id, status="COMPLETED", started_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.flush()
        record.voice_session_id = session.id
        record.sequence = 1
    team = TeamModel(name=f"Synthetic inspection team {uuid4().hex}")
    db.add(team)
    await db.flush()
    target_membership = AgentTeam(agent_id=target.id, team_id=team.id)
    db.add_all([AgentTeam(agent_id=caller.id, team_id=team.id), target_membership])
    await db.commit()

    await sync_integrated_service_connections(caller.id)
    grants = dict((await db.execute(select(Service.code, Connection).join(Connection).where(
        Connection.agent_id == caller.id, Service.code.in_(("service", "chat")),
    ))).all())
    service, chat = grants["service"], grants["chat"]
    await connections.set_connection_function_state(chat.id, name, "enabled")
    await connections.set_management_scope(chat.id, "all", authorized=True)
    await connections.set_management_scope(service.id, "usage", authorized=True)
    server = build_galaris_fastmcp(caller.id, runtime="internal", enabled_service_codes={"chat"})
    async with Client(server) as client:
        args = {argument: str(record.id)}
        assert (await client.call_tool(name, args, raise_on_error=False)).is_error
        await connections.set_management_scope(service.id, "personal", authorized=True)
        assert (await client.call_tool(name, args, raise_on_error=False)).is_error
        await connections.set_management_scope(service.id, "team", authorized=True)
        result = await client.call_tool(name, args)
        assert result.structured_content[key]["id"] == str(record.id)

        await db.delete(target_membership)
        await db.commit()
        assert (await client.call_tool(name, args, raise_on_error=False)).is_error
        await connections.set_management_scope(service.id, "all", authorized=True)
        result = await client.call_tool(name, args)
        assert result.structured_content["agent"]["id"] == target.id
        await connections.set_connection_function_state(chat.id, name, "disabled")
        assert (await client.call_tool(name, args, raise_on_error=False)).is_error
