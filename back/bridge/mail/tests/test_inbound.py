"""Synthetic receive → common consent → read → canonical Task workflows."""

from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.connection import facade as connections
from app.contact.facade import is_known_mail_contact
from app.memory import create_mail_contact, forget_messenger_contact
from app.task import Task
from app.tools.authorization import answer_action, can_remember_action
from app.tools.authorization_models import ActionAuthorization
from app.tools.models import Tool
from core.database import get_db_session
from bridge.mail import inbound, service
from bridge.mail.contracts import MailMessageDetail, MailMessageRef, MailSearchPage, MailSearchQuery
from bridge.mail.models import MailInboundReceipt
from .test_chat_approvals import _setup_mail_chat
from .test_messenger import _summary


@pytest_asyncio.fixture
async def inbox(committed_database, monkeypatch):
    async with get_db_session() as db:
        config, manager, outsider, _smtp = await _setup_mail_chat(db, monkeypatch)
        connection = await connections.get_connection(config.connection_id)
        mail_tool = await db.scalar(select(Tool).where(Tool.code == "mail"))
        connection.tool_id = mail_tool.id
        await db.commit()
        manager_id, outsider_id = manager.id, outsider.id
    config = config.model_copy(update={"approval_required": False})
    monkeypatch.setattr(inbound, "resolve_connection", AsyncMock(return_value=config))
    monkeypatch.setattr(service, "resolve_mail_connection", AsyncMock(return_value=config))
    read = Mock(side_effect=lambda ref, **_kwargs: MailMessageDetail(
        **_summary(ref.uid).model_dump(), body="Synthetic private body", body_format="plain",
        body_start=0, body_end=22, body_total=22,
    ))
    monkeypatch.setattr(inbound.ImapClient, "get_message", read)
    monkeypatch.setattr(inbound.ImapClient, "get_summary", lambda _self, ref: _summary(ref.uid))
    return config, manager_id, outsider_id, read


@pytest.mark.asyncio
@pytest.mark.parametrize("mailbox", ["INBOX", "inbox", "Sent", "Corbeille", "Archive", "INBOX/Archive"])
async def test_only_inbox_search_results_enter_the_reception_journal(inbox, monkeypatch, mailbox):
    config, _manager, _outsider, read = inbox
    summary = _summary(121).model_copy(update={
        "ref": MailMessageRef(mailbox=mailbox, uid_validity=9, uid=121).encode(),
    })
    monkeypatch.setattr(service.ImapClient, "search", lambda *_args: MailSearchPage(
        mailbox=mailbox, uid_validity=9, messages=[summary],
    ))
    async with get_db_session() as db:
        page = await service.search(config.agent_id, MailSearchQuery(mailbox=mailbox))
        assert page.messages == [summary]
        assert await db.scalar(select(func.count()).select_from(MailInboundReceipt)) == (
            1 if mailbox.upper() == "INBOX" else 0
        )
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        assert await db.scalar(select(func.count()).select_from(ActionAuthorization)) == 0
    read.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mailbox", ["Sent", "Corbeille", "INBOX/Archive"])
@pytest.mark.parametrize("operation", ["receive", "get", "attachment"])
async def test_non_inbox_mail_cannot_be_processed_or_downloaded(inbox, monkeypatch, mailbox, operation):
    config, _manager, _outsider, read = inbox
    summary = _summary(122).model_copy(update={
        "ref": MailMessageRef(mailbox=mailbox, uid_validity=9, uid=122).encode(),
    })
    headers, attachment = Mock(), Mock()
    monkeypatch.setattr(inbound.ImapClient, "get_summary", headers)
    monkeypatch.setattr(inbound.ImapClient, "get_attachment", attachment)
    async with get_db_session() as db:
        with pytest.raises(PermissionError, match="INBOX"):
            if operation == "receive":
                await inbound.receive(config, summary)
            elif operation == "get":
                await service.get_message(config.agent_id, summary.ref)
            else:
                await service.get_attachment(config.agent_id, summary.ref, "1")
        assert await db.scalar(select(func.count()).select_from(MailInboundReceipt)) == 0
        assert await db.scalar(select(func.count()).select_from(ActionAuthorization)) == 0
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
    headers.assert_not_called()
    read.assert_not_called()
    attachment.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mailbox", ["Sent", "Corbeille"])
@pytest.mark.parametrize("cached_body", [False, True])
async def test_legacy_non_inbox_receipts_cannot_resume_processing(inbox, mailbox, cached_body):
    config, _manager, _outsider, read = inbox
    summary = _summary(123).model_copy(update={
        "ref": MailMessageRef(mailbox=mailbox, uid_validity=9, uid=123).encode(),
    })
    async with get_db_session() as db:
        await create_mail_contact(owner_agent_id=config.agent_id,
            display_name="Synthetic Sender", email="sender@example.org")
        row = await inbound.record_receipt(config, _summary(123), dispatch=True)
        await inbound.authorize_receipt(row)
        assert row.authorized_at is not None
        # Keep a valid grant while reproducing an old receipt from another folder.
        row.message_ref = summary.ref
        row.summary = summary.model_dump(mode="json")
        if cached_body:
            row.content = {"body": "Synthetic previously read body"}
        await db.commit()
        await inbound.resume_receipts(config.connection_id)
        await db.refresh(row)
        assert row.status == "blocked"
        assert row.read_at is None and row.admitted_at is None
        with pytest.raises(PermissionError, match="INBOX"):
            await service.get_message(config.agent_id, summary.ref)
        assert await db.scalar(select(func.count()).select_from(ActionAuthorization)) == 0
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
    read.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["allow", "deny", "always"])
async def test_unknown_sender_is_logged_but_not_read_until_common_consent(inbox, decision):
    config, manager, outsider, read = inbox
    summary = _summary(41)
    async with get_db_session() as db:
        await inbound.receive(config, summary)
        await inbound.receive(config, summary)
        receipt = await db.scalar(select(MailInboundReceipt))
        assert receipt.status == "pending_approval"
        assert receipt.content is None and receipt.read_at is None
        assert await db.scalar(select(func.count()).select_from(MailInboundReceipt)) == 1
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        read.assert_not_called()
        authorization = await db.get(ActionAuthorization, receipt.authorization_id)
        assert authorization.capability_name == "mail_process"
        assert await can_remember_action(authorization)
        assert not await answer_action(authorization.id, user_id=outsider, approved=True)
        assert await answer_action(authorization.id, user_id=manager, approved=decision != "deny", remember=decision == "always")
        receipt_id = receipt.id
    async with get_db_session() as db:
        # The same wake used by the common reconciler; duplicates remain harmless.
        await inbound._wake(config.agent_id, f"mail-inbound:{receipt_id}")
        await inbound.receive(config, summary)
        receipt = await db.get(MailInboundReceipt, receipt_id, populate_existing=True)
        if decision == "deny":
            assert receipt.status == "rejected"
            assert receipt.content is None
            read.assert_not_called()
            assert await db.scalar(select(func.count()).select_from(Task)) == 0
        else:
            assert receipt.status == "admitted", receipt.error
            assert receipt.content["body"] == "Synthetic private body"
            assert receipt.read_at is not None
            assert await db.scalar(select(func.count()).select_from(Task)) == 1
        if decision == "always":
            await inbound.receive(config, _summary(42))
            assert await db.scalar(select(func.count()).select_from(Task)) == 2
            assert await db.scalar(select(func.count()).select_from(ActionAuthorization).where(
                ActionAuthorization.capability_name == "mail_process")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "ask", "enabled", "disabled"])
async def test_contact_default_and_explicit_processing_modes(inbox, mode):
    config, manager, _outsider, read = inbox
    async with get_db_session() as db:
        contact = await create_mail_contact(owner_agent_id=config.agent_id,
            display_name="Synthetic Sender", email="sender@example.org")
        assert await is_known_mail_contact(agent_id=config.agent_id, address="SENDER@example.org")
        assert not await is_known_mail_contact(agent_id=config.agent_id + 1000, address="sender@example.org")
        assert not await is_known_mail_contact(agent_id=config.agent_id, address="other@example.org")
        if mode != "default":
            await connections.set_connection_function_state(config.connection_id, "mail_process", mode)
        await inbound.receive(config, _summary(51))
        row = await db.scalar(select(MailInboundReceipt))
        assert row.status == {"default": "admitted", "enabled": "admitted", "ask": "pending_approval", "disabled": "blocked"}[mode], row.error
        assert read.call_count == (1 if mode in ("default", "enabled") else 0)
        assert row.known_contact is (mode != "disabled")
        page = await inbound.list_receipts(current_user_id=manager, agent_ids=frozenset(),
            agent_id=None, search="", offset=0, limit=500)
        assert page.total == 0
        assert await inbound.get_receipt(row.id, current_user_id=manager, agent_ids=frozenset()) is None
        page = await inbound.list_receipts(current_user_id=manager, agent_ids=frozenset({config.agent_id}),
            agent_id=None, search="sender@", offset=0, limit=500)
        assert page.total == 1 and page.items[0].subject == _summary(51).subject
        # A forgotten contact must not continue to grant trust.
        async def clear(_identifier):
            return {}
        await forget_messenger_contact(contact_item_id=contact.memory_item_id, clear_references=clear)
        await db.commit()
        assert not await is_known_mail_contact(agent_id=config.agent_id, address="sender@example.org")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "attachment", "reply", "forward"])
async def test_alternate_read_paths_cannot_download_unknown_mail_before_consent(inbox, monkeypatch, operation):
    from app.tools.authorization import AuthorizationRequired
    config, _manager, _outsider, read = inbox
    attachment = Mock()
    monkeypatch.setattr(inbound.ImapClient, "get_attachment", attachment)
    async with get_db_session():
        with pytest.raises(AuthorizationRequired):
            if operation == "get":
                await service.get_message(config.agent_id, _summary(61).ref)
            elif operation == "attachment":
                await service.get_attachment(config.agent_id, _summary(61).ref, "1")
            elif operation == "reply":
                await service.reply(config.agent_id, runtime="internal", task_id=None, message_ref=_summary(61).ref,
                    body="Synthetic reply", html_body=None, reply_all=False, additional_to=[], attachment_uris=[], idempotency_key="synthetic-reply")
            else:
                await service.forward(config.agent_id, runtime="internal", task_id=None, message_ref=_summary(61).ref,
                    to=["other@example.org"], cc=[], bcc=[], body="Synthetic forward", html_body=None,
                    include_original=True, include_original_attachments=True, attachment_uris=[], idempotency_key="synthetic-forward")
    read.assert_not_called()
    attachment.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_admission_survives_concurrent_delivery_and_revocation(inbox):
    import asyncio
    from bridge.mail.messenger import MailMessenger
    from app.messenger import dispatch_incoming
    from app.connection.models import ConnectionParam

    config, _manager, _outsider, _read = inbox
    async with get_db_session():
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
    async def deliver():
        async with get_db_session():
            await inbound.receive(config, _summary(71))
    await asyncio.gather(deliver(), deliver())
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 1
        row = await db.scalar(select(MailInboundReceipt))
        connection = await connections.get_connection(config.connection_id)
        message = MailMessenger(config, tool_id=connection.tool_id).message(_summary(71))
        # A different provider identifier cannot reuse the approved mail's room.
        message.id = 'forged-provider-message'
        await dispatch_incoming(message)
        assert await db.scalar(select(func.count()).select_from(Task)) == 1
        await connections.set_connection_function_state(config.connection_id, "mail_process", "disabled")
        with pytest.raises(PermissionError):
            await service.get_message(config.agent_id, row.message_ref)
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
        db.add(ConnectionParam(connection_id=config.connection_id, param_name="imap_host", param_value="changed.example.org"))
        await db.commit()
        with pytest.raises(PermissionError, match="configuration changed"):
            await service.get_message(config.agent_id, row.message_ref)


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_point", ["common_claim", "local_grant"])
async def test_consent_claim_is_recovered_before_dispatch_after_a_crash(inbox, monkeypatch, crash_point):
    config, manager, _outsider, read = inbox
    async with get_db_session() as db:
        row = await inbound.record_receipt(config, _summary(81), dispatch=True)
        await inbound.process_receipt(row.id)
        identifier, receipt_id = row.authorization_id, row.id
        assert await answer_action(identifier, user_id=manager, approved=True)
    # Inject between the common claim and the durable local grant.
    original_claim = inbound.claim_action
    original_finish = inbound.finish_action
    async def claimed_then_crash(action):
        await original_claim(action)
        raise RuntimeError('Synthetic crash after common claim')
    async def crash_after_grant(*_args, **_kwargs):
        raise RuntimeError('Synthetic crash after local grant')
    if crash_point == "common_claim":
        monkeypatch.setattr(inbound, 'claim_action', claimed_then_crash)
    else:
        monkeypatch.setattr(inbound, 'finish_action', crash_after_grant)
    async with get_db_session():
        await inbound.process_receipt(receipt_id)
    read.assert_not_called()
    monkeypatch.setattr(inbound, 'claim_action', original_claim)
    monkeypatch.setattr(inbound, 'finish_action', original_finish)
    async with get_db_session() as db:
        await inbound.resume_receipts(config.connection_id)
        row = await db.get(MailInboundReceipt, receipt_id, populate_existing=True)
        assert row.status == 'admitted', row.error
        assert await db.scalar(select(func.count()).select_from(Task)) == 1
        decision = await db.get(ActionAuthorization, identifier)
        assert decision.status == 'completed'


@pytest.mark.asyncio
async def test_generic_file_read_keeps_its_waiting_context_for_consent(inbox):
    from uuid import uuid4
    from app.tools.contracts import ToolExecutionContext, tool_execution
    from app.tools.authorization import AuthorizationRequired

    config, _manager, _outsider, read = inbox
    context = f"task:{uuid4()}"
    async with get_db_session() as db:
        with tool_execution(ToolExecutionContext(operation_id=uuid4(), tool_name="file_read", authorization_context=context)):
            with pytest.raises(AuthorizationRequired):
                await service.get_attachment(config.agent_id, _summary(91).ref, "1")
        row = await db.scalar(select(MailInboundReceipt))
        assert row.waiting_contexts == [context]
    read.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_managed_mail_read_resumes_only_its_registered_waiter(inbox, monkeypatch, approved):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from uuid import UUID, uuid4
    from fastmcp import Client
    from httpx import ASGITransport, AsyncClient
    from app.agent import AgentSnapshot, ResolvedExecutionTarget
    from app.agent.tests.test_driver_testkit import _request
    from app.harnesses.models import AgentHarness
    from app.mcp.service import ensure_system_token
    from app.task import task_service
    from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter
    from app.task.models import TaskAttempt, TaskStatus
    from app.tools import build_agent_galaris_fastmcp
    from app.tools.authorization_models import RuntimeRunGrant
    from app.tools.runtime_authorization import issue_runtime_run_grant, renew_runtime_run_grant, runtime_authorizations_ready
    from core.params import Params, params_service
    from main import app

    config, manager, _outsider, read = inbox
    await params_service.get_all()
    monkeypatch.setitem(params_service._params_cache, Params.HARNESS_DEEPSEEK_ENABLED, "true")
    async with get_db_session() as db:
        assignment = AgentHarness(agent_id=config.agent_id, provider_code="deepseek_harness",
            lifecycle_status="ready", runtime_base_url="http://synthetic.example.test/v1", runtime_model="synthetic")
        task = Task(agent_id=config.agent_id, label="Synthetic mail read", objective="<p>Read one email.</p>",
            status=TaskStatus.EXEC, lease_token=uuid4(),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add_all([assignment, task])
        await db.flush()
        attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH", status="CLAIMED",
            worker_id="synthetic", lease_token=task.lease_token)
        db.add(attempt)
        await db.flush()
        task_id, attempt_id, assignment_id = task.id, attempt.id, assignment.id
        bearer = await ensure_system_token(config.agent_id)
    request = replace(_request(), task_id=task_id, attempt_id=attempt_id, driver_code="openai_messages",
        agent=AgentSnapshot(id=config.agent_id, code="synthetic", first_name="Synthetic", last_name="Reader", driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code="deepseek_harness", target_ref=f"harness:{assignment_id}", revision="1"))
    credential = await issue_runtime_run_grant(request)
    async with get_db_session() as db:
        grant = await db.scalar(select(RuntimeRunGrant).where(RuntimeRunGrant.run_key == request.run_id))
        grant_id = grant.id
        server = await build_agent_galaris_fastmcp(config.agent_id, runtime="openai_messages", task_id=task_id,
            resources={"runtime_grant_id": str(grant_id), "authorization_context": f"task:{task_id}"},
            allowed_tool_names={"mail_get"})
    arguments = {"message_ref": _summary(111).ref, "body_limit": 1200}
    async with Client(server) as mcp:
        pending = await mcp.call_tool("mail_get", arguments, raise_on_error=False)
        assert pending.is_error
        identifier = UUID(pending.meta["galaris.authorization/v1"]["request_id"])
        read.assert_not_called()
        headers = {"Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": credential}
        endpoint = f"/api/tools/runtime-authorizations/{identifier}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
            response = await http.get(endpoint, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "pending"
            # Knowing a UUID does not register a waiter or authorize a receipt write.
            assert (await http.get(f"/api/tools/runtime-authorizations/{uuid4()}", headers=headers)).status_code == 404
            assert (await http.post("/api/tools/runtime-authorizations/receipt", headers=headers,
                json={"request_id": str(identifier), "outcome": "completed", "receipt": {}})).status_code == 404
            async with get_db_session() as db:
                receipt = await db.scalar(select(MailInboundReceipt).where(MailInboundReceipt.authorization_id == identifier))
                receipt_id = receipt.id
                receipt.waiting_contexts = []
            assert (await http.get(endpoint, headers=headers)).status_code == 404
            async with get_db_session() as db:
                receipt = await db.get(MailInboundReceipt, receipt_id)
                receipt.waiting_contexts = [f"task:{task_id}"]
                assert await answer_action(identifier, user_id=manager, approved=approved)
            assert (await http.get(endpoint, headers=headers)).json()["status"] == "pending"
            async with get_db_session() as db:
                task = await db.get(Task, task_id)
                SqlAlchemyAgentTaskAdapter().suspend(task, task_service.PAUSE_APPROVAL)
                task.data = {**(task.data or {}), "authorization_requests": [str(identifier)]}
                task.lease_token = task.lease_expires_at = None
                (await db.get(TaskAttempt, attempt_id)).status = "WAITING_APPROVAL"
            async with get_db_session():
                assert await inbound._wake(config.agent_id, f"mail-inbound:{receipt_id}")
            # The domain can finish its approval before the Task acquires a new lease.
            assert (await http.get(endpoint, headers=headers)).json()["status"] == "pending"
            assert not await runtime_authorizations_ready(credential, agent_id=config.agent_id, identifiers=[identifier])
            async with get_db_session() as db:
                task = await db.get(Task, task_id)
                task.status = TaskStatus.EXEC
                task.lease_token = uuid4()
                task.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
                resumed = TaskAttempt(task_id=task_id, attempt_number=2, phase="DISPATCH", status="CLAIMED",
                    worker_id="synthetic-resumed", lease_token=task.lease_token)
                db.add(resumed)
                await db.flush()
                resumed_id = resumed.id
            assert (await http.get(endpoint, headers=headers)).json()["status"] == "pending"
            await renew_runtime_run_grant(credential, replace(request, run_id=uuid4(), attempt_id=resumed_id))
            assert await runtime_authorizations_ready(credential, agent_id=config.agent_id, identifiers=[identifier])
            assert (await http.get(endpoint, headers=headers)).json()["status"] == ("completed" if approved else "denied")
        result = await mcp.call_tool("mail_get", arguments, raise_on_error=False)
        assert result.is_error is not approved
        assert read.call_count == int(approved)


@pytest.mark.asyncio
async def test_reception_http_requires_privilege_and_hides_other_agents(inbox, client):
    from core.authorize import Assignment, Role
    from core.user import UserModel
    from core.user.auth_service import create_access_token

    config, manager, outsider, read = inbox
    async with get_db_session() as db:
        await inbound.receive(config, _summary(101))
        row = await db.scalar(select(MailInboundReceipt))
        detail_url = f"/api/mail/inbound/{row.id}"
        role = await db.scalar(select(Role).where(Role.code == "mail-reviewer-test"))
        headers = {}
        for identifier in (manager, outsider):
            user = await db.get(UserModel, identifier)
            headers[identifier] = {"Authorization": "Bearer " + create_access_token({
                "sub": user.email, "user_id": user.id, "role_id": role.id,
            })}
        role_id = role.id
    for url in ("/api/mail/inbound", detail_url):
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=headers[outsider])).status_code == 403
    response = await client.get("/api/mail/inbound?limit=500", headers=headers[manager])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["sender_address"] == _summary(101).from_address
    assert "content" not in item
    response = await client.get(detail_url, headers=headers[manager])
    assert response.status_code == 200, response.text
    assert response.json()["content"] is None
    # Read access to the journal still restricts the caller to managed agents.
    async with get_db_session() as db:
        db.add(Assignment(user_id=outsider, role_id=role_id))
        await db.commit()
    response = await client.get("/api/mail/inbound", headers=headers[outsider])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert (await client.get(detail_url, headers=headers[outsider])).status_code == 404
    assert (await client.get(f"/api/mail/inbound?agent_id={config.agent_id}", headers=headers[outsider])).status_code == 404
    read.assert_not_called()
