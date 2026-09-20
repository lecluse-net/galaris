"""System services stay visible and enabled; administrative mutations are rejected."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionFunctionState, ToolFunctionState
from app.connection import connection_service, router as connection_router
from app.connection.schemas import ConnectionCreate, ConnectionUpdate, FunctionStateUpdate
from app.tools import tool_service
from app.tools.connection_functions import list_available_connection_functions
from app.tools.dbadmin import datasets
from app.tools.descriptions import bridge_description
from app.tools.mandatory_tools import SYSTEM_TOOL_CODES, sync_integrated_tool_connections
from app.tools.mcp_loader import (
    get_disabled_internal_function_names,
    get_enabled_integrated_tool_codes,
    mcp_tool_names_by_tool_code,
)
from app.tools.models import Tool
from app.tools.router import _to_public
from app.tools.schemas import ToolCreate, ToolGlobalParamsUpdate, ToolUpdate
from core.dbadmin import reconcile_dataset


@pytest.mark.asyncio
@pytest.mark.parametrize("code", sorted(SYSTEM_TOOL_CODES))
async def test_system_connections_and_function_grants_are_immutable(db, monkeypatch, code):
    title = Title(label="System", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code=f"system-{code}",
        first_name="System",
        last_name="Agent",
        agent_driver="internal",
    )
    db.add(agent)
    await db.commit()
    await sync_integrated_tool_connections(agent.id)
    tool = await db.scalar(select(Tool).where(Tool.code == code))
    connection = await db.scalar(
        select(Connection).where(Connection.tool_id == tool.id, Connection.agent_id == agent.id)
    )
    assert _to_public(tool).can_disable is False
    names = mcp_tool_names_by_tool_code()[code]
    function = names[0]
    optional_tool = await db.scalar(select(Tool).where(Tool.code == "search"))
    db.add(ToolFunctionState(tool_id=optional_tool.id, function_name=function, enabled=False))
    # Existing installations may have disabled connections and either cascade level.
    connection.active = False
    tool.conversation_enabled = False
    db.add_all(
        [
            ConnectionFunctionState(
                connection_id=connection.id, function_name=function, enabled=False
            ),
            ToolFunctionState(tool_id=tool.id, function_name=function, enabled=False),
        ]
    )
    await db.commit()
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await db.commit()
    await db.refresh(connection)
    await db.refresh(tool)
    assert connection.active and tool.conversation_enabled
    assert code in await get_enabled_integrated_tool_codes(agent.id)
    assert await connection_service.get_disabled_function_names(connection) == set()
    assert not set(names) & await get_disabled_internal_function_names(agent.id)
    catalogue = await list_available_connection_functions(connection.id)
    assert catalogue["success"] and catalogue["functions"]
    assert all(item["effective"] for item in catalogue["functions"])
    assert all(
        item["connection_state"] == item["global_state"] == "enabled"
        for item in catalogue["functions"]
    )

    monkeypatch.setattr(
        connection_router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(1, None)),
    )
    for operation in (
        lambda: connection_router.update_connection(connection.id, ConnectionUpdate(active=False)),
        lambda: connection_router.update_connection(connection.id, ConnectionUpdate(agent_id=999)),
        lambda: connection_router.delete_connection(connection.id),
        lambda: connection_router.create_connection(
            ConnectionCreate(tool_id=tool.id, agent_id=agent.id)
        ),
        lambda: connection_router.set_connection_function(
            connection.id, function, FunctionStateUpdate(state="disabled")
        ),
        lambda: connection_router.set_connection_function_global(
            connection.id, function, FunctionStateUpdate(state="disabled")
        ),
        lambda: connection_router.delete_param(connection.id, "anything"),
    ):
        with pytest.raises(HTTPException) as error:
            await operation()
        assert error.value.status_code == 403
    for operation in (
        lambda: connection_service.set_connection_active(connection.id, False),
        lambda: connection_service.set_param(connection.id, "anything", "value"),
        lambda: tool_service.update_conversation_access(tool.id, enabled=False),
        lambda: tool_service.update_global_params(tool.id, ToolGlobalParamsUpdate()),
        lambda: tool_service.update_tool(tool.id, ToolUpdate(label="Changed")),
        lambda: tool_service.delete_tool(tool.id),
    ):
        with pytest.raises(ValueError):
            await operation()
    await db.refresh(connection)
    assert connection.active and connection.agent_id == agent.id


def test_native_function_families_have_their_expected_owners():
    names = mcp_tool_names_by_tool_code()
    assert {"llm_call", "llm_calls"} <= set(names["galaris_admin"])
    assert not {"llm_call", "llm_calls"} & set(names["galaris"])
    conversation_names = {
        name
        for group in names.values()
        for name in group
        if name.startswith("conversation_") and name != "conversation_round_get"
    }
    assert conversation_names <= set(names["conversation"])
    assert len(conversation_names) == 9


@pytest.mark.asyncio
async def test_bridge_descriptions_fill_gaps_and_preserve_custom_prose(db):
    tools = [
        Tool(code="team-matrix", label="Matrix", messenger_config={"service": "matrix"}),
        Tool(code="team-files", label="Files", file_share_config={"service": "nextcloud"}),
        Tool(
            code="custom-matrix",
            label="Custom",
            description="Our support team",
            messenger_config={"service": "matrix"},
        ),
        Tool(code="plain-custom", label="Custom"),
        Tool(
            code="existing-nextcloud",
            label="Nextcloud",
            file_share_config={"service": "nextcloud"},
            description=bridge_description({"service": "nextcloud"}, overview_only=True),
        ),
        Tool(
            code="redmine", label="Redmine", description="# Redmine\n\nOutil de gestion de projet"
        ),
    ]
    db.add_all(tools)
    await db.commit()
    for _ in range(2):
        await reconcile_dataset(db, datasets()[2])
        await db.commit()
    for tool in tools:
        await db.refresh(tool)
    assert "Matrix" in tools[0].description
    assert "Nextcloud" in tools[1].description
    assert tools[2].description == "Our support team"
    assert tools[3].description == ""
    assert tools[4].description == bridge_description({"service": "nextcloud"})
    assert tools[5].description == "# Redmine\n\nOutil de gestion de projet"

    created = await tool_service.create_tool(
        ToolCreate.model_validate(
            {
                "code": "new-matrix",
                "label": "New Matrix",
                "can_disable": False,
                "messenger_config": {
                    "service": "matrix",
                    "settings": {"homeserver": "https://matrix.example.test"},
                    "param_map": {"user_id": "user_id"},
                },
                "connection_schema": {"params": {"user_id": {"type": "string"}}},
            }
        )
    )
    assert created.can_disable is True
    assert "Matrix" in created.description
    updated = await tool_service.update_tool(
        created.id,
        ToolUpdate.model_validate(
            {
                "label": "Custom name",
                "description": "Our connector",
                "can_disable": False,
            }
        ),
    )
    assert updated.can_disable is True
    assert updated.label == "Custom name" and updated.description == "Our connector"
