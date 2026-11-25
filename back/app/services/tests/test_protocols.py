"""Provider Services compose protocols while preserving connection ownership and upgrades."""

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionParam, ConnectionFunctionState, ServiceFunctionState, connection_service
from app.services import service, native_service_codes_for_service
from app.services.models import Service
from app.services.protocols import ProtocolConfig, bind_protocol_connection, protocol_parameters, reset_protocol_connection
from app.services.schemas import ServiceCreate, ServiceUpdate, ServiceGlobalParamsUpdate, ServiceGlobalParamUpdate, FileShareConfig, ConnectionSchema, McpAuth, McpConfig
from app.services.projections import to_public
from app.services.protocol_migration import _convert_legacy_tools, _introduces_protocols, _legacy_tools_converted
from app.calendar.models import CalendarFeed
from bridge.mail.models import MailOutboundDelivery
from bridge.mail.connection_service import resolve_connection, resolve_mail_connection
from core.dbadmin import SchemaTransitionSet
from core.util import get_encryption_service
from app.services.rest_contracts import RestAuth, RestConfig


def test_mail_advertises_an_optional_integer_connection_polling_interval():
    from app.services.capabilities import supported_capabilities

    mail = next(item for item in supported_capabilities() if item.code == "mail").protocols[0]
    interval = mail.connection_parameters["poll_interval_minutes"]
    assert interval["parameter"] == "poll_interval_minutes"
    assert interval["definition"]["type"] == "integer"
    assert not interval["definition"]["required"]
    assert "poll_interval_s" not in mail.parameters
    assert "poll_interval_s" not in mail.connection_parameters


def test_ical_advertises_standard_connection_parameter_bindings():
    from app.services.capabilities import supported_capabilities

    calendar = next(item for item in supported_capabilities() if item.code == "calendar")
    protocol = calendar.protocols[0]
    assert protocol.connection_parameters["url"]["parameter"] == "url"
    assert protocol.connection_parameters["url"]["definition"]["type"] == "password"
    assert protocol.connection_parameters["username"]["parameter"] == "login"
    assert protocol.connection_parameters["password"]["parameter"] == "password"
    assert protocol.connection_parameters["sync_interval_hours"]["definition"]["type"] == "integer"
    assert protocol.connection_parameters["sync_interval_hours"]["definition"]["default"] == "2"
    assert "sync_interval_hours" not in protocol.parameters
    assert "url" not in protocol.parameters
    assert not {"access_mode", "trigger_on_start", "trigger_on_alarm", "action_kind",
        "process_workflow_id", "action_instructions"} & protocol.connection_parameters.keys()


@pytest.mark.asyncio
async def test_basic_mcp_keeps_its_password_parameter_until_authentication_is_disabled(db):
    mcp = McpConfig(type="http", url="https://mcp.example.test", auth=McpAuth(type="basic"))
    provider = await service.create_service(ServiceCreate(code="synthetic-basic-mcp", label="Synthetic Basic MCP", mcp_config=mcp))
    assert to_public(provider).connection_schema.params["password"].type == "password"
    updated = await service.update_service(provider.id, ServiceUpdate(
        mcp_config=mcp.model_copy(update={"auth": McpAuth()}), expected_mcp_auth_type="basic",
    ))
    assert updated is not None
    assert "password" not in to_public(updated).connection_schema.params


@pytest.mark.asyncio
async def test_open_mcp_does_not_invent_a_password_parameter(db):
    mcp = McpConfig(type="http", url="https://mcp.example.test/mcp")
    provider = await service.create_service(ServiceCreate(code="synthetic-open-mcp", label="Synthetic open MCP", mcp_config=mcp))
    options = await connection_service.connection_tool_options()
    option = next(item for item in options if item["id"] == provider.id)
    assert "password" not in option["connection_schema"]["params"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "bearer", "header", "query"])
async def test_rest_projects_only_declared_connection_parameters(db, mode):
    declared = {"token": {"type": "password"}} if mode != "none" else {}
    provider = await service.create_service(ServiceCreate(code=f"synthetic-rest-{mode}", label="Synthetic REST",
        rest_config=RestConfig(base_url="https://api.example.test", auth=RestAuth(type=mode, param="token")),
        connection_schema=ConnectionSchema.model_validate({"params": declared})))
    assert provider.rest_config["auth"]["password_param"] == "password"
    assert set(to_public(provider).connection_schema.params) == declared.keys()

    # Earlier saves could materialize the unrelated Mail definition in the Service.
    provider.connection_schema = {"params": {**declared, "password": protocol_parameters("mail")["password"]}}
    await db.flush()
    option = next(item for item in await connection_service.connection_tool_options() if item["id"] == provider.id)
    assert set(option["connection_schema"]["params"]) == declared.keys()
    updated = await service.update_service(provider.id, ServiceUpdate(label="Renamed REST",
        connection_schema=ConnectionSchema.model_validate({"params": declared})))
    assert set(updated.connection_schema["params"]) == declared.keys()
    with pytest.raises(ValueError, match="declared connection parameters"):
        await service.update_service(provider.id, ServiceUpdate(
            rest_config=RestConfig(base_url="https://api.example.test", auth=RestAuth(type="bearer", param="password"))))


@pytest.mark.asyncio
async def test_provider_composes_mail_calendar_and_keeps_connections_isolated(db):
    provider = await service.create_service(ServiceCreate(code="synthetic-provider", label="Synthetic provider",
        mail_config=ProtocolConfig(), calendar_config=ProtocolConfig()))
    public = to_public(provider)
    assert public.can_edit and public.has_mail and public.has_calendar
    assert public.has_function_permissions
    assert not public.has_messenger and not public.has_file_share
    assert {"mail", "calendar"} <= native_service_codes_for_service(await service.get_service_by_id(provider.id))
    assert public.connection_schema.params["password"].type == "password"
    from app.services.admin_service import list_services
    from app.services.admin_contracts import AdministrationContext
    catalogue = await list_services(AdministrationContext(), capability="mail")
    assert provider.id in {item["id"] for item in catalogue["items"]}
    exported = service._record_to_export_dict(provider)
    copied = await service.create_service(ServiceCreate.model_validate({**exported, "code": "copied-provider"}))
    assert to_public(copied).has_mail and to_public(copied).has_calendar
    await service.update_global_params(provider.id, ServiceGlobalParamsUpdate(params={
        "imap_host": ServiceGlobalParamUpdate(value="imap.example.test"),
        "smtp_host": ServiceGlobalParamUpdate(value="smtp.example.test"),
    }))
    title = Title(label="Synthetic", gender="N")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"protocol-agent-{i}", first_name="Synthetic", last_name=str(i)) for i in range(2)]
    db.add_all(agents)
    await db.flush()
    connections = [Connection(service_id=provider.id, agent_id=agent.id, active=True) for agent in agents]
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
    await service.update_service(provider.id, ServiceUpdate(connection_schema=ConnectionSchema.model_validate({"params": {
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
        await service.update_service(provider.id, ServiceUpdate(mail_config=ProtocolConfig(param_map={**mapping, "smtp_password": "relay_login"})))
    assert (await resolve_connection(connections[0].id)).smtp.password.get_secret_value() == "synthetic-relay-secret"

    other = await service.create_service(ServiceCreate.model_validate({"code": "second-provider", "label": "Second provider",
        "connection_schema": {"params": {"login": {"type": "string"}, "password": {"type": "password"},
            "poll_interval_minutes": {"type": "integer", "required": False}}},
        "mail_config": {"settings": {"imap_host": "imap.other.example.test", "smtp_host": "smtp.other.example.test"},
            "param_map": {"email_address": "login", "imap_username": "login", "imap_password": "password",
                "smtp_username": "login", "smtp_password": "password", "allowed_mailboxes": "", "approver_user_id": "",
                "poll_interval_minutes": "poll_interval_minutes"}},
        "file_share_config": {"service": "nextcloud", "base_url": "https://files.example.test", "param_map": {"login": "login", "password": "password"}},
        "messenger_config": {"service": "nextcloud_talk", "settings": {"base_url": "https://talk.example.test"}, "param_map": {"login": "login", "password": "password"}},
        "mcp_config": {"type": "http", "url": "https://mcp.example.test", "auth": {"type": "basic", "login_param": "login", "password_param": "password"}},
        "rest_config": {"base_url": "https://api.example.test", "auth": {"type": "basic", "login_param": "login", "password_param": "password"}}}))
    assert len(other.capabilities) == 5
    assert {name for name in to_public(other).connection_schema.params if not name.startswith("services.")} == {
        "login", "password", "poll_interval_minutes",
    }
    shared = Connection(service_id=other.id, agent_id=agents[0].id, active=True, singleton_key=None)
    second_mailbox = Connection(service_id=other.id, agent_id=agents[0].id, active=True, singleton_key=None)
    db.add_all([shared, second_mailbox])
    await db.flush()
    await connection_service.set_params_bulk(shared.id, {"login": "shared@example.org", "password": "synthetic-shared-secret"})
    await connection_service.set_params_bulk(second_mailbox.id,
        {"login": "second@example.org", "password": "synthetic-second-secret"})
    mutualized = await resolve_connection(shared.id, require_active=True)
    assert mutualized.imap.host == "imap.other.example.test" and mutualized.smtp.host == "smtp.other.example.test"
    assert str(mutualized.email_address) == mutualized.imap.username == mutualized.smtp.username == "shared@example.org"
    assert mutualized.imap.password.get_secret_value() == mutualized.smtp.password.get_secret_value() == "synthetic-shared-secret"
    assert mutualized.poll_interval_s == 600
    await connection_service.set_params_bulk(shared.id, {"poll_interval_minutes": "3"})
    assert (await resolve_connection(shared.id)).poll_interval_s == 180
    assert (await resolve_connection(second_mailbox.id)).poll_interval_s == 600
    for invalid in ("0", "1441"):
        with pytest.raises(ValueError, match="minutes between 1 and 1440"):
            await connection_service.set_params_bulk(shared.id, {"poll_interval_minutes": invalid})
    assert (await resolve_connection(shared.id)).poll_interval_s == 180
    await connection_service.set_params_bulk(shared.id, {"poll_interval_minutes": ""})
    assert (await resolve_connection(shared.id)).poll_interval_s == 600
    await service.update_service(other.id, ServiceUpdate(mail_config=ProtocolConfig(
        settings={**other.mail_config["settings"], "poll_interval_s": "240"},
        param_map=other.mail_config["param_map"],
    )))
    assert (await resolve_connection(shared.id)).poll_interval_s == 240
    await connection_service.set_params_bulk(shared.id, {"poll_interval_minutes": "3"})
    assert (await resolve_connection(shared.id)).poll_interval_s == 180
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
    await service.update_service(provider.id, ServiceUpdate(mail_config=None))
    updated = await service.get_service_by_id(provider.id)
    assert "mail" not in native_service_codes_for_service(updated)
    assert "calendar" in native_service_codes_for_service(updated)
    with pytest.raises(ValueError, match="not a Mail connection"):
        await resolve_connection(connections[0].id, require_active=True)


@pytest.mark.asyncio
async def test_protocol_upgrade_preserves_legacy_connections_secrets_and_calendar_history(db):
    from app.services.mandatory_services import sync_mandatory_services

    transitions = SchemaTransitionSet(added_columns=frozenset({"services.mail_config", "services.calendar_config"}))
    assert _introduces_protocols(transitions)
    assert not _introduces_protocols(SchemaTransitionSet())
    legacy_mail = Service(code="mail", label="Existing mailbox provider", connection_schema={"params": {"password": {"type": "password"}}},
        messenger_config={"service": "mail"}, file_share_config={"service": "mail", "base_url": ""},
        global_params={"imap_host": {"value": "imap.example.test", "forced": True}})
    legacy_calendar = Service(code="calendar", label="Existing calendar provider", global_params={})
    native = (await db.scalars(select(Service).where(Service.code == "calendar"))).one()
    native.code = "agenda"
    native_id = native.id
    await db.flush()
    title = Title(label="Migration", gender="N")
    db.add_all([legacy_mail, legacy_calendar, title])
    await db.flush()
    agent = Agent(title_id=title.id, code="migration-protocol-agent", first_name="Synthetic", last_name="Migration")
    db.add(agent)
    await db.flush()
    mail = Connection(service_id=legacy_mail.id, agent_id=agent.id, active=False)
    calendar = Connection(service_id=legacy_calendar.id, agent_id=agent.id, active=True)
    db.add_all([mail, calendar])
    await db.flush()
    secret = get_encryption_service().encrypt("synthetic-migration-password")
    db.add(ConnectionParam(connection_id=mail.id, param_name="password", param_value=secret))
    feed = CalendarFeed(connection_id=calendar.id, label="Synthetic retained calendar",
        url_encrypted=get_encryption_service().encrypt("https://calendar.example.test/private.ics"))
    db.add(feed)
    global_policy = ServiceFunctionState(service_id=legacy_mail.id, function_name="mail_send", state="ask", enabled=False)
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
    for _ in range(2):
        await sync_mandatory_services()
        await db.refresh(native)
        await db.refresh(legacy_calendar)
        assert (native.id, native.code, native.label) == (native_id, "calendar", "Agenda")
        assert native.calendar_config is None
        assert legacy_calendar.code == "calendar-provider"
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
        await service.update_service(legacy_mail.id, ServiceUpdate(file_share_config=FileShareConfig(
            service="nextcloud", base_url="https://files.example.test")))
    assert legacy_mail.file_share_config is None
    await service.update_service(legacy_mail.id, ServiceUpdate(label="Renamed provider", mail_config=None))
    from app.services.mandatory_services import sync_mandatory_services
    await sync_mandatory_services()
    await db.refresh(legacy_mail)
    assert legacy_mail.label == "Renamed provider" and legacy_mail.mail_config is None


@pytest.mark.asyncio
async def test_disabling_mail_preserves_credentials_referenced_by_another_protocol(db):
    tool = await service.create_service(ServiceCreate(code="shared-credentials", label="Synthetic shared service",
        mail_config=ProtocolConfig(), rest_config=RestConfig(base_url="https://api.example.test",
            auth=RestAuth(type="basic", login_param="email_address", password_param="password"))))
    await service.update_global_params(tool.id, ServiceGlobalParamsUpdate(params={
        "password": ServiceGlobalParamUpdate(value="synthetic-retained-password"),
    }))
    retained = tool.global_params["password"]
    await service.update_service(tool.id, ServiceUpdate(mail_config=None, connection_schema=ConnectionSchema()))
    await db.refresh(tool)
    schema = service.connection_schema_for_service(tool)["params"]
    assert "imap_host" not in schema
    assert schema["password"]["type"] == "password" and "email_address" in schema
    assert not to_public(tool).connection_schema.params["password"].builtin
    assert tool.global_params["password"] == retained
    assert to_public(tool).has_api and not to_public(tool).has_mail
