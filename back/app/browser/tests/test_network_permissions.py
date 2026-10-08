"""Observable browser policy and durable approval journeys with real DB/services."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.agent.models import Agent, Title
from app.connection.models import Connection, ConnectionParam
from app.messenger import create_internal_room, answer_internal_interaction, resolve_from_message
from app.messenger.models import Interaction, Message, MessengerUser, PermissionDecision, Room
from app.messenger.permissions import request_permission
from app.tools.models import Tool
from core.user.models import User
from app.browser.network import NetworkRequest, authorize_network, canonical_origin, filter_matches, is_local


async def setup_scope(db, *, create_rooms=True, public_access_mode="ask"):
    suffix = uuid4().hex
    users = [User(email=f"network-{suffix}-{i}@example.test", hashed_password="unused", is_active=True, language="en") for i in range(2)]
    title = Title(label="Network tests", gender="X")
    db.add_all([*users, title])
    await db.flush()
    agents = [Agent(user_id=user.id, title_id=title.id, code=f"net-{suffix}-{i}", first_name=f"Browser {i}",
                    last_name="Synthetic", agent_driver="internal") for i, user in enumerate(users)]
    db.add_all(agents)
    await db.flush()
    browser = await db.scalar(select(Tool).where(Tool.code == "browser"))
    chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
    connections = []
    for agent in agents:
        connection = Connection(agent_id=agent.id, tool_id=browser.id, active=True)
        connections.append(connection)
        db.add_all([connection, Connection(agent_id=agent.id, tool_id=chat.id, active=True)])
    await db.flush()
    if public_access_mode is not None:
        db.add_all([ConnectionParam(connection_id=connection.id, param_name="public_access_mode",
                                    param_value=public_access_mode) for connection in connections])
        await db.flush()
    if create_rooms:
        for agent, user in zip(agents, users):
            await create_internal_room(actor_user_id=user.id, agent_id=agent.id)
    return agents, users, connections


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_mode", ["button", "text"])
@pytest.mark.parametrize("allow", [True, False])
async def test_saved_choice_reused_and_deleted_choice_asks_again(db, answer_mode, allow):
    agents, users, _ = await setup_scope(db)
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com/a", method="POST", addresses=["93.184.215.14"])
    first = await authorize_network(request)
    assert not first.allowed and first.code == "permission_required"
    record = await db.scalar(select(PermissionDecision).where(PermissionDecision.agent_id == agents[0].id))
    assert record.interaction_id is not None
    interaction = await db.get(Interaction, record.interaction_id)
    with pytest.raises(LookupError):
        await answer_internal_interaction(users[1].id, UUID(interaction.room_id), interaction.id, option_id="allow")
    if answer_mode == "button":
        await answer_internal_interaction(users[0].id, UUID(interaction.room_id), interaction.id, option_id="allow" if allow else "deny")
    else:
        message = Message(connection_id=interaction.connection_id, tool_id=interaction.tool_id,
                          text="oui" if allow else "non", direction="inbound")
        message.room = await db.get(Room, UUID(interaction.room_id))
        message.sender = await db.scalar(select(MessengerUser).where(
            MessengerUser.tool_id == interaction.tool_id, MessengerUser.external_id == f"user:{users[0].id}"))
        assert await resolve_from_message(message, agent_id=agents[0].id) is not None
    request.url = "https://EXAMPLE.com:443/another?different=value"
    repeated = await authorize_network(request)
    assert repeated.allowed is allow
    assert await db.scalar(select(func.count()).select_from(Interaction).where(Interaction.kind == "remembered_permission")) == 1
    request.owner.agent_id = agents[1].id
    assert (await authorize_network(request)).code == "permission_required"
    record.soft_delete()
    await db.commit()
    request.owner.agent_id = agents[0].id
    assert (await authorize_network(request)).code == "permission_required"
    new_record = await request_permission(agents[0].id, first.permission_keys[0], "Same permission")
    assert new_record.id != record.id
    assert new_record.allowed is None and new_record.question != "Same permission"
    archived = await db.scalar(select(PermissionDecision).where(PermissionDecision.id == record.id).execution_options(include_historized=True))
    assert archived.allowed is allow and archived.answered_at is not None


@pytest.mark.asyncio
async def test_configuration_precedes_saved_grants_and_public_get_needs_no_choice(db):
    agents, users, connections = await setup_scope(db)
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com", method="GET", addresses=["93.184.215.14"])
    assert (await authorize_network(request)).allowed
    request.addresses = ["192.168.10.20"]
    assert (await authorize_network(request)).code == "local_network_blocked"
    assert await db.scalar(select(func.count()).select_from(PermissionDecision)) == 0
    param = ConnectionParam(connection_id=connections[0].id, param_name="allow_local_network", param_value="true")
    db.add(param)
    await db.commit()
    pending = await authorize_network(request)
    assert pending.code == "permission_required"
    record = await db.scalar(select(PermissionDecision))
    interaction = await db.get(Interaction, record.interaction_id)
    await answer_internal_interaction(users[0].id, UUID(interaction.room_id), interaction.id, option_id="allow")
    assert (await authorize_network(request)).allowed
    param.param_value = "false"
    await db.commit()
    assert (await authorize_network(request)).code == "local_network_blocked"
    request.addresses = ["93.184.215.14"]
    db.add(ConnectionParam(connection_id=connections[0].id, param_name="network_filter", param_value="example.com"))
    await db.commit()
    assert (await authorize_network(request)).code == "destination_blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_mode", [None, "ask", "allow"])
async def test_upgrade_preserves_existing_browser_site_policy(db, saved_mode):
    from app.tools import mandatory_tools

    agents, _, connections = await setup_scope(db, public_access_mode=None)
    browser = await db.get(Tool, connections[0].tool_id)
    globals_before = {name: entry for name, entry in browser.global_params.items() if name != "public_access_mode"}
    if saved_mode is not None:
        globals_before["public_access_mode"] = {"value": saved_mode, "forced": True}
    browser.global_params = globals_before
    await db.commit()
    expected_mode = saved_mode or "ask"
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://upgrade.example.test/",
                             method="POST", addresses=["93.184.215.14"])
    for _ in range(2):
        await mandatory_tools.sync_mandatory_tools()
        await db.refresh(browser)
        assert browser.global_params["public_access_mode"] == {
            "value": expected_mode, "forced": saved_mode is not None,
        }
        decision = await authorize_network(request)
        assert decision.allowed is (expected_mode == "allow")
        assert decision.code == ("allowed" if expected_mode == "allow" else "permission_required")


@pytest.mark.asyncio
async def test_public_access_mode_inherits_global_settings_and_supports_agent_override(db):
    from app.connection import connection_service
    from app.tools import tool_service
    from app.tools.schemas import ToolGlobalParamsUpdate

    agents, _, connections = await setup_scope(db, public_access_mode=None)
    tool_id = connections[0].tool_id
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://inherited.example.test/",
                             method="POST", addresses=["93.184.215.14"])
    await tool_service.update_global_params(tool_id, ToolGlobalParamsUpdate(params={
        "public_access_mode": {"value": "allow"},
    }))
    assert (await authorize_network(request)).allowed
    request.owner.agent_id = agents[1].id
    assert (await authorize_network(request)).allowed
    await connection_service.set_param(connections[1].id, "public_access_mode", "ask")
    assert (await authorize_network(request)).code == "permission_required"
    request.owner.agent_id = agents[0].id
    assert (await authorize_network(request)).allowed
    request.url = "http://localhost/"
    request.addresses = ["127.0.0.1"]
    assert (await authorize_network(request)).code == "local_network_blocked"
    with pytest.raises(ValueError):
        await connection_service.set_param(connections[0].id, "public_access_mode", "invalid")
    await tool_service.update_global_params(tool_id, ToolGlobalParamsUpdate(params={
        "public_access_mode": {"value": "allow", "forced": True},
    }))
    request.owner.agent_id = agents[1].id
    request.url, request.addresses = "https://inherited.example.test/", ["93.184.215.14"]
    assert (await authorize_network(request)).allowed
    with pytest.raises(ValueError):
        await connection_service.set_param(connections[1].id, "public_access_mode", "ask")


@pytest.mark.asyncio
async def test_public_sites_are_allowed_by_default_without_opening_local_network(db):
    agents, users, connections = await setup_scope(db, public_access_mode=None)
    await db.commit()
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://public.example.test/", method="POST",
                             addresses=["93.184.215.14"])
    for origin in ("https://public.example.test/", "https://other.example.test:8443/", "wss://socket.example.test/"):
        request.url = origin
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"):
            request.method = method
            assert (await authorize_network(request)).allowed
    assert await db.scalar(select(func.count()).select_from(PermissionDecision)) == 0
    assert await db.scalar(select(func.count()).select_from(Interaction).where(Interaction.kind == "remembered_permission")) == 0
    human_request = NetworkRequest(owner={"user_id": users[0].id}, url="https://public.example.test/", method="POST",
                                   addresses=["93.184.215.14"])
    assert (await authorize_network(human_request)).code == "blocked_url"

    request.url = "http://localhost/"
    for addresses in (["127.0.0.1"], ["::1"], ["192.168.10.20"], ["169.254.169.254"],
                      ["::ffff:127.0.0.1"], ["93.184.215.14", "10.0.0.1"]):
        request.addresses = addresses
        assert (await authorize_network(request)).code == "local_network_blocked"
    db.add(ConnectionParam(connection_id=connections[0].id, param_name="allow_local_network", param_value="true"))
    await db.commit()
    request.addresses = ["127.0.0.1"]
    assert (await authorize_network(request)).code == "permission_required"

    # Returning to per-site approval does not inherit any automatic public grant.
    mode = ConnectionParam(connection_id=connections[0].id, param_name="public_access_mode", param_value="ask")
    db.add(mode)
    await db.commit()
    request.url, request.addresses, request.method = "https://public.example.test/", ["93.184.215.14"], "POST"
    assert (await authorize_network(request)).code == "permission_required"
    permission = await db.scalar(select(PermissionDecision).where(
        PermissionDecision.permission_key == "browser:v1:post:https://public.example.test:443"))
    interaction = await db.get(Interaction, permission.interaction_id)
    await answer_internal_interaction(users[0].id, UUID(interaction.room_id), interaction.id, option_id="deny")
    mode.param_value = "allow"
    await db.commit()
    assert (await authorize_network(request)).code == "permission_denied"

    request.url = "https://filtered.example.test/"
    db.add(ConnectionParam(connection_id=connections[0].id, param_name="network_filter", param_value="filtered.example.test"))
    await db.commit()
    assert (await authorize_network(request)).code == "destination_blocked"
    connections[0].active = False
    await db.commit()
    request.url = "https://other.example.test/"
    assert (await authorize_network(request)).code == "connection_inactive"


@pytest.mark.asyncio
async def test_allowlist_requires_every_dns_address_and_invalid_methods_fail_closed(db):
    agents, _, connections = await setup_scope(db)
    db.add_all([
        ConnectionParam(connection_id=connections[0].id, param_name="network_filter_mode", param_value="allow"),
        ConnectionParam(connection_id=connections[0].id, param_name="network_filter", param_value="93.184.215.0/24"),
    ])
    await db.commit()
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com", method="GET", addresses=["93.184.215.14"])
    assert (await authorize_network(request)).allowed
    request.addresses.append("8.8.8.8")
    assert (await authorize_network(request)).code == "destination_blocked"
    request.addresses = ["93.184.215.14"]
    db.add(ConnectionParam(connection_id=connections[0].id, param_name="permission_methods", param_value="POTS"))
    await db.commit()
    with pytest.raises(ValueError, match="Invalid permission methods"):
        await authorize_network(request)


@pytest.mark.asyncio
async def test_expired_question_is_replaced_without_losing_permission_identity(db):
    from datetime import datetime, timedelta, timezone
    agents, _, _ = await setup_scope(db)
    record = await request_permission(agents[0].id, "synthetic:permission", "Synthetic question")
    old_id = record.interaction_id
    previous = await db.get(Interaction, old_id)
    previous.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    renewed = await request_permission(agents[0].id, "synthetic:permission", "New wording")
    assert renewed.id == record.id and renewed.question == "Synthetic question"
    assert renewed.interaction_id is not None and renewed.interaction_id != old_id


@pytest.mark.asyncio
async def test_concurrent_requests_create_one_question_across_database_sessions(committed_database):
    import asyncio
    from core.database import get_db_session
    async with get_db_session() as db:
        agents, _, _ = await setup_scope(db, create_rooms=False)
        agent_id = agents[0].id
    async def ask():
        async with get_db_session():
            return (await request_permission(agent_id, "synthetic:concurrent", "Concurrent question")).id
    results = await asyncio.gather(*(ask() for _ in range(6)))
    assert len(set(results)) == 1
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(PermissionDecision).where(PermissionDecision.agent_id == agent_id)) == 1
        assert await db.scalar(select(func.count()).select_from(Interaction).where(Interaction.agent_id == agent_id)) == 1


@pytest.mark.asyncio
async def test_deleting_pending_permission_expires_old_question_and_never_restores_grant(db):
    from app.messenger.permissions import delete_decision
    agents, users, _ = await setup_scope(db)
    record = await request_permission(agents[0].id, "synthetic:pending", "Pending question")
    previous = await db.get(Interaction, record.interaction_id)
    assert await delete_decision(record.id, managed_agent_ids=frozenset({agents[0].id}))
    renewed = await request_permission(agents[0].id, "synthetic:pending", "Pending question")
    with pytest.raises(ValueError):
        await answer_internal_interaction(users[0].id, UUID(previous.room_id), previous.id, option_id="allow")
    assert renewed.allowed is None and renewed.id != record.id


@pytest.mark.asyncio
async def test_permission_http_management_is_scoped_and_sidecar_requires_credential(client):
    from core.database import get_db_session
    from core.authorize.models import Assignment, Role, Privilege
    from core.user.auth_service import create_access_token
    async with get_db_session() as db:
        agents, users, _ = await setup_scope(db)
        roles = []
        for index, codes in enumerate([["CONNECTION_ACCESS", "CONNECTION_EDIT"], ["CONNECTION_ACCESS"], []]):
            role = Role(code=f"permission-{uuid4().hex}", display_name=f"Permission fixture {index}")
            role.privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(codes)))).all())
            db.add(role); await db.flush(); roles.append(role)
            db.add_all([Assignment(user_id=user.id, role_id=role.id) for user in users])
        await db.commit()
        record = await request_permission(agents[0].id, "synthetic:managed", "Managed question")
        identifier = str(record.id)
        def headers(user, role):
            return {"Authorization": "Bearer " + create_access_token({"sub": user.email, "user_id": user.id, "role_id": role.id})}
        own = headers(users[0], roles[0]); other = headers(users[1], roles[0])
        readonly = headers(users[0], roles[1]); none = headers(users[0], roles[2])
    endpoint = "/api/messenger/permissions"
    assert (await client.get(endpoint)).status_code == 401
    assert (await client.get(endpoint, headers=none)).status_code == 403
    response = await client.get(endpoint + "?limit=500", headers=own)
    assert response.status_code == 200 and response.json()["total"] == 1
    assert response.json()["items"][0]["question"] == "Managed question"
    assert (await client.get(endpoint, headers=other)).json()["total"] == 0
    assert (await client.delete(endpoint + "/" + identifier, headers=readonly)).status_code == 403
    assert (await client.delete(endpoint + "/" + identifier, headers=other)).status_code == 404
    assert (await client.delete(endpoint + "/" + identifier, headers=own)).status_code == 204
    assert (await client.get(endpoint, headers=own)).json()["total"] == 0
    body = {"owner": {"agent_id": agents[0].id}, "url": "https://example.com", "method": "GET", "addresses": ["93.184.215.14"]}
    assert (await client.post("/api/browser/network/authorize", json=body, headers=own)).status_code == 401


def test_equivalent_origins_filters_and_mapped_local_addresses():
    assert canonical_origin("https://EXAMPLE.com./a?x=1")[0] == canonical_origin("https://example.com:443/b")[0]
    assert canonical_origin("https://example.com:8443")[0] != canonical_origin("http://example.com")[0]
    for address in ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1", "fc00::1", "224.0.0.1"]:
        assert is_local(address)
    assert not is_local("93.184.215.14")
    assert filter_matches("*.example.com:443", "sub.example.com", 443, ["93.184.215.14"])
    assert not filter_matches("*.example.com", "example.com.evil.test", 443, ["93.184.215.14"])
    assert filter_matches("192.168.0.0/16", "app.test", 80, ["::ffff:192.168.1.2"])
    with pytest.raises(ValueError):
        filter_matches("bad:port", "example.com", 443, ["93.184.215.14"])


@pytest.mark.asyncio
@pytest.mark.parametrize("language,title,label", [(None, "Demande d’autorisation", "Toujours autoriser tous les sites"),
                                                   ("fr", "Demande d’autorisation", "Toujours autoriser tous les sites"),
                                                   ("zh-CN", "授权请求", "始终允许所有网站")])
async def test_all_sites_approval_is_localized_reusable_scoped_and_revocable(db, monkeypatch, language, title, label):
    from app.messenger.permissions import delete_decision
    from core.params.runtime_settings import runtime_settings
    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "fr")
    agents, users, connections = await setup_scope(db)
    users[0].language = language
    await db.commit()
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com/a", method="POST", addresses=["93.184.215.14"])
    assert (await authorize_network(request)).code == "permission_required"
    decision = await db.scalar(select(PermissionDecision).where(PermissionDecision.agent_id == agents[0].id))
    interaction = await db.get(Interaction, decision.interaction_id)
    assert interaction.title == title
    assert next(option for option in interaction.options if option["id"] == "allow_always")["label"] == label
    await answer_internal_interaction(users[0].id, UUID(interaction.room_id), interaction.id, option_id="allow_always")
    request.method = "PUT"
    request.url = "https://example.com/another"
    assert (await authorize_network(request)).allowed
    request.url = "https://other.example.com/"
    assert (await authorize_network(request)).allowed
    request.url = "http://another.example.test:8080/elsewhere"
    for method in ["POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"]:
        request.method = method
        assert (await authorize_network(request)).allowed
    assert await db.scalar(select(func.count()).select_from(Interaction).where(Interaction.agent_id == agents[0].id)) == 1
    request.method = "PUT"
    request.url = "https://example.com/"
    request.owner.agent_id = agents[1].id
    assert (await authorize_network(request)).code == "permission_required"
    request.owner.agent_id = agents[0].id
    # Destination filters still take precedence over remembered consent.
    filter_param = ConnectionParam(connection_id=connections[0].id, param_name="network_filter", param_value="example.com")
    db.add(filter_param)
    await db.commit()
    assert (await authorize_network(request)).code == "destination_blocked"
    await db.delete(filter_param)
    await db.commit()
    # All-sites consent never opens the local network.
    request.addresses = ["192.168.10.20"]
    assert (await authorize_network(request)).code == "local_network_blocked"
    db.add(ConnectionParam(connection_id=connections[0].id, param_name="allow_local_network", param_value="true"))
    await db.commit()
    assert (await authorize_network(request)).code == "permission_required"
    request.addresses = ["93.184.215.14"]
    all_sites = await db.scalar(select(PermissionDecision).where(PermissionDecision.permission_key == "browser:v1:all-sites"))
    assert await delete_decision(all_sites.id, managed_agent_ids=frozenset({agents[0].id}))
    assert (await authorize_network(request)).code == "permission_required"
    request.method = "POST"
    assert (await authorize_network(request)).code == "permission_required"


@pytest.mark.asyncio
async def test_existing_site_grant_is_never_silently_extended_to_all_sites(db):
    agents, users, _ = await setup_scope(db)
    db.add(PermissionDecision(agent_id=agents[0].id, permission_key="browser:v1:site:https://example.com:443",
                             approver_user_id=users[0].id, question="Synthetic consent for one site", allowed=True))
    await db.commit()
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com/a", method="POST", addresses=["93.184.215.14"])
    assert (await authorize_network(request)).allowed
    request.url = "https://another.example.test/"
    assert (await authorize_network(request)).code == "permission_required"


@pytest.mark.asyncio
async def test_pending_site_question_is_replaced_before_all_sites_consent(db):
    agents, users, _ = await setup_scope(db)
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com/", method="POST", addresses=["93.184.215.14"])
    assert (await authorize_network(request)).code == "permission_required"
    decision = await db.scalar(select(PermissionDecision).where(PermissionDecision.agent_id == agents[0].id))
    previous = await db.get(Interaction, decision.interaction_id)
    # Synthetic durable question from the earlier, per-site consent contract.
    previous.metadata_ = {**previous.metadata_, "always_key": "browser:v1:site:https://example.com:443",
                          "always_question": "Allow only this synthetic site"}
    previous.options = [{**option, "label": "Always allow this site"} if option["id"] == "allow_always" else option
                        for option in previous.options]
    await db.commit()
    assert (await authorize_network(request)).code == "permission_required"
    await db.refresh(decision)
    current = await db.get(Interaction, decision.interaction_id)
    assert current.id != previous.id
    assert next(option for option in current.options if option["id"] == "allow_always")["label"] == "Always allow all sites"
    with pytest.raises(ValueError):
        await answer_internal_interaction(users[0].id, UUID(previous.room_id), previous.id, option_id="allow_always")
    assert await db.scalar(select(PermissionDecision).where(PermissionDecision.permission_key == "browser:v1:all-sites")) is None
    await answer_internal_interaction(users[0].id, UUID(current.room_id), current.id, option_id="allow_always")
    request.url = "https://another.example.test/"
    assert (await authorize_network(request)).allowed


@pytest.mark.asyncio
async def test_all_sites_consent_respects_explicit_denials_connection_and_manager(db):
    agents, users, connections = await setup_scope(db)
    db.add_all([
        PermissionDecision(agent_id=agents[0].id, permission_key="browser:v1:all-sites",
                           approver_user_id=users[0].id, question="Synthetic consent for all websites", allowed=True),
        PermissionDecision(agent_id=agents[0].id, permission_key="browser:v1:delete:https://example.com:443",
                           approver_user_id=users[0].id, question="Synthetic refusal", allowed=False),
    ])
    await db.commit()
    request = NetworkRequest(owner={"agent_id": agents[0].id}, url="https://example.com/", method="DELETE", addresses=["93.184.215.14"])
    assert (await authorize_network(request)).code == "permission_denied"
    request.method = "POST"
    assert (await authorize_network(request)).allowed
    connections[0].active = False
    await db.commit()
    assert (await authorize_network(request)).code == "connection_inactive"
    connections[0].active = True
    agents[0].user_id = users[1].id
    await db.commit()
    assert (await authorize_network(request)).code == "permission_required"
