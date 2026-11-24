from tests.protocol_tools import protocol_tool
"""Synthetic receive → common consent → read → canonical Task workflows."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from pypdf import PdfWriter
from sqlalchemy import func, select

from app.connection import facade as connections
from app.contact.facade import is_known_mail_contact
from app.memory import create_mail_contact, forget_messenger_contact
from app.task import Task
from app.services.authorization import AuthorizationRequired, answer_action, can_remember_action
from app.services.authorization_models import ActionAuthorization
from app.services.models import Service
from core.database import get_db_session
from bridge.mail import inbound, service
from bridge.mail.contracts import MailMessageDetail, MailMessageRef, MailSearchPage, MailSearchQuery, StaleMailMessageReference
from bridge.mail.models import MailInboundReceipt
from .test_chat_approvals import _setup_mail_chat
from .test_messenger import _summary


@pytest_asyncio.fixture
async def inbox(committed_database, monkeypatch):
    async with get_db_session() as db:
        config, manager, outsider, _smtp = await _setup_mail_chat(db, monkeypatch)
        connection = await connections.get_connection(config.connection_id)
        mail_tool = await protocol_tool(db, "mail")
        connection.service_id = mail_tool.id
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
@pytest.mark.parametrize("cached_body", [False, True])
async def test_excluding_inbox_revokes_historical_processing_and_attachment_access(inbox, monkeypatch, cached_body):
    config, _manager, _outsider, read = inbox
    async with get_db_session() as db:
        await create_mail_contact(owner_agent_id=config.agent_id,
            display_name="Synthetic Sender", email="sender@example.org")
        row = await inbound.record_receipt(config, _summary(124), dispatch=True)
        await inbound.authorize_receipt(row)
        assert row.authorized_at is not None
        if cached_body:
            row.content = {"body": "Synthetic cached content"}
            await db.commit()
        restricted = config.model_copy(update={"allowed_mailboxes": ("Projects",)})
        monkeypatch.setattr(inbound, "resolve_connection", AsyncMock(return_value=restricted))
        monkeypatch.setattr(service, "resolve_mail_connection", AsyncMock(return_value=restricted))
        with pytest.raises(PermissionError, match="not allowed"):
            await service.get_attachment(config.agent_id, row.message_ref, "part-1")
        await inbound.process_receipt(row.id)
        await db.refresh(row)
        assert row.status == "blocked"
        assert row.admitted_at is None
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
    read.assert_not_called()


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
@pytest.mark.parametrize("operation", ["receive", "get", "attachment", "mime-export"])
async def test_non_inbox_mail_cannot_be_processed_or_downloaded(inbox, monkeypatch, mailbox, operation):
    config, _manager, _outsider, read = inbox
    from bridge.mail import browser_service
    monkeypatch.setattr(browser_service, "resolve_mail_connection", AsyncMock(return_value=config))
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
            elif operation == "mime-export":
                await browser_service.read_raw_message(config.agent_id, summary.ref, browser=False, max_bytes=1_000_000)
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
@pytest.mark.parametrize("decision", ["allow", "deny", "always", "never"])
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
        assert await answer_action(authorization.id, user_id=manager,
            approved=decision in {"allow", "always"}, remember=decision in {"always", "never"})
        receipt_id = receipt.id
    async with get_db_session() as db:
        # The same wake used by the common reconciler; duplicates remain harmless.
        await inbound._wake(config.agent_id, f"mail-inbound:{receipt_id}")
        await inbound.receive(config, summary)
        receipt = await db.get(MailInboundReceipt, receipt_id, populate_existing=True)
        if decision in {"deny", "never"}:
            # A permanent denial uses the existing Blocked connection policy.
            assert receipt.status == ("blocked" if decision == "never" else "rejected")
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
        if decision == "never":
            await inbound.receive(config, _summary(42))
            following = await db.scalar(select(MailInboundReceipt).where(MailInboundReceipt.id != receipt_id))
            assert following.status == "blocked" and following.authorization_id is None
            read.assert_not_called()
            assert await db.scalar(select(func.count()).select_from(Task)) == 0
            assert await db.scalar(select(func.count()).select_from(ActionAuthorization).where(
                ActionAuthorization.capability_name == "mail_process")) == 1


@pytest.mark.asyncio
async def test_authorized_mail_and_attachments_enter_private_dream_index(inbox, monkeypatch, tmp_path):
    from app.dream import interface
    from app.dream.mechanisms import file_catalogue, resource_index
    from app.dream.service import mark_success
    from app.file_share import FileCatalogueEnrichmentPort, ResourceContext, materialize_resource
    from app.file_share import resource_index as shared_index
    from app.file_share.models import FileCatalogEntry
    from app.file_share.resource_index_query import search_resource_index
    from app.memory import service as memory
    from app.memory import local_source_date
    from app.memory.schemas import MemorySearchRequest
    from core.params import runtime_settings
    from core.user import get_user_record, user_identity_context
    from bridge.mail import search_index
    from bridge.mail.contracts import MailAttachment

    config, manager, outsider, read = inbox
    summary = _summary(141)
    body = "Synthetic billing record FCT-485 with the keyword amberquartzaudit. Payment due on 9 October."
    pdf_buffer = BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=200, height=100)
    pdf.write(pdf_buffer)
    attachment_bytes = pdf_buffer.getvalue()
    read.side_effect = None
    read.return_value = MailMessageDetail(
        **summary.model_dump(), body=body, body_format="plain", body_start=0,
        body_end=len(body), body_total=len(body), attachments=[MailAttachment(
            part_id="part-2", filename="synthetic-invoice.pdf", media_type="application/pdf", size=len(attachment_bytes),
            uri=f"mail://attachment/{summary.ref}/part-2/synthetic-invoice.pdf",
        )],
    )
    monkeypatch.setattr(search_index, "resolve_connection", AsyncMock(return_value=config))
    monkeypatch.setattr(interface, "_file_catalogue", FileCatalogueEnrichmentPort())
    for kind in ("TEXT", "DOCUMENT", "IMAGE", "VIDEO"):
        monkeypatch.setattr(runtime_settings, f"DREAM_ATTACHMENT_{kind}_ENABLED", False)
    analyze = AsyncMock()
    monkeypatch.setattr(file_catalogue, "analyze_attachment", analyze)

    async with get_db_session() as db:
        await inbound.receive(config, summary)
        receipt = (await db.scalars(select(MailInboundReceipt))).one()
        assert await db.scalar(select(func.count()).select_from(FileCatalogEntry)) == 0
        read.assert_not_called()
        assert await answer_action(receipt.authorization_id, user_id=manager, approved=True)
        await inbound._wake(config.agent_id, f"mail-inbound:{receipt.id}")
        await inbound.receive(config, summary)
        entries = list(await db.scalars(select(FileCatalogEntry).order_by(FileCatalogEntry.uri)))
        assert len(entries) == 2
        assert all(f"/account/{config.connection_id}/" in entry.uri or
                   f"://account/{config.connection_id}/" in entry.uri for entry in entries)
        assert entries[1].descriptor["name"] == "synthetic-invoice.pdf"
        assert entries[1].descriptor["media_type"] == "application/pdf"
        body_uri, attachment_uri = (entry.uri for entry in entries)
        read.assert_called_once()

    # Let the real Dream mechanism hash and index the body from its authorized URI.
    mechanism = file_catalogue.file_catalogue_mechanism
    # Attachment bytes are fetched separately by the file pipeline.
    import bridge.mail.file_transport as transport
    from bridge.mail.contracts import OutgoingAttachment

    fetch_part = AsyncMock(return_value=OutgoingAttachment(
        filename="synthetic-invoice.pdf", content=attachment_bytes, media_type="application/pdf",
    ))
    monkeypatch.setattr(transport, "fetch_attachment", fetch_part)
    for _ in range(3):
        claim = await mechanism.claim_one()
        assert claim is not None
        prepared = await mechanism.prepare(claim)
        assert body not in str(prepared.payload)
        result = await mechanism.apply(claim, prepared.payload)
        assert result == 1
        await mark_success(claim, result_count=result)
    analyze.assert_not_awaited()
    fetch_part.assert_awaited_once()

    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_TEXT_ENABLED", True)
    analyze.return_value = "Synthetic attachment reference violetquartzaudit"
    attachment_claim = await mechanism.claim_one()
    assert attachment_claim is not None and attachment_claim.prepared_payload["uri"] == attachment_uri
    prepared = await mechanism.prepare(attachment_claim)
    assert await mechanism.apply(attachment_claim, prepared.payload) == 1
    await mark_success(attachment_claim, result_count=1)
    analyze.assert_awaited_once()

    from app.connection import Connection

    monkeypatch.setattr(interface, "_file_catalogue", FileCatalogueEnrichmentPort(shared_index=True))
    monkeypatch.setattr(shared_index, "_embedding_model", AsyncMock(return_value=None))
    index_mechanism = resource_index.resource_index_mechanism
    for _ in range(2):
        index_claim = await index_mechanism.claim_one()
        assert index_claim is not None
        prepared = await index_mechanism.prepare(index_claim)
        assert body not in str(prepared.payload)
        assert await index_mechanism.apply(index_claim, prepared.payload) == 1
        await mark_success(index_claim, result_count=1)

    async with get_db_session() as db:
        request = MemorySearchRequest(agent_id=config.agent_id, query="amberquartzaudit")
        ctx = ResourceContext(config.agent_id, "internal")
        indexed = await search_resource_index(ctx, "amberquartzaudit", mode="text", uri=body_uri)
        assert indexed is not None and indexed.hits[0].passages[0]["section"] == "message"
        question = "Quelle est l’échéance de la facture FCT-485 ?"
        answer = await search_resource_index(ctx, question, mode="text", uri=body_uri)
        assert answer is not None and "9 October" in answer.hits[0].excerpt
        sent_date = local_source_date(summary.date) if summary.date else None
        assert sent_date is not None
        dated_query = f"amberquartzaudit en {sent_date.year}"
        dated = await search_resource_index(ctx, dated_query, mode="text", uri=body_uri)
        assert dated is not None and dated.hits[0].resource.metadata["chronology"]["source_date"] == sent_date.isoformat()
        assert dated.hits[0].resource.metadata["chronology"]["source_date_origin"] == "mail_date"
        assert (await memory.search_items(request)).hits
        assert (await memory.search_items(request.model_copy(update={"query": "violetquartzaudit"}))).hits
        reader = await get_user_record(outsider)
        assert reader is not None
        with user_identity_context(reader):
            hidden = await memory.search_items(request)
            assert not hidden.hits and hidden.total == 0
            assert await search_resource_index(ctx, "amberquartzaudit", mode="text", uri=body_uri) is None
            assert await search_resource_index(ctx, question, mode="text") is None
            assert await search_resource_index(ctx, dated_query, mode="text") is None
        connection = await connections.get_connection(config.connection_id)
        other = Connection(agent_id=config.agent_id, service_id=connection.service_id, singleton_key=None)
        db.add(other)
        await db.flush()
        await inbound.record_receipt(config.model_copy(update={"connection_id": other.id}), summary)
        wrong_account = body_uri.replace(f"account/{config.connection_id}/", f"account/{other.id}/")
        with pytest.raises(PermissionError):
            await materialize_resource(ctx, wrong_account, tmp_path / "other", max_bytes=1024)
        await connections.set_connection_function_state(config.connection_id, "mail_process", "disabled")
        hidden = await memory.search_items(request)
        assert not hidden.hits and hidden.total == 0
        assert await search_resource_index(ctx, "amberquartzaudit", mode="text", uri=body_uri) is None
        assert await search_resource_index(ctx, question, mode="text") is None
        assert not (await memory.search_items(request.model_copy(update={"query": "violetquartzaudit"}))).hits
        with pytest.raises(PermissionError):
            await materialize_resource(ctx, body_uri, tmp_path / "body", max_bytes=1024)


@pytest.mark.asyncio
async def test_admitted_mail_can_be_read_after_fresh_consent_for_changed_configuration(inbox, monkeypatch):
    config, manager, outsider, read = inbox
    summary = _summary(43)
    async with get_db_session() as db:
        await connections.set_connection_function_state(config.connection_id, "mail_process", "ask")
        await inbound.receive(config, summary)
        receipt = (await db.scalars(select(MailInboundReceipt))).one()
        original_request = receipt.authorization_id
        assert original_request is not None
        assert await answer_action(original_request, user_id=manager, approved=True)
        await inbound._wake(config.agent_id, f"mail-inbound:{receipt.id}")
        await db.refresh(receipt)
        assert receipt.status == "admitted"
        original_admission = receipt.admitted_at
        task = (await db.scalars(select(Task))).one()
        read.reset_mock()

        original_params = connections.get_params_as_dict
        changed = True

        async def effective_params(*args, **kwargs):
            connection, params = await original_params(*args, **kwargs)
            if changed:
                params = {**params, "operation_timeout_s": "45"}
            return connection, params

        monkeypatch.setattr(connections, "get_params_as_dict", effective_params)

        async def request_read_approval():
            async with get_db_session():
                with pytest.raises(AuthorizationRequired) as required:
                    await service.get_message(config.agent_id, summary.ref, parent_context=f"task:{task.id}")
                return required.value.request_id

        for use_changed_config in (True, False):
            changed = use_changed_config
            request_id, repeated_id = await asyncio.gather(request_read_approval(), request_read_approval())
            assert request_id != original_request
            assert repeated_id == request_id
            assert not await answer_action(request_id, user_id=outsider, approved=True)
            assert await answer_action(request_id, user_id=manager, approved=True)
            read.assert_not_called()
            detail = await service.get_message(config.agent_id, summary.ref, parent_context=f"task:{task.id}")
            assert detail.body == "Synthetic private body"
            read.assert_called_once()
            read.reset_mock()
            await db.refresh(receipt)
            assert receipt.status == "admitted" and receipt.admitted_at == original_admission
            assert await db.scalar(select(func.count()).select_from(Task)) == 1

        await connections.set_connection_function_state(config.connection_id, "mail_process", "disabled")
        with pytest.raises(PermissionError, match="blocked"):
            await service.get_message(config.agent_id, summary.ref)
        read.assert_not_called()


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
@pytest.mark.parametrize("operation", ["get", "attachment", "reply", "forward", "mime-export"])
async def test_alternate_read_paths_cannot_download_unknown_mail_before_consent(inbox, monkeypatch, operation):
    from app.services.authorization import AuthorizationRequired
    config, _manager, _outsider, read = inbox
    from bridge.mail import browser_service
    monkeypatch.setattr(browser_service, "resolve_mail_connection", AsyncMock(return_value=config))
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
            elif operation == "mime-export":
                await browser_service.read_raw_message(config.agent_id, _summary(61).ref, browser=False, max_bytes=1_000_000)
            else:
                await service.forward(config.agent_id, runtime="internal", task_id=None, message_ref=_summary(61).ref,
                    to=["other@example.org"], cc=[], bcc=[], body="Synthetic forward", html_body=None,
                    include_original=True, include_original_attachments=True, attachment_uris=[], idempotency_key="synthetic-forward")
    read.assert_not_called()
    attachment.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_admission_survives_concurrent_delivery_and_revocation(inbox, monkeypatch):
    from bridge.mail.messenger import MailMessenger
    from app.messenger import dispatch_incoming
    from app.messenger.service import MissingInboundTaskError
    from app.connection.models import ConnectionParam

    config, _manager, _outsider, read = inbox
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
        message = MailMessenger(config, service_id=connection.service_id).message(_summary(71))
        # A different provider identifier cannot reuse the approved mail's room.
        message.id = 'forged-provider-message'
        with pytest.raises(MissingInboundTaskError):
            await dispatch_incoming(message)
        assert await db.scalar(select(func.count()).select_from(Task)) == 1
        await connections.set_connection_function_state(config.connection_id, "mail_process", "disabled")
        with pytest.raises(PermissionError):
            await service.get_message(config.agent_id, row.message_ref)
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
        db.add(ConnectionParam(connection_id=config.connection_id, param_name="imap_host", param_value="changed.example.org"))
        await db.commit()
        read.reset_mock()
        with monkeypatch.context() as patches:
            different_mail = _summary(71).model_copy(update={"from_address": "other@example.org"})
            patches.setattr(inbound.ImapClient, "get_summary", Mock(return_value=different_mail))
            with pytest.raises(StaleMailMessageReference, match="original receipt"):
                await service.get_message(config.agent_id, row.message_ref)
        read.assert_not_called()
        detail = await service.get_message(config.agent_id, row.message_ref)
        assert detail.body == "Synthetic private body"
        assert await db.scalar(select(func.count()).select_from(Task)) == 1


@pytest.mark.asyncio
async def test_authorized_mail_admits_one_task_even_if_prefetch_fails(inbox):
    config, _manager, _outsider, read = inbox
    read.side_effect = TimeoutError("Synthetic IMAP timeout")
    summary = _summary(73)
    async with get_db_session() as db:
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
        await inbound.receive(config, summary)
        await inbound.receive(config, summary)
        task = (await db.scalars(select(Task))).one()
        receipt = await db.scalar(select(MailInboundReceipt))
        assert receipt.status == "admitted" and receipt.read_at is None
        assert summary.ref in task.objective
    read.assert_called_once()


@pytest.mark.asyncio
async def test_receipt_recovers_an_admission_without_a_task(inbox, monkeypatch):
    from app.messenger import Message, facade

    config, manager, _outsider, read = inbox
    summary = _summary(72)
    original_enabled = facade.is_kind_enabled
    async with get_db_session() as db:
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
        monkeypatch.setattr(facade, "is_kind_enabled", lambda kind: kind != "mail" and original_enabled(kind))
        await inbound.receive(config, summary)
        receipt = await db.scalar(select(MailInboundReceipt))
        assert receipt.status == "error"
        assert receipt.admitted_at is None
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        receipt_id = receipt.id
        # Simulate a receipt incorrectly marked admitted by an earlier version.
        receipt.status, receipt.admitted_at = "admitted", receipt.read_at
        message = (await db.scalars(select(Message).where(
            Message.connection_id == config.connection_id, Message.room_id == summary.ref,
        ))).one()
        assert message.status == "failed"
        message.status = "admitted"
        await db.commit()
    monkeypatch.setattr(facade, "is_kind_enabled", original_enabled)
    async with get_db_session() as db:
        await inbound.resume_receipts(config.connection_id, repair_admissions=True)
        await inbound.resume_receipts(config.connection_id)
        task = (await db.scalars(select(Task))).one()
        receipt = await inbound.get_receipt(receipt_id, current_user_id=manager,
            agent_ids=frozenset({config.agent_id}), include_task=True)
        assert receipt is not None and receipt.status == "admitted"
        assert receipt.task_uri == f"galaris://task/{task.id}"
        assert task.contact_memory_item_id is not None
        assert f"connection_id={config.connection_id}" in task.objective
        assert summary.ref in task.objective
        page = await inbound.list_receipts(current_user_id=manager, agent_ids=frozenset({config.agent_id}),
            agent_id=None, search="", offset=0, limit=50, include_task=True)
        assert [item.task_uri for item in page.items] == [receipt.task_uri]
        task.soft_delete()
        await db.commit()
        await inbound.resume_receipts(config.connection_id, repair_admissions=True)
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        page = await inbound.list_receipts(current_user_id=manager, agent_ids=frozenset({config.agent_id}),
            agent_id=None, search="", offset=0, limit=50, include_task=True)
        assert [item.task_uri for item in page.items] == [None]
    read.assert_called_once()


@pytest.mark.asyncio
async def test_inbound_task_defaults_to_its_mail_account_with_multiple_connections(inbox, monkeypatch):
    from app.connection import Connection
    from app.services import build_agent_galaris_fastmcp, current_protocol_connection
    from app.services import mcp_loader
    from fastmcp import Client

    config, _manager, _outsider, _read = inbox
    summary = _summary(74)
    enabled_codes = mcp_loader.get_enabled_integrated_service_codes

    async def enabled_with_messenger(agent_id):
        return (await enabled_codes(agent_id)) | {"messenger"}

    monkeypatch.setattr(mcp_loader, "get_enabled_integrated_service_codes", enabled_with_messenger)
    allowed_names = {"mail_get", "messenger_room_send_message"}
    async with get_db_session() as db:
        connection = await connections.get_connection(config.connection_id)
        db.add(Connection(agent_id=config.agent_id, service_id=connection.service_id, active=True,
            singleton_key=None))
        await db.commit()
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
        await inbound.receive(config, summary)
        task = (await db.scalars(select(Task))).one()
        server = await build_agent_galaris_fastmcp(config.agent_id, task_id=task.id, allowed_tool_names=allowed_names)
        generic_tools = await mcp_loader.list_enabled_native_mcp_definitions(config.agent_id,
            runtime="internal", allowed_tool_names=allowed_names)
        assert {tool.name for tool in generic_tools} == allowed_names

    async def resolve(agent_id):
        assert current_protocol_connection("mail", agent_id) == config.connection_id
        return config

    monkeypatch.setattr(service, "resolve_mail_connection", resolve)
    async with Client(server) as client:
        assert {tool.name for tool in await client.list_tools()} == {"mail_get"}
        unavailable = await client.call_tool("mail_get", {"message_ref": summary.ref, "connection_id": 9999999},
            raise_on_error=False)
        assert unavailable.is_error
        assert "omit connection_id" in str(unavailable.content)
        with monkeypatch.context() as patches:
            patches.setattr(inbound.ImapClient, "get_summary", Mock(side_effect=StaleMailMessageReference("UIDVALIDITY changed")))
            stale = await client.call_tool("mail_get", {"message_ref": _summary(75).ref}, raise_on_error=False)
        assert stale.is_error
        assert "UIDVALIDITY" in str(stale.content) and "mail_search" in str(stale.content)
        result = await client.call_tool("mail_get", {"message_ref": summary.ref}, raise_on_error=False)
        assert not result.is_error, result
        assert "Synthetic private body" in str(result.content)


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
    from app.services.contracts import ToolExecutionContext, tool_execution
    from app.services.authorization import AuthorizationRequired

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
async def test_mail_search_schema_rejects_unsupported_filter_before_imap(inbox, monkeypatch):
    from fastmcp import Client
    from app.services import build_agent_galaris_fastmcp
    from bridge.mail.contracts import MailSearchPage

    config, _manager, _outsider, _read = inbox
    search = AsyncMock(return_value=MailSearchPage(mailbox="INBOX", uid_validity=1))
    monkeypatch.setattr(service, "search", search)
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(config.agent_id, allowed_tool_names={"mail_search"})
    async with Client(server) as client:
        refused = await client.call_tool("mail_search", {"has_attachments": False}, raise_on_error=False)
        assert refused.is_error
        search.assert_not_called()
        for value in (None, True):
            result = await client.call_tool("mail_search", {"has_attachments": value}, raise_on_error=False)
            assert not result.is_error
            assert search.call_args.args[1].has_attachments is value


@pytest.mark.asyncio
async def test_empty_flag_change_is_rejected_before_requesting_consent(inbox, monkeypatch):
    from fastmcp import Client
    from app.services import build_agent_galaris_fastmcp

    config, _manager, _outsider, _read = inbox
    mutate = AsyncMock()
    monkeypatch.setattr(service, "set_flags", mutate)
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(config.agent_id, allowed_tool_names={"mail_set_flags"})
    async with Client(server) as client:
        args = {"message_ref": _summary(112).ref}
        refused = await client.call_tool("mail_set_flags", args, raise_on_error=False)
        assert refused.is_error
        assert not (refused.meta or {}).get("galaris.authorization/v1")
        assert "seen or flagged" in str(refused.content)
        async with get_db_session() as db:
            assert await db.scalar(select(func.count()).select_from(ActionAuthorization)) == 0
        corrected = await client.call_tool("mail_set_flags", {**args, "seen": False}, raise_on_error=False)
        assert corrected.meta["galaris.authorization/v1"]["disposition"] == "authorization_required"
        mutate.assert_not_called()


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
    from app.services import build_agent_galaris_fastmcp
    from app.services.authorization_models import RuntimeRunGrant
    from app.services.runtime_authorization import issue_runtime_run_grant, renew_runtime_run_grant, runtime_authorizations_ready
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
        endpoint = f"/api/services/runtime-authorizations/{identifier}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
            response = await http.get(endpoint, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "pending"
            # Knowing a UUID does not register a waiter or authorize a receipt write.
            assert (await http.get(f"/api/services/runtime-authorizations/{uuid4()}", headers=headers)).status_code == 404
            assert (await http.post("/api/services/runtime-authorizations/receipt", headers=headers,
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
    from core.authorize import Assignment, Privilege, Role, RolePrivilege
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
    async with get_db_session() as db:
        await connections.set_connection_function_state(config.connection_id, "mail_process", "enabled")
        await inbound.receive(config, _summary(102))
        new_receipt = await db.scalar(select(MailInboundReceipt).where(
            MailInboundReceipt.message_ref == _summary(102).ref))
        task = (await db.scalars(select(Task))).one()
        task_uri = f"galaris://task/{task.id}"
        new_detail_url = f"/api/mail/inbound/{new_receipt.id}"
    response = await client.get(new_detail_url, headers=headers[manager])
    assert response.status_code == 200 and response.json()["task_uri"] is None
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "TASK_ACCESS"))
        db.add(RolePrivilege(role_id=role_id, privilege_id=privilege.id))
    response = await client.get(new_detail_url, headers=headers[manager])
    assert response.status_code == 200 and response.json()["task_uri"] == task_uri
    response = await client.get("/api/mail/inbound", headers=headers[manager])
    assert {item["task_uri"] for item in response.json()["items"]} == {task_uri, None}
    assert (await client.get(new_detail_url, headers=headers[outsider])).status_code == 404
