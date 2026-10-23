from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.conversation import mcp as conversation_mcp
from app.tools import McpToolContext
from app.tools.facade import AdministrationScope
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
    monkeypatch.setattr("app.tools.facade.administration_scope", authorize)
    monkeypatch.setattr(conversation_mcp, "inspect_round", inspect)

    result = await conversation_mcp.conversation_round_get(
        McpToolContext(agent_id=7, runtime="internal"),
        round_id=str(identifier),
    )

    assert result == {"round": {"id": str(identifier)}}
    authorize.assert_awaited_once_with(7, "galaris_admin")
    inspect.assert_awaited_once_with(identifier, agent_ids=frozenset({7}))


@pytest.mark.asyncio
async def test_voice_turn_admin_tool_maps_uuid_to_complete_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    authorize = AsyncMock(return_value=AdministrationScope("personal", frozenset({7})))
    inspect = AsyncMock(return_value={"turn": {"id": str(identifier)}})
    monkeypatch.setattr(database, "get_db_session", _session)
    monkeypatch.setattr("app.tools.facade.administration_scope", authorize)
    monkeypatch.setattr("app.voice.inspection_service.inspect_turn", inspect)

    result = await voice_mcp.voice_turn_get(
        McpToolContext(agent_id=7, runtime="internal"),
        turn_id=str(identifier),
    )

    assert result == {"turn": {"id": str(identifier)}}
    authorize.assert_awaited_once_with(7, "galaris_admin")
    inspect.assert_awaited_once_with(identifier, agent_ids=frozenset({7}))


@pytest.mark.asyncio
async def test_admin_tools_reject_non_uuid_identifiers() -> None:
    ctx = McpToolContext(agent_id=7, runtime="internal")

    with pytest.raises(ValueError, match="conversation round UUID"):
        await conversation_mcp.conversation_round_get(ctx, round_id="not-an-id")
    with pytest.raises(ValueError, match="voice conversation turn UUID"):
        await voice_mcp.voice_turn_get(ctx, turn_id="not-an-id")
