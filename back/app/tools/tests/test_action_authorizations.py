"""Approval protects the actual dispatch across retries and concurrent decisions."""

import asyncio
from unittest.mock import AsyncMock
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent import Agent, Title
from app.agent.authorization import set_yolo
from app.tools.authorization import (
    AuthorizationAction, AuthorizationClosed, AuthorizationRequired,
    answer_action, claim_action, finish_action,
)
from app.tools.authorization_models import ActionAuthorization
from core.database import get_db_session
from core.user import UserModel


@pytest_asyncio.fixture
async def action(committed_database):
    async with get_db_session() as db:
        user = UserModel(email=f"approver-{uuid4().hex}@example.test", hashed_password="synthetic")
        title = Title(label="Synthetic", gender="X")
        db.add_all([user, title])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"approval-{uuid4().hex}", first_name="Synthetic", last_name="Agent")
        db.add(agent)
        await db.flush()
        return AuthorizationAction(agent_id=agent.id, runtime="internal", context_key="principal:synthetic-run",
                                   callback_key=str(uuid4()), source="runtime", name="command",
                                   arguments={"command": "echo synthetic", "cwd": "/workspace"},
                                   configuration={"session": "synthetic-session"})


async def pending(action):
    with pytest.raises(AuthorizationRequired) as caught:
        await claim_action(action)
    return caught.value.request_id


@pytest.mark.asyncio
async def test_deleted_agent_cannot_answer_or_resume_but_keeps_the_audit(action):
    from app.tools.authorization_notifications import reconcile_authorizations
    identifier = await pending(action)
    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        agent.soft_delete()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True) is False
    with pytest.raises(PermissionError, match="unavailable"):
        await claim_action(action)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "invalidated" and row.encrypted_arguments is None
        assert row.agent_id == action.agent_id and row.approver_user_id is not None


@pytest.mark.asyncio
async def test_refused_arguments_cannot_create_a_new_question_under_a_new_callback(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=False)
    with pytest.raises(AuthorizationClosed, match="denied") as refused:
        await claim_action(replace(action, callback_key=str(uuid4())))
    assert refused.value.request_id == identifier


@pytest.mark.asyncio
async def test_runtime_run_grant_is_scoped_renewable_and_revoked_by_assignment_changes(action, monkeypatch):
    from app.agent import AgentSnapshot, ResolvedExecutionTarget, AgentRunCheckpoint
    from app.agent.tests.test_driver_testkit import _request
    from app.harnesses.models import Harness, AgentHarness
    from app.tools.runtime_authorization import issue_runtime_run_grant, resolve_runtime_run_grant, renew_runtime_run_grant, revoke_runtime_run_grant
    from app.tools.runtime_principals import runtime_principal_port
    from app.mcp.service import rotate_system_token
    from app.mcp.service import create_token_for_agent
    from app.mcp.schemas import AgentMcpTokenCreate
    async with get_db_session() as db:
        agent = await db.get(Agent, action.agent_id)
        harness = Harness(name="Synthetic approval harness", provider_code="openai_messages", driver_code="openai_messages",
            enabled=True, base_url="http://harness.example.test/v1", model="synthetic", capabilities=["execute", "stream"])
        db.add(harness)
        await db.flush()
        agent.task_harness_id = harness.id
        assignment = AgentHarness(agent_id=agent.id, harness_id=harness.id, provider_code="openai_messages", lifecycle_status="ready")
        db.add(assignment)
        await db.flush()
        agent_id, assignment_id, harness_id = agent.id, assignment.id, harness.id
        bearer = await rotate_system_token(agent_id)
        _, visible_bearer = await create_token_for_agent(agent_id, AgentMcpTokenCreate(label="Synthetic external client"))
        principal = await runtime_principal_port().for_agent(agent_id)
    request = replace(_request(), task_id=None, driver_code="openai_messages",
        agent=AgentSnapshot(id=agent_id, code="synthetic", first_name="Synthetic", last_name="Runtime", driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code="openai_messages", target_ref=f"harness:{assignment_id}", revision="1"))
    credential = await issue_runtime_run_grant(request)
    grant = await resolve_runtime_run_grant(credential, principal=principal)
    from httpx import ASGITransport, AsyncClient
    from main import app
    headers = {"Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": credential}
    endpoint = "/api/tools/runtime-authorizations"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 401
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={**headers, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 200
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={"Authorization": f"Bearer {visible_bearer}", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 200
        assert (await client.get(endpoint + "/context", headers={"Authorization": f"Bearer {bearer}"})).status_code == 401
        assert (await client.get(endpoint + "/context", headers={**headers, "Authorization": "Bearer invalid-synthetic-principal"})).status_code == 401
        assert (await client.get(endpoint + "/context", headers={**headers, "X-Galaris-Run-Context": "foreign-synthetic-context"})).status_code == 403
        assert (await client.get(endpoint + "/context", headers=headers)).json()["active"] is True
        payload = {"callback_key": "one-call", "name": "write_file", "session": "synthetic",
            "arguments": {"path": "synthetic.txt", "content": "approved"}}
        response = await client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 200 and response.json()["status"] == "pending"
        identifier = UUID(response.json()["request_id"])
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["request_id"] == str(identifier)
        assert (await client.get(endpoint + f"/{uuid4()}", headers=headers)).status_code == 404
        assert (await client.get(endpoint + f"/{identifier}", headers=headers)).json()["status"] == "pending"
        assert (await client.post(f"/api/tools/action-authorizations/{identifier}/answer", headers=headers,
            json={"approved": True})).status_code in (401, 403)
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["claimed"] is True
        assert (await client.post(endpoint, headers=headers, json=payload)).json()["claimed"] is False
        receipt = {"request_id": str(identifier), "outcome": "completed", "receipt": {"written": True}}
        assert (await client.post(endpoint + "/receipt", headers=headers,
            json={**receipt, "request_id": str(uuid4())})).status_code == 404
        assert (await client.post(endpoint + "/receipt", headers=headers, json=receipt)).status_code == 200
        assert (await client.get(endpoint + f"/{identifier}", headers=headers)).json()["status"] == "completed"
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=replace(principal, agent_id=agent_id + 100000))
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=replace(principal, enabled=False))
    resumed = replace(request, run_id=uuid4(), attempt_id=uuid4(), resume_checkpoint=AgentRunCheckpoint(
        driver_code="openai_messages", runtime_run_id=grant.actor_key, status="waiting_for_authorization"))
    assert await renew_runtime_run_grant(credential, resumed) == credential
    with pytest.raises(PermissionError):
        await renew_runtime_run_grant(credential, replace(resumed, resume_checkpoint=None))
    from app.tools import runtime_authorization
    changed_configuration = AsyncMock(return_value={"terminal_signature": "changed-governed-connection"})
    monkeypatch.setitem(runtime_authorization._runtime_configurations, "openai_messages", changed_configuration)
    with pytest.raises(PermissionError, match="context changed"):
        await resolve_runtime_run_grant(credential, principal=principal)
    with pytest.raises(PermissionError, match="context changed"):
        await renew_runtime_run_grant(credential, resumed)
    monkeypatch.delitem(runtime_authorization._runtime_configurations, "openai_messages")
    async with get_db_session() as db:
        (await db.get(Harness, harness_id)).enabled = False
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=principal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get(endpoint + "/context", headers=headers)).status_code == 403
        assert (await client.post(f"/api/mcp/{agent.code}",
            headers={**headers, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})).status_code == 403
    async with get_db_session() as db:
        (await db.get(Harness, harness_id)).enabled = True
        (await db.get(AgentHarness, assignment_id)).revision += 1
    with pytest.raises(PermissionError):
        await resolve_runtime_run_grant(credential, principal=principal)
    revoked = await revoke_runtime_run_grant(resumed.run_id)
    assert revoked is not None and not revoked.active


@pytest.mark.asyncio
async def test_user_pause_preserves_agreement_until_resume_but_amendment_invalidates_it(action):
    from app.task.models import Task, TaskStatus
    from app.task import task_service
    async with get_db_session() as db:
        task = Task(agent_id=action.agent_id, label="Synthetic authorization", objective="<p>Synthetic objective</p>", status=TaskStatus.EXEC)
        db.add(task)
        await db.flush()
        identifier = task.id
    scoped = replace(action, context_key=f"task:{identifier}")
    request_id = await pending(scoped)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, request_id)
        assert await answer_action(request_id, user_id=row.approver_user_id, approved=True)
        task = await db.get(Task, identifier)
        task_service.suspend(task, task_service.PAUSE_USER)
    assert await pending(scoped) == request_id
    async with get_db_session() as db:
        assert (await db.get(ActionAuthorization, request_id)).status == "approved"
        task = await db.get(Task, identifier)
        task_service.release(task, task_service.PAUSE_USER)
        task.objective = "<p>Changed synthetic objective</p>"
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(scoped)


@pytest.mark.asyncio
async def test_reconciler_invalidates_a_revoked_approver_and_wakes_without_dispatch(action, monkeypatch):
    from app.tools.authorization_notifications import reconcile_authorizations
    import app.tools.authorization_notifications as outbox
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        (await db.get(UserModel, row.approver_user_id)).is_active = False
    wake = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "wake_authorization_context", wake)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "invalidated" and row.encrypted_arguments is None and row.wake_due_at is None
    wake.assert_awaited_once_with(action.agent_id, action.context_key)


@pytest.mark.asyncio
async def test_private_payload_is_encrypted_and_not_copied_into_secret_key_previews(action):
    from app.tools.authorization import redacted_action_arguments
    from core.util import get_encryption_service
    import json
    url = "https://synthetic-user:synthetic-url-password@example.test/resource?signature=synthetic-signed-secret#synthetic-fragment"
    arguments = {"token": "synthetic-private-token", "nested": {"password": "synthetic-password"}, "url": url}
    identifier = await pending(replace(action, arguments=arguments))
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert "synthetic-private-token" not in row.preview and "synthetic-password" not in row.preview
        assert "synthetic-private-token" not in row.encrypted_arguments
        assert "https://example.test/resource" in row.preview
        for private_value in ("synthetic-user", "synthetic-url-password", "synthetic-signed-secret", "synthetic-fragment"):
            assert private_value not in row.preview
            assert private_value not in str(redacted_action_arguments(arguments))
        assert json.loads(get_encryption_service().decrypt(row.encrypted_arguments))["url"] == url


@pytest.mark.asyncio
async def test_notification_failure_stays_visible_and_retries_without_dispatch(action, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import app.tools.authorization_notifications as outbox
    from app.connection import Connection
    from app.tools.models import Tool
    async with get_db_session() as db:
        chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
        db.add(Connection(agent_id=action.agent_id, tool_id=chat.id, active=True))
    identifier = await pending(action)
    monkeypatch.setattr(outbox, "request_user_choice", AsyncMock(side_effect=RuntimeError("Synthetic delivery failure")))
    await outbox.deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "pending" and row.claimed_at is None
        assert row.notification_failed_at is not None and row.interaction_id is None
        assert row.notification_due_at > datetime.now(timezone.utc)
        row.notification_due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    from app.messenger import request_user_choice
    monkeypatch.setattr(outbox, "request_user_choice", request_user_choice)
    await outbox.deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "pending" and row.claimed_at is None
        assert row.notification_failed_at is None and row.interaction_id is not None


@pytest.mark.asyncio
async def test_retention_preserves_unknown_evidence_and_accepts_late_authoritative_receipt(action):
    from datetime import datetime, timedelta, timezone
    from app.tools.authorization_notifications import reconcile_authorizations
    async with get_db_session():
        await set_yolo(action.agent_id, enabled=True, acknowledged=True)
    unknown = await claim_action(action)
    closed = await claim_action(replace(action, callback_key=str(uuid4()), arguments={"command": "other synthetic command"}))
    await finish_action(unknown, outcome="outcome_unknown", receipt={"delivery": "unknown"})
    await finish_action(closed, receipt={"delivery": "confirmed"})
    async with get_db_session() as db:
        for identifier in (unknown, closed):
            (await db.get(ActionAuthorization, identifier)).finished_at = datetime.now(timezone.utc) - timedelta(days=91)
    await reconcile_authorizations()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, unknown)
        assert row.status == "outcome_unknown" and row.encrypted_arguments and row.encrypted_receipt
        row = await db.get(ActionAuthorization, closed)
        assert row.status == "completed" and row.encrypted_arguments is None and row.encrypted_receipt is None and row.preview == ""
    await finish_action(unknown, outcome="completed", receipt={"external_receipt": "synthetic-proof"})
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(action)
    # A late conflicting callback cannot rewrite a reconciled terminal result.
    await finish_action(unknown, outcome="failed", receipt={"external_receipt": "conflicting-proof"})
    async with get_db_session() as db:
        assert (await db.get(ActionAuthorization, unknown)).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["fr", "zh-CN"])
async def test_remembered_approval_enables_only_this_connection_function_and_preserves_resume(action, language):
    from app.connection import Connection, facade as connections
    from app.messenger import answer_internal_interaction
    from app.messenger.models import Interaction
    from app.tools.authorization_notifications import deliver_authorization_notifications
    from app.tools.models import Tool
    async with get_db_session() as db:
        tool = await db.scalar(select(Tool).where(Tool.code == "topic"))
        connection = Connection(agent_id=action.agent_id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        action = replace(action, source="mcp", tool_id=tool.id, connection_id=connection.id,
                         name="topic_create", arguments={"title": "Synthetic topic"})
        chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
        db.add(Connection(agent_id=action.agent_id, tool_id=chat.id, active=True))
        manager = await db.get(UserModel, (await db.get(Agent, action.agent_id)).user_id)
        manager.language = language
    with pytest.raises(AuthorizationRequired) as caught:
        await claim_action(action)
    identifier = caught.value.request_id
    await deliver_authorization_notifications()
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert not await answer_action(identifier, user_id=row.approver_user_id + 100000, approved=True, remember=True)
        interaction = await db.get(Interaction, row.interaction_id)
        expected = (["Autoriser cette action", "Refuser cette action", "Toujours autoriser cette fonction"]
                    if language == "fr" else ["允许此操作", "拒绝此操作", "始终允许此功能"])
        assert [option["label"] for option in interaction.options] == expected
        assert "topic_create" in interaction.body
        await answer_internal_interaction(row.approver_user_id, UUID(interaction.room_id), interaction.id, option_id="allow_always")
        assert (await connections.resolve_function(connection, "topic_create"))["effective_state"] == "enabled"
        assert (await connections.resolve_function(connection, "topic_update"))["effective_state"] == "ask"
    assert await claim_action(replace(action, continuation=caught.value.continuation)) == identifier
    await finish_action(identifier)
    assert await claim_action(replace(action, callback_key=str(uuid4()), arguments={"title": "Another synthetic topic"})) is None
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(action)
    async with get_db_session():
        await connections.set_connection_function_state(connection.id, "topic_create", "ask")
    await pending(replace(action, callback_key=str(uuid4())))


@pytest.mark.asyncio
async def test_runtime_approval_cannot_be_made_permanent(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert not await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=True)
        assert row.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_before_question", [False, True])
async def test_permanent_function_choice_rejects_a_changed_remote_configuration(action, changed_before_question):
    from app.connection import Connection
    from app.connection import facade as connections
    from app.tools import ToolModel
    from app.tools.authorization import can_remember_action, tool_authorization_configuration
    from app.tools.tool_service import get_tool_by_id
    async with get_db_session() as db:
        tool = ToolModel(code=f"remote-{uuid4().hex}", label="Synthetic remote service",
            mcp_config={"type": "http", "url": "https://original.example.test/mcp"})
        db.add(tool)
        await db.flush()
        connection = Connection(agent_id=action.agent_id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        tool_id, connection_id = tool.id, connection.id
        await connections.set_connection_function_state(connection_id, "publish", "ask")
    async with get_db_session() as db:
        configuration = {"tool": tool_authorization_configuration(await get_tool_by_id(tool_id)), "params": {}}
        if changed_before_question:
            (await db.get(ToolModel, tool_id)).mcp_config = {"type": "http", "url": "https://changed.example.test/mcp"}
    action = replace(action, source="mcp", tool_id=tool_id, connection_id=connection_id,
                     name="publish", configuration=configuration)
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await can_remember_action(row) is (not changed_before_question)
        if not changed_before_question:
            (await db.get(ToolModel, tool_id)).mcp_config = {"type": "http", "url": "https://changed.example.test/mcp"}
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert not await can_remember_action(row)
        assert not await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=True)
        assert (await connections.resolve_function(await connections.get_connection(connection_id), "publish"))["effective_state"] == "ask"
        assert row.status == "pending"


@pytest.mark.asyncio
async def test_pending_is_durable_and_approval_dispatches_exactly_once(action):
    identifiers = await asyncio.gather(pending(action), pending(action))
    assert identifiers[0] == identifiers[1]
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifiers[0])
        assert row.status == "pending"
        assert "echo synthetic" not in row.encrypted_arguments
        assert not await answer_action(row.id, user_id=row.approver_user_id + 100000, approved=True)
        assert await answer_action(row.id, user_id=row.approver_user_id, approved=True)
    dispatched = []

    async def dispatch():
        try:
            receipt = await claim_action(action)
        except AuthorizationClosed:
            return
        dispatched.append("effect")
        await finish_action(receipt, receipt={"delivered": True})

    await asyncio.gather(dispatch(), dispatch())
    assert dispatched == ["effect"]
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(action)


@pytest.mark.asyncio
async def test_approval_cannot_execute_changed_arguments(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(replace(action, arguments={"command": "different"}))
    with pytest.raises(AuthorizationClosed, match="invalidated"):
        await claim_action(action)


@pytest.mark.asyncio
async def test_yolo_does_not_answer_existing_human_question_and_new_effects_are_audited(action):
    identifier = await pending(action)
    async with get_db_session():
        await set_yolo(action.agent_id, enabled=True, acknowledged=True)
    assert await pending(action) == identifier
    receipt = await claim_action(replace(action, callback_key=str(uuid4())))
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, receipt)
        assert row.status == "executing"
        assert row.decision_source == "agent_yolo"
        assert row.policy_version == 1
    await finish_action(receipt, outcome="outcome_unknown")
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, receipt)
        assert row.encrypted_arguments is not None


@pytest.mark.asyncio
async def test_refusal_survives_yolo_and_unknown_outcome_never_replays(action):
    identifier = await pending(action)
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=False)
        await set_yolo(action.agent_id, enabled=True, acknowledged=True)
    with pytest.raises(AuthorizationClosed, match="denied"):
        await claim_action(action)
    unknown = replace(action, callback_key=str(uuid4()))
    receipt = await claim_action(unknown)
    await finish_action(receipt, outcome="outcome_unknown")
    with pytest.raises(AuthorizationClosed, match="outcome_unknown"):
        await claim_action(unknown)


@pytest.mark.asyncio
async def test_opaque_continuation_survives_new_callback_but_is_bound_to_identity_and_arguments(action):
    with pytest.raises(AuthorizationRequired) as caught:
        await claim_action(action)
    identifier, continuation = caught.value.request_id, caught.value.continuation
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    from app.tools.contracts import ToolCallRejectedError
    with pytest.raises(ToolCallRejectedError, match="continuation is invalid"):
        await claim_action(replace(action, arguments={"command": "changed"}, continuation=continuation))
    assert await claim_action(replace(action, callback_key=str(uuid4()), continuation=continuation)) == identifier
    await finish_action(identifier)
    with pytest.raises(AuthorizationClosed, match="completed"):
        await claim_action(replace(action, callback_key=str(uuid4()), continuation=continuation))


def test_every_declared_native_function_has_explicit_approval_metadata():
    from app.tools.mcp_loader import load_mcp_tools
    definitions = load_mcp_tools()
    assert len(definitions) > 100
    assert all(definition.approval_reason != "Unclassified native action" for definition in definitions)
    assert {definition.name: definition.approval for definition in definitions}["file_create"] == "ask"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("remember", [False, True])
async def test_file_copy_approval_is_bound_to_the_observed_source_bytes(action, tmp_path, monkeypatch, changed, remember):
    from fastmcp import Client
    from app.file_share import resource_service
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.connection import Connection
    from app.tools import ToolModel, build_agent_galaris_fastmcp
    transport = TemporaryFileTransport(tmp_path / "console")
    source = transport.resolve_path("source.txt")
    source.write_text("approved source")
    async def resolve(_context):
        return transport
    monkeypatch.setattr(resource_service, "_console_transport", resolve)
    async with get_db_session() as db:
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == "file_sharing"))
        db.add(Connection(agent_id=action.agent_id, tool_id=tool.id, active=True))
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(action.agent_id, allowed_tool_names={"file_copy"},
            resources={"console": object()})
    arguments = {"source": "console://source.txt", "destination": "console://destination.txt", "unused": "private"}
    operation = str(uuid4())
    meta = {"galaris.execution/v1": {"operation_id": operation}}
    async with Client(server) as client:
        result = await client.call_tool("file_copy", arguments, meta=meta, raise_on_error=False)
        control = result.meta["galaris.authorization/v1"]
        assert control["disposition"] == "authorization_required"
        identifier = UUID(control["request_id"])
        if changed:
            source.write_text("changed source")
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=remember)
        meta["galaris.authorization/v1"] = {"continuation": control["continuation"]}
        # Approval remains bound to the effective call, not discarded arguments.
        arguments["unused"] = "different-private-value"
        result = await client.call_tool("file_copy", arguments, meta=meta, raise_on_error=False)
        destination = transport.resolve_path("destination.txt")
        assert destination.exists() is (not changed)
        if changed:
            assert result.is_error and result.meta["galaris.authorization/v1"]["status"] == "invalidated"
        else:
            assert not result.is_error and destination.read_text() == "approved source"


@pytest.mark.asyncio
async def test_realtime_native_effect_waits_for_the_same_human_agreement(action):
    import json
    from app.connection import Connection
    from app.tools.models import Tool
    from app.voice.realtime_tools import realtime_tools, execute_realtime_tool
    async with get_db_session() as db:
        tool = await db.scalar(select(Tool).where(Tool.code == "voice"))
        if tool is None:
            tool = Tool(code="voice", label="Synthetic voice")
            db.add(tool)
            await db.flush()
        db.add(Connection(agent_id=action.agent_id, tool_id=tool.id, active=True))
        await db.commit()
    hangup = asyncio.Event()
    tools = realtime_tools(agent_id=action.agent_id, conversation_id="synthetic-room", transport_kind="synthetic",
        language="en", hangup_requested=hangup)
    operation = uuid4()
    first = json.loads(await execute_realtime_tool(tools, name="voice_call_stop", arguments="{}", operation_id=operation))
    assert not hangup.is_set()
    identifier = UUID(first["authorization_required"])
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == "pending" and row.capability_name == "voice_call_stop"
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
    result = json.loads(await execute_realtime_tool(tools, name="voice_call_stop", arguments="{}", operation_id=operation))
    assert result["ok"] is True and hangup.is_set()
    replay = json.loads(await execute_realtime_tool(tools, name="voice_call_stop", arguments="{}", operation_id=operation))
    assert replay["authorization_status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_pydantic_deferred_call_resumes_the_same_operation_without_a_new_model_decision(action, approved):
    from fastmcp import FastMCP
    from pydantic_ai import Agent as PydanticAgent, DeferredToolRequests
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.mcp import MCPToolset
    from fastmcp.tools import ToolResult
    from app.agent import AgentSnapshot
    from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
    from app.harness.mcp_toolset import ExecutionEvidenceClient
    from app.harness.tests.test_checkpoint import _request
    from app.tools.authorization import AUTHORIZATION_META_KEY
    from app.tools.contracts import current_tool_execution
    from app.tools.execution_evidence import ExecutionEvidenceMiddleware

    server = FastMCP("synthetic-deferred-effect")
    server.add_middleware(ExecutionEvidenceMiddleware({"synthetic_write"}))
    effects = []

    @server.tool()
    async def synthetic_write(content: str) -> ToolResult:
        operation = current_tool_execution()
        assert operation is not None
        try:
            permit = await claim_action(replace(action, callback_key=str(operation.operation_id), arguments={"content": content}))
        except AuthorizationRequired as exc:
            return ToolResult(content=str(exc), is_error=True, meta={AUTHORIZATION_META_KEY: {
                "disposition": "authorization_required", "status": "pending", "request_id": str(exc.request_id)}})
        effects.append(content)
        await finish_action(permit, receipt={"written": content})
        return ToolResult(content="written")

    def model(messages, _info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("synthetic_write", {"content": "approved bytes"}, tool_call_id="synthetic-call")])
        return ModelResponse(parts=[TextPart("The action has been resolved")])

    save = AsyncMock()
    request = replace(_request(save_checkpoint=save), agent=AgentSnapshot(
        id=action.agent_id, code="synthetic", first_name="Synthetic", last_name="Agent", driver_code="internal"))
    journal = HarnessRunCheckpoint(request)
    toolset = MCPToolset(ExecutionEvidenceClient(server))
    agent = PydanticAgent(FunctionModel(model), output_type=[str, DeferredToolRequests], retries=0,
        toolsets=wrap_toolsets([toolset], journal))
    result = await agent.run("Write the synthetic content")
    assert isinstance(result.output, DeferredToolRequests)
    assert effects == []
    await journal.interrupted(result.all_messages())
    snapshot = save.await_args.args[0]
    identifier = UUID(str(snapshot.data["effects"][0]["authorization_request_id"]))
    async with get_db_session() as db:
        row = await db.get(ActionAuthorization, identifier)
        assert await answer_action(identifier, user_id=row.approver_user_id, approved=approved)
    resumed = HarnessRunCheckpoint(replace(request, resume_checkpoint=snapshot))
    await resumed.prepare_resume()
    history = resumed.restored_messages()
    deferred = await resumed.deferred_results()
    continued = PydanticAgent(FunctionModel(model), output_type=[str, DeferredToolRequests], retries=0,
        toolsets=wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], resumed))
    final = await continued.run(None, message_history=history, deferred_tool_results=deferred)
    assert final.output == "The action has been resolved"
    assert effects == (["approved bytes"] if approved else [])
    assert len(resumed.effects) == 1


@pytest.mark.asyncio
async def test_native_system_mutation_has_no_effect_until_exact_approval(action, tmp_path, monkeypatch):
    from fastmcp import Client
    from app.connection import facade as connections
    from app.file_share import mcp, resource_service
    from app.file_share.resource_contracts import ResourceContext
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.tools import mandatory_tools, mcp_loader
    from app.tools.contracts import EXECUTION_META_KEY
    from app.tools.authorization import AUTHORIZATION_META_KEY
    from app.tools.models import Tool
    from app.connection.models import Connection
    transport = TemporaryFileTransport(tmp_path / "console")
    monkeypatch.setattr(resource_service, "_console_transport", AsyncMock(return_value=transport))
    monkeypatch.setattr(mcp, "_resource_context", AsyncMock(return_value=ResourceContext(
        agent_id=action.agent_id, runtime="internal", console_resource=transport)))
    async with get_db_session() as db:
        await mandatory_tools.sync_integrated_tool_connections(action.agent_id)
        connection = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == action.agent_id, Tool.code == "file_sharing"))
        connection_id = connection.id
        await connections.set_connection_function_state(connection_id, "file_create", "ask")
        server = await mcp_loader.build_agent_galaris_fastmcp(action.agent_id, runtime="internal")
    operation = str(uuid4())
    arguments = {"path": "console://approved.txt", "content": "synthetic"}
    async with Client(server) as client:
        result = await client.call_tool("file_create", arguments, raise_on_error=False,
            meta={EXECUTION_META_KEY: {"operation_id": operation}})
        assert result.is_error
        control = result.meta[AUTHORIZATION_META_KEY]
        identifier = UUID(control["request_id"])
        assert not (transport.root_path() / "approved.txt").exists()
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
        approved = await client.call_tool("file_create", arguments, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert not approved.is_error
        assert (transport.root_path() / "approved.txt").read_text() == "synthetic"
        replay = await client.call_tool("file_create", arguments, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert replay.is_error and replay.meta[AUTHORIZATION_META_KEY]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("remember", [False, True])
async def test_external_proxy_guards_dispatch_and_keeps_capability_kinds_separate(action, tmp_path, monkeypatch, remember):
    from fastmcp import Client, FastMCP
    from app.connection import facade as connections
    from app.connection.models import Connection
    from app.tools import mcp_loader
    from app.tools.models import Tool
    from app.tools.authorization import AUTHORIZATION_META_KEY
    remote = FastMCP("Synthetic external boundary")
    effects = []

    @remote.tool(name="same")
    def mutate(value: str) -> str:
        effects.append(value)
        return value

    @remote.resource("synthetic://same")
    def read_resource() -> str:
        return "resource"

    @remote.prompt(name="same")
    def prompt() -> str:
        return "prompt"

    monkeypatch.setattr(mcp_loader, "_external_transport", lambda *_args: remote)
    async with get_db_session() as db:
        tool = Tool(code=f"external_{uuid4().hex}", label="Synthetic MCP", mcp_config={"type": "http", "url": "https://mcp.example.test/mcp"})
        db.add(tool)
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=action.agent_id, active=True)
        db.add(connection)
        await db.flush()
        connection_id, code = connection.id, tool.code
        await connections.set_connection_function_state(connection_id, "same", "ask")
        await connections.set_connection_function_state(connection_id, "same", "disabled", capability_kind="prompt")
        server = await mcp_loader.build_agent_mcp(action.agent_id, resources={"mcp_principal": "synthetic-caller"})
    async with Client(server) as client:
        assert not await client.list_prompts()
        assert len(await client.list_resources()) == 1
        pending_result = await client.call_tool(f"{code}_same", {"value": "once"}, raise_on_error=False)
        assert pending_result.is_error and effects == []
        control = pending_result.meta[AUTHORIZATION_META_KEY]
        identifier = UUID(control["request_id"])
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True, remember=remember)
        result = await client.call_tool(f"{code}_same", {"value": "once"}, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert not result.is_error and effects == ["once"]
        replay = await client.call_tool(f"{code}_same", {"value": "once"}, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}})
        assert replay.is_error and effects == ["once"]
        if remember:
            subsequent = await client.call_tool(f"{code}_same", {"value": "future"}, raise_on_error=False)
            assert not subsequent.is_error and effects == ["once", "future"]
