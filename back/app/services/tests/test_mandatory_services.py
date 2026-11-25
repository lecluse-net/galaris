from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.services import mandatory_services, service
from app.services import dbadmin as tools_dbadmin
from app.services.conversation_catalog import read_conversation_tools
from app.services.mcp_loader import (
    BUILTIN_CONVERSATION_TOOLS,
    mcp_tools_by_service_code,
    native_service_codes_for_service,
)
from app.services.models import Service
import core.dbadmin as core_dbadmin


@pytest.mark.asyncio
async def test_sync_integrated_connections_delegates_to_dbadmin_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()
    tools_dataset = SimpleNamespace(key="app.services.mandatory.services")
    connections_dataset = SimpleNamespace(key="app.services.mandatory.connections")
    reconcile = AsyncMock(return_value=SimpleNamespace(inserted=1))
    monkeypatch.setattr(mandatory_services, "get_db", lambda: db)
    monkeypatch.setattr(
        tools_dbadmin,
        "datasets",
        lambda **_kwargs: (tools_dataset, connections_dataset),
    )
    monkeypatch.setattr(core_dbadmin, "reconcile_dataset", reconcile)

    created = await mandatory_services.sync_integrated_service_connections(agent_id=7)

    assert created == 1
    reconcile.assert_awaited_once_with(db, connections_dataset)


@pytest.mark.asyncio
@pytest.mark.parametrize("service_code", [
    "browser", "multimedia", "skills", "contact", "task",
    "galaris", "chat", "memory", "document", "file_sharing",
])
async def test_connection_dataset_is_idempotent_and_preserves_admin_activation(
    db: AsyncSession,
    service_code: str,
) -> None:
    title = Title(label="Dataset", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code="dataset-agent",
        first_name="Data",
        last_name="Source",
        agent_driver="internal",
    )
    db.add(agent)
    await db.commit()

    first = await mandatory_services.sync_integrated_service_connections(agent.id)
    await db.commit()
    integrated_connection = (
        await db.execute(
            select(Connection)
            .join(Service, Service.id == Connection.service_id)
            .where(Connection.agent_id == agent.id, Service.code == service_code)
        )
    ).scalar_one()
    topic_connection = (
        await db.execute(
            select(Connection)
            .join(Service, Service.id == Connection.service_id)
            .where(Connection.agent_id == agent.id, Service.code == "topic")
        )
    ).scalar_one_or_none()
    assert topic_connection is None
    assert integrated_connection.active is True
    tool = await db.get(Service, integrated_connection.service_id)
    assert tool is not None
    if service_code == "skills":
        from app.skill.interface import get_agent_scope
        from app.skill.contracts import SkillScope
        assert await get_agent_scope(agent.id) == SkillScope.PERSONAL
    if service_code == "chat":
        from app.services.mcp_loader import list_enabled_native_mcp_definitions
        definitions = await list_enabled_native_mcp_definitions(agent.id, runtime="internal", conversation_only=True)
        assert {"process_pending", "process_respond"} <= {item.name for item in definitions}
    integrated_connection.active = False
    await db.commit()

    second = await mandatory_services.sync_integrated_service_connections(agent.id)
    await db.commit()
    await db.refresh(integrated_connection)

    assert first > 0
    assert second == 0
    assert integrated_connection.active is (service_code in mandatory_services.SYSTEM_SERVICE_CODES)


def test_tool_defaults_enable_personal_skills_processes_and_goals() -> None:
    specs = {spec.code: spec for spec in mandatory_services.INTEGRATED_SERVICE_SPECS}

    assert {"team_list", "team_members"} <= set(specs["agent"].mcp_tools)
    assert {"task_get", "task_run"} <= set(specs["task"].mcp_tools)
    assert {"contact", "task"} <= mandatory_services.DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES
    assert {
        "file_schemes",
        "file_list",
        "file_info",
        "file_search",
        "file_read",
        "file_create",
        "file_write",
        "file_append",
        "file_edit",
        "file_copy",
        "file_move",
        "file_rename",
        "file_delete",
        "file_to_pdf",
        "dataset_query",
    } == set(specs["file_sharing"].mcp_tools)
    assert specs["file_sharing"].default_active is True
    assert set(specs["file_sharing"].mcp_tools).isdisjoint(
        specs["galaris"].mcp_tools
    )
    assert {
        "task_list_running",
        "goal_list",
        "goal_get",
        "goal_get_suivi",
    }.isdisjoint(specs["galaris"].mcp_tools)
    assert specs["goal"].auto_connect_agents is True
    assert specs["goal"].default_active is True
    assert set(specs["goal"].mcp_tools).isdisjoint(specs["galaris"].mcp_tools)
    assert set(specs["goal"].mcp_tools) == {
        "goal_update_suivi", "goal_run_now", "goal_ask_referrer",
        "goal_retrospective_evidence", "goal_retrospective_learn", "goal_retrospective_record",
        "goal_create",
        "goal_update",
        "goal_delete",
        "goal_pause",
        "goal_resume",
        "goal_complete",
    }
    assert specs["skills"].auto_connect_agents is True
    assert specs["skills"].default_active is True
    assert specs["process"].auto_connect_agents is True
    assert specs["process"].default_active is True
    assert {"goal", "process"} <= mandatory_services.DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES
    assert {"platform_admin", "voice", "audio", "image", "search"}.isdisjoint(specs)
    assert set(mandatory_services.ADMIN_TOOLS) <= set(specs["galaris"].mcp_tools)
    assert set(mandatory_services.CONVERSATION_INSPECTION_TOOLS + mandatory_services.VOICE_TOOLS) <= set(specs["chat"].mcp_tools)


@pytest.mark.asyncio
async def test_conversation_policy_is_fixed_for_builtin_services(db: AsyncSession) -> None:
    codes = mandatory_services.INTEGRATED_SERVICE_CODES
    services = {tool.code: tool for tool in await db.scalars(select(Service).where(Service.code.in_(codes)))}
    assert services.keys() == codes

    definitions = mcp_tools_by_service_code()
    for code, tool in services.items():
        catalog = await read_conversation_tools(tool.id)
        assert catalog is not None
        native = {
            definition.name: definition.conversation_policy != "forbidden"
            for family in native_service_codes_for_service(tool)
            for definition in definitions.get(family, ())
        }
        allowed = BUILTIN_CONVERSATION_TOOLS.get(code, frozenset())
        assert {entry.name: entry.enabled for entry in catalog.tools} == {
            name: eligible and name in allowed for name, eligible in native.items()
        }, code
        expected = {
            "calendar": {"calendar_list", "calendar_events"},
            "agent": {"agent_list", "agent_get", "team_list", "team_members", "agent_team_list"},
            "chat": native.keys() - {"chat_round_get", "voice_turn_get"},
            "document": {"document_show", "document_sharing", "document_share"},
            "skills": {"skills_list", "skill_read"},
            "multimedia": {"image_read", "audio_read", "audio_transcribe"},
            "file_sharing": {"file_schemes", "file_list", "file_info", "file_search", "file_read", "dataset_query"},
        }
        if code in expected:
            assert {entry.name for entry in catalog.tools if entry.enabled} == expected[code], code
        assert all(entry.source == "native" for entry in catalog.tools)

    tool = services["multimedia"]
    with pytest.raises(ValueError):
        await service.set_conversation_tool(tool.id, "image_generate", source="native", enabled=True)
    with pytest.raises(ValueError):
        await service.set_conversation_tool(tool.id, "image_read", source="native", enabled=False)


def test_chat_is_mandatory_and_combines_mcp_and_native_messaging() -> None:
    specs = {spec.code: spec for spec in mandatory_services.INTEGRATED_SERVICE_SPECS}
    chat = specs["chat"]

    assert chat.auto_connect_agents is True
    assert chat.default_active is True
    assert set(chat.mcp_tools) == set(mandatory_services.CHAT_TOOLS)
    assert "chat" in mandatory_services.SYSTEM_SERVICE_CODES and "conversation" not in specs
    assert chat.messenger_service == "internal"


def test_browser_package_is_configurable_and_active_by_default() -> None:
    specs = {spec.code: spec for spec in mandatory_services.INTEGRATED_SERVICE_SPECS}
    browser = specs["browser"]

    assert browser.auto_connect_agents is True
    assert browser.default_active is True
    assert "browser" in mandatory_services.DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES
    row = next(
        row for row in mandatory_services.mandatory_service_rows()
        if row["code"] == "browser"
    )
    default_output = row["connection_schema"]["params"]["default_output"]
    assert default_output["default"] == "content"
    assert default_output["required"] is False


def test_internal_connection_parameters_supply_translation_keys_and_valid_choices() -> None:
    from app.services.schemas import ConnectionParamDef

    for row in mandatory_services.mandatory_service_rows():
        for definition in row["connection_schema"]["params"].values():
            param = ConnectionParamDef.model_validate(definition)
            assert param.label.startswith("services.connectionParamLabels.")
            for option in param.options:
                assert option.label.startswith("services.connectionParamOptions.")


def test_console_host_key_is_a_write_only_connection_parameter() -> None:
    row = next(
        row for row in mandatory_services.mandatory_service_rows()
        if row["code"] == "console"
    )

    known_host_key = row["connection_schema"]["params"]["known_host_key"]
    assert known_host_key["type"] == "password"
    assert known_host_key["required"] is True
    assert "mode" not in row["connection_schema"]["params"]
    assert row["file_share_config"] == {
        "service": "console",
        "base_url": "",
        "param_map": {},
    }


def test_mail_connection_parameters_keep_transport_and_reviewer_configuration() -> None:
    from app.services.protocols import protocol_parameters
    params = protocol_parameters("mail")

    assert set(params) == {
        "email_address",
        "password",
        "imap_host",
        "imap_port",
        "imap_security",
        "allowed_mailboxes",
        "smtp_host",
        "smtp_port",
        "smtp_security",
        "connect_timeout_s",
        "operation_timeout_s",
        "poll_interval_s",
        "poll_interval_minutes",
        "max_attachment_mb",
        "max_total_attachment_mb",
        "approver_user_id",
    }


def test_administration_scopes_are_explicit_local_and_domain_bounded() -> None:
    scopes = {
        "skills": ("personal", ["usage", "personal", "team", "all"]),
        "service": ("usage", ["usage", "personal", "team", "all"]),
        "process": ("personal", ["usage", "personal", "team", "all"]),
        "goal": ("personal", ["usage", "personal", "team", "all"]),
        "calendar": ("personal", ["personal", "team", "all"]),
        "contact": ("personal", ["personal", "team", "all"]),
        "document": ("personal", ["personal", "team", "all"]),
        "task": ("personal", ["personal", "team", "all"]),
        "agent": ("usage", ["usage", "team", "all"]),
    }
    rows = {row["code"]: row for row in mandatory_services.mandatory_service_rows()}
    assert "services.management_scope" not in rows["galaris"]["connection_schema"]["params"]
    for code, (default, options) in scopes.items():
        row = rows[code]
        parameter = row["connection_schema"]["params"]["services.management_scope"]
        assert parameter["default"] == default
        assert [item["value"] for item in parameter["options"]] == options
        assert "services.management_scope" not in row["global_params"]

    from app.services.mcp_loader import load_mcp_tools

    inspections = {
        "chat_round_get": "chat", "voice_turn_get": "chat",
        "llm_call": "galaris", "llm_calls": "galaris", "incident_get": "galaris", "incidents_list": "galaris",
    }
    definitions = load_mcp_tools()
    assert len({definition.name for definition in definitions}) == len(definitions)
    assert {d.name: d.service_code for d in definitions if d.execution_inspection} == inspections
    for definition in definitions:
        expected = "service" if definition.name in inspections else (
            definition.service_code if definition.service_code in scopes else None
        )
        assert definition.management_scope_service == expected, definition.name
    for spec in mandatory_services.INTEGRATED_SERVICE_SPECS:
        assert {d.name for d in definitions if d.service_code == spec.code} == set(spec.mcp_tools), spec.code


def test_messaging_scopes_are_connection_only_and_exclude_personal_management() -> None:
    for row in mandatory_services.mandatory_service_rows():
        if not row["messenger_config"]:
            continue
        scope = row["connection_schema"]["params"]["services.management_scope"]
        assert scope["default"] == "team"
        assert {item["value"] for item in scope["options"]} == {"none", "team", "all"}
        assert "services.management_scope" not in row["global_params"]

    from app.services.service import connection_schema_for_service
    custom = Service(code="synthetic-messaging", label="Synthetic transport", description="",
                  connection_schema={}, messenger_config={"service": "matrix"})
    schema = connection_schema_for_service(custom)
    assert schema["params"]["services.management_scope"]["default"] == "team"


def test_external_mail_and_ical_remain_optional_while_personal_agenda_is_a_system_service() -> None:
    from app.services.protocols import protocol_parameters
    rows = {row["code"]: row for row in mandatory_services.mandatory_service_rows()}
    assert {"mail", "agenda", "calendar-provider"}.isdisjoint(rows)
    assert "calendar" in mandatory_services.SYSTEM_SERVICE_CODES
    assert rows["calendar"]["label"] == "Agenda"
    assert rows["calendar"]["capabilities"] == ["internal.calendar"]
    assert {"timezone", "workday_start", "workday_end", "slot_step_minutes"} <= protocol_parameters("calendar").keys()


def test_topic_tool_is_seeded_without_agent_connections() -> None:
    specs = {spec.code: spec for spec in mandatory_services.INTEGRATED_SERVICE_SPECS}
    topic = specs["topic"]

    assert topic.auto_connect_agents is False
    assert topic.default_active is False
    assert set(topic.mcp_tools) == {
        "topic_list",
        "topic_items_list",
        "topic_create",
        "topic_update",
        "topic_item_move",
        "topic_merge",
        "topic_split",
    }
    assert "topic" not in mandatory_services.AUTO_CONNECTED_INTEGRATED_SERVICE_CODES
    row = next(
        row for row in mandatory_services.mandatory_service_rows()
        if row["code"] == "topic"
    )
    assert row["connection_schema"] == {"params": {}}


def test_external_bridges_are_not_mandatory_tools() -> None:
    assert {
        "n8n",
        "affine",
        "messenger",
        "nextcloud",
        "nextcloud_talk",
        "matrix",
        "telegram",
        "whatsapp",
        "one_bot",
    }.isdisjoint(mandatory_services.INTEGRATED_SERVICE_CODES)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["n8n", "nextcloud", "affine"])
async def test_bridge_named_custom_tools_survive_sync_and_remain_editable(db, code):
    from app.process.models import ProcessDefinition
    from app.services.assertions import service_can_edit
    from app.services.schemas import ServiceCreate, ServiceUpdate

    tool = await db.scalar(select(Service).where(Service.code == code))
    if tool is None:
        tool = await service.create_service(ServiceCreate(code=code, label="Synthetic integration"))
    tool.label = "Synthetic integration"
    tool.description = "Administrator-owned description"
    config = {"service": code, "base_url": "https://files.example.test", "param_map": {}}
    if code != "n8n":
        tool.file_share_config = config
    definition = None
    if code == "n8n":
        definition = ProcessDefinition(service_id=tool.id, engine_process_id="synthetic-workflow",
                                       label="Synthetic workflow")
        db.add(definition)
    await db.commit()

    for _ in range(2):
        await mandatory_services.sync_mandatory_services()
        await db.commit()
    await db.refresh(tool)
    assert tool.label == "Synthetic integration"
    assert tool.description == "Administrator-owned description"
    if code != "n8n":
        assert tool.file_share_config == config
    assert service_can_edit(tool)
    updated = await service.update_service(tool.id, ServiceUpdate(label="Updated integration"))
    assert updated.label == "Updated integration"
    if definition is not None:
        from app.process import process_service

        await db.refresh(definition)
        assert definition.service_id == tool.id
        assert (await process_service.get_process_tool_by_code("n8n")).id == tool.id
