"""One technical protocol per functional capability, including external identifiers."""

import pytest
from uuid import uuid4
from pydantic import ValidationError
from sqlalchemy import select

from app.services import service
from app.services.capabilities import supported_capabilities
from app.services.capability_migration import _introduces_selections, _populate_selections, _selections_populated
from app.services.models import Service
from app.services.projections import to_public
from app.services.schemas import ServiceCreate, ServiceUpdate
from core.dbadmin import SchemaTransitionSet


@pytest.mark.parametrize("values", [["http.mcp", "sse.mcp"], ["nextcloud.file_share", "samba.file_share"],
    ["custom.sensors", "another.sensors"], ["sensors", "sensors"], [""]])
def test_rejects_duplicate_functional_capabilities(values):
    for schema in (ServiceCreate, ServiceUpdate):
        with pytest.raises(ValidationError):
            schema.model_validate({"code": "synthetic", "label": "Synthetic", "capabilities": values})


@pytest.mark.asyncio
async def test_explicit_selections_preserve_custom_values_across_edits_exports_and_reimports(db):
    selections = ["imap_smtp.mail", "caldav.calendar", "vendor.custom_sensors", "Unclassified extension"]
    tool = await service.create_service(ServiceCreate(code="capability-provider", label="Synthetic provider", capabilities=selections))
    assert to_public(tool).capabilities == selections
    assert to_public(tool).has_mail and to_public(tool).has_calendar
    await service.update_service(tool.id, ServiceUpdate(label="Renamed provider"))
    assert to_public(tool).capabilities == selections
    exported = service.serialize_to_yaml(tool)
    copy, created = await service.import_from_yaml_string(exported.replace("code: capability-provider", "code: capability-copy"))
    assert created and to_public(copy).capabilities == selections

    await service.update_service(tool.id, ServiceUpdate(capabilities=selections[1:]))
    await db.refresh(tool)
    assert tool.mail_config is None and tool.calendar_config == {}
    assert to_public(tool).capabilities == selections[1:]
    # Legacy configuration clients still add/remove their own settings and retain extensions.
    await service.update_service(tool.id, ServiceUpdate(calendar_config=None))
    assert to_public(tool).capabilities == selections[2:]
    await service.update_service(tool.id, ServiceUpdate(mail_config={}))
    assert set(to_public(tool).capabilities) == {"imap_smtp.mail", *selections[2:]}


@pytest.mark.asyncio
async def test_selection_configuration_mismatch_cannot_change_saved_protocol(db):
    tool = await service.create_service(ServiceCreate(code="capability-mcp", label="Synthetic MCP",
        capabilities=["http.mcp"], mcp_config={"type": "http", "url": "https://mcp.example.test"}))
    with pytest.raises(ValueError, match="does not match"):
        await service.update_service(tool.id, ServiceUpdate(capabilities=["sse.mcp"]))
    await db.refresh(tool)
    assert tool.capabilities == ["http.mcp"] and tool.mcp_config["type"] == "http"
    await service.update_service(tool.id, ServiceUpdate(capabilities=["sse.mcp"],
        mcp_config={"type": "sse", "url": "https://mcp.example.test/events"}))
    assert tool.capabilities == ["sse.mcp"] and tool.mcp_config["type"] == "sse"
    await service.update_service(tool.id, ServiceUpdate(capabilities=[]))
    assert tool.capabilities == [] and tool.mcp_config is None


@pytest.mark.asyncio
async def test_capability_backfill_keeps_existing_configuration_and_is_idempotent(db):
    delta = SchemaTransitionSet(added_columns=frozenset({"services.capabilities"}))
    assert _introduces_selections(delta) and not _introduces_selections(SchemaTransitionSet())
    tool = Service(code="capability-migration", label="Existing synthetic service",
        mcp_config={"type": "sse", "url": "https://mcp.example.test", "auth": {"token": "opaque-encrypted-value"}},
        file_share_config={"service": "vendor_share", "base_url": "https://files.example.test"},
        mail_config={}, calendar_config={}, global_params={"host": {"value": "imap.example.test", "forced": True}})
    db.add(tool)
    await db.flush()
    original = (tool.id, tool.label, tool.mcp_config.copy(), tool.file_share_config.copy(), tool.global_params.copy())
    assert not await _selections_populated(db, delta)
    await _populate_selections(db, delta)
    await _populate_selections(db, delta)
    assert await _selections_populated(db, delta)
    assert tool.capabilities == ["sse.mcp", "vendor_share.file_share", "imap_smtp.mail", "caldav.calendar"]
    assert (tool.id, tool.label, tool.mcp_config, tool.file_share_config, tool.global_params) == original
    assert await db.scalar(select(Service.id).where(Service.id == tool.id)) == original[0]


def test_catalogue_exposes_functional_strings_and_translatable_standard_labels():
    catalogue = {item.code: item for item in supported_capabilities()}
    assert set(catalogue) == {"mcp", "api", "file_share", "messenger", "listener", "mail", "calendar"}
    assert {item.value for item in catalogue["mcp"].protocols} == {"http.mcp", "sse.mcp", "stdio.mcp"}
    for capability in catalogue.values():
        assert capability.label == f"services.capabilityLabels.{capability.code}"
        for protocol in capability.protocols:
            assert protocol.capability == capability.code
            if protocol.builtin:
                assert protocol.label.startswith("services.protocolLabels.")
    assert not any(item.value in {"mail.messenger", "internal.messenger"} for item in catalogue["messenger"].protocols)
    assert {"imap_host", "smtp_host"} <= catalogue["mail"].protocols[0].parameters.keys()
    assert not {"email_address", "password", "allowed_mailboxes", "approver_user_id"} & catalogue["mail"].protocols[0].parameters.keys()
    bindings = catalogue["mail"].protocols[0].connection_parameters
    assert bindings["imap_password"]["parameter"] == bindings["smtp_password"]["parameter"] == "password"
    assert bindings["imap_username"]["parameter"] == bindings["smtp_username"]["parameter"] == "login"
    assert bindings["email_address"]["parameter"] == "email"
    assert bindings["allowed_mailboxes"]["parameter"] == "folders"
    assert bindings["allowed_mailboxes"]["definition"]["widget"] == "mail_folder_tree"
    assert {"timezone", "workday_start", "slot_step_minutes"} <= catalogue["calendar"].protocols[0].parameters.keys()


@pytest.mark.asyncio
async def test_protocol_editor_requires_privileges_and_saves_settings_atomically(client):
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user import UserModel
    from core.user.user_service import encrypt_password

    path = "/api/services/capabilities"
    assert (await client.get(path)).status_code == 401
    suffix = uuid4().hex
    password = "synthetic-capability-password"
    actors = {}
    for privilege_code, expected in ((None, 403), ("SERVICE_ACCESS", 200), ("SERVICE_EDIT", 200)):
        email = f"capability-{privilege_code}-{suffix}@example.com"
        async with get_db_session() as db:
            privilege = await db.scalar(select(Privilege).where(Privilege.code == privilege_code)) if privilege_code else None
            role = Role(code=f"capability-{privilege_code}-{suffix}", privileges=[privilege] if privilege else [])
            user = UserModel(email=email, hashed_password=encrypt_password(password), is_active=True)
            db.add_all([role, user])
            await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        actors[privilege_code] = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await client.get(path, headers=actors[privilege_code])
        assert response.status_code == expected, response.text
        if expected == 200:
            assert "imap_smtp.mail" in {protocol["value"] for item in response.json() for protocol in item["protocols"]}

    definition = {"code": f"inline-provider-{suffix}", "label": "Synthetic inline provider",
        "capabilities": ["imap_smtp.mail", "caldav.calendar"],
        "connection_schema": {"params": {"login": {"type": "string"}, "password": {"type": "password"}}},
        "mail_config": {"settings": {"imap_host": "imap.example.test", "smtp_host": "smtp.example.test", "smtp_port": "587"},
            "param_map": {"email_address": "login", "imap_username": "login", "imap_password": "password",
                "smtp_username": "login", "smtp_password": "password", "allowed_mailboxes": "", "approver_user_id": ""}},
        "calendar_config": {"settings": {"timezone": "Europe/Paris"}}}
    invalid = {**definition, "mail_config": {**definition["mail_config"],
        "settings": {**definition["mail_config"]["settings"], "smtp_port": "invalid"}}}
    unmapped = {**definition, "mail_config": {**definition["mail_config"], "param_map": {}}}
    assert (await client.post("/api/services", json=unmapped, headers=actors["SERVICE_EDIT"])).status_code == 422
    assert (await client.post("/api/services", json=invalid, headers=actors["SERVICE_EDIT"])).status_code == 422
    # A rejected save must not leave a partially created provider behind.
    response = await client.post("/api/services", json=definition, headers=actors["SERVICE_EDIT"])
    assert response.status_code == 201, response.text
    public = response.json()
    assert public["mail_config"] == definition["mail_config"]
    assert public["calendar_config"]["settings"] == definition["calendar_config"]["settings"]
    assert {name for name in public["connection_schema"]["params"] if not name.startswith("services.")} == {"login", "password"}
    tool_path = f"/api/services/{public['id']}"
    assert (await client.put(tool_path, json={"label": "Forbidden"}, headers=actors["SERVICE_ACCESS"])).status_code == 403
    failed = await client.put(tool_path, headers=actors["SERVICE_EDIT"], json={"label": "Must not persist",
        "mail_config": invalid["mail_config"]})
    assert failed.status_code == 422
    retained = (await client.get(tool_path, headers=actors["SERVICE_EDIT"])).json()
    assert retained["label"] == definition["label"] and retained["mail_config"] == definition["mail_config"]
    updated = await client.put(tool_path, headers=actors["SERVICE_EDIT"], json={"label": "Renamed synthetic provider",
        "calendar_config": {"settings": {"timezone": "Europe/London"}}})
    assert updated.status_code == 200, updated.text
    assert updated.json()["mail_config"] == definition["mail_config"]
    assert updated.json()["calendar_config"]["settings"]["timezone"] == "Europe/London"
