"""One provider can own distinct Mail accounts for the same agent."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import connection_service
from app.tools import tool_service
from app.tools.protocols import ProtocolConfig, bind_protocol_connection, reset_protocol_connection
from app.tools.schemas import ToolCreate, ToolUpdate, ConnectionSchema
from app.tools.mcp_loader import McpToolContext, get_disabled_internal_function_names, load_mcp_tools, list_agent_mcp_tools
from app.tools.mcp_authorization import bind_native_action
from bridge.mail.connection_service import resolve_mail_connection
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel, auth_service, refresh_session_service


@pytest.mark.asyncio
async def test_same_provider_accounts_are_distinct_and_other_tools_remain_unique(client):
    suffix = uuid4().hex
    async with get_db_session() as db:
        role = Role(code=f"mail-accounts-{suffix}", privileges=list(await db.scalars(
            select(Privilege).where(Privilege.code.in_(["CONNECTION_EDIT", "CONNECTION_ACCESS"])))))
        user = UserModel(email=f"mail-accounts-{suffix}@example.test", hashed_password="synthetic", is_active=True)
        title = Title(label="Synthetic mailbox owner", gender="N")
        db.add_all([role, user, title])
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        agent = Agent(user_id=user.id, title_id=title.id, code=f"mail-accounts-{suffix}", first_name="Synthetic", last_name="Agent")
        db.add(agent)
        await db.flush()
        provider = await tool_service.create_tool(ToolCreate(code=f"mail-{suffix}", label="Synthetic provider",
            mail_config=ProtocolConfig(settings={"imap_host": "imap.example.test", "smtp_host": "smtp.example.test"},
                param_map={"email_address": "email", "imap_username": "email", "imap_password": "password",
                    "smtp_username": "email", "smtp_password": "password", "allowed_mailboxes": "", "approver_user_id": ""}),
            connection_schema=ConnectionSchema.model_validate({"params": {"email": {"type": "string"}, "password": {"type": "password"}}})))
        ordinary = await tool_service.create_tool(ToolCreate(code=f"ordinary-{suffix}", label="Synthetic ordinary Tool"))
        refresh = await refresh_session_service.create_refresh_session(user.id)
        token = await auth_service.create_access_token_for_user(user, session_family=await refresh_session_service.family_for_token(refresh))
        agent_id, provider_id, ordinary_id = agent.id, provider.id, ordinary.id
    headers = {"Authorization": f"Bearer {token}"}
    accounts = []
    for index in range(2):
        response = await client.post("/api/connections", headers=headers, json={
            "tool_id": provider_id, "agent_id": agent_id,
            "params": {"email": f"box-{index}@example.org", "password": f"synthetic-secret-{index}"}})
        assert response.status_code == 201, response.text
        accounts.append(response.json()["id"])
    assert accounts[0] != accounts[1]
    async with get_db_session():
        with pytest.raises(ValueError, match="exact active mail connection"):
            await resolve_mail_connection(agent_id)
        for index, identity in enumerate(accounts):
            binding = bind_protocol_connection("mail", agent_id, identity)
            try:
                config = await resolve_mail_connection(agent_id)
                assert str(config.email_address) == f"box-{index}@example.org"
                assert config.imap.password.get_secret_value() == f"synthetic-secret-{index}"
            finally:
                reset_protocol_connection(binding)
            definition = next(item for item in load_mcp_tools() if item.name == "mail_search")
            action = await bind_native_action(McpToolContext(agent_id=agent_id, runtime="internal",
                resources={"source_connection_id": identity}), definition, {"connection_id": identity})
            assert action.connection_id == identity and action.tool_id == provider_id
        with pytest.raises(ValueError, match="connection_id"):
            await connection_service.get_connection_by_agent_tool(provider_id, agent_id)
        await connection_service.set_connection_function_state(accounts[0], "mail_search", "disabled")
        await connection_service.set_connection_function_state(accounts[1], "mail_search", "enabled")
        assert "mail_search" not in await get_disabled_internal_function_names(agent_id)
        catalogue = [group for group in await list_agent_mcp_tools(agent_id) if group["tool_id"] == provider_id]
        assert {group["connection_id"] for group in catalogue} == set(accounts)
        assert {group["mail_address"] for group in catalogue} == {"box-0@example.org", "box-1@example.org"}
        for group in catalogue:
            search = next(item for item in group["mcp_tools"] if item["name"] == "mail_search")
            assert search["enabled"] == (group["connection_id"] == accounts[1])
        from app.tools.mcp import list_mcp_tools
        rendered = await list_mcp_tools(McpToolContext(agent_id=agent_id, runtime="internal"))
        for index, identity in enumerate(accounts):
            assert f"connection_id={identity}" in rendered and f"box-{index}@example.org" in rendered
            assert f"synthetic-secret-{index}" not in rendered
        with pytest.raises(ValueError, match="additional Mail connections"):
            await tool_service.update_tool(provider_id, ToolUpdate(mail_config=None))
    assert (await client.post("/api/connections", headers=headers, json={"tool_id": ordinary_id, "agent_id": agent_id})).status_code == 201
    assert (await client.post("/api/connections", headers=headers, json={"tool_id": ordinary_id, "agent_id": agent_id})).status_code == 409
    # Re-saving either account must update only that identity.
    response = await client.patch(f"/api/connections/{accounts[1]}", headers=headers,
        json={"tool_id": provider_id, "agent_id": agent_id, "active": False})
    assert response.status_code == 200, response.text
    assert (await client.get(f"/api/connections/{accounts[0]}", headers=headers)).json()["active"] is True
