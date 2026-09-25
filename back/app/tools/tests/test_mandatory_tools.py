from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.tools import mandatory_tools
from app.tools import dbadmin as tools_dbadmin
from app.tools.models import Tool
import core.dbadmin as core_dbadmin


@pytest.mark.asyncio
async def test_sync_integrated_connections_delegates_to_dbadmin_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()
    tools_dataset = object()
    connections_dataset = object()
    reconcile = AsyncMock(return_value=SimpleNamespace(inserted=1))
    monkeypatch.setattr(mandatory_tools, "get_db", lambda: db)
    monkeypatch.setattr(
        tools_dbadmin,
        "datasets",
        lambda **_kwargs: (tools_dataset, connections_dataset),
    )
    monkeypatch.setattr(core_dbadmin, "reconcile_dataset", reconcile)

    created = await mandatory_tools.sync_integrated_tool_connections(agent_id=7)

    assert created == 1
    reconcile.assert_awaited_once_with(db, connections_dataset)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_code", [
    "browser", "search", "image", "multimedia",
    "galaris", "conversation", "memory", "file_sharing",
])
async def test_connection_dataset_is_idempotent_and_preserves_admin_activation(
    db: AsyncSession,
    tool_code: str,
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

    first = await mandatory_tools.sync_integrated_tool_connections(agent.id)
    await db.commit()
    integrated_connection = (
        await db.execute(
            select(Connection)
            .join(Tool, Tool.id == Connection.tool_id)
            .where(Connection.agent_id == agent.id, Tool.code == tool_code)
        )
    ).scalar_one()
    topic_connection = (
        await db.execute(
            select(Connection)
            .join(Tool, Tool.id == Connection.tool_id)
            .where(Connection.agent_id == agent.id, Tool.code == "topic")
        )
    ).scalar_one_or_none()
    assert topic_connection is None
    assert integrated_connection.active is True
    tool = await db.get(Tool, integrated_connection.tool_id)
    assert tool is not None and tool.conversation_enabled is True
    integrated_connection.active = False
    await db.commit()

    second = await mandatory_tools.sync_integrated_tool_connections(agent.id)
    await db.commit()
    await db.refresh(integrated_connection)

    assert first > 0
    assert second == 0
    assert integrated_connection.active is (tool_code in mandatory_tools.SYSTEM_TOOL_CODES)


def test_management_tool_packages_are_connected_inactive_by_default() -> None:
    specs = {spec.code: spec for spec in mandatory_tools.INTEGRATED_TOOL_SPECS}

    assert {
        "task_get",
        "goal_update_suivi",
        "goal_run_now",
        "goal_ask_referrer",
    } <= set(specs["galaris"].mcp_tools)
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
        "file_delete",
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
    assert specs["goal_management"].auto_connect_agents is True
    assert specs["goal_management"].default_active is False
    assert set(specs["goal_management"].mcp_tools) == {
        "goal_create",
        "goal_update",
        "goal_delete",
        "goal_pause",
        "goal_resume",
        "goal_complete",
    }
    assert specs["skill_management"].auto_connect_agents is True
    assert specs["skill_management"].default_active is False
    assert specs["skill_management"].label == "Gestion des compétences"
    assert specs["process_admin"].auto_connect_agents is True
    assert specs["process_admin"].default_active is False
    assert specs["galaris_admin"].auto_connect_agents is True
    assert specs["galaris_admin"].default_active is False
    assert set(specs["galaris_admin"].mcp_tools) == {
        "conversation_round_get",
        "voice_turn_get",
        "llm_call",
        "llm_calls",
        "documentation_catalog",
        "documentation_search",
    }
    assert {
        "goal_management",
        "skill_management",
        "process_admin",
        "galaris_admin",
    } <= (
        mandatory_tools.DEFAULT_INACTIVE_INTEGRATED_TOOL_CODES
    )


def test_default_tools_are_enabled_for_new_conversation_installations() -> None:
    assert {
        "galaris", "memory", "file_sharing",
        "browser", "console", "search", "image", "multimedia",
    } <= (
        mandatory_tools.DEFAULT_CONVERSATION_TOOL_CODES
    )


def test_chat_is_auto_connected_active_without_mcp_tools() -> None:
    specs = {spec.code: spec for spec in mandatory_tools.INTEGRATED_TOOL_SPECS}
    chat = specs["chat"]

    assert chat.auto_connect_agents is True
    assert chat.default_active is True
    assert chat.mcp_tools == ()
    assert chat.messenger_service == "internal"


def test_browser_package_is_configurable_and_active_by_default() -> None:
    specs = {spec.code: spec for spec in mandatory_tools.INTEGRATED_TOOL_SPECS}
    browser = specs["browser"]

    assert browser.auto_connect_agents is True
    assert browser.default_active is True
    assert "browser" in mandatory_tools.DEFAULT_ACTIVE_INTEGRATED_TOOL_CODES
    row = next(
        row for row in mandatory_tools.mandatory_tool_rows()
        if row["code"] == "browser"
    )
    default_output = row["connection_schema"]["params"]["default_output"]
    assert default_output["default"] == "content"
    assert default_output["required"] is False


def test_console_host_key_is_a_write_only_connection_parameter() -> None:
    row = next(
        row for row in mandatory_tools.mandatory_tool_rows()
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


def test_mail_connection_parameters_have_a_stable_logical_order() -> None:
    row = next(
        row for row in mandatory_tools.mandatory_tool_rows()
        if row["code"] == "mail"
    )
    params = row["connection_schema"]["params"]

    assert [
        name for name, _ in sorted(params.items(), key=lambda item: item[1]["order"])
    ] == [
        "email_address",
        "password",
        "imap_host",
        "imap_port",
        "imap_security",
        "smtp_host",
        "smtp_port",
        "smtp_security",
        "connect_timeout_s",
        "operation_timeout_s",
        "poll_interval_s",
        "max_attachment_mb",
        "max_total_attachment_mb",
        "approval_required",
        "approver_user_id",
    ]


def test_calendar_requires_an_administrator_connection() -> None:
    specs = {spec.code: spec for spec in mandatory_tools.INTEGRATED_TOOL_SPECS}
    calendar = specs["calendar"]

    assert calendar.auto_connect_agents is False
    assert calendar.default_active is False
    assert {
        "calendar_events",
        "calendar_is_available",
        "calendar_find_free_slots",
        "calendar_create_event",
    } <= set(calendar.mcp_tools)
    row = next(
        row for row in mandatory_tools.mandatory_tool_rows()
        if row["code"] == "calendar"
    )
    assert list(row["connection_schema"]["params"]) == [
        "timezone",
        "workday_start",
        "workday_end",
        "slot_step_minutes",
    ]


def test_topic_tool_is_seeded_without_agent_connections() -> None:
    specs = {spec.code: spec for spec in mandatory_tools.INTEGRATED_TOOL_SPECS}
    topic = specs["topic"]

    assert topic.auto_connect_agents is False
    assert topic.default_active is False
    assert set(topic.mcp_tools) == {
        "topic_list",
        "topic_get",
        "topic_items_list",
        "topic_create",
        "topic_update",
        "topic_item_move",
        "topic_merge",
        "topic_split",
    }
    assert "topic" not in mandatory_tools.AUTO_CONNECTED_INTEGRATED_TOOL_CODES
    row = next(
        row for row in mandatory_tools.mandatory_tool_rows()
        if row["code"] == "topic"
    )
    assert row["connection_schema"] == {"params": {}}


def test_messaging_bridges_are_not_mandatory_tools() -> None:
    assert {
        "messenger",
        "nextcloud",
        "nextcloud_talk",
        "matrix",
        "telegram",
        "whatsapp",
        "one_bot",
    }.isdisjoint(mandatory_tools.INTEGRATED_TOOL_CODES)
