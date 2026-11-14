"""Tests for Service administration routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services import router
from app.services.schemas import (
    ServiceGlobalParamPublic,
    ServiceGlobalParamsUpdate,
    ServiceMcpTestRequest,
    ServiceMcpTestResponse,
    ServiceCreate,
    ServiceUpdate,
)


@pytest.mark.asyncio
async def test_mcp_connection_delegates_with_existing_secret_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_config = {"type": "http", "headers": {"X-Secret": "encrypted"}}
    get_record = AsyncMock(
        return_value=SimpleNamespace(mcp_config=existing_config)
    )
    expected = ServiceMcpTestResponse(
        success=True,
        message="2 MCP functions available",
    )
    diagnose = AsyncMock(return_value=expected)
    monkeypatch.setattr(router.service, "get_service_record_by_id", get_record)
    monkeypatch.setattr(router, "diagnose_mcp_connection", diagnose)
    request = ServiceMcpTestRequest(
        service_id=7,
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
    monkeypatch.setattr(router.service, "update_global_params", update)
    monkeypatch.setattr(
        router.service,
        "public_global_params",
        lambda _record: {
            "host": ServiceGlobalParamPublic(
                value="ssh.example.test",
                configured=True,
                forced=False,
            )
        },
    )
    request = ServiceGlobalParamsUpdate(
        params={"host": {"value": "ssh.example.test", "forced": False}}
    )

    result = await router.update_global_params(7, request)

    assert result.service_id == 7
    assert result.params["host"].value == "ssh.example.test"
    update.assert_awaited_once_with(7, request)


@pytest.mark.asyncio
@pytest.mark.parametrize("language,prefix", [
    ("fr", "Le nom technique"),
    ("en", "The technical name"),
    ("zh", "启用文件共享"),
])
async def test_resource_service_code_errors_use_the_request_language(db, monkeypatch, language, prefix):
    from core.i18n import i18n_service

    monkeypatch.setattr(i18n_service, "current_language", AsyncMock(return_value=language))
    code = f"synthetic_share_{uuid4().hex}"
    config = {"service": "samba", "base_url": "smb://files.example.test", "param_map": {}}
    definition = ServiceCreate(code=code, label="Synthetic share", file_share_config=config)
    with pytest.raises(HTTPException) as creation:
        await router.create_service(definition)
    record = await router.service.create_service(ServiceCreate(code=code, label="Synthetic share"))
    with pytest.raises(HTTPException) as update:
        await router.update_service(record.id, ServiceUpdate(file_share_config=config))
    with pytest.raises(HTTPException) as imported:
        await router.import_service(body=(
            f"code: {code}-import\nlabel: Synthetic share\n"
            "file_share_config:\n  service: samba\n  base_url: smb://files.example.test\n"
        ))
    for rejection in (creation, update, imported):
        assert rejection.value.status_code == 422
        assert rejection.value.detail.startswith(prefix)
        assert "resource-capable Service code" not in rejection.value.detail
    await db.refresh(record)
    assert record.file_share_config is None
