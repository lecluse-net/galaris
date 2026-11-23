"""Catalog discovery batches connection configuration and sees revocations."""

import pytest
import tracemalloc
from uuid import uuid4
from sqlalchemy import select, update

from app.memory.tests.conftest import agents as agents
from app.connection.models import Connection, ConnectionFunctionState, ServiceFunctionState
from app.services import mcp_loader
from app.services.models import Service
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
@pytest.mark.parametrize("unrelated", [0, 500])
async def test_delegated_tool_page_does_not_materialize_unselected_configuration(db, unrelated):
    from app.connection.facade import admin_tools

    prefix = f"synthetic-projection-{uuid4().hex}"
    db.add_all([Service(code=f"{prefix}-a-{index:03d}", label=f"Synthetic selected {index}",
        connection_schema={"params": {
            "credential": {"type": "password", "default": "synthetic-private-value"},
            "region": {"type": "string", "default": "north"},
        }}) for index in range(10)])
    db.add_all([Service(code=f"{prefix}-z-{index:03d}", label=f"Synthetic unrelated {index}",
        description="Synthetic private configuration. " * 4096,
        connection_schema={"params": {"region": {"type": "string", "default": "south"}}})
        for index in range(unrelated)])
    await db.commit()
    db.expunge_all()
    tracemalloc.start()
    try:
        page = await admin_tools(prefix, 0, 10)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert page["total"] == 10 + unrelated
    assert [item["label"] for item in page["items"]] == [f"Synthetic selected {index}" for index in range(10)]
    assert all(item["connection_schema"]["params"]["region"]["default"] == "north" for item in page["items"])
    assert "synthetic-private-value" not in repr(page)
    assert peak < 6_000_000, "A small page must not materialize unrelated private Service configuration"
    # Existing full-catalogue consumers must still receive configuration, even
    # after the same session has opened the lightweight delegated page.
    from app.services import service

    full = {record.code: record for record in await service.get_all_service_records()}
    assert full[f"{prefix}-a-000"].connection_schema["params"]["region"]["default"] == "north"
    if unrelated:
        assert full[f"{prefix}-z-000"].description == "Synthetic private configuration. " * 4096
        assert full[f"{prefix}-z-000"].connection_schema["params"]["region"]["default"] == "south"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [10, 500])
async def test_service_admin_metadata_page_does_not_materialize_private_configuration(db, count):
    from app.services.facade import administration, AdministrationContext

    prefix = f"synthetic-admin-projection-{uuid4().hex}"
    tools = [Service(code=f"{prefix}-{index:03d}", label=f"Synthetic admin catalogue {index}",
        description="Synthetic private configuration. " * 4096,
        connection_schema={"params": {
            "region": {"type": "string", "default": "north"},
            "credential": {"type": "password", "default": "synthetic-private-value"},
        }}) for index in range(count)]
    db.add_all(tools)
    await db.commit()
    expected = [{"id": tool.id, "code": tool.code, "label": tool.label,
        "integrated": False, "system": False}
        for tool in tools]
    del tools
    db.expunge_all()
    tracemalloc.start()
    try:
        page = await administration.list_services(AdministrationContext(), search=prefix, kind="custom", limit=count)
        _,peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert page == {"items": expected, "total": count, "offset": 0, "limit": count}
    assert peak < 6_000_000, "A metadata page must not materialize private Service configuration"
    # Opening the detail afterwards must still hydrate all required fields.
    detail = await administration.get(AdministrationContext(), service_id=expected[0]["id"])
    assert detail["tool"]["description"] == "Synthetic private configuration. " * 4096
    assert detail["tool"]["connection_schema"]["params"]["region"]["default"] == "north"
    assert "synthetic-private-value" not in repr(detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [10, 50, 500])
async def test_delegated_tool_catalogue_bounds_reads_and_preserves_public_pages(db, count):
    from app.connection.facade import admin_tools

    prefix = f"synthetic-catalogue-{uuid4().hex}"
    tools = [Service(code=f"{prefix}-{index:03d}", label=f"Synthetic Straße {index}",
                  can_disable=index != 0, connection_schema={"params": {
                      "credential": {"type": "password", "default": "synthetic-private-value"},
                      "region": {"type": "string", "default": "north"},
                  }}) for index in range(count)]
    db.add_all(tools)
    await db.commit()
    expected = [(tool.id, tool.code, tool.label) for tool in tools]
    db.expunge_all()
    async with measured_reads(db, f"delegated-tool-catalogue-{count}") as reads:
        page = await admin_tools(prefix, 0, count)
    assert page["total"] == count and page["skip"] == 0 and page["limit"] == count
    assert [(item["id"], item["code"], item["label"]) for item in page["items"]] == expected
    assert page["items"][0]["mandatory"] and not any(item["mandatory"] for item in page["items"][1:])
    assert all(not item["human_only"] for item in page["items"])
    assert all(item["connection_schema"]["params"]["credential"]["default"] == "" for item in page["items"])
    assert all(item["connection_schema"]["params"]["region"]["default"] == "north" for item in page["items"])
    assert "synthetic-private-value" not in repr(page)
    assert len(reads) <= 2, "Reading more Services must not add one configuration query per item"
    partial = await admin_tools(prefix, count - 2, 5)
    assert partial["total"] == count and [item["id"] for item in partial["items"]] == [item[0] for item in expected[-2:]]
    assert (await admin_tools("STRASSE", 0, count))["total"] == count
    assert (await admin_tools(prefix, count, count))["items"] == []
    assert (await admin_tools(f"{prefix}-absent", 0, count))["total"] == 0


@pytest.mark.asyncio
async def test_delegated_tool_catalogue_reopens_with_current_configuration(inference_db, committed_database):
    from app.connection.facade import admin_tools

    db = inference_db
    prefix = f"synthetic-reopen-{uuid4().hex}"
    record = Service(code=prefix, label="Synthetic old label", connection_schema={"params": {
        "region": {"type": "string", "default": "north"},
    }})
    db.add(record)
    await db.commit()
    identifier = record.id
    assert (await admin_tools(prefix, 0, 50))["items"][0]["label"] == "Synthetic old label"
    # A different writer changes metadata while this session still owns the old ORM object.
    async with committed_database() as writer:
        await writer.execute(update(Service).where(Service.id == identifier).values(
            label="Synthetic current label", can_disable=False, connection_schema={"params": {
                "region": {"type": "string", "default": "south"},
                "credential": {"type": "password", "default": "synthetic-new-private-value"},
            }}))
        await writer.commit()
    reopened = (await admin_tools(prefix, 0, 50))["items"][0]
    assert reopened["label"] == "Synthetic current label" and reopened["mandatory"]
    assert reopened["connection_schema"]["params"]["region"]["default"] == "south"
    assert reopened["connection_schema"]["params"]["credential"]["default"] == ""
    assert "synthetic-new-private-value" not in repr(reopened)


@pytest.mark.asyncio
async def test_native_catalog_batches_configuration_and_reloads_function_overrides(db, agents):
    owner, _ = agents
    known = set(mcp_loader.mcp_tools_by_service_code())
    tools = list(await db.scalars(select(Service).where(Service.code.in_(known)).order_by(Service.id).limit(12)))
    assert len(tools) >= 8
    connections = [Connection(agent_id=owner.id, service_id=tool.id, active=True) for tool in tools]
    db.add_all(connections)
    await db.flush()
    index = next(index for index, tool in enumerate(tools) if tool.code == "calendar")
    function = "calendar_list"
    db.add(ServiceFunctionState(service_id=tools[index].id, function_name=function, state="disabled"))
    await db.flush()
    async with measured_reads(db, "native-tools-discovery") as enabled_reads:
        enabled = await mcp_loader.get_enabled_integrated_service_codes(owner.id)
    async with measured_reads(db, "native-tools-overrides") as disabled_reads:
        disabled = await mcp_loader.get_disabled_internal_function_names(owner.id)
    assert {tool.code for tool in tools} - {"messenger"} <= enabled
    assert function in disabled
    # The override projection also checks the fixed set of multimedia models.
    # Its budget must stay independent of the number of active connections.
    assert len(enabled_reads) <= 3 and len(disabled_reads) <= 20
    db.add(ConnectionFunctionState(connection_id=connections[index].id,
        function_name=function, state="ask"))
    await db.flush()
    assert function not in await mcp_loader.get_disabled_internal_function_names(owner.id)
    connections[index].active = False
    await db.flush()
    assert "calendar" not in await mcp_loader.get_enabled_integrated_service_codes(owner.id)


@pytest.mark.asyncio
async def test_aggregate_catalog_reads_stay_bounded_with_more_active_connections(db, agents):
    from app.services.mcp_authorization import bind_native_action

    owner, _ = agents
    agent_id = owner.id
    native_service_id = await db.scalar(select(Service.id).where(Service.code == "process"))
    db.add(Connection(agent_id=agent_id, service_id=native_service_id, active=True))
    await db.flush()
    db.expunge_all()
    context = mcp_loader.McpToolContext(agent_id=agent_id, runtime="internal")
    definition = next(tool for tool in mcp_loader.mcp_tools_by_service_code()["process"]
                      if tool.name == "process_list_runs")
    async with measured_reads(db, "aggregate-mcp-initial") as initial_reads:
        initial = await mcp_loader.build_agent_mcp(agent_id)
        initial_action = await bind_native_action(context, definition, {"limit": 50})
    native_names = [tool.name for tool in await initial.list_tools()]
    assert "process_list_runs" in native_names

    services = [Service(code=f"synthetic-aggregate-{index}", label="Synthetic non-MCP", connection_schema={})
                for index in range(50)]
    db.add_all(services)
    await db.flush()
    db.add_all([Connection(agent_id=agent_id, service_id=service.id, active=True) for service in services])
    await db.flush()
    db.expunge_all()

    async with measured_reads(db, "aggregate-mcp-many-connections") as expanded_reads:
        expanded = await mcp_loader.build_agent_mcp(agent_id)
        expanded_action = await bind_native_action(context, definition, {"limit": 50})

    assert [tool.name for tool in await expanded.list_tools()] == native_names
    assert expanded_action.connection_id == initial_action.connection_id
    assert expanded_action.configuration == initial_action.configuration
    assert len(expanded_reads) <= len(initial_reads), "Service reads must not grow with the number of active connections"
