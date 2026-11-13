"""Provider Tools compose protocols while preserving connection ownership and upgrades."""

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionParam, ConnectionFunctionState, ToolFunctionState, connection_service
from app.tools import tool_service, native_tool_codes_for_tool
from app.tools.models import Tool
from app.tools.protocols import ProtocolConfig, bind_protocol_connection, reset_protocol_connection
from app.tools.schemas import ToolCreate, ToolUpdate, ToolGlobalParamsUpdate, ToolGlobalParamUpdate, FileShareConfig, ConnectionSchema
from app.tools.projections import to_public
from app.tools.protocol_migration import _convert_legacy_tools, _introduces_protocols, _legacy_tools_converted
from app.calendar.models import CalendarFeed
from bridge.mail.models import MailOutboundDelivery
from bridge.mail.connection_service import resolve_connection, resolve_mail_connection
from core.dbadmin import SchemaTransitionSet
from core.util import get_encryption_service
from app.tools.rest_contracts import RestAuth, RestConfig


def test_ical_advertises_standard_connection_parameter_bindings():
    from app.tools.capabilities import supported_capabilities

    calendar = next(item for item in supported_capabilities() if item.code == "calendar")
    protocol = calendar.protocols[0]
    assert protocol.connection_parameters["url"]["parameter"] == "url"
    assert protocol.connection_parameters["url"]["definition"]["type"] == "password"
    assert protocol.connection_parameters["username"]["parameter"] == "login"
    assert protocol.connection_parameters["password"]["parameter"] == "password"
    assert "url" not in protocol.parameters
    assert not {"access_mode", "trigger_on_start", "trigger_on_alarm", "action_kind",
        "process_workflow_id", "action_instructions"} & protocol.connection_parameters.keys()


@pytest.mark.asyncio
async def test_provider_composes_mail_calendar_and_keeps_connections_isolated(db):
    provider = await tool_service.create_tool(ToolCreate(code="synthetic-provider", label="Synthetic provider",
        mail_config=ProtocolConfig(), calendar_config=ProtocolConfig()))
    public = to_public(provider)
    assert public.can_edit and public.has_mail and public.has_calendar
    assert not public.has_messenger and not public.has_file_share
    assert {"mail", "calendar"} <= native_tool_codes_for_tool(await tool_service.get_tool_by_id(provider.id))
    assert public.connection_schema.params["password"].type == "password"
    from app.tools.admin_service import list_tools
    from app.tools.admin_contracts import AdministrationContext
    catalogue = await list_tools(AdministrationContext(), capability="mail")
    assert provider.id in {item["id"] for item in catalogue["items"]}
    exported = tool_service._record_to_export_dict(provider)
    copied = await tool_service.create_tool(ToolCreate.model_validate({**exported, "code": "copied-provider"}))
    assert to_public(copied).has_mail and to_public(copied).has_calendar
    await tool_service.update_global_params(provider.id, ToolGlobalParamsUpdate(params={
        "imap_host": ToolGlobalParamUpdate(value="imap.example.test"),
        "smtp_host": ToolGlobalParamUpdate(value="smtp.example.test"),
    }))
    title = Title(label="Synthetic", gender="N")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"protocol-agent-{i}", first_name="Synthetic", last_name=str(i)) for i in range(2)]
    db.add_all(agents)
    await db.flush()
    connections = [Connection(tool_id=provider.id, agent_id=agent.id, active=True) for agent in agents]
    db.add_all(connections)
    await db.flush()
    for index, connection in enumerate(connections):
        await connection_service.set_params_bulk(connection.id,
            {"email_address": f"box-{index}@example.org", "password": f"synthetic-password-{index}"})
        config = await resolve_connection(connection.id, require_active=True)
        assert config.agent_id == agents[index].id
        assert config.imap.host == "imap.example.test"
        assert str(config.email_address) == f"box-{index}@example.org"
        assert config.smtp.password.get_secret_value() == f"synthetic-password-{index}"
    stored = await db.scalar(select(ConnectionParam.param_value).where(
        ConnectionParam.connection_id == connections[0].id, ConnectionParam.param_name == "password"))
    assert stored != "synthetic-password-0" and get_encryption_service().is_encrypted(stored)

    mapping = {"email_address": "email_address", "imap_username": "email_address", "imap_password": "password",
        "smtp_username": "relay_login", "smtp_password": "relay_secret", "allowed_mailboxes": "folder_access", "approver_user_id": ""}
    await tool_service.update_tool(provider.id, ToolUpdate(connection_schema=ConnectionSchema.model_validate({"params": {
        **provider.connection_schema["params"], "relay_login": {"type": "string"}, "relay_secret": {"type": "password"},
        "folder_access": {"type": "string", "required": False, "widget": "mail_folder_tree"}}}),
        mail_config=ProtocolConfig(param_map=mapping)))
    await connection_service.set_params_bulk(connections[0].id, {"relay_login": "relay-account",
        "relay_secret": "synthetic-relay-secret", "folder_access": '["INBOX","Projects/Active"]'})
    separate = await resolve_connection(connections[0].id, require_active=True)
    assert separate.imap.username == "box-0@example.org" and separate.smtp.username == "relay-account"
    assert separate.imap.password.get_secret_value() == "synthetic-password-0"
    assert separate.smtp.password.get_secret_value() == "synthetic-relay-secret"
    assert separate.allowed_mailboxes == ("INBOX", "Projects/Active")
    assert to_public(provider).connection_schema.params["folder_access"].widget == "mail_folder_tree"
    assert to_public(provider).mail_config.param_map["smtp_password"] == "relay_secret"
    encrypted_relay = await db.scalar(select(ConnectionParam.param_value).where(
        ConnectionParam.connection_id == connections[0].id, ConnectionParam.param_name == "relay_secret"))
    assert get_encryption_service().is_encrypted(encrypted_relay)
    with pytest.raises(ValueError, match="connection parameter"):
        await tool_service.update_tool(provider.id, ToolUpdate(mail_config=ProtocolConfig(param_map={**mapping, "smtp_password": "relay_login"})))
    assert (await resolve_connection(connections[0].id)).smtp.password.get_secret_value() == "synthetic-relay-secret"

    other = await tool_service.create_tool(ToolCreate.model_validate({"code": "second-provider", "label": "Second provider",
        "connection_schema": {"params": {"login": {"type": "string"}, "password": {"type": "password"}}},
        "mail_config": {"settings": {"imap_host": "imap.other.example.test", "smtp_host": "smtp.other.example.test"},
            "param_map": {"email_address": "login", "imap_username": "login", "imap_password": "password",
                "smtp_username": "login", "smtp_password": "password", "allowed_mailboxes": "", "approver_user_id": ""}},
        "file_share_config": {"service": "nextcloud", "base_url": "https://files.example.test", "param_map": {"login": "login", "password": "password"}},
        "messenger_config": {"service": "nextcloud_talk", "settings": {"base_url": "https://talk.example.test"}, "param_map": {"login": "login", "password": "password"}},
        "mcp_config": {"type": "http", "url": "https://mcp.example.test", "auth": {"type": "basic", "login_param": "login", "password_param": "password"}},
        "rest_config": {"base_url": "https://api.example.test", "auth": {"type": "basic", "login_param": "login", "password_param": "password"}}}))
    assert len(other.capabilities) == 5
    assert {name for name in to_public(other).connection_schema.params if not name.startswith("tools.")} == {"login", "password"}
    shared = Connection(tool_id=other.id, agent_id=agents[0].id, active=True)
    db.add(shared)
    await db.flush()
    await connection_service.set_params_bulk(shared.id, {"login": "shared@example.org", "password": "synthetic-shared-secret"})
    mutualized = await resolve_connection(shared.id, require_active=True)
    assert mutualized.imap.host == "imap.other.example.test" and mutualized.smtp.host == "smtp.other.example.test"
    assert str(mutualized.email_address) == mutualized.imap.username == mutualized.smtp.username == "shared@example.org"
    assert mutualized.imap.password.get_secret_value() == mutualized.smtp.password.get_secret_value() == "synthetic-shared-secret"
    await db.commit()
    with pytest.raises(ValueError, match="exact active mail connection"):
        await resolve_mail_connection(agents[0].id)
    token = bind_protocol_connection("mail", agents[0].id, connections[0].id)
    try:
        assert (await resolve_mail_connection(agents[0].id)).connection_id == connections[0].id
        with pytest.raises(ValueError, match="another agent"):
            foreign = bind_protocol_connection("mail", agents[1].id, connections[0].id)
            try:
                await resolve_mail_connection(agents[1].id)
            finally:
                reset_protocol_connection(foreign)
    finally:
        reset_protocol_connection(token)
    await tool_service.update_tool(provider.id, ToolUpdate(mail_config=None))
    updated = await tool_service.get_tool_by_id(provider.id)
    assert "mail" not in native_tool_codes_for_tool(updated)
    assert "calendar" in native_tool_codes_for_tool(updated)
    with pytest.raises(ValueError, match="not a Mail connection"):
        await resolve_connection(connections[0].id, require_active=True)


@pytest.mark.asyncio
async def test_protocol_upgrade_preserves_legacy_connections_secrets_and_calendar_history(db):
    transitions = SchemaTransitionSet(added_columns=frozenset({"tools.mail_config", "tools.calendar_config"}))
    assert _introduces_protocols(transitions)
    assert not _introduces_protocols(SchemaTransitionSet())
    legacy_mail = Tool(code="mail", label="Existing mailbox provider", connection_schema={"params": {"password": {"type": "password"}}},
        messenger_config={"service": "mail"}, file_share_config={"service": "mail", "base_url": ""},
        global_params={"imap_host": {"value": "imap.example.test", "forced": True}})
    legacy_calendar = Tool(code="calendar", label="Existing calendar provider", global_params={})
    title = Title(label="Migration", gender="N")
    db.add_all([legacy_mail, legacy_calendar, title])
    await db.flush()
    agent = Agent(title_id=title.id, code="migration-protocol-agent", first_name="Synthetic", last_name="Migration")
    db.add(agent)
    await db.flush()
    mail = Connection(tool_id=legacy_mail.id, agent_id=agent.id, active=False)
    calendar = Connection(tool_id=legacy_calendar.id, agent_id=agent.id, active=True)
    db.add_all([mail, calendar])
    await db.flush()
    secret = get_encryption_service().encrypt("synthetic-migration-password")
    db.add(ConnectionParam(connection_id=mail.id, param_name="password", param_value=secret))
    feed = CalendarFeed(connection_id=calendar.id, label="Synthetic retained calendar",
        url_encrypted=get_encryption_service().encrypt("https://calendar.example.test/private.ics"))
    db.add(feed)
    global_policy = ToolFunctionState(tool_id=legacy_mail.id, function_name="mail_send", state="ask", enabled=False)
    local_policy = ConnectionFunctionState(connection_id=mail.id, function_name="mail_get", state="disabled", enabled=False)
    delivery = MailOutboundDelivery(connection_id=mail.id, agent_id=agent.id, agent_label="Synthetic Migration",
        sender_address="migration@example.org", idempotency_key="protocol-migration-receipt",
        payload_fingerprint="a" * 64, rfc_message_id="<migration@example.org>",
        ai_disclosure_version="synthetic", status="sent")
    db.add_all([global_policy, local_policy, delivery])
    await db.flush()
    original = (mail.id, calendar.id, feed.id, feed.url_encrypted, legacy_mail.global_params)
    assert not await _legacy_tools_converted(db, transitions)
    await _convert_legacy_tools(db, transitions)
    await _convert_legacy_tools(db, transitions)
    assert await _legacy_tools_converted(db, transitions)
    assert (mail.id, calendar.id, feed.id, feed.url_encrypted, legacy_mail.global_params) == original
    assert not mail.active and calendar.active
    assert (await db.scalar(select(ConnectionParam.param_value).where(ConnectionParam.connection_id == mail.id))) == secret
    assert to_public(legacy_mail).can_edit and to_public(legacy_calendar).can_edit
    assert legacy_mail.mail_config == {} and legacy_calendar.calendar_config == {}
    assert legacy_mail.messenger_config is None and legacy_mail.file_share_config is None
    await db.refresh(global_policy)
    await db.refresh(local_policy)
    await db.refresh(delivery)
    assert global_policy.state == "ask" and local_policy.state == "disabled"
    assert delivery.connection_id == mail.id and delivery.status == "sent"
    with pytest.raises(ValueError):
        await tool_service.update_tool(legacy_mail.id, ToolUpdate(file_share_config=FileShareConfig(
            service="nextcloud", base_url="https://files.example.test")))
    assert legacy_mail.file_share_config is None
    await tool_service.update_tool(legacy_mail.id, ToolUpdate(label="Renamed provider", mail_config=None))
    from app.tools.mandatory_tools import sync_mandatory_tools
    await sync_mandatory_tools()
    await db.refresh(legacy_mail)
    assert legacy_mail.label == "Renamed provider" and legacy_mail.mail_config is None


@pytest.mark.asyncio
async def test_disabling_mail_preserves_credentials_referenced_by_another_protocol(db):
    tool = await tool_service.create_tool(ToolCreate(code="shared-credentials", label="Synthetic shared service",
        mail_config=ProtocolConfig(), rest_config=RestConfig(base_url="https://api.example.test",
            auth=RestAuth(type="basic", login_param="email_address", password_param="password"))))
    await tool_service.update_global_params(tool.id, ToolGlobalParamsUpdate(params={
        "password": ToolGlobalParamUpdate(value="synthetic-retained-password"),
    }))
    retained = tool.global_params["password"]
    await tool_service.update_tool(tool.id, ToolUpdate(mail_config=None, connection_schema=ConnectionSchema()))
    await db.refresh(tool)
    schema = tool_service.connection_schema_for_tool(tool)["params"]
    assert "imap_host" not in schema
    assert schema["password"]["type"] == "password" and "email_address" in schema
    assert tool.global_params["password"] == retained
    assert to_public(tool).has_api and not to_public(tool).has_mail
