"""Agent scoping for the Calendar MCP family."""

from types import SimpleNamespace

import pytest

from app.tools.mcp_loader import McpToolContext
from bridge.calendar import mcp
from bridge.calendar.schemas import CalendarAvailability


@pytest.mark.asyncio
async def test_calendar_list_is_scoped_to_current_agent(monkeypatch) -> None:
    observed = []

    async def list_feeds(*, agent_id=None):
        observed.append(agent_id)
        return [SimpleNamespace(model_dump=lambda **_kwargs: {"agent_id": agent_id})]

    monkeypatch.setattr(mcp.service, "list_feeds", list_feeds)
    result = await mcp.calendar_list(McpToolContext(agent_id=42, runtime="internal"))
    assert result == [{"agent_id": 42}]
    assert observed == [42]


@pytest.mark.asyncio
async def test_calendar_availability_is_scoped_to_current_agent(monkeypatch) -> None:
    observed = []

    async def availability(agent_id, start, end, *, calendar_ids=None):
        observed.append((agent_id, calendar_ids))
        return CalendarAvailability(start=start, end=end, available=True)

    monkeypatch.setattr(mcp.service, "availability_for_agent", availability)
    result = await mcp.calendar_is_available(
        McpToolContext(agent_id=42, runtime="internal"),
        "2026-08-24T09:00:00Z",
        "2026-08-24T10:00:00Z",
        calendar_ids=[3],
    )

    assert result["available"] is True
    assert observed == [(42, [3])]
