"""Real durable MIME and approvals; only SMTP and IMAP transports are replaced."""

from dataclasses import replace
import asyncio
from threading import Lock
import time
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.connection import facade as connections
from app.tools.authorization import (
    AuthorizationAction, AuthorizationClosed, AuthorizationRequired, answer_action,
    prepared_authorization,
)
from app.tools.authorization_models import ActionAuthorization
from core.database import get_db_session
from bridge.mail import service
from bridge.mail.models import MailOutboundDelivery as MailDelivery
from .test_chat_approvals import _setup_mail_chat
from .test_service import _outgoing


@pytest.mark.asyncio
@pytest.mark.parametrize("archive_failure", ["none", "before_append", "after_append"])
async def test_common_approval_binds_frozen_mime_and_sends_once(committed_database, monkeypatch, archive_failure):
    copies = {}
    first_archive = True
    active_archives = peak_archives = 0
    archive_lock = Lock()

    def archive(_self, raw_message, *, message_id, sent_at):
        nonlocal first_archive, active_archives, peak_archives
        with archive_lock:
            active_archives += 1
            peak_archives = max(peak_archives, active_archives)
            fail = first_archive
            first_archive = False
        try:
            time.sleep(.05)
            assert sent_at is not None
            if fail and archive_failure == "before_append":
                raise OSError("Synthetic IMAP outage before APPEND")
            copies.setdefault(message_id, raw_message)
            if fail and archive_failure == "after_append":
                raise OSError("Synthetic lost APPEND response")
            return "Sent"
        finally:
            with archive_lock:
                active_archives -= 1

    async with get_db_session():
        from core.database import get_db
        config, approver, _, smtp = await _setup_mail_chat(get_db(), monkeypatch)
        monkeypatch.setattr(service.ImapClient, "store_sent_message", archive)
        connection = await connections.get_connection(config.connection_id)
        await connections.set_connection_function_state(connection.id, "mail_send", "ask")
        action = AuthorizationAction(agent_id=config.agent_id, connection_id=connection.id,
            tool_id=connection.tool_id, runtime="internal", context_key="principal:synthetic-mail",
            callback_key=str(uuid4()), name="mail_send", arguments={"subject": "Bonjour"},
            configuration={"account": "synthetic-account"})
        with prepared_authorization(action):
            with pytest.raises(AuthorizationRequired) as caught:
                await service.send_outgoing(config, _outgoing(), idempotency_key="common-review")
        smtp.assert_not_called()
        delivery = await get_db().scalar(select(MailDelivery).where(MailDelivery.idempotency_key == "common-review"))
        original_mime = bytes(delivery.raw_message)
        assert original_mime and delivery.status == "claimed"
        assert await answer_action(caught.value.request_id, user_id=approver.id, approved=True)

    async with get_db_session():
        with prepared_authorization(action):
            receipt = await service.send_outgoing(config, _outgoing(), idempotency_key="common-review")
        assert receipt.status == "sent"
        if archive_failure == "none":
            assert list(copies.values()) == [original_mime]
        else:
            assert "Sent copy" in receipt.detail
        async def replay():
            async with get_db_session():
                with prepared_authorization(action):
                    return await service.send_outgoing(config, _outgoing(), idempotency_key="common-review")

        replays = await asyncio.gather(replay(), replay())
        assert all(item.status == "sent" and "Sent copy verified" in item.detail for item in replays)
        assert peak_archives == 1
        assert smtp.call_count == 1
        assert list(copies.values()) == [original_mime]
        from core.database import get_db
        delivery = await get_db().get(MailDelivery, receipt.delivery_id)
        assert bytes(delivery.raw_message) == original_mime
        row = await get_db().get(ActionAuthorization, caught.value.request_id)
        assert row.status == "completed" and row.decision_source == "human"


@pytest.mark.asyncio
async def test_only_the_designated_mail_approver_can_answer(committed_database, monkeypatch):
    async with get_db_session() as db:
        config, manager, reviewer, smtp = await _setup_mail_chat(db, monkeypatch)
        config = config.model_copy(update={"approver_user_id": reviewer.id})
        connection = await connections.get_connection(config.connection_id)
        await connections.set_connection_function_state(connection.id, "mail_send", "ask")
        action = AuthorizationAction(agent_id=config.agent_id, connection_id=connection.id,
            tool_id=connection.tool_id, runtime="internal", context_key="principal:synthetic-mail",
            callback_key=str(uuid4()), name="mail_send", arguments={}, configuration={"account": "synthetic"})
        with prepared_authorization(action):
            with pytest.raises(AuthorizationRequired) as caught:
                await service.send_outgoing(config, _outgoing(), idempotency_key="distinct-reviewer")
        smtp.assert_not_called()
        row = await db.get(ActionAuthorization, caught.value.request_id)
        assert row.approver_user_id == reviewer.id and row.decision_source is None
        assert not await answer_action(row.id, user_id=manager.id, approved=True)
        assert not await answer_action(row.id, user_id=reviewer.id, approved=False)
        from core.authorize import Assignment, Role
        role = await db.scalar(select(Role).where(Role.code == "mail-reviewer-test"))
        db.add(Assignment(user_id=reviewer.id, role_id=role.id))
        await db.flush()
        assert await answer_action(row.id, user_id=reviewer.id, approved=False)
    async with get_db_session():
        with prepared_authorization(replace(action, callback_key=action.callback_key)):
            with pytest.raises(AuthorizationClosed, match="denied"):
                await service.send_outgoing(config, _outgoing(), idempotency_key="distinct-reviewer")
        smtp.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('channel', ['chat', 'journal', 'concurrent'])
@pytest.mark.parametrize('approved', [False, True])
@pytest.mark.parametrize('legacy_link', [False, True])
async def test_mail_journal_and_conversation_resolve_the_same_prepared_authorization(committed_database, monkeypatch, channel, approved, legacy_link):
    from app.messenger import answer_internal_interaction
    from app.messenger.models import Interaction
    from app.tools.authorization_notifications import deliver_authorization_notifications
    from core.database import get_db
    from uuid import UUID

    async with get_db_session():
        config, approver, outsider, smtp = await _setup_mail_chat(get_db(), monkeypatch)
        connection = await connections.get_connection(config.connection_id)
        await connections.set_connection_function_state(connection.id, 'mail_send', 'ask')
        action = AuthorizationAction(agent_id=config.agent_id, connection_id=connection.id,
            tool_id=connection.tool_id, runtime='internal', context_key='principal:journal-convergence',
            callback_key=str(uuid4()), name='mail_send', arguments={'subject': 'Bonjour'},
            configuration={'account': 'synthetic-account'})
        with prepared_authorization(action):
            with pytest.raises(AuthorizationRequired) as caught:
                await service.send_outgoing(config, _outgoing(), idempotency_key='journal-convergence')
        delivery = await get_db().scalar(select(MailDelivery).where(MailDelivery.idempotency_key == 'journal-convergence'))
        delivery_id, identifier, approver_id = delivery.id, caught.value.request_id, approver.id
        original_mime = bytes(delivery.raw_message)
        if legacy_link:
            from bridge.mail import dbadmin
            from core.dbadmin import SchemaTransitionSet
            delivery.authorization_id = None
            await get_db().flush()
            delta = SchemaTransitionSet(added_columns=frozenset({'mail_outbound_deliveries.authorization_id'}))
            assert not await dbadmin._all_prepared_authorizations_linked(get_db(), delta)
            await dbadmin._backfill_authorization_links(get_db(), delta)
            await dbadmin._backfill_authorization_links(get_db(), delta)
            assert await dbadmin._all_prepared_authorizations_linked(get_db(), delta)
            await get_db().commit()  # DbAdmin commits the upgrade before application continuations run.
            smtp.assert_not_called()
        pending = await service.list_deliveries(current_user_id=approver_id, scope='pending',
            agent_id=config.agent_id, search_text='', offset=0, limit=50)
        assert [item.id for item in pending.items] == [delivery_id]
        assert pending.items[0].can_review and pending.items[0].status == 'pending_approval'
        with pytest.raises(service.MailApprovalForbiddenError):
            await service.approve_delivery(delivery_id, current_user_id=outsider.id)
        await deliver_authorization_notifications()
        choice = await get_db().scalar(select(Interaction).where(Interaction.kind == 'tool_action_authorization'))
        assert choice is not None
        choice_id, room_id = choice.id, UUID(choice.room_id)

    async with get_db_session() as db:
        if channel == 'concurrent':
            async def chat_decision():
                async with get_db_session():
                    try:
                        await answer_internal_interaction(approver_id, room_id, choice_id, option_id='allow' if approved else 'deny')
                    except ValueError:
                        pass  # The journal may already have settled this same choice.
            async def journal_decision():
                async with get_db_session():
                    if approved:
                        await service.approve_delivery(delivery_id, current_user_id=approver_id)
                    else:
                        await service.reject_delivery(delivery_id, current_user_id=approver_id, reason='Synthetic refusal')
            await asyncio.gather(chat_decision(), journal_decision())
        elif channel == 'chat':
            await answer_internal_interaction(approver_id, room_id, choice_id, option_id='allow' if approved else 'deny')
        elif approved:
            receipt = await service.approve_delivery(delivery_id, current_user_id=approver_id)
            assert receipt.status == 'claimed'
        else:
            await service.reject_delivery(delivery_id, current_user_id=approver_id, reason='Synthetic refusal')
        smtp.assert_not_called()  # A decision never dispatches the owner's prepared call.
        row = await db.get(ActionAuthorization, identifier)
        assert row.status == ('approved' if approved else 'denied')
        detail = await service.get_delivery(delivery_id, current_user_id=approver_id)
        assert detail.authorization_id == identifier
        assert detail.authorization_status == row.status and not detail.can_review
        assert bytes((await db.get(MailDelivery, delivery_id)).raw_message) == original_mime
        pending = await service.list_deliveries(current_user_id=approver_id, scope='pending',
            agent_id=config.agent_id, search_text='', offset=0, limit=50)
        assert pending.total == 0
        with pytest.raises(service.MailDeliveryStateError):
            if approved:
                await service.reject_delivery(delivery_id, current_user_id=approver_id, reason='Too late')
            else:
                await service.approve_delivery(delivery_id, current_user_id=approver_id)
        if approved:
            with prepared_authorization(action):
                result = await service.send_outgoing(config, _outgoing(), idempotency_key='journal-convergence')
            assert result.status == 'sent'
            with prepared_authorization(action):
                await service.send_outgoing(config, _outgoing(), idempotency_key='journal-convergence')
            assert smtp.call_count == 1 and smtp.call_args.args[0] == original_mime
        else:
            with prepared_authorization(action):
                with pytest.raises(AuthorizationClosed, match='denied'):
                    await service.send_outgoing(config, _outgoing(), idempotency_key='journal-convergence')
            smtp.assert_not_called()
