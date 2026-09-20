"""Real HTTP and DB checks: dedicated privileges never imply management access."""
import pytest
from uuid import uuid4
from sqlalchemy import select
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from app.agent.models import Agent, Title
from app.connection import Connection
from app.tools import ToolModel
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize("public_origin", ["http://localhost", "https://galaris.example"])
async def test_team_membership_controls_chat_without_granting_management_over_http(client, monkeypatch, public_origin):
    from core import settings
    monkeypatch.setattr(settings, "APP_HOST", public_origin)
    password = "teams-password-123"
    credentials = {"email": "teams-admin@example.com", "password": password}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    admin = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post("/api/auth/users", headers=admin, json={"email": "teams-human@example.com", "password": password})
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    admin_id = (await client.get("/api/auth/me", headers=admin)).json()["id"]
    async with get_db_session() as db:
        codes = ["TEAM_ACCESS", "CHAT_ACCESS", "CHAT_MANAGE", "CHAT_SEND"]
        permissions = list((await db.scalars(select(Privilege).where(Privilege.code.in_(codes)))).all())
        role = Role(code="teams-reader", display_name="Teams reader", privileges=permissions)
        title = Title(label="Teams", gender="M")
        db.add_all([role, title])
        await db.flush()
        db.add(Assignment(user_id=user_id, role_id=role.id, is_default=True))
        agent = Agent(user_id=admin_id, title_id=title.id, code="team-agent", first_name="Team", last_name="Agent", avatar=b"\x89PNG-test")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
        assert tool is not None
        db.add(Connection(agent_id=agent_id, tool_id=tool.id, active=True))
    # These actors represent separate browsers. Reusing the admin's refresh cookie
    # would intentionally revoke its session when logging in as the human.
    client.cookies.clear()
    login = await client.post("/api/auth/login-json", json={"email": "teams-human@example.com", "password": password})
    human = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/teams")).status_code in {401, 403}
    assert (await client.post("/api/teams", headers=human, json={"name": "Denied"})).status_code == 403
    team_response = await client.post("/api/teams", headers=admin, json={"name": "Commercial"})
    assert team_response.status_code == 201, team_response.text
    team_id = team_response.json()["id"]
    second_team = await client.post("/api/teams", headers=admin, json={"name": "Support"})
    second_id = second_team.json()["id"]
    assert second_team.json()["order"] > team_response.json()["order"]
    move_url = f"/api/teams/{second_id}/position"
    move_data = {"target_team_id": team_id, "after": False}
    assert (await client.put(move_url, headers=human, json=move_data)).status_code == 403
    assert (await client.put(move_url, headers=admin, json=move_data)).status_code == 204
    assert (await client.put(move_url, headers=admin, json=move_data)).status_code == 204
    assert (await client.put(move_url, headers=admin, json={"target_team_id": 999999})).status_code == 404
    ordered_ids = [team["id"] for team in (await client.get("/api/teams", headers=admin)).json()]
    assert ordered_ids.index(second_id) < ordered_ids.index(team_id)
    assert (await client.get("/api/teams", headers=human)).status_code == 200
    avatar_url = f"/api/agents/{agent_id}/avatar"
    assert (await client.get(avatar_url)).status_code in {401, 403}
    avatar = await client.get(avatar_url, headers=human)
    assert avatar.status_code == 200
    assert avatar.content == b"\x89PNG-test"
    assert avatar.headers["content-type"] == "image/png"
    catalogue = await client.get("/api/agents/teams/agents", headers=human)
    assert catalogue.status_code == 200, catalogue.text
    assert catalogue.json()[0]["has_avatar"] is True
    assert (await client.post("/api/chat/rooms", headers=human, json={"agent_id": agent_id})).status_code == 404
    # The manager can contact their agent without sharing a team.
    assert (await client.post("/api/chat/rooms", headers=admin, json={"agent_id": agent_id})).status_code == 201
    member_url = f"/api/teams/{team_id}/humans/{user_id}"
    agent_url = f"/api/agents/teams/{team_id}/members/{agent_id}"
    assert (await client.put(member_url, headers=human, json={"present": True})).status_code == 403
    assert (await client.put(agent_url, headers=human, json={"present": True})).status_code == 403
    assert (await client.put(member_url, headers=admin, json={"present": True})).status_code == 204
    assert (await client.put(agent_url, headers=admin, json={"present": True})).status_code == 204
    team_list = (await client.get("/api/teams", headers=human)).json()
    listed = next(team for team in team_list if team["id"] == team_id)
    assert listed["human_count"] == 1
    assert listed["human_members"][0]["id"] == user_id
    updated = await client.put(f"/api/teams/{team_id}", headers=admin, json={"name": "Sales"})
    assert updated.status_code == 200
    assert updated.json()["human_count"] == 1
    assert updated.json()["order"] == 1
    created_room = await client.post("/api/chat/rooms", headers=human, json={"agent_id": agent_id})
    assert created_room.status_code == 201, created_room.text
    room_id = created_room.json()["id"]
    assert (await client.get(f"/api/agents/{agent_id}", headers=human)).status_code == 403
    assert (await client.put(member_url, headers=admin, json={"present": False})).status_code == 204
    history = await client.get(f"/api/chat/rooms/{room_id}", headers=human)
    assert history.status_code == 200, history.text
    assert not history.json()["writable"]
    assert (await client.post(f"/api/chat/rooms/{room_id}/messages", headers=human, json={"text": "Denied", "client_message_id": "denied"})).status_code == 403
    assert (await client.get(f"/api/chat/rooms/{room_id}", headers=admin)).status_code == 403
    # Calling needs only CHAT_CALL, while text sending still needs a shared team.
    call_url = f"/api/chat/rooms/{room_id}/calls/status"
    assert (await client.get(call_url, headers=human)).status_code == 403
    async with get_db_session() as db:
        from core.authorize import RolePrivilege
        call_privilege_id = await db.scalar(select(Privilege.id).where(Privilege.code == "CHAT_CALL"))
        db.add(RolePrivilege(role_id=role.id, privilege_id=call_privilege_id))
    call_status = await client.get(call_url, headers=human)
    assert call_status.status_code == 200, call_status.text
    assert (await client.get(call_url, headers=admin)).status_code == 404
    async with get_db_session() as db:
        from app.chat.events import _can_receive_event
        recipient = await db.get(UserModel, user_id)
        assert await _can_receive_event(recipient, "call", {"room_id": room_id})
        assert await _can_receive_event(recipient, "voice_transcription", {"room_id": room_id})
        assert not await _can_receive_event(recipient, "message", {"room_id": room_id})
        assert not await _can_receive_event(recipient, "runtime", {"room_id": room_id})
    assert (await client.post(f"/api/chat/rooms/{room_id}/messages", headers=human, json={"text": "Still denied", "client_message_id": "still-denied"})).status_code == 403
    assert (await client.put(member_url, headers=admin, json={"present": True})).status_code == 204
    assert (await client.get(f"/api/chat/rooms/{room_id}", headers=human)).json()["writable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("member_count", [0, 2, 12])
async def test_team_summary_counts_members_and_preserves_avatar_previews(db, member_count):
    from core.team.models import Team, TeamUser
    from core.team.service import list_teams, search_humans, team_humans

    team = Team(name=f"Summary-{uuid4()}")
    db.add(team)
    await db.flush()
    people = [UserModel(email=f"summary-{uuid4()}@example.com", hashed_password="unused",
                        avatar_key=uuid4(), avatar_mime_type="image/png", is_active=True)
              for _ in range(member_count)]
    db.add_all(people)
    await db.flush()
    db.add_all([TeamUser(team_id=team.id, user_id=user.id) for user in people])
    await db.flush()
    summary = next(item for item in await list_teams() if item.id == team.id)
    assert summary.human_count == member_count
    if member_count <= 3:
        assert {item.id: item.avatar_url for item in summary.human_members} == {user.id: user.avatar_url for user in people}
    else:
        assert summary.human_members == []
    assert len(await team_humans(team.id)) == member_count
    if people:
        results = await search_humans(people[0].email)
        assert results[0].avatar_url == people[0].avatar_url
