from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import connection_service
from app.connection.models import Connection
from app.messenger import resolve_messenger_configuration
from app.tools.models import Tool


async def _agent(db: AsyncSession, suffix: str) -> Agent:
    title = Title(label=f"Messenger Tool {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Messenger",
        last_name="Tool",
        code=f"messenger-tool-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.mark.asyncio
async def test_nextcloud_messenger_and_file_share_configs_are_independent(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    agent = await _agent(db, suffix)
    tool = Tool(
        code=f"nextcloud-combined-{suffix}",
        label="Combined Nextcloud",
        description="MCP, files and messaging may coexist on one Tool.",
        mcp_config={
            "type": "http",
            "url": "https://mcp.example.test",
            "headers": {},
            "env": {},
            "args": [],
            "auth": {"type": "none"},
            "timeout": 120,
        },
        file_share_config={
            "service": "nextcloud",
            "base_url": "https://files.example.test",
            "param_map": {
                "login": "files_login",
                "password": "files_password",
            },
        },
        messenger_config={
            "service": "nextcloud_talk",
            "settings": {"base_url": "https://talk.example.test"},
            "param_map": {
                "login": "talk_login",
                "password": "talk_password",
            },
        },
        connection_schema={
            "params": {
                "files_login": {"type": "string", "required": True},
                "files_password": {"type": "password", "required": True},
                "talk_login": {"type": "string", "required": True},
                "talk_password": {"type": "password", "required": True},
            }
        },
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    await connection_service.set_params_bulk(
        int(connection.id),
        {
            "files_login": "files-bot",
            "files_password": "files-secret",
            "talk_login": "talk-bot",
            "talk_password": "talk-secret",
        },
    )

    resolved = await resolve_messenger_configuration(
        int(connection.id),
        expected_service="nextcloud_talk",
    )

    assert resolved.settings == {"base_url": "https://talk.example.test"}
    assert resolved.params["login"] == "talk-bot"
    assert resolved.params["password"] == "talk-secret"
    assert tool.file_share_config == {
        "service": "nextcloud",
        "base_url": "https://files.example.test",
        "param_map": {
            "login": "files_login",
            "password": "files_password",
        },
    }
