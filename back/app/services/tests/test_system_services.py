"""System definitions remain mandatory; human function policies survive convergence."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionFunctionState, ServiceFunctionState
from app.connection import connection_service, router as connection_router
from app.connection.schemas import ConnectionCreate, ConnectionUpdate, FunctionStateUpdate
from app.services import service
from app.services.connection_functions import list_available_connection_functions
from app.services.dbadmin import datasets
from app.services.descriptions import bridge_description
from app.services.mandatory_services import SYSTEM_SERVICE_CODES, sync_integrated_service_connections
from app.services.mcp_loader import (
    get_disabled_internal_function_names,
    mcp_tool_names_by_service_code,
)
from app.services.models import Service
from app.services.router import _to_public
from app.services.schemas import ServiceCreate, ServiceGlobalParamsUpdate, ServiceUpdate
from core.dbadmin import reconcile_dataset


@pytest.mark.asyncio
@pytest.mark.parametrize("code", sorted(SYSTEM_SERVICE_CODES))
async def test_system_definitions_are_immutable_and_function_modes_are_editable(db, monkeypatch, code):
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
    await sync_integrated_service_connections(agent.id)
    tool = await db.scalar(select(Service).where(Service.code == code))
    connection = await db.scalar(
        select(Connection).where(Connection.service_id == tool.id, Connection.agent_id == agent.id)
    )
    assert _to_public(tool).can_disable is False
    # Provider services may expose a shared native family (Agenda uses Calendar).
    # The protected guarantee is the connection's effective function catalogue.
    available = await list_available_connection_functions(connection.id)
    assert available["success"] and available["functions"]
    function = available["functions"][0]["name"]
    optional_tool = await db.scalar(select(Service).where(Service.code == "search"))
    db.add(ServiceFunctionState(service_id=optional_tool.id, function_name=function, enabled=False))
    # Existing installations may have disabled connections and either cascade level.
    connection.active = False
    tool.conversation_enabled = False
    db.add_all(
        [
            ConnectionFunctionState(
                connection_id=connection.id, function_name=function, enabled=False, state="disabled"
            ),
            ServiceFunctionState(service_id=tool.id, function_name=function, enabled=False, state="disabled"),
        ]
    )
    await db.commit()
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await db.commit()
    await db.refresh(connection)
    await db.refresh(tool)
    assert connection.active and tool.conversation_enabled
    assert await connection_service.get_disabled_function_names(connection) == {function}
    assert function in await get_disabled_internal_function_names(agent.id)
    catalogue = await list_available_connection_functions(connection.id)
    assert catalogue["success"] and catalogue["functions"]
    blocked = next(item for item in catalogue["functions"] if item["name"] == function)
    assert blocked["effective_state"] == blocked["connection_state"] == blocked["global_state"] == "disabled"
    assert not blocked["effective"]

    monkeypatch.setattr(
        connection_router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(1, None)),
    )
    request = Request({'type': 'http', 'method': 'PATCH', 'path': '/synthetic'})
    for operation in (
        lambda: connection_router.update_connection(connection.id, ConnectionUpdate(active=False), request),
        lambda: connection_router.update_connection(connection.id, ConnectionUpdate(agent_id=999), request),
        lambda: connection_router.delete_connection(connection.id),
        lambda: connection_router.create_connection(
            ConnectionCreate(service_id=tool.id, agent_id=agent.id), request
        ),
        lambda: connection_router.delete_param(connection.id, "anything", request),
    ):
        with pytest.raises(HTTPException) as error:
            await operation()
        assert error.value.status_code == 403
    for operation in (
        lambda: connection_service.set_connection_active(connection.id, False),
        lambda: connection_service.set_param(connection.id, "anything", "value"),
        lambda: service.update_conversation_access(tool.id, enabled=False),
        lambda: service.update_global_params(tool.id, ServiceGlobalParamsUpdate()),
        lambda: service.update_service(tool.id, ServiceUpdate(label="Changed")),
        lambda: service.delete_service(tool.id),
        lambda: service.deletion_impact(tool.id),
        lambda: service.delete_service(tool.id, cascade=True, expected_version="synthetic-confirmation"),
    ):
        with pytest.raises(ValueError):
            await operation()
    await db.refresh(connection)
    assert connection.active and connection.agent_id == agent.id
    # This service journey supplies the human decision boundary; HTTP role
    # denials are covered by test_action_authorizations and test_connections.
    monkeypatch.setattr(connection_router, "_require_permission_state", AsyncMock())
    changed = await connection_router.set_connection_function(connection.id, function, FunctionStateUpdate(state="ask"))
    assert changed.effective_state == "ask"
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    resolved = await connection_service.resolve_function(connection, function)
    assert resolved["effective_state"] == "ask" and resolved["global_state"] == "disabled"


def test_native_function_families_have_their_expected_owners():
    names = mcp_tool_names_by_service_code()
    assert {"llm_call", "llm_calls"} <= set(names["platform_admin"])
    assert not {"llm_call", "llm_calls"} & set(names["galaris"])
    conversation_names = {
        name
        for group in names.values()
        for name in group
        if name.startswith("conversation_") and name != "conversation_round_get"
    }
    assert conversation_names <= set(names["conversation"])
    assert {
        "conversation_choice_resolve", "conversation_task_submit", "conversation_task_list",
        "conversation_task_status", "conversation_task_pause", "conversation_task_resume",
        "conversation_task_retry", "conversation_task_stop", "conversation_process_start",
        "conversation_process_pending", "conversation_process_respond",
    } <= conversation_names


@pytest.mark.asyncio
async def test_bridge_descriptions_fill_gaps_and_preserve_custom_prose(db):
    tools = [
        Service(code="team-matrix", label="Matrix", messenger_config={"service": "matrix"}),
        Service(code="team-files", label="Files", file_share_config={"service": "nextcloud"}),
        Service(
            code="custom-matrix",
            label="Custom",
            description="Our support team",
            messenger_config={"service": "matrix"},
        ),
        Service(code="plain-custom", label="Custom"),
        Service(
            code="existing-nextcloud",
            label="Nextcloud",
            file_share_config={"service": "nextcloud"},
            description=bridge_description({"service": "nextcloud"}, overview_only=True),
        ),
        Service(
            code="redmine", label="Redmine", description="# Redmine\n\nOutil de gestion de projet"
        ),
    ]
    db.add_all(tools)
    await db.commit()
    for _ in range(2):
        await reconcile_dataset(db, next(item for item in datasets() if item.key == "app.services.bridge_descriptions"))
        await db.commit()
    for tool in tools:
        await db.refresh(tool)
    assert "Matrix" in tools[0].description
    assert "Nextcloud" in tools[1].description
    assert tools[2].description == "Our support team"
    assert tools[3].description == ""
    assert tools[4].description == bridge_description({"service": "nextcloud"})
    assert tools[5].description == "# Redmine\n\nOutil de gestion de projet"

    created = await service.create_service(
        ServiceCreate.model_validate(
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
    updated = await service.update_service(
        created.id,
        ServiceUpdate.model_validate(
            {
                "label": "Custom name",
                "description": "Our connector",
                "can_disable": False,
            }
        ),
    )
    assert updated.can_disable is True
    assert updated.label == "Custom name" and updated.description == "Our connector"
