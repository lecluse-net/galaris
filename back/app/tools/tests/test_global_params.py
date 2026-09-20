from unittest.mock import AsyncMock

import pytest

from app.tools.models import Tool as ToolModel
from app.tools.schemas import ToolGlobalParamsUpdate
from app.tools import tool_service


def test_new_schema_defaults_are_merged_without_overwriting_global_values() -> None:
    merged = tool_service.merge_default_global_params(
        {"host": {"value": "custom.example.test", "forced": True}},
        {
            "params": {
                "host": {"type": "string", "default": "default.example.test"},
                "poll_interval_s": {"type": "integer", "default": "60"},
            }
        },
    )

    assert merged == {
        "host": {"value": "custom.example.test", "forced": True},
        "poll_interval_s": {"value": "60", "forced": False},
    }


@pytest.mark.asyncio
async def test_global_params_encrypt_secrets_and_preserve_them_on_empty_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ToolModel(
        id=7,
        code="remote",
        label="Remote",
        connection_schema={
            "params": {
                "host": {"type": "string"},
                "password": {"type": "password"},
            }
        },
        global_params=None,
    )
    db = AsyncMock()
    db.get.return_value = record
    monkeypatch.setattr(tool_service, "get_db", lambda: db)

    await tool_service.update_global_params(
        7,
        ToolGlobalParamsUpdate(params={
            "host": {"value": "shared.example.test"},
            "password": {"value": "secret", "forced": True},
        }),
    )

    encrypted = record.global_params["password"]["value"]  # type: ignore[index]
    assert encrypted != "secret"
    assert tool_service._encryption.decrypt(encrypted) == "secret"  # pyright: ignore[reportPrivateUsage]
    assert record.global_params["password"]["forced"] is True  # type: ignore[index]

    await tool_service.update_global_params(
        7,
        ToolGlobalParamsUpdate(params={
            "password": {"value": None, "forced": False, "clear": False},
        }),
    )

    assert record.global_params["password"]["value"] == encrypted  # type: ignore[index]
    assert record.global_params["password"]["forced"] is False  # type: ignore[index]


@pytest.mark.asyncio
async def test_global_param_clear_removes_value_and_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ToolModel(
        id=8,
        code="remote",
        label="Remote",
        connection_schema={"params": {"host": {"type": "string"}}},
        global_params={
            "host": {"value": "shared.example.test", "forced": True},
        },
    )
    db = AsyncMock()
    db.get.return_value = record
    monkeypatch.setattr(tool_service, "get_db", lambda: db)

    await tool_service.update_global_params(
        8,
        ToolGlobalParamsUpdate(params={
            "host": {"value": None, "forced": True, "clear": True},
        }),
    )

    assert record.global_params == {"host": {"value": None, "forced": False}}
