"""First-package creation must preserve live Skills policy and useful diagnostics."""

import json

import pytest
from fastmcp import Client
from sqlalchemy import select

from app.connection import Connection, ConnectionFunctionState
from app.skill import interface, storage
from app.skill.models import Skill
from app.skill.tests.test_personal_packages import agents, personal, set_scope
from app.tools import ToolModel, build_agent_galaris_fastmcp


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["usage", "inactive"])
async def test_first_personal_package_reports_denial_then_creates_after_delegation(db, agents, denial):
    owner, _, _ = agents
    actor_id = owner.id
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "file_sharing"))
    connection = Connection(agent_id=actor_id, tool_id=tool.id, active=True)
    db.add(connection)
    await db.flush()
    db.add(ConnectionFunctionState(connection_id=connection.id, function_name="file_create",
                                   state="enabled", enabled=True))
    await db.commit()
    code = "synthetic-first-guide"
    uri = f"galaris://skill/personnal/{actor_id}/{code}/SKILL.md"
    markdown = personal(code).markdown
    server = await build_agent_galaris_fastmcp(actor_id, runtime="internal",
                                              allowed_tool_names={"file_create"})
    async with Client(server) as client:
        skills_connection = await db.scalar(select(Connection).join(ToolModel).where(
            Connection.agent_id == actor_id, ToolModel.code == "skills"))
        if denial == "inactive":
            skills_connection.active = False
            await db.commit()
        else:
            await set_scope(actor_id, "usage")
        denied = await client.call_tool("file_create", {"path": uri, "content": markdown},
                                        raise_on_error=False)
        assert denied.is_error
        message = " ".join(item.text for item in denied.content if item.type == "text")
        assert "PermissionError" in message
        assert "parent directory" not in message and "répertoire parent" not in message
        assert "not authorized" in message or "pas autorisée" in message
        assert await db.scalar(select(Skill.id).where(
            Skill.owner_agent_id == actor_id, Skill.code == code)) is None
        assert not storage.skill_dir(code, owner_agent_id=actor_id).exists()

        skills_connection.active = True
        await db.commit()
        await set_scope(actor_id, "personal")
        created = await client.call_tool("file_create", {"path": uri, "content": markdown},
                                         raise_on_error=False)
        assert not created.is_error, created
        result = json.loads(next(item.text for item in created.content if item.type == "text"))
        assert result["uri"] == uri
        package = await interface.resolve_package(code, owner_agent_id=actor_id,
                                                  actor_agent_id=actor_id)
        assert (await interface.read_package_file(package.id, "SKILL.md",
                                                  actor_agent_id=actor_id)).content.decode() == markdown
        assert package.id in {item.id for item in await interface.personal_packages(actor_id)}
