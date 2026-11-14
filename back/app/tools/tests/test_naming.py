"""The product name belongs exclusively to the built-in product Tool."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionFunctionState, ToolFunctionState
from app.tools.dbadmin import datasets
from app.tools.mandatory_tools import INTEGRATED_TOOL_SPECS
from app.tools.mandatory_tools import sync_mandatory_tools
from app.tools.models import Tool
from app.tools.schemas import ToolCreate, ToolUpdate
from core.dbadmin import reconcile_dataset


@pytest.mark.parametrize("name", ["galaris", "GALARIS", "GaLaRiS_admin", "My Galaris Tool", "ＧＡＬＡＲＩＳ"])
def test_custom_tools_cannot_use_the_product_name(name: str) -> None:
    for definition in ({"code": name, "label": "External service"}, {"code": "external", "label": name}):
        with pytest.raises(ValidationError, match="reserved"):
            ToolCreate.model_validate(definition)
    with pytest.raises(ValidationError, match="reserved"):
        ToolUpdate(label=name)


def test_only_the_product_tool_uses_the_product_name() -> None:
    for spec in INTEGRATED_TOOL_SPECS:
        if spec.code == "galaris":
            assert spec.label == "Galaris"
        else:
            assert "galaris" not in spec.code.casefold()
            assert "galaris" not in spec.label.casefold()
            ToolCreate(code=spec.code, label=spec.label)
    assert ToolUpdate(description="Connects to Galaris").description == "Connects to Galaris"


@pytest.mark.asyncio
async def test_administration_rename_preserves_connections_and_function_policies(db: AsyncSession) -> None:
    tool = await db.scalar(select(Tool).where(Tool.code == "platform_admin"))
    assert tool is not None
    original_id = tool.id
    tool.code = "galaris_admin"
    tool.label = "Galaris Admin"
    tool.conversation_enabled = True
    tool.global_params = {"custom": {"value": "preserved", "forced": False}}
    title = Title(label="Naming", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, code="naming-agent", first_name="Naming", last_name="Agent", agent_driver="internal")
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=False)
    db.add(connection)
    await db.flush()
    connection_policy = ConnectionFunctionState(connection_id=connection.id, function_name="llm_calls", enabled=False, state="disabled")
    tool_policy = ToolFunctionState(tool_id=tool.id, function_name="llm_calls", enabled=False, state="disabled")
    db.add_all([connection_policy, tool_policy])
    await db.commit()

    for _ in range(2):
        await sync_mandatory_tools()
        await db.commit()
        await db.refresh(tool)
        await db.refresh(connection)
        await db.refresh(connection_policy)
        await db.refresh(tool_policy)
        assert tool.id == original_id and tool.code == "platform_admin" and tool.label == "Administration"
        assert tool.conversation_enabled is True
        assert tool.global_params and tool.global_params["custom"]["value"] == "preserved"
        assert connection.tool_id == original_id and connection.active is False
        assert connection_policy.state == tool_policy.state == "disabled"
        assert await db.scalar(select(Tool.id).where(Tool.code == "galaris_admin")) is None


@pytest.mark.asyncio
async def test_administration_rename_refuses_a_code_collision_without_modifying_either_tool(db: AsyncSession) -> None:
    legacy = Tool(code="galaris_admin", label="Galaris Admin")
    db.add(legacy)
    await db.commit()
    dataset = next(item for item in datasets() if item.key == "app.tools.builtin_names")
    with pytest.raises(ValueError, match="already exists"):
        await reconcile_dataset(db, dataset)
    await db.refresh(legacy)
    assert legacy.code == "galaris_admin"
    assert await db.scalar(select(Tool.id).where(Tool.code == "platform_admin")) is not None
