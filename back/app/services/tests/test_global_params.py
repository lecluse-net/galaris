from unittest.mock import AsyncMock

import pytest

from app.services.models import Service as ServiceModel
from app.services.schemas import ServiceGlobalParamsUpdate
from app.services import service


@pytest.fixture(autouse=True)
def isolate_database_locks(monkeypatch):
    # Locking/concurrency is verified against PostgreSQL in test_service_admin.
    monkeypatch.setattr(service, "lock_services", AsyncMock())


def test_new_schema_defaults_are_merged_without_overwriting_global_values() -> None:
    merged = service.merge_default_global_params(
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
    record = ServiceModel(
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
    monkeypatch.setattr(service, "get_db", lambda: db)

    await service.update_global_params(
        7,
        ServiceGlobalParamsUpdate(params={
            "host": {"value": "shared.example.test"},
            "password": {"value": "secret", "forced": True},
        }),
    )

    encrypted = record.global_params["password"]["value"]  # type: ignore[index]
    assert encrypted != "secret"
    assert service._encryption.decrypt(encrypted) == "secret"  # pyright: ignore[reportPrivateUsage]
    assert record.global_params["password"]["forced"] is True  # type: ignore[index]

    await service.update_global_params(
        7,
        ServiceGlobalParamsUpdate(params={
            "password": {"value": None, "forced": False, "clear": False},
        }),
    )

    assert record.global_params["password"]["value"] == encrypted  # type: ignore[index]
    assert record.global_params["password"]["forced"] is False  # type: ignore[index]


@pytest.mark.asyncio
async def test_global_param_clear_removes_value_and_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ServiceModel(
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
    monkeypatch.setattr(service, "get_db", lambda: db)

    await service.update_global_params(
        8,
        ServiceGlobalParamsUpdate(params={
            "host": {"value": None, "forced": True, "clear": True},
        }),
    )

    assert record.global_params == {"host": {"value": None, "forced": False}}
