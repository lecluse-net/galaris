import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["internal", "telegram", "matrix", "nextcloud_talk", "one_bot", "whatsapp"])
async def test_reception_checks_only_existing_active_connections_for_the_provider(db, monkeypatch, provider):
    from app.agent.models import Agent, Title
    from app.connection import Connection
    from app.messenger import facade, service
    from app.tools import ToolModel
    from core.params import runtime_settings

    kinds = ["internal", "telegram", "matrix", "nextcloud_talk", "one_bot", "whatsapp"]
    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", json.dumps(kinds))
    service.register_messaging()
    suffix = uuid4().hex
    title = Title(label="Synthetic reception check", gender="X")
    tools = {kind: ToolModel(code=f"reception-{kind}-{suffix}", label=f"Synthetic {kind}",
        description="", connection_schema={}, messenger_config={"service": kind}) for kind in kinds}
    db.add_all([title, *tools.values()])
    await db.flush()
    agents = [Agent(code=f"reception-{index}-{suffix}", title_id=title.id,
        first_name="Synthetic", last_name=f"Receiver {index}", agent_driver="internal") for index in range(4)]
    db.add_all(agents)
    await db.flush()
    selected = Connection(agent_id=agents[0].id, tool_id=tools[provider].id, active=True)
    inactive = Connection(agent_id=agents[3].id, tool_id=tools[provider].id, active=False)
    # Agent 1 has only other providers; agent 2 has no messaging connection at all.
    others = [Connection(agent_id=agents[1].id, tool_id=tool.id, active=True)
        for kind, tool in tools.items() if kind != provider]
    db.add_all([selected, inactive, *others])
    await db.flush()
    builders = {}
    for kind in kinds:
        transport = SimpleNamespace(kind=kind, self_id="synthetic-bot", tool_id=tools[kind].id,
            check_connection=AsyncMock(return_value="Synthetic reception available"), close=AsyncMock())
        factory = facade.get_factory(kind)
        assert factory is not None
        builders[kind] = AsyncMock(return_value=transport)
        monkeypatch.setattr(factory, "from_connection_id", builders[kind])

    result = await service.check_configuration(provider)

    assert result["provider"] == provider
    assert result["ok"] is True
    assert [(row["connection_id"], row["agent_id"], row["provider"]) for row in result["connections"]] == [
        (selected.id, agents[0].id, provider)]
    builders[provider].assert_awaited_once_with(selected.id)
    for kind in kinds:
        if kind != provider:
            builders[kind].assert_not_awaited()
        builders[kind].reset_mock()

    selected.active = False
    await db.flush()
    assert await service.check_configuration(provider) == {"provider": provider, "ok": False, "connections": []}
    for builder in builders.values():
        builder.assert_not_awaited()

    selected.active = True
    await db.flush()
    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", json.dumps([kind for kind in kinds if kind != provider]))
    assert await service.check_configuration(provider) == {"provider": provider, "ok": False, "connections": []}
    for builder in builders.values():
        builder.assert_not_awaited()
    # The existing aggregate API still checks every configured, enabled connection.
    aggregate = await service.check_configuration()
    assert aggregate["provider"] == "multi"
    assert {row["connection_id"] for row in aggregate["connections"]} == {connection.id for connection in others}


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
