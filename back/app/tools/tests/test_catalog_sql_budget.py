"""Catalog discovery batches connection configuration and sees revocations."""

import pytest
from sqlalchemy import select

from app.memory.tests.conftest import agents as agents
from app.connection.models import Connection, ConnectionFunctionState, ToolFunctionState
from app.tools import mcp_loader
from app.tools.models import Tool
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
async def test_native_catalog_batches_configuration_and_reloads_function_overrides(db, agents):
    owner, _ = agents
    known = set(mcp_loader.mcp_tools_by_tool_code())
    tools = list(await db.scalars(select(Tool).where(Tool.code.in_(known)).order_by(Tool.id).limit(12)))
    assert len(tools) >= 8
    connections = [Connection(agent_id=owner.id, tool_id=tool.id, active=True) for tool in tools]
    db.add_all(connections)
    await db.flush()
    db.add(ToolFunctionState(tool_id=tools[0].id, function_name="synthetic_disabled", state="disabled"))
    await db.flush()
    async with measured_reads(db, "native-tools-discovery") as enabled_reads:
        enabled = await mcp_loader.get_enabled_integrated_tool_codes(owner.id)
    async with measured_reads(db, "native-tools-overrides") as disabled_reads:
        disabled = await mcp_loader.get_disabled_internal_function_names(owner.id)
    assert {tool.code for tool in tools} - {"messenger"} <= enabled
    assert "synthetic_disabled" in disabled
    # The override projection also checks the fixed set of multimedia models.
    # Its budget must stay independent of the number of active connections.
    assert len(enabled_reads) <= 3 and len(disabled_reads) <= 20
    db.add(ConnectionFunctionState(connection_id=connections[0].id,
        function_name="synthetic_disabled", state="ask"))
    await db.flush()
    assert "synthetic_disabled" not in await mcp_loader.get_disabled_internal_function_names(owner.id)
    connections[0].active = False
    await db.flush()
    assert tools[0].code not in await mcp_loader.get_enabled_integrated_tool_codes(owner.id)
