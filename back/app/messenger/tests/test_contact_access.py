"""Live, connection-specific peer policy at the canonical transport boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from pathlib import Path

import pytest
from app.agent.models import Agent, AgentTeam, Title
from app.connection import Connection, ConnectionParam
from app.messenger import contact_access
from app.messenger.facade import MessengerFacade
from app.messenger.models import Message, MessengerUser, Room, RoomUser
from app.tools import ToolModel
from core.team import TeamModel
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize(("scope", "shared", "allowed"), [
    (None, True, True), (None, False, False),
    ("none", True, False), ("team", True, True), ("team", False, False),
    ("all", False, True), ("personal", True, False), ("usage", True, False),
    ("", True, False),
])
async def test_peer_scope_protects_transport_boundaries_and_rechecks_revocation(db, monkeypatch, scope, shared, allowed):
    manager = UserModel(email=f"synthetic-contact-{uuid4().hex}@example.test",
                        hashed_password="unused", is_active=True)
    title = Title(label="Synthetic contact", gender="X")
    team = TeamModel(name=f"Synthetic contact team {uuid4().hex}")
    # A forged global value must never override the local contact policy.
    tool = ToolModel(code=f"synthetic-contact-{uuid4().hex}", label="Synthetic messenger",
                     description="", connection_schema={}, messenger_config={"service": "matrix"},
                     global_params={"tools.management_scope": {"value": "all", "forced": True}})
    db.add_all([manager, title, team, tool])
    await db.flush()
    caller = Agent(code=f"caller-{uuid4().hex}", first_name="Caller", last_name="Synthetic",
                   title_id=title.id, user_id=manager.id)
    peer = Agent(code=f"peer-{uuid4().hex}", first_name="Peer", last_name="Synthetic",
                 title_id=title.id, group_id=team.id if shared else None)
    db.add_all([caller, peer])
    await db.flush()
    db.add(AgentTeam(agent_id=caller.id, team_id=team.id))
    connection = Connection(tool_id=tool.id, agent_id=caller.id, active=True)
    identity = MessengerUser(tool_id=tool.id, external_id="synthetic-peer", agent_id=peer.id, is_ai=True)
    human = MessengerUser(tool_id=tool.id, external_id="synthetic-manager", galaris_user_id=manager.id)
    db.add_all([connection, identity, human])
    await db.flush()
    setting = None
    if scope is not None:
        setting = ConnectionParam(connection_id=connection.id, param_name="tools.management_scope", param_value=scope)
        db.add(setting)
    room = Room(connection_id=connection.id, external_id="synthetic-room", label="Synthetic room",
                kind="group", conversation_type="text")
    db.add(room)
    await db.flush()
    db.add_all([RoomUser(room_id=room.id, user_id=identity.id), RoomUser(room_id=room.id, user_id=human.id)])
    await db.flush()
    incoming = Message(platform="matrix", sender=identity)
    checks = [
        lambda: contact_access.require_outgoing_user(connection.id, tool.id, identity.external_id),
        lambda: contact_access.require_outgoing_room(connection.id, room.id),
        lambda: contact_access.require_incoming_contact(caller.id, incoming, connection_id=connection.id),
    ]
    if allowed:
        for check in checks:
            await check()
        if setting is None:
            setting = ConnectionParam(connection_id=connection.id, param_name="tools.management_scope", param_value="none")
            db.add(setting)
        else:
            setting.param_value = "none"
        await db.flush()
    human_consent = AsyncMock(return_value=True)
    monkeypatch.setitem(contact_access._inbound_authorizers, "matrix", human_consent)
    for check in checks:
        with pytest.raises(PermissionError, match="not authorized"):
            await check()
    human_consent.assert_not_awaited()
    transport = AsyncMock()
    messenger = MessengerFacade(SimpleNamespace(tool_id=tool.id, send_to_user=transport), connection.id)
    with pytest.raises(PermissionError):
        await messenger.send_to_user(identity.external_id, "Synthetic denied message")
    transport.assert_not_awaited()
    await contact_access.require_outgoing_user(connection.id, tool.id, human.external_id)
    await contact_access.require_incoming_contact(caller.id, Message(platform="matrix", sender=human),
                                                  connection_id=connection.id)

    if allowed:
        # Re-enabling the same connection must work without a new runtime/session.
        setting.param_value = scope
        await db.flush()
        for check in checks:
            await check()
        setting.param_value = "none"
        await db.flush()

    # A different connection carrying all must not authorize this one.
    other_tool = ToolModel(code=f"synthetic-other-{uuid4().hex}", label="Other", description="", connection_schema={})
    db.add(other_tool)
    await db.flush()
    other = Connection(tool_id=other_tool.id, agent_id=caller.id, active=True)
    db.add(other)
    await db.flush()
    db.add(ConnectionParam(connection_id=other.id, param_name="tools.management_scope", param_value="all"))
    await db.flush()
    for check in checks:
        with pytest.raises(PermissionError):
            await check()
    connection.active = False
    await db.flush()
    with pytest.raises(PermissionError):
        await contact_access.require_outgoing_user(connection.id, tool.id, human.external_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("left_scope", ["none", "team", "all"])
@pytest.mark.parametrize("right_scope", ["none", "team", "all"])
@pytest.mark.parametrize("shared_team", [False, True], ids=["other-team", "same-team"])
async def test_asymmetric_peer_scopes_cover_both_directions_and_all_delivery_types(
    db, left_scope, right_scope, shared_team,
):
    """Each external side enforces its own live scope before send or admission."""
    class TransportReached(RuntimeError):
        pass

    title = Title(label="Synthetic reciprocal contact", gender="X")
    team = TeamModel(name=f"Synthetic reciprocal team {uuid4().hex}")
    tool = ToolModel(code=f"synthetic-reciprocal-{uuid4().hex}", label="Synthetic messenger",
                     description="", connection_schema={}, messenger_config={"service": "matrix"})
    db.add_all([title, team, tool])
    await db.flush()
    agents = [Agent(code=f"reciprocal-{uuid4().hex}", first_name="Synthetic", last_name=label,
                    title_id=title.id) for label in ("A", "B")]
    db.add_all(agents)
    await db.flush()
    db.add(AgentTeam(agent_id=agents[0].id, team_id=team.id))
    if shared_team:
        db.add(AgentTeam(agent_id=agents[1].id, team_id=team.id))
    connections = [Connection(agent_id=agent.id, tool_id=tool.id, active=True) for agent in agents]
    identities = [MessengerUser(tool_id=tool.id, external_id=f"synthetic-agent-{agent.id}",
                                agent_id=agent.id, is_ai=True) for agent in agents]
    db.add_all([*connections, *identities])
    await db.flush()
    scopes = [left_scope, right_scope]
    db.add_all([ConnectionParam(connection_id=connection.id, param_name="tools.management_scope", param_value=scope)
                for connection, scope in zip(connections, scopes, strict=True)])
    rooms = [Room(connection_id=connection.id, external_id=f"synthetic-room-{connection.id}",
                  label="Synthetic reciprocal room", kind="group", conversation_type="text")
             for connection in connections]
    db.add_all(rooms)
    await db.flush()
    db.add_all([RoomUser(room_id=room.id, user_id=identity.id) for room in rooms for identity in identities])
    await db.flush()

    for source, target in ((0, 1), (1, 0)):
        outgoing_allowed = scopes[source] == "all" or scopes[source] == "team" and shared_team
        incoming_allowed = scopes[target] == "all" or scopes[target] == "team" and shared_team
        transports = {name: AsyncMock(side_effect=TransportReached) for name in (
            "send_to_user", "send_to_room", "upload_file", "upload_file_path", "send_voice_note",
            "ensure_direct_room", "create_room", "add_user",
        )}
        messenger = MessengerFacade(SimpleNamespace(tool_id=tool.id, **transports), connections[source].id)
        peer = identities[target].external_id
        room = rooms[source].id
        deliveries = {
            "send_to_user": lambda: messenger.send_to_user(peer, "Synthetic text"),
            "send_to_room": lambda: messenger.send_to_room(room, "Synthetic text"),
            "upload_file": lambda: messenger.upload_file(room, b"synthetic", "synthetic.txt"),
            "upload_file_path": lambda: messenger.upload_file_path(room, Path("/tmp/synthetic.txt")),
            "send_voice_note": lambda: messenger.send_voice_note(room, Path("/tmp/synthetic.wav")),
            "ensure_direct_room": lambda: messenger.ensure_direct_room(peer),
            "create_room": lambda: messenger.create_room("Synthetic group", [peer]),
            "add_user": lambda: messenger.add_user(room, peer),
        }
        for name, delivery in deliveries.items():
            if outgoing_allowed:
                with pytest.raises(TransportReached):
                    await delivery()
                transports[name].assert_awaited_once()
            else:
                with pytest.raises(PermissionError):
                    await delivery()
                transports[name].assert_not_awaited()

        message = Message(platform="matrix", sender=identities[source])
        if incoming_allowed:
            await contact_access.require_incoming_contact(agents[target].id, message,
                                                          connection_id=connections[target].id)
        else:
            with pytest.raises(PermissionError):
                await contact_access.require_incoming_contact(agents[target].id, message,
                                                              connection_id=connections[target].id)


@pytest.mark.asyncio
async def test_messaging_scope_http_requires_global_web_delegation_and_preserves_denied_changes(client):
    from sqlalchemy import select

    from core.authorize.models import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user.user_service import encrypt_password
    from app.connection.facade import get_management_scope

    password = "synthetic-peer-scope-password"
    suffix = uuid4().hex[:16]
    async with get_db_session() as db:
        privileges = {row.code: row for row in (await db.scalars(select(Privilege).where(
            Privilege.code.in_(["CONNECTION_ACCESS", "CONNECTION_EDIT", "AGENT_MANAGE_ALL"]),
        ))).all()}
        assert len(privileges) == 3
        base = [privileges["CONNECTION_ACCESS"], privileges["CONNECTION_EDIT"]]
        roles = [Role(code=f"synthetic-peer-manager-{suffix}", privileges=base),
                 Role(code=f"synthetic-peer-global-{suffix}", privileges=[*base, privileges["AGENT_MANAGE_ALL"]])]
        password_hash = encrypt_password(password)
        users = [UserModel(email=f"synthetic-peer-{suffix}-{index}@example.com",
                           hashed_password=password_hash, is_active=True) for index in range(3)]
        title = Title(label="Synthetic HTTP peer", gender="X")
        db.add_all([*roles, *users, title])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=roles[1 if index == 2 else 0].id, is_default=True)
                    for index, user in enumerate(users)])
        agent = Agent(code=f"synthetic-http-peer-{suffix}", first_name="Synthetic", last_name="HTTP",
                      title_id=title.id, user_id=users[0].id)
        db.add(agent)
        await db.flush()
        tool_id = await db.scalar(select(ToolModel.id).where(ToolModel.code == "chat"))
        assert tool_id is not None
        connection = Connection(agent_id=agent.id, tool_id=tool_id, active=True)
        db.add(connection)
        await db.flush()
        connection_id, agent_id = connection.id, agent.id
        db.add(ConnectionParam(connection_id=connection_id, param_name="tools.management_scope", param_value="none"))

    headers = []
    for index in range(3):
        # Each actor owns a separate browser session, including on plain HTTP.
        # Reusing a previous actor's refresh cookie would revoke that session.
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={
            "email": f"synthetic-peer-{suffix}-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    token = await client.post("/api/auth/me/tokens", headers=headers[2], json={"label": "Synthetic scope API"})
    assert token.status_code == 201, token.text
    api_headers = {"Authorization": f"Bearer {token.json()['token']}"}
    prefix = f"/api/connections/{connection_id}"
    scope_name = "tools.management_scope"

    async def state():
        record = await client.get(prefix, headers=headers[2])
        params = await client.get(f"{prefix}/params", headers=headers[2])
        assert record.status_code == params.status_code == 200
        return record.json()["active"], record.json()["agent_id"], params.json()["params"]

    before = await state()
    operations = [
        ("POST", f"{prefix}/params", {"connection_id": connection_id, "param_name": scope_name, "param_value": "all"}),
        ("POST", f"{prefix}/params/bulk", {"connection_id": connection_id, "params": {scope_name: "all"}}),
        ("PATCH", f"{prefix}/params/{scope_name}", {"param_value": "all"}),
        ("PATCH", prefix, {"active": False, "params": {scope_name: "all"}}),
        ("DELETE", f"{prefix}/params/{scope_name}", None),
    ]
    for actor_headers, expected in (({}, 401), (headers[0], 403), (headers[1], 404), (api_headers, 403)):
        for method, path, body in operations:
            response = await client.request(method, path, headers=actor_headers, json=body)
            assert response.status_code == expected, (method, path, response.status_code, response.text)
            assert await state() == before

    for value in ("none", "team", "all"):
        response = await client.post(f"{prefix}/params/bulk", headers=headers[2], json={
            "connection_id": connection_id, "params": {scope_name: value},
        })
        assert response.status_code == 201, response.text
        assert (await state())[2][scope_name] == value
    for value in ("personal", "usage", "unknown"):
        response = await client.patch(prefix, headers=headers[2], json={
            "active": False, "params": {scope_name: value},
        })
        assert response.status_code == 422, response.text
        assert await state() == (True, agent_id, {scope_name: "all"})
    removed = await client.delete(f"{prefix}/params/{scope_name}", headers=headers[2])
    assert removed.status_code == 204, removed.text
    async with get_db_session():
        assert await get_management_scope(agent_id, connection_id=connection_id, default="team") == "team"
