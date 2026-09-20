"""Tests for Tool administration routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools import router
from app.tools.schemas import (
    ToolGlobalParamPublic,
    ToolGlobalParamsUpdate,
    ToolMcpTestRequest,
    ToolMcpTestResponse,
)


@pytest.mark.asyncio
async def test_mcp_connection_delegates_with_existing_secret_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_config = {"type": "http", "headers": {"X-Secret": "encrypted"}}
    get_record = AsyncMock(
        return_value=SimpleNamespace(mcp_config=existing_config)
    )
    expected = ToolMcpTestResponse(
        success=True,
        message="2 MCP functions available",
    )
    diagnose = AsyncMock(return_value=expected)
    monkeypatch.setattr(router.tool_service, "get_tool_record_by_id", get_record)
    monkeypatch.setattr(router, "diagnose_mcp_connection", diagnose)
    request = ToolMcpTestRequest(
        tool_id=7,
        code="issue_tracker",
        mcp_config={
            "type": "http",
            "url": "https://preview.example.test/mcp",
            "headers": {"X-Secret": "••••••••"},
        },
        params={"token": "temporary", "unused": None},
    )

    result = await router.test_mcp_connection(request)

    assert result is expected
    get_record.assert_awaited_once_with(7)
    diagnose.assert_awaited_once_with(
        request,
        existing_config=existing_config,
    )


@pytest.mark.asyncio
async def test_integrated_tool_global_params_can_be_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(id=7, code="console")
    update = AsyncMock(return_value=record)
    monkeypatch.setattr(router.tool_service, "update_global_params", update)
    monkeypatch.setattr(
        router.tool_service,
        "public_global_params",
        lambda _record: {
            "host": ToolGlobalParamPublic(
                value="ssh.example.test",
                configured=True,
                forced=False,
            )
        },
    )
    request = ToolGlobalParamsUpdate(
        params={"host": {"value": "ssh.example.test", "forced": False}}
    )

    result = await router.update_global_params(7, request)

    assert result.tool_id == 7
    assert result.params["host"].value == "ssh.example.test"
    update.assert_awaited_once_with(7, request)
