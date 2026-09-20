from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from app.tools import mcp
from app.tools.mcp_loader import McpToolContext


@asynccontextmanager
async def _session() -> AsyncIterator[None]:
    yield None


@pytest.mark.asyncio
async def test_tools_list_omits_every_unauthorized_function_and_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [
        {
            "tool_code": "galaris",
            "tool_label": "Galaris",
            "tool_description": "Includes allowed_function and denied_function.",
            "active": True,
            "mcp_tools": [
                {
                    "name": "allowed_function",
                    "description": "Allowed.",
                    "enabled": True,
                },
                {
                    "name": "denied_function",
                    "description": "Denied.",
                    "enabled": False,
                },
            ],
        },
        {
            "tool_code": "process_admin",
            "tool_label": "Process administration",
            "tool_description": "Includes process_admin_start.",
            "active": False,
            "mcp_tools": [
                {
                    "name": "process_admin_start",
                    "description": "Start another agent's process.",
                    "enabled": False,
                }
            ],
        },
    ]
    monkeypatch.setattr(mcp, "list_agent_mcp_tools", AsyncMock(return_value=groups))
    monkeypatch.setattr(mcp, "context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.list_mcp_tools(
        McpToolContext(agent_id=7, runtime="internal")
    )

    assert "allowed_function" in result
    assert "denied_function" not in result
    assert "process_admin_start" not in result
    assert "Process administration" not in result
    assert "Includes" not in result
    assert "unavailable" not in result
    assert "only functions currently authorized" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr"])
async def test_tools_list_distinguishes_newly_enabled_tools_from_current_run(
    monkeypatch: pytest.MonkeyPatch, language: str,
) -> None:
    groups = [{
        "tool_code": "browser", "tool_label": "Browser",
        "mcp_tools": [
            {"name": "browser_open", "description": "Open.", "enabled": True},
            {"name": "browser_secret", "description": "Denied.", "enabled": False},
        ],
    }]
    monkeypatch.setattr(mcp, "list_agent_mcp_tools", AsyncMock(return_value=groups))
    monkeypatch.setattr(mcp, "context_language", AsyncMock(return_value=language))
    names = AsyncMock(return_value=frozenset({"tools_list"}))
    ctx = McpToolContext(
        agent_id=7, runtime="internal", resources={"run_tool_names": names},
    )
    result = await mcp.list_mcp_tools(ctx)
    assert "browser_secret" not in result
    assert ("absent de cette exécution" if language == "fr" else "absent from this run") in result
    assert "load_capability" in result

    names.return_value = frozenset({"tools_list", "browser_open"})
    result = await mcp.list_mcp_tools(ctx)
    assert ("présent dans cette exécution" if language == "fr" else "present in this run") in result
    assert ("absent de cette exécution" if language == "fr" else "absent from this run") not in result
