from uuid import uuid4

import pytest
from sqlalchemy import select

from core.team import TeamModel, human_memberships
from core.team.service import set_human_membership
from core.user import UserModel
from app.agent.dialogue_contracts import DialogueAgent, DialoguePolicy
from app.agent.models import AgentTeam
from app.agent.dialogue_service import policy_snapshot, set_agent_membership
from app.agent.models import Agent, Title


@pytest.mark.asyncio
async def test_outbound_transport_and_stream_stop_when_permission_is_revoked(db):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from core.authorize import Assignment, Privilege, Role
    from app.connection import Connection
    from app.tools import ToolModel
    from app.messenger.models import MessengerUser
    from app.messenger.facade import MessengerFacade
    from app.agent.openai_service import _authorized_stream

    human = UserModel(email=f"stream-{uuid4()}@example.com", hashed_password="unused", is_active=True)
    title = Title(label="Mx", gender="M")
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "AGENT_API_ACCESS"))
    role = Role(code=f"stream-{uuid4().hex}", display_name="API", privileges=[privilege])
    tool = ToolModel(code=f"team-{uuid4().hex}", label="Transport", description="", connection_schema={})
    db.add_all([human, title, role, tool])
    await db.flush()
    agent = Agent(code=f"test-{uuid4().hex[:12]}", first_name="A", last_name="B", title_id=title.id)
    db.add(agent)
    db.add(Assignment(user_id=human.id, role_id=role.id))
    await db.flush()
    connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
    identity = MessengerUser(tool_id=tool.id, external_id="verified-human", galaris_user_id=human.id, is_ai=False)
    db.add_all([connection, identity])
    await db.flush()
    transport = AsyncMock(side_effect=RuntimeError("transport reached"))
    messenger = MessengerFacade(SimpleNamespace(tool_id=tool.id, send_to_user=transport), connection.id)
    with pytest.raises(PermissionError):
        await messenger.send_to_user("verified-human", "denied")
    transport.assert_not_awaited()
    team = TeamModel(name="Shared contact")
    db.add(team)
    await db.flush()
    await set_agent_membership(team.id, agent.id, True)
    await set_human_membership(team.id, human.id, True)
    with pytest.raises(RuntimeError, match="transport reached"):
        await messenger.send_to_user("verified-human", "allowed")
    transport.assert_awaited_once()

    async def output():
        yield "first permitted fragment"
        await set_human_membership(team.id, human.id, False)
        yield "private fragment after revocation"

    fragments = [chunk async for chunk in _authorized_stream(output(), agent.id, human.id, role.id)]
    assert fragments[0] == "first permitted fragment"
    assert not any("private fragment" in chunk for chunk in fragments)
    assert any("permission_denied" in chunk for chunk in fragments)
    with pytest.raises(PermissionError):
        await messenger.send_to_user("verified-human", "revoked")
    with pytest.raises(PermissionError):
        await messenger.send_to_user("unmapped-human", "unverified")
    transport.assert_awaited_once()


def policy() -> DialoguePolicy:
    return DialoguePolicy(agents={
        1: DialogueAgent(id=1, label="A", code="a", manager_user_id=10, team_ids=[100]),
        2: DialogueAgent(id=2, label="B", code="b", manager_user_id=20, team_ids=[200]),
    }, humans={30: {100}, 40: {200}})


def test_common_team_is_automatic_but_not_transitive_or_management():
    p = policy()
    p.humans[50] = {100, 200}
    assert p.human(30, 1).source == "same_team"
    assert not p.human(30, 2).allowed
    assert not p.peers(1, 2).allowed
    assert not p.human(30, 1, active=False).allowed
    assert p.human(10, 1).source == "manager"


def test_agents_require_a_shared_team_in_both_directions():
    p = policy()
    assert not p.peers(1, 2).allowed and not p.peers(2, 1).allowed
    p.agents[2].team_ids.append(100)
    assert p.peers(1, 2).source == "same_team"
    assert p.peers(2, 1).source == "same_team"
    p.agents[2].team_ids.remove(100)
    assert not p.peers(1, 2).allowed and not p.peers(2, 1).allowed


def test_only_manager_and_global_access_bypass_team_membership():
    p = policy()
    assert p.human(10, 1).source == "manager"
    assert not p.human(10, 2).allowed
    assert p.human(40, 1, global_access=True).source == "global"
    assert not p.human(10, 1, active=False).allowed
    assert not p.human(40, 1, global_access=True, active=False).allowed
    assert not p.human(40, 1).allowed


@pytest.mark.asyncio
async def test_membership_persists_and_revokes_without_stale_scope(db):
    manager = UserModel(email=f"manager-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    human = UserModel(email=f"human-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    team = TeamModel(name="Mixed")
    title = Title(label="Mx", gender="M")
    db.add_all([manager, human, team, title])
    await db.flush()
    agent = Agent(code=f"test-{uuid4().hex[:12]}", first_name="Agent", last_name="Test", user_id=manager.id, title_id=title.id)
    db.add(agent)
    await db.flush()
    assert not (await policy_snapshot()).human(human.id, agent.id).allowed
    await set_agent_membership(team.id, agent.id, True)
    await set_agent_membership(team.id, agent.id, True)
    await set_human_membership(team.id, human.id, True)
    await db.flush()
    assert (await policy_snapshot()).human(human.id, agent.id).source == "same_team"
    assert len((await db.scalars(select(AgentTeam).where(AgentTeam.agent_id == agent.id))).all()) == 1
    await set_human_membership(team.id, human.id, False)
    assert human.id not in await human_memberships()
    assert not (await policy_snapshot()).human(human.id, agent.id).allowed
    await set_human_membership(team.id, human.id, True)
    await set_agent_membership(team.id, agent.id, False)
    assert not (await policy_snapshot()).human(human.id, agent.id).allowed
