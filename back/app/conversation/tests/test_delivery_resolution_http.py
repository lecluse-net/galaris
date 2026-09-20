"""Exercise real authentication, privileges and owner scope on delivery commands."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation.models import ConversationRound, ConversationTaskLink
from app.messenger.models import Room
from app.task import Task, TaskStatus
from app.tools import ToolModel
from core.authorize.models import Assignment, Privilege, Role, RolePrivilege
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_resolution_requires_edit_privilege_and_owner_scope(client):
    suffix = uuid4().hex
    password = "Delivery-test-password-42!"
    async with get_db_session() as db:
        users = [UserModel(email=f"delivery-{i}-{suffix}@example.com", is_active=True,
                           hashed_password=encrypt_password(password)) for i in range(3)]
        roles = [Role(code=f"delivery-{i}-{suffix}") for i in range(2)]
        title = Title(label="Delivery", gender="X")
        db.add_all([*users, *roles, title])
        await db.flush()
        privileges = {p.code: p.id for p in await db.scalars(select(Privilege).where(
            Privilege.code.in_(["TASK_ACCESS", "TASK_EDIT"])
        ))}
        assert len(privileges) == 2
        db.add_all([RolePrivilege(role_id=roles[0].id, privilege_id=privileges[code])
                    for code in privileges])
        db.add(RolePrivilege(role_id=roles[1].id, privilege_id=privileges["TASK_ACCESS"]))
        for i, user in enumerate(users):
            db.add(Assignment(user_id=user.id, role_id=roles[1 if i == 2 else 0].id, is_default=True))
        agent = Agent(user_id=users[0].id, title_id=title.id, first_name="Delivery", last_name="Test", code=suffix)
        db.add(agent)
        await db.flush()
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
        assert tool is not None
        connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        room = Room(connection_id=connection.id, external_id=suffix, kind="direct", label="Private",
                    conversation_type="text")
        db.add(room)
        await db.flush()
        round_ = ConversationRound(room_id=room.id, status="SUCCEEDED", delivery_state="DELIVERED")
        work = Task(label="Preserved", agent_id=agent.id, status=TaskStatus.ERROR)
        db.add_all([round_, work])
        await db.flush()
        link = ConversationTaskLink(round_id=round_.id, task_id=work.id, action_key="http-test",
                                    notification_state="UNKNOWN", notification_attempt_count=1)
        db.add(link)
        await db.commit()
        url = f"/api/conversations/rounds/{round_.id}/delivery-resolution"
        payload = {"decision": "DELIVERED", "evidence": "Verified in the destination channel",
                   "notification": {"kind": "task", "link_id": str(link.id), "attempt_number": 1}}
        emails = [user.email for user in users]

    assert (await client.post(url, json=payload)).status_code == 401
    for index, expected in [(2, 403), (1, 404), (0, 200)]:
        login = await client.post("/api/auth/login-json", json={"email": emails[index], "password": password})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await client.post(url, json=payload, headers=headers)
        assert response.status_code == expected, response.text
        if expected == 200:
            assert response.json()["unknown_notifications"] == []
            assert (await client.post(url, json=payload, headers=headers)).status_code == 200
            conflict = await client.post(url, json={**payload, "decision": "SKIPPED"}, headers=headers)
            assert conflict.status_code == 409
        else:
            async with get_db_session() as db:
                stored = await db.get(ConversationTaskLink, link.id)
                assert stored.notification_state == "UNKNOWN"
