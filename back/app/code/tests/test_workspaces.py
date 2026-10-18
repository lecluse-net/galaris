"""Durable repository ACLs and launch capabilities, using real PostgreSQL storage."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select

from app.agent import Agent, Title
from app.code import service
from app.code import CodeConnection, WorkspaceTarget
from app.code.models import CodeGrant, CodeSession, CodeWorkspace
from app.console import RepositoryTarget, SshConnectionConfig, connection_generation
from app.connection import Connection
from app.tools import ToolModel
from core.authorize import Assignment, Privilege, Role, RolePrivilege
from core.user import UserModel


@pytest.mark.parametrize("label,origin,accepted", [
    ("dev", "http://localhost:8484", True),
    ("prod", "https://app.example.test", True),
    ("test", "http://localhost:8484", False),
    ("demo", "http://localhost:8484", False),
    ("prod", "https://app.example.test/path", False),
    ("dev", "", False),
    ("dev", "http://user:password@localhost:8484", False),
])
def test_editor_uses_the_application_origin_and_preserves_production_protections(monkeypatch, label, origin, accepted):
    monkeypatch.setattr(service.settings, "APP_ENV", label)
    monkeypatch.setattr(service.settings, "APP_HOST", origin)
    if accepted:
        assert service.editor_origin() == origin
    else:
        with pytest.raises(RuntimeError, match="APP_HOST"):
            service.editor_origin()


@pytest_asyncio.fixture
async def repository_scope(db, monkeypatch):
    users = [UserModel(email=f"code-{uuid4().hex}@example.test", hashed_password="synthetic") for _ in range(3)]
    title = Title(label="Synthetic code developer", gender="X")
    db.add_all([*users, title])
    await db.flush()
    agent = Agent(title_id=title.id, user_id=users[0].id, first_name="Synthetic", last_name="Developer",
                  code=f"code-{uuid4().hex[:12]}", agent_driver="internal")
    db.add(agent)
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "console"))
    assert tool is not None
    await db.flush()
    connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
    db.add(connection)
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "CODE_ACCESS"))
    assert privilege is not None
    role = Role(code=f"code-{uuid4().hex}")
    db.add(role)
    await db.flush()
    db.add(RolePrivilege(role_id=role.id, privilege_id=privilege.id))
    db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users])
    await db.flush()
    config = SshConnectionConfig(connection_id=connection.id, host="synthetic.test", username="developer",
        private_key=SecretStr("synthetic console key"), known_host_key="synthetic pinned key")
    target = WorkspaceTarget(home="/home/developer", root="/home/developer/project",
        git_paths=("/home/developer/project/.git",), generation="a" * 64, branch="main", head="b" * 40)
    monkeypatch.setattr(service, "get_current_user", AsyncMock(return_value=users[0]))
    monkeypatch.setattr(service, "current_web_session_family", lambda: "synthetic-session-family")
    monkeypatch.setattr(service, "web_session_active", AsyncMock(return_value=True))
    monkeypatch.setattr(service.settings, "APP_HOST", "https://app.example.test")
    runtime = AsyncMock()
    reference = CodeConnection(connection_id=config.connection_id, fingerprint=connection_generation(config), owner_user_id=agent.user_id)
    runtime.connection_for_agent.return_value = reference
    runtime.connection.return_value = reference
    runtime.discover.return_value = target
    monkeypatch.setattr(service, "runtime", lambda: runtime)
    return users, agent, config, target, runtime


@pytest.mark.asyncio
async def test_discovery_is_owner_only_and_full_paths_distinguish_checkouts(repository_scope, db):
    from app.code.contracts import RepositoryCandidates

    users, agent, _, target, runtime = repository_scope
    runtime.repositories.return_value = RepositoryCandidates(paths=["work/project", "archive/project"])
    with pytest.raises(PermissionError):
        await service.human_repository_candidates(agent.id, users[1].id)
    runtime.repositories.assert_not_awaited()
    result = await service.human_repository_candidates(agent.id, users[0].id)
    assert result.paths == ["work/project", "archive/project"]
    # Discovery itself neither registers a workspace nor starts an IDE.
    assert (await db.scalars(select(CodeWorkspace))).all() == []
    runtime.open.assert_not_awaited()
    target.root = "/home/developer/work/project"
    first = await service.register_repository("console://work/project/", agent.id)
    target.root = "/home/developer/archive/project"
    second = await service.register_repository("console://archive/project/", agent.id)
    assert first.id != second.id
    assert service.info(first, "edit").label == "work/project"
    assert service.info(second, "edit").label == "archive/project"


@pytest.mark.asyncio
async def test_chat_repository_discovery_and_opening_check_room_and_console_rights(repository_scope, db, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from main import app
    from app.code import contracts
    from app.code.contracts import RepositoryCandidates
    from app.messenger import create_internal_room
    from core.database import database, middleware
    from core.user.auth_service import create_access_token_for_user
    from core.user.refresh_session_service import create_refresh_session, family_for_token

    users, agent, _, target, runtime = repository_scope
    chat_tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
    assert chat_tool is not None
    db.add(Connection(agent_id=agent.id, tool_id=chat_tool.id, active=True))
    await db.flush()
    room = await create_internal_room(actor_user_id=users[0].id, agent_id=agent.id)
    assert room is not None
    target.root = "/home/developer/work/project"
    runtime.repositories.return_value = RepositoryCandidates(paths=["work/project"])
    monkeypatch.setattr(contracts, "_runtime", runtime)
    monkeypatch.setattr(middleware, "AsyncSessionLocal", database.AsyncSessionLocal)
    headers = []
    for user in users[:2]:
        refresh = await create_refresh_session(user.id)
        token = await create_access_token_for_user(user, db, session_family=await family_for_token(refresh))
        headers.append({"Authorization": "Bearer " + token})
    url = f"/api/chat/rooms/{room.id}/repositories"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost:8484") as http:
        for method in (http.get, http.post):
            denied = await method(url, headers=headers[1], params={"uri": "console://work/project/"})
            assert denied.status_code == 403, denied.text
        runtime.repositories.assert_not_awaited()
        listing = await http.get(url, headers=headers[0])
        assert listing.status_code == 200, listing.text
        assert listing.json() == {"paths": ["work/project"], "truncated": False}
        assert (await db.scalars(select(CodeWorkspace))).all() == []
        opened = await http.post(url, headers=headers[0], params={"uri": "console://work/project/"})
        assert opened.status_code == 200, opened.text
        assert opened.json()["label"] == "work/project"
        # Existing room lists now contain the same path and durable identity.
        linked = await http.get(f"/api/code/rooms/{room.id}", headers=headers[0])
        assert linked.json() == [opened.json()]
        runtime.open.assert_not_awaited()


@pytest.mark.asyncio
async def test_registration_deduplicates_and_neither_room_nor_agent_management_grants_access(repository_scope, db):
    from app.file_share import resource_service
    from app.file_share.resource_contracts import ResourceContext
    users, agent, config, _, _ = repository_scope
    first = await service.register_repository("console://project/", agent.id)
    second = await service.register_repository("console://project/", agent.id)
    assert first.id == second.id
    assert first.connection_fingerprint == connection_generation(config)
    assert await service.human_mode(first, users[0].id) == "edit"
    with pytest.raises(PermissionError):
        await service.human_mode(first, users[1].id)
    assert len((await db.scalars(select(CodeGrant).where(CodeGrant.workspace_id == first.id))).all()) == 2
    assert await service.workspace_for_agent(first.id, agent.id) is first
    with pytest.raises(PermissionError):
        await service.workspace_for_agent(first.id, agent.id + 1000)
    uri = f"galaris://code/{first.id}"
    metadata = await resource_service.resource_read(ResourceContext(agent_id=agent.id, runtime="internal"), uri)
    assert "main" in metadata.content and uri in metadata.content
    assert first.root not in metadata.content and "credential" not in metadata.content
    with pytest.raises(FileNotFoundError):
        await resource_service.resource_read(ResourceContext(agent_id=agent.id + 1000, runtime="internal"), uri)
    repository_scope[-1].open.assert_not_awaited()


@pytest.mark.asyncio
async def test_human_directory_registration_preserves_grants_and_links_the_repository(repository_scope, db):
    from app.code.models import CodeConversationLink
    from app.messenger.models import Room
    from core.database.database import db_session_ctx
    from sqlalchemy.ext.asyncio import AsyncSession
    users, agent, _, _, runtime = repository_scope
    # The link uses a real room foreign key, independently of the HTTP authorization boundary.
    room = Room(connection_id=repository_scope[2].connection_id,
                         external_id=f"synthetic-{uuid4()}", label="Synthetic code room", conversation_type="text")
    db.add(room)
    await db.flush()
    with pytest.raises(PermissionError):
        await service.human_directory_repository("console://project/", agent.id, users[1].id, room.id)
    assert (await db.scalars(select(CodeWorkspace))).all() == []
    await db.commit()
    # Model the resolving HTTP request closing before the separate IDE session request.
    async with AsyncSession(bind=db.bind, expire_on_commit=False, join_transaction_mode="create_savepoint") as request:
        token = db_session_ctx.set(request)
        try:
            opened = await service.human_directory_repository("console://project/", agent.id, users[0].id, room.id)
        finally:
            db_session_ctx.reset(token)
    again = await service.human_directory_repository("console://project/", agent.id, users[0].id, room.id)
    assert opened.id == again.id and opened.mode == "edit"
    assert len((await db.scalars(select(CodeConversationLink).where(
        CodeConversationLink.workspace_id == opened.id, CodeConversationLink.room_id == room.id))).all()) == 1
    with pytest.raises(PermissionError):
        await service.human_directory_repository("console://project/", agent.id, users[1].id, room.id)
    db.add(CodeGrant(workspace_id=opened.id, user_id=users[1].id, mode="read"))
    await db.flush()
    shared = await service.human_directory_repository("console://project/", agent.id, users[1].id, room.id)
    assert shared.id == opened.id and shared.mode == "read"
    runtime.open.assert_not_awaited()


@pytest.mark.asyncio
async def test_sessions_reuse_runtime_identity_and_launch_tickets_expire_or_lose_their_grant(repository_scope, db):
    users, agent, _, _, runtime = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    first = await service.open_session(workspace.id, None)
    second = await service.open_session(workspace.id, None)
    assert first.id == second.id
    assert runtime.open.await_args.args[2] == first.id
    session = await db.get(CodeSession, first.id)
    assert session is not None and session.state == "ready"
    ticket = second.url.split("ticket=", 1)[1]
    await service.authorize_session(session.id, ticket, ticket=True)
    session.ticket_expires_at = service.now() - timedelta(seconds=1)
    with pytest.raises(PermissionError):
        await service.authorize_session(session.id, ticket, ticket=True)
    session.cookie_digest = service.digest("synthetic cookie")
    await db.flush()
    grant = await db.scalar(select(CodeGrant).where(CodeGrant.workspace_id == workspace.id, CodeGrant.user_id == users[0].id))
    assert grant is not None
    grant.mode = "read"
    await db.flush()
    with pytest.raises(PermissionError):
        await service.authorize_session(session.id, "synthetic cookie")


@pytest.mark.asyncio
async def test_read_grant_cannot_start_editing_and_changed_target_is_not_reused(repository_scope, db):
    users, agent, _, target, runtime = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    grant = await db.scalar(select(CodeGrant).where(CodeGrant.workspace_id == workspace.id, CodeGrant.user_id == users[0].id))
    grant.mode = "read"
    await db.flush()
    with pytest.raises(PermissionError):
        await service.open_session(workspace.id, "edit")
    read = await service.open_session(workspace.id, None)
    assert read.workspace.mode == "read"
    runtime.open.assert_awaited_once()
    workspace.generation = "c" * 64
    with pytest.raises(PermissionError):
        await service.open_session(workspace.id, "read")


@pytest.mark.parametrize("path", ["../sessions", "%2e%2e/sessions", "assets/../sessions", "\\sessions", "assets/%00"])
def test_proxy_paths_cannot_reach_runtime_management_routes(path):
    from app.code.gateway import validate_proxy_path
    with pytest.raises(PermissionError):
        validate_proxy_path(path)


@pytest.mark.asyncio
async def test_browser_families_are_independent_and_revocation_closes_an_existing_cookie(repository_scope, db, monkeypatch):
    _, agent, _, _, _ = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    first = await service.open_session(workspace.id, None)
    monkeypatch.setattr(service, "current_web_session_family", lambda: "second-synthetic-browser-family")
    second = await service.open_session(workspace.id, None)
    assert first.id != second.id
    session = await db.get(CodeSession, first.id)
    session.cookie_digest = service.digest("synthetic-cookie")
    await db.flush()
    monkeypatch.setattr(service, "web_session_active", AsyncMock(return_value=False))
    with pytest.raises(PermissionError, match="Browser session revoked"):
        await service.authorize_session(first.id, "synthetic-cookie")
    monkeypatch.setattr(service, "web_session_active", AsyncMock(return_value=True))
    session.role_bound, session.role_id = True, None
    await db.flush()
    with pytest.raises(PermissionError, match="Editor role revoked"):
        await service.authorize_session(first.id, "synthetic-cookie")


@pytest.mark.asyncio
async def test_context_requires_a_presented_room_and_retained_session_is_recoverable(repository_scope, db, monkeypatch):
    users, agent, _, _, _ = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    with pytest.raises(PermissionError, match="not presented"):
        await service.workspace_context(workspace.id, users[0].id, uuid4())
    opened = await service.open_session(workspace.id, None)
    session = await db.get(CodeSession, opened.id)
    session.state, session.cookie_digest = "closed", service.digest("old-cookie")
    await db.flush()
    monkeypatch.setattr(service, "current_web_session_family", lambda: "new-synthetic-login-family")
    recovered = await service.open_session(workspace.id, None)
    assert recovered.id == opened.id
    assert session.cookie_digest is None
    assert session.session_family == "new-synthetic-login-family"


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["grant", "family", "connection", "checkout", "role", "auth"])
async def test_expired_session_recovery_rechecks_its_original_access_and_target(repository_scope, db, monkeypatch, denial):
    users, agent, _, _, runtime = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    opened = await service.open_session(workspace.id, None)
    session = await db.get(CodeSession, opened.id)
    session.expires_at = service.now() - timedelta(seconds=1)
    if denial == "grant":
        grant = await db.scalar(select(CodeGrant).where(CodeGrant.workspace_id == workspace.id, CodeGrant.user_id == users[0].id))
        grant.mode = "read"
    elif denial == "family":
        monkeypatch.setattr(service, "current_web_session_family", lambda: "another-browser-family")
    elif denial == "connection":
        runtime.connection.return_value = runtime.connection.return_value.model_copy(update={"fingerprint": "changed-console"})
    elif denial == "checkout":
        runtime.discover.return_value = runtime.discover.return_value.model_copy(update={"generation": "changed-checkout"})
    elif denial == "role":
        session.role_bound, session.role_id = True, None
    else:
        session.auth_version -= 1
    await db.flush()
    runtime.open.reset_mock()
    with pytest.raises(PermissionError):
        await service.resume_session(session.id)
    runtime.open.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("replaced,live_session", [(False, False), (True, False), (False, True)])
async def test_editor_deployment_preserves_verified_repository_links_but_never_rebinds_a_replaced_checkout(repository_scope, db, replaced, live_session):
    from app.code.runtime_configuration import prepare_runtime_configuration, finish_runtime_configuration, lock_runtime_upgrade

    _, agent, config, target, _ = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    previous = CodeConnection(connection_id=config.connection_id, fingerprint=connection_generation(config))
    verified = await prepare_runtime_configuration(previous, AsyncMock(return_value=target))
    if live_session:
        await service.open_session(workspace.id, None)
    current = CodeConnection(connection_id=config.connection_id, fingerprint="new-runtime-fingerprint")
    changed = target.model_copy(update={"generation": "c" * 64, **({"root_identity": "10:99"} if replaced else {})})
    if live_session:
        with pytest.raises(ValueError, match="wait for sessions to expire"):
            await lock_runtime_upgrade(previous)
        with pytest.raises(ValueError, match="wait for sessions to expire"):
            await finish_runtime_configuration(current, verified, AsyncMock(return_value=changed))
    else:
        await lock_runtime_upgrade(previous)
        await finish_runtime_configuration(current, verified, AsyncMock(return_value=changed))
    await db.flush()
    assert workspace.id in verified
    assert workspace.generation == (target.generation if replaced or live_session else changed.generation)
    assert workspace.connection_fingerprint == (previous.fingerprint if replaced or live_session else current.fingerprint)


@pytest.mark.asyncio
async def test_a_dead_runtime_does_not_starve_other_session_cleanup(repository_scope, db, monkeypatch):
    from app.code import lifecycle
    _, agent, _, _, runtime = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    sessions = []
    for index in range(3):
        monkeypatch.setattr(service, "current_web_session_family", lambda index=index: f"synthetic-cleanup-{index}")
        opened = await service.open_session(workspace.id, None)
        session = await db.get(CodeSession, opened.id)
        sessions.append(session)
    for session in sessions:
        session.expires_at = service.now() - timedelta(minutes=1)
    await db.commit()
    async def cleanup(config, identifier, **kwargs):
        if identifier == sessions[0].id:
            raise RuntimeError("Synthetic unreachable target")
    runtime.close.side_effect = cleanup
    monkeypatch.setattr(lifecycle, "runtime", lambda: runtime)
    monkeypatch.setattr(lifecycle, "RECONCILIATION_BATCH_SIZE", 2)
    await lifecycle.reconcile_sessions()
    assert sessions[0].state == "closing" and sessions[1].state == "closed"
    assert sessions[2].state == "ready"
    await lifecycle.reconcile_sessions()
    assert sessions[2].state == "closed"
    assert all(session.reconciled_at is not None for session in sessions)


@pytest.mark.asyncio
async def test_linked_live_task_presents_before_completion_and_superseded_round_does_not_take_focus(repository_scope, db, monkeypatch):
    from app.conversation import repository_display
    from app.conversation.models import ConversationRound, ConversationTaskLink
    from app.code.models import CodeDisplayRequest
    from app.messenger import create_internal_room
    from app.task import Task, TaskStatus
    from app.tools import McpToolContext

    _, agent, _, _, _ = repository_scope
    for code in ("chat", "conversation"):
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == code))
        db.add(Connection(agent_id=agent.id, tool_id=tool.id, active=True))
    await db.flush()
    room = await create_internal_room(actor_user_id=agent.user_id, agent_id=agent.id)
    origin = ConversationRound(room_id=room.id, requester_user_id=agent.user_id,
        language="en", status="SUCCEEDED", created_at=service.now())
    task = Task(agent_id=agent.id, label="Synthetic repository development", status=TaskStatus.EXEC,
        paused=False, lease_token=uuid4(), lease_expires_at=service.now() + timedelta(minutes=5))
    db.add_all([origin, task])
    await db.flush()
    db.add(ConversationTaskLink(round_id=origin.id, task_id=task.id, action_key="synthetic-repository-task"))
    await db.flush()
    publisher = AsyncMock()
    monkeypatch.setattr(repository_display, "_publisher", publisher)
    ctx = McpToolContext(agent_id=agent.id, runtime="internal", task_id=task.id)
    shown = await repository_display.show_repository(ctx, "console://project/", "source.py", "changes")
    assert shown["status"] == "requested"
    publisher.assert_awaited_once()
    assert task.status == TaskStatus.EXEC
    first_sequence = int(publisher.await_args.args[-1])
    db.add(ConversationRound(room_id=room.id, requester_user_id=agent.user_id,
        language="en", status="RUNNING", created_at=origin.created_at + timedelta(seconds=1)))
    await db.flush()
    referenced = await repository_display.show_repository(ctx, shown["uri"], None, "files")
    assert referenced["status"] == "referenced"
    assert publisher.await_count == 1
    requests = (await db.scalars(select(CodeDisplayRequest).where(CodeDisplayRequest.room_id == room.id).order_by(CodeDisplayRequest.id))).all()
    assert len(requests) == 2 and requests[0].id == first_sequence
    task.paused = True
    await db.flush()
    with pytest.raises(PermissionError):
        await repository_display.show_repository(ctx, shown["uri"], None, "changes")
    unlinked = Task(agent_id=agent.id, label="Synthetic autonomous task", status=TaskStatus.EXEC,
        lease_token=uuid4(), lease_expires_at=service.now() + timedelta(minutes=5))
    db.add(unlinked)
    await db.flush()
    assert not await repository_display.can_show_repository(McpToolContext(agent_id=agent.id, runtime="internal", task_id=unlinked.id))


@pytest.mark.asyncio
async def test_http_launch_tickets_sharing_and_heartbeat_have_durable_effects(repository_scope, db, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from main import app
    from core.database import database, middleware
    from core.settings import settings
    from core.user import get_current_user, current_web_session_family, web_session_active
    from core.user.auth_service import create_access_token_for_user
    from core.user.refresh_session_service import create_refresh_session, family_for_token
    from app.code import contracts, gateway

    users, agent, _, _, runtime = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    refresh = await create_refresh_session(users[0].id)
    family = await family_for_token(refresh)
    token = await create_access_token_for_user(users[0], db, session_family=family)
    monkeypatch.setattr(service, "get_current_user", get_current_user)
    monkeypatch.setattr(service, "current_web_session_family", current_web_session_family)
    monkeypatch.setattr(service, "web_session_active", web_session_active)
    monkeypatch.setattr(contracts, "_runtime", runtime)
    monkeypatch.setattr(middleware, "AsyncSessionLocal", database.AsyncSessionLocal)
    monkeypatch.setattr(settings, "APP_HOST", "https://localhost:8484")
    headers = {"Authorization": "Bearer " + token}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost:8484") as http:
        from bridge.code_server.adapter import CodeServerRuntime

        # Use the real adapter's preflight: an accessible external checkout alone
        # does not provide an IDE, and the API must retain this actionable cause.
        config = repository_scope[2]
        runtime.open.side_effect = CodeServerRuntime(AsyncMock(return_value=config)).open
        unavailable = await http.post(f"/api/code/workspaces/{workspace.id}/sessions", headers=headers, json={})
        assert unavailable.status_code == 503
        assert unavailable.json() == {"detail": "code_runtime_not_configured"}
        failed_session = await db.scalar(select(CodeSession).where(CodeSession.workspace_id == workspace.id))
        assert failed_session.state == "failed"
        runtime.open.side_effect = None
        opened = await http.post(f"/api/code/workspaces/{workspace.id}/sessions", headers=headers, json={})
        assert opened.status_code == 200, opened.text
        # Ordinary opening leaves native VS Code navigation unchanged.
        runtime.navigate.assert_not_awaited()
        data = opened.json()
        identifier = data["id"]
        assert identifier == str(failed_session.id)
        themed = await http.post(f"/api/code/sessions/{identifier}/theme", headers=headers, json={"theme": "dark"})
        assert themed.status_code == 404
        ticket = data["url"].split("#ticket=")[1]
        launch_path = f"/api/code/gateway/{identifier}/launch"
        assert data["url"].startswith("https://localhost:8484" + launch_path + "#ticket=")
        bootstrap = await http.get(launch_path)
        assert bootstrap.status_code == 200
        assert bootstrap.headers["x-frame-options"] == "SAMEORIGIN"
        assert bootstrap.headers["referrer-policy"] == "no-referrer"
        wrong_host = await http.get("https://localhost:8485" + launch_path)
        assert wrong_host.status_code == 403
        launch_url = "https://localhost:8484" + launch_path
        foreign_origin = await http.post(launch_url, headers={"Origin": "https://foreign.example.test"}, json={"ticket": ticket})
        assert foreign_origin.status_code == 403
        launched = await http.post(launch_url, headers={"Origin": "https://localhost:8484"}, json={"ticket": ticket})
        assert launched.status_code == 200, launched.text
        cookie_header = launched.headers["set-cookie"]
        assert "HttpOnly" in cookie_header and "Secure" in cookie_header and "SameSite=strict" in cookie_header
        assert f"Path=/api/code/gateway/{identifier}/" in cookie_header
        assert ticket not in launched.text and "transport" not in launched.text
        replay = await http.post(launch_url, headers={"Origin": "https://localhost:8484"}, json={"ticket": ticket})
        assert replay.status_code == 403
        shared = await http.put(f"/api/code/workspaces/{workspace.id}/grants", headers=headers,
            json={"user_id": users[1].id, "mode": "read"})
        assert shared.status_code == 404
        assert await db.scalar(select(CodeGrant.id).where(CodeGrant.workspace_id == workspace.id, CodeGrant.user_id == users[1].id)) is None
        assert (await http.get(f"/api/code/workspaces/{workspace.id}/grants", headers=headers)).status_code == 404
        assert (await http.delete(f"/api/code/sessions/{identifier}", headers=headers)).status_code == 404
        session = await db.get(CodeSession, identifier, populate_existing=True)
        session.expires_at = service.now() + timedelta(seconds=30)
        await db.commit()
        heartbeat = await http.post(f"/api/code/sessions/{identifier}/heartbeat", headers=headers)
        assert heartbeat.status_code == 200, heartbeat.text
        persisted = await db.get(CodeSession, identifier, populate_existing=True)
        assert persisted.expires_at > service.now() + timedelta(minutes=9)
        # Explicit recovery renews the same IDE and cookie, without a new frame
        # or profile. An expired heartbeat alone must never renew authorization.
        old_cookie = http.cookies.get('galaris_code')
        persisted.expires_at = service.now() - timedelta(seconds=1)
        await db.commit()
        assert (await http.post(f"/api/code/sessions/{identifier}/heartbeat", headers=headers)).status_code == 410
        resumed = await http.post(f"/api/code/sessions/{identifier}/resume", headers=headers)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()['restart_required'] is False
        persisted = await db.get(CodeSession, identifier, populate_existing=True)
        assert persisted.state == 'ready'
        assert persisted.expires_at > service.now() + timedelta(minutes=9)
        assert http.cookies.get('galaris_code') != old_cookie
        assert runtime.open.await_args.args[2] == persisted.id
        assert 'HttpOnly' in resumed.headers['set-cookie']
        assert f'Path=/api/code/gateway/{identifier}/' in resumed.headers['set-cookie']
        # A stopped runtime is recoverable, whereas a network outage stays a 503.
        from app.code.contracts import CodeSessionUnavailableError
        runtime.touch.side_effect = RuntimeError('Synthetic network interruption')
        assert (await http.post(f"/api/code/sessions/{identifier}/heartbeat", headers=headers)).status_code == 503
        runtime.touch.side_effect = CodeSessionUnavailableError('Synthetic stopped IDE')
        assert (await http.post(f"/api/code/sessions/{identifier}/heartbeat", headers=headers)).status_code == 410
        recovered = await http.post(f"/api/code/sessions/{identifier}/resume", headers=headers)
        assert recovered.status_code == 200
        assert recovered.json()['restart_required'] is True
        assert recovered.json()['url'] == f'https://localhost:8484/api/code/gateway/{identifier}/editor/'
        runtime.touch.side_effect = None
        # A revoked browser family invalidates an already launched IDE cookie.
        from core.user.refresh_session_service import revoke_refresh_token
        await revoke_refresh_token(refresh)
        denied = await http.get(f"https://localhost:8484/api/code/gateway/{identifier}/editor/")
        assert denied.status_code == 403
        assert (await http.post(f"/api/code/sessions/{identifier}/resume", headers=headers)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_editor_deployment_endpoint_requires_edit_rights_and_agent_ownership(repository_scope, db, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from main import app
    from core.database import database, middleware
    from core.user.auth_service import create_access_token_for_user
    from app.console import router as console_router
    from app.console.schemas import ConsoleEditorInstallResult

    users, _, config, _, _ = repository_scope
    monkeypatch.setattr(middleware, "AsyncSessionLocal", database.AsyncSessionLocal)
    installer = AsyncMock(return_value=ConsoleEditorInstallResult(connection_id=config.connection_id,
        port=32123, version="4.141.0", ready=True, already_installed=False))
    monkeypatch.setattr(console_router, "install_connection_editor", installer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost:8484") as http:
        token = await create_access_token_for_user(users[0], db)
        headers = {"Authorization": "Bearer " + token}
        url = f"/api/console/connections/{config.connection_id}/install-editor"
        denied = await http.post(url, headers=headers)
        assert denied.status_code == 403
        installer.assert_not_awaited()
        role = await db.scalar(select(Assignment.role_id).where(Assignment.user_id == users[0].id))
        privilege = await db.scalar(select(Privilege.id).where(Privilege.code == "CONNECTION_EDIT"))
        db.add(RolePrivilege(role_id=role, privilege_id=privilege))
        await db.commit()
        outsider = await create_access_token_for_user(users[1], db)
        denied = await http.post(url, headers={"Authorization": "Bearer " + outsider})
        assert denied.status_code == 404
        installer.assert_not_awaited()
        installed = await http.post(url, headers=headers)
        assert installed.status_code == 200, installed.text
        assert installed.json()["ready"] is True
        assert "token" not in installed.text
        installer.assert_awaited_once_with(config.connection_id, False)
        upgraded = await http.post(url + "?upgrade=true", headers=headers)
        assert upgraded.status_code == 200, upgraded.text
        installer.assert_awaited_with(config.connection_id, True)
        from bridge.code_server.deployment import EditorDeploymentError
        installer.side_effect = EditorDeploymentError("upgrade", "sessions_active")
        blocked = await http.post(url + "?upgrade=true", headers=headers)
        assert blocked.status_code == 400
        assert "sessions_active" in blocked.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("forwarding_works,management_works", [(False, True), (True, True), (True, False)])
@pytest.mark.parametrize("automatic", [False, "current", "changed", "busy", "wrong_port", "wrong_credential", "unmanaged", "remote_busy", "remote_unknown"])
async def test_console_editor_deployment_only_publishes_verified_credentials_and_preserves_links(repository_scope, db, monkeypatch, forwarding_works, management_works, automatic):
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    import httpx
    from app.console.contracts import ConsoleResult, ConsoleStatus
    from app.console import editor_service
    from app.connection.facade import set_params_bulk, get_params_as_dict
    from bridge.code_server import deployment

    _, agent, config, target, _ = repository_scope
    from app.agent import AgentManagementScope
    monkeypatch.setattr(editor_service, "current_management_scope", AsyncMock(return_value=AgentManagementScope(user_id=agent.user_id, agent_ids=frozenset({agent.id}) if management_works else frozenset())))
    await set_params_bulk(config.connection_id, {"host": config.host, "username": config.username,
        "private_key": config.private_key.get_secret_value(), "known_host_key": config.known_host_key})
    workspace = await service.register_repository("console://project/", agent.id)
    synthetic_token = "synthetic-editor-deployment-credential-0000001"
    configured_token = "synthetic-different-credential-0000000001" if automatic == "wrong_credential" else synthetic_token
    if automatic:
        await set_params_bulk(config.connection_id, {"code_runtime_port": "32124" if automatic == "wrong_port" else "32123", "code_runtime_token": configured_token})
        if automatic in ("current", "busy"):
            # Current runtimes remain usable; upgrades must preserve live buffers.
            await service.open_session(workspace.id, None)
    await db.commit()
    files = {}

    class RemoteFile:
        def __init__(self, path):
            self.path = path
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def write(self, payload):
            files[self.path] = payload
        async def read(self, count):
            return synthetic_token.encode()[:count]

    class Sftp:
        async def realpath(self, path):
            return path
        async def lstat(self, path):
            return object()
        async def chmod(self, path, mode):
            pass
        async def posix_rename(self, source, destination):
            files[destination] = files.pop(source)
        async def remove(self, path):
            import asyncssh
            if path not in files:
                raise asyncssh.SFTPNoSuchFile("Synthetic missing file")
            files.pop(path)
        def open(self, path, *args, **kwargs):
            return RemoteFile(path)
        def exit(self):
            pass

    transport = SimpleNamespace(status=AsyncMock(return_value=ConsoleStatus(reachable=True, authenticated=True,
        host_key_verified=True, home_writable=True, sftp_available=True)),
        connection=AsyncMock(return_value=SimpleNamespace(start_sftp_client=AsyncMock(return_value=Sftp()))),
        home=AsyncMock(return_value=target.home), close=AsyncMock(),
        exec=AsyncMock(return_value=ConsoleResult(status="completed", exit_code=0,
            stdout=json.dumps({"port": 32123, "version": "4.141.0", "already_installed": False}))))
    if automatic:
        deployed = transport.exec.return_value
        if automatic in ("remote_busy", "remote_unknown"):
            deployed = ConsoleResult(status="failed", exit_code=1,
                stdout=json.dumps({"error": "sessions_active" if automatic == "remote_busy" else synthetic_token,
                    "diagnostic": [{"command": "docker top synthetic-runtime -eo pid,comm", "exit_code": 1,
                                    "stderr": "Synthetic Docker explanation"}]}),
                stderr=synthetic_token)
        transport.exec.side_effect = [
            ConsoleResult(status="completed", exit_code=0, stdout=json.dumps({
                "managed": automatic != "unmanaged", "update_required": automatic != "current", "port": 32123})),
            deployed,
        ]
    monkeypatch.setattr(deployment, "SshExecutionTransport", lambda config: transport)
    async def discover(config, path):
        return RepositoryTarget.model_validate(target.model_copy(update={
            "generation": "c" * 64 if config.code_runtime_token else target.generation,
        }).model_dump())
    monkeypatch.setattr(deployment, "discover_repository", discover)
    @asynccontextmanager
    async def tunnel(config):
        assert config.code_runtime_token.get_secret_value() == synthetic_token
        yield "http://synthetic-runtime.test"
    monkeypatch.setattr(deployment, "code_runtime_tunnel", tunnel)
    original_client = httpx.AsyncClient
    def client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(
            200 if forwarding_works else 503,
            json={"ready": True, "protocol": 1, "version": "4.141.0"})))
    monkeypatch.setattr(deployment.httpx, "AsyncClient", client)
    monkeypatch.setattr(editor_service, "_installer", deployment.deploy_connection_code_editor)
    succeeded = forwarding_works and (management_works or automatic) and automatic not in ("busy", "wrong_port", "wrong_credential", "unmanaged", "remote_busy", "remote_unknown")
    install = deployment.update_connection_code_editor if automatic else editor_service.install_connection_editor
    if automatic == "unmanaged":
        assert await install(config.connection_id) is None
    elif automatic in ("remote_busy", "remote_unknown"):
        with pytest.raises(deployment.EditorDeploymentError) as failure:
            await install(config.connection_id)
        assert "upgrade" in str(failure.value)
        assert ("sessions_active" in str(failure.value)) == (automatic == "remote_busy")
        assert synthetic_token not in str(failure.value)
        assert failure.value.diagnostic[0]["stderr"] == "Synthetic Docker explanation"
    elif succeeded:
        result = await install(config.connection_id)
        assert result.ready and result.port == 32123
        assert synthetic_token not in result.model_dump_json()
    else:
        message = ("configured port" if automatic == "wrong_port" else
                   "configured credential" if automatic == "wrong_credential" else
                   "wait for sessions to expire" if automatic == "busy" else
                   "forwarding verification failed" if not forwarding_works else "management access changed")
        with pytest.raises(ValueError, match=message):
            await install(config.connection_id)
    _, params = await get_params_as_dict(config.connection_id, decrypt_passwords=True)
    assert params.get("code_runtime_token") == (configured_token if automatic else synthetic_token if succeeded else None)
    assert workspace.generation == ("c" * 64 if succeeded and not automatic else target.generation)
    assert workspace.id in (await db.scalars(select(CodeWorkspace.id))).all()
    transport.close.assert_awaited_once()
    if automatic in ("busy", "wrong_port", "wrong_credential", "unmanaged"):
        assert transport.exec.await_count == 1  # Inspection only, no replacement.


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["configured", "embedded", "unconfigured", "partial", "inactive"])
async def test_editor_maintenance_selects_only_active_configured_external_consoles(repository_scope, db, kind):
    from app.console import configured_external_editor_connections
    from app.connection.facade import set_params_bulk

    _, _, config, _, _ = repository_scope
    params = {"host": "ssh-executor" if kind == "embedded" else "synthetic.test"}
    if kind != "unconfigured":
        params["code_runtime_port"] = "32123"
    if kind not in ("unconfigured", "partial"):
        params["code_runtime_token"] = "synthetic-editor-credential-00000001"
    await set_params_bulk(config.connection_id, params)
    if kind == "inactive":
        connection = await db.get(Connection, config.connection_id)
        connection.active = False
        await db.commit()
    selected = await configured_external_editor_connections()
    assert (config.connection_id in selected) == (kind in ("configured", "partial"))


@pytest.mark.asyncio
@pytest.mark.parametrize("recognized", [False, True])
async def test_editor_update_reports_failures_without_secrets_and_continues_other_targets(repository_scope, db, monkeypatch, capsys, recognized, tmp_path):
    import code_editor_update
    from bridge.code_server import deployment
    from app.connection.facade import set_params_bulk
    from app.console import ConsoleEditorInstallResult
    from core import update_diagnostics
    monkeypatch.setattr(update_diagnostics, "DIAGNOSTIC_ROOT", tmp_path)

    _, agent, config, _, _ = repository_scope
    other = Agent(title_id=agent.title_id, user_id=agent.user_id, first_name="Synthetic", last_name="Other developer",
                  code=f"code-{uuid4().hex[:12]}", agent_driver="internal")
    db.add(other)
    await db.flush()
    first = await db.get(Connection, config.connection_id)
    second = Connection(agent_id=other.id, tool_id=first.tool_id, active=True)
    db.add(second)
    await db.flush()
    identifiers = [first.id, second.id]
    for identifier in identifiers:
        await set_params_bulk(identifier, {"host": "synthetic.test", "code_runtime_port": "32123",
            "code_runtime_token": "synthetic-private-editor-credential-00001"})
    await db.commit()
    error = (deployment.EditorDeploymentError("upgrade", "docker_command_failed", [{
                 "command": "docker top synthetic-runtime -eo comm", "exit_code": 1,
                 "stderr": "Couldn't find PID field in ps output; token=synthetic-private-editor-credential-00001",
             }]) if recognized else
             RuntimeError("synthetic-private-editor-credential-00001"))
    updater = AsyncMock(side_effect=[error,
        ConsoleEditorInstallResult(connection_id=second.id, port=32123, version="4.141.0", ready=True, already_installed=True)])
    monkeypatch.setattr(deployment, "update_connection_code_editor", updater)
    assert not await code_editor_update.update_editors()
    assert [call.args[0] for call in updater.await_args_list] == identifiers
    output = capsys.readouterr()
    assert "update failed" in output.err and "rerun make update" in output.err
    assert "verified" in output.out
    assert ("docker_command_failed" in output.err) == recognized
    assert "synthetic-private-editor-credential-00001" not in output.err + output.out
    diagnostics = list(tmp_path.glob("update-*.json"))
    assert len(diagnostics) == 1
    assert str(diagnostics[0]) in output.err
    assert "synthetic-private-editor-credential-00001" not in diagnostics[0].read_text()
    if recognized:
        assert "Couldn't find PID field" in diagnostics[0].read_text()
        assert '"exit_code": 1' in diagnostics[0].read_text()


@pytest.mark.asyncio
async def test_editor_update_cli_boots_without_an_authenticated_request(db):
    import asyncio
    import subprocess
    import sys

    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "code_editor_update"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_an_open_websocket_is_closed_after_editing_is_revoked(repository_scope, db, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from main import app
    from core.database import database, middleware
    from app.code import contracts, gateway, RuntimeEndpoint
    from websockets.asyncio.server import serve

    users, agent, _, _, runtime = repository_scope
    workspace = await service.register_repository("console://project/", agent.id)
    opened = await service.open_session(workspace.id, None)
    session = await db.get(CodeSession, opened.id)
    session.cookie_digest = service.digest("synthetic-ide-cookie")
    await db.commit()
    monkeypatch.setattr(middleware, "AsyncSessionLocal", database.AsyncSessionLocal)
    monkeypatch.setattr(contracts, "_runtime", runtime)
    monkeypatch.setattr(service.settings, "APP_HOST", "https://localhost:8484")
    monkeypatch.setattr(gateway, "REVOCATION_CHECK_SECONDS", 0.02)

    async def echo(connection):
        assert connection.request.headers["Authorization"] == "Bearer synthetic-broker-credential"
        async for payload in connection:
            await connection.send(payload)

    async with serve(echo, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        @asynccontextmanager
        async def endpoint(config):
            yield RuntimeEndpoint(url=f"http://127.0.0.1:{port}", credential="synthetic-broker-credential")
        runtime.endpoint = endpoint
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        scope = {"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "wss",
            "path": f"/api/code/gateway/{opened.id}/editor/", "raw_path": b"/", "query_string": b"",
            "root_path": "", "server": ("localhost", 8484), "client": ("127.0.0.1", 20000),
            "subprotocols": [], "headers": [(b"host", b"localhost:8484"), (b"origin", b"https://localhost:8484"),
                (b"cookie", b"galaris_code=synthetic-ide-cookie")]}
        await incoming.put({"type": "websocket.connect"})
        connection = asyncio.create_task(app(scope, incoming.get, outgoing.put))
        try:
            accepted = await asyncio.wait_for(outgoing.get(), 3)
            assert accepted["type"] == "websocket.accept", accepted
            await incoming.put({"type": "websocket.receive", "bytes": b"synthetic IDE protocol bytes"})
            echoed = await asyncio.wait_for(outgoing.get(), 3)
            assert echoed["type"] == "websocket.send" and echoed["bytes"] == b"synthetic IDE protocol bytes"
            grant = await db.scalar(select(CodeGrant).where(CodeGrant.workspace_id == workspace.id, CodeGrant.user_id == users[0].id))
            grant.mode = "read"
            await db.commit()
            closed = await asyncio.wait_for(outgoing.get(), 3)
            assert closed["type"] == "websocket.close" and closed["code"] == 1008
        finally:
            connection.cancel()
            await asyncio.gather(connection, return_exceptions=True)
