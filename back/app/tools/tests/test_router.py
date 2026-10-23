"""Tests for Tool administration routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.tools import router
from app.tools.schemas import (
    ToolGlobalParamPublic,
    ToolGlobalParamsUpdate,
    ToolMcpTestRequest,
    ToolMcpTestResponse,
    ToolCreate,
    ToolUpdate,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("language,prefix", [
    ("fr", "Le nom technique"),
    ("en", "The technical name"),
    ("zh", "启用文件共享"),
])
async def test_resource_tool_code_errors_use_the_request_language(db, monkeypatch, language, prefix):
    from core.i18n import i18n_service

    monkeypatch.setattr(i18n_service, "current_language", AsyncMock(return_value=language))
    code = f"synthetic_share_{uuid4().hex}"
    config = {"service": "samba", "base_url": "smb://files.example.test", "param_map": {}}
    definition = ToolCreate(code=code, label="Synthetic share", file_share_config=config)
    with pytest.raises(HTTPException) as creation:
        await router.create_tool(definition)
    record = await router.tool_service.create_tool(ToolCreate(code=code, label="Synthetic share"))
    with pytest.raises(HTTPException) as update:
        await router.update_tool(record.id, ToolUpdate(file_share_config=config))
    with pytest.raises(HTTPException) as imported:
        await router.import_tool(body=(
            f"code: {code}-import\nlabel: Synthetic share\n"
            "file_share_config:\n  service: samba\n  base_url: smb://files.example.test\n"
        ))
    for rejection in (creation, update, imported):
        assert rejection.value.status_code == 422
        assert rejection.value.detail.startswith(prefix)
        assert "resource-capable Tool code" not in rejection.value.detail
    await db.refresh(record)
    assert record.file_share_config is None
