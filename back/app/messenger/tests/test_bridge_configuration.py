import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.messenger import available_bridges
from app.messenger.schemas import MessengerBridgeInfo, MessengerBridgeParam
from app.tools import (
    ConnectionParamDef,
    ConnectionSchema,
    MessengerConfig,
    ToolCreate,
    ToolUpdate,
    tool_service,
)
from app.tools import router as tool_router
from app.tools.secrets import runtime_messenger_config
from core.util import SECRET_MASK, get_encryption_service


def _keys(rows: list[MessengerBridgeParam]) -> list[str]:
    return [row.key for row in rows]


def test_bridge_catalog_declares_tool_and_connection_contracts() -> None:
    bridges = {
        bridge.service: bridge
        for bridge in (
            MessengerBridgeInfo.model_validate(row)
            for row in available_bridges()
        )
    }

    assert _keys(bridges["nextcloud_talk"].settings) == ["base_url"]
    assert _keys(bridges["nextcloud_talk"].params) == ["login", "password"]
    assert _keys(bridges["matrix"].settings) == ["homeserver"]
    assert _keys(bridges["matrix"].params) == ["user_id", "token", "password"]
    matrix_params = {
        param.key: param
        for param in bridges["matrix"].params
    }
    assert matrix_params["token"].required is False
    assert matrix_params["password"].required is False
    assert bridges["telegram"].settings == []
    assert _keys(bridges["telegram"].params) == ["token"]
    assert _keys(bridges["whatsapp"].settings) == [
        "app_secret",
        "verify_token",
    ]
    assert _keys(bridges["whatsapp"].params) == [
        "access_token",
        "phone_number_id",
    ]
    assert _keys(bridges["one_bot"].settings) == ["platform"]
    assert _keys(bridges["one_bot"].params) == ["user_id", "token"]


@pytest.mark.asyncio
async def test_tool_creation_rejects_a_missing_required_messenger_mapping(
    db: AsyncSession,
) -> None:
    del db
    with pytest.raises(ValueError, match="login"):
        await tool_service.create_tool(
            ToolCreate(
                code="invalid-nextcloud-messenger",
                label="Invalid Nextcloud",
                messenger_config=MessengerConfig(
                    service="nextcloud_talk",
                    settings={"base_url": "https://cloud.example.test"},
                    param_map={"password": "password"},
                ),
                connection_schema=ConnectionSchema(
                    params={
                        "password": ConnectionParamDef(type="password"),
                    }
                ),
            )
        )


@pytest.mark.asyncio
async def test_whatsapp_server_secrets_are_encrypted_and_write_only(
    db: AsyncSession,
) -> None:
    del db
    app_secret = "whatsapp-app-secret-sentinel"
    verify_token = "whatsapp-verify-token-sentinel"
    record = await tool_service.create_tool(
        ToolCreate(
            code="whatsapp-secret-storage",
            label="WhatsApp",
            messenger_config=MessengerConfig(
                service="whatsapp",
                settings={
                    "app_secret": app_secret,
                    "verify_token": verify_token,
                },
                param_map={
                    "access_token": "access_token",
                    "phone_number_id": "phone_number_id",
                },
            ),
            connection_schema=ConnectionSchema(
                params={
                    "access_token": ConnectionParamDef(type="password"),
                    "phone_number_id": ConnectionParamDef(),
                }
            ),
        )
    )

    assert record.messenger_config is not None
    stored_settings = record.messenger_config["settings"]
    encryption = get_encryption_service()
    assert encryption.is_encrypted(stored_settings["app_secret"])
    assert encryption.is_encrypted(stored_settings["verify_token"])
    runtime = runtime_messenger_config(
        record.messenger_config,
        secret_fields=frozenset({"app_secret", "verify_token"}),
    )
    assert runtime["settings"] == {
        "app_secret": app_secret,
        "verify_token": verify_token,
    }
    public = tool_router._to_public(record)  # pyright: ignore[reportPrivateUsage]
    assert public.messenger_config is not None
    assert public.messenger_config.settings == {
        "app_secret": SECRET_MASK,
        "verify_token": SECRET_MASK,
    }


@pytest.mark.asyncio
async def test_tool_update_can_disable_messenger_capability(
    db: AsyncSession,
) -> None:
    del db
    record = await tool_service.create_tool(
        ToolCreate(
            code="disable-messenger-capability",
            label="Telegram",
            messenger_config=MessengerConfig(
                service="telegram",
                param_map={"token": "bot_token"},
            ),
            connection_schema=ConnectionSchema(
                params={
                    "bot_token": ConnectionParamDef(type="password"),
                }
            ),
        )
    )

    updated = await tool_service.update_tool(
        int(record.id),
        ToolUpdate(messenger_config=None),
    )

    assert updated is not None
    assert updated.messenger_config is None
