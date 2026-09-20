"""Contract tests for restricted skill-management MCP functions."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from app.tools.mcp_loader import McpToolContext

from .. import mcp


@asynccontextmanager
async def _session() -> AsyncIterator[None]:
    yield


class _Authorization:
    def __init__(self, code: str, effective: bool) -> None:
        self.code = code
        self.effective = effective

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {"code": self.code, "effective": self.effective}


@pytest.mark.asyncio
async def test_skills_list_returns_only_effective_skills_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorizations = [_Authorization("active", True), _Authorization("blocked", False)]
    monkeypatch.setattr(
        mcp.skill_service,
        "list_authorizations",
        AsyncMock(return_value=authorizations),
    )
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_skills_list(
        McpToolContext(agent_id=90, runtime="internal"),
        agent_id=12,
    )

    assert result == [{"code": "active", "effective": True}]


@pytest.mark.asyncio
async def test_skill_read_exposes_only_skill_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp.skill_service,
        "get_by_code",
        AsyncMock(return_value=SimpleNamespace(code="research")),
    )
    monkeypatch.setattr(
        mcp.storage,
        "inspect",
        lambda _code: SimpleNamespace(available=True),
    )

    def read_text(code: str, path: str) -> str:
        return f"{code}:{path}"

    monkeypatch.setattr(mcp.storage, "read_text", read_text)
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_skill_read(
        McpToolContext(agent_id=90, runtime="internal"),
        skill_code="research",
    )

    assert result == "research:SKILL.md"
