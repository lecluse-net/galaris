"""Synthetic Mail → private Chat → SMTP workflows, with real persistence."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent.models import Agent
from app.connection.models import Connection
from app.messenger import answer_internal_interaction, read_internal_interaction
from app.messenger.models import Interaction
from app.chat.provider import InternalMessenger
from app.tools.models import Tool
from core.authorize import Assignment, Privilege, Role, RolePrivilege
from core.user.models import User
from core.database import get_db_session
from bridge.mail import service
from .test_service import _config, _outgoing, _persist_connection


@pytest_asyncio.fixture
async def mail_chat(db, monkeypatch):
    return await _setup_mail_chat(db, monkeypatch)


async def _setup_mail_chat(db, monkeypatch):
    approver = User(email="reviewer@example.test", hashed_password="unused", is_active=True, language="fr")
    outsider = User(email="outsider@example.test", hashed_password="unused", is_active=True)
    db.add_all([approver, outsider])
    await db.flush()
    connection_id, agent_id = await _persist_connection(db, user_id=approver.id)
    agent = await db.get(Agent, agent_id)
    agent.user_id = approver.id
    tool = await db.scalar(select(Tool).where(Tool.code == "chat"))
    assert tool is not None
    db.add(Connection(agent_id=agent_id, tool_id=tool.id, active=True))
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "CONNECTION_ACCESS"))
    assert privilege is not None
    role = Role(code="mail-reviewer-test", display_name="Mail reviewer")
    db.add(role)
    await db.flush()
    db.add_all([RolePrivilege(role_id=role.id, privilege_id=privilege.id), Assignment(user_id=approver.id, role_id=role.id)])
    await db.commit()
    config = _config(connection_id, agent_id=agent_id).model_copy(
        update={"approval_required": True, "approver_user_id": approver.id}
    )
    smtp = Mock(return_value=(1, 0))
    monkeypatch.setattr(service.SmtpClient, "send", smtp)
    monkeypatch.setattr(service, "resolve_connection", AsyncMock(return_value=config))
    return config, approver, outsider, smtp


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["approve", "reject"])
async def test_mail_is_reviewed_once_by_its_approver_in_private_chat(db, mail_chat, option):
    config, approver, outsider, smtp = mail_chat
    receipt = await service.send_outgoing(config, _outgoing(), idempotency_key="chat-review")
    assert receipt.status == "pending_approval"
    smtp.assert_not_called()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    assert choice is not None
    assert choice.user_id == f"user:{approver.id}"
    assert "alice@example.org" in choice.body and "Bonjour" in choice.body and "Message" in choice.body
    room_id = UUID(choice.room_id)
    with pytest.raises(LookupError):
        await answer_internal_interaction(outsider.id, room_id, choice.id, option_id=option)
    result = await answer_internal_interaction(approver.id, room_id, choice.id, option_id=option)
    assert result.status == "RESOLVED"
    await answer_internal_interaction(approver.id, room_id, choice.id, option_id=option)
    replay = await service.send_outgoing(config, _outgoing(), idempotency_key="chat-review")
    assert replay.status == ("sent" if option == "approve" else "rejected")
    assert smtp.call_count == (1 if option == "approve" else 0)
    assert (await read_internal_interaction(approver.id, room_id, choice.id)).can_answer is False


@pytest.mark.asyncio
@pytest.mark.parametrize("review", ["approve", "reject", "expire"])
async def test_journal_review_or_expiry_disables_chat_without_a_second_send(db, mail_chat, review):
    config, approver, _, smtp = mail_chat
    receipt = await service.send_outgoing(config, _outgoing(), idempotency_key="journal-review")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    assert choice is not None
    if review == "approve":
        await service.approve_delivery(receipt.delivery_id, current_user_id=approver.id)
    elif review == "reject":
        await service.reject_delivery(receipt.delivery_id, current_user_id=approver.id, reason="Review elsewhere")
    else:
        choice.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    with pytest.raises(ValueError):
        await answer_internal_interaction(approver.id, UUID(choice.room_id), choice.id, option_id="approve")
    assert smtp.call_count == (1 if review == "approve" else 0)
    if review == "expire":
        # Expiring a chat question does not prevent the designated human using the journal.
        await service.approve_delivery(receipt.delivery_id, current_user_id=approver.id)
        assert smtp.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["privilege", "management", "active"])
async def test_chat_rechecks_the_approvers_current_rights(db, mail_chat, loss):
    config, approver, outsider, smtp = mail_chat
    receipt = await service.send_outgoing(config, _outgoing(), idempotency_key="rights-review")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    if loss == "privilege":
        assignment = await db.scalar(select(Assignment).where(Assignment.user_id == approver.id))
        assignment.soft_delete()
    elif loss == "management":
        agent = await db.get(Agent, config.agent_id)
        agent.user_id = outsider.id
    else:
        approver.is_active = False
    await db.commit()
    # Exercise the captured handler as a restart would, after permissions have changed.
    from app.messenger.interactions import _pending_from_record, ChoiceResolution
    from bridge.mail.approvals import handle_approval
    await handle_approval(_pending_from_record(choice), ChoiceResolution(choice.id, choice.kind, "approve", choice.metadata_))
    smtp.assert_not_called()
    delivery = await db.get(service.MailOutboundDelivery, receipt.delivery_id)
    assert delivery.status == "pending_approval"


@pytest.mark.asyncio
async def test_failed_chat_notification_retries_without_repreparing_or_sending_mail(db, monkeypatch, mail_chat):
    from bridge.mail.approvals import retry_approval_notifications
    config, approver, _, smtp = mail_chat
    original = InternalMessenger.send_to_room
    monkeypatch.setattr(InternalMessenger, "send_to_room", AsyncMock(side_effect=ConnectionError("Synthetic outage")))
    receipt = await service.send_outgoing(config, _outgoing(), idempotency_key="retry-review")
    assert receipt.status == "pending_approval"
    delivery = await db.get(service.MailOutboundDelivery, receipt.delivery_id)
    original_mime = delivery.raw_message
    assert delivery.approval_notified_at is None
    monkeypatch.setattr(InternalMessenger, "send_to_room", original)
    delivery.approval_notification_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await retry_approval_notifications()
    await retry_approval_notifications()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    assert choice is not None and choice.prompt_message_id is not None
    assert await db.scalar(select(func.count()).select_from(Interaction).where(Interaction.kind == "mail_approval")) == 1
    await answer_internal_interaction(approver.id, UUID(choice.room_id), choice.id, option_id="approve")
    smtp.assert_called_once()
    assert smtp.call_args.args[0] == original_mime


@pytest.mark.asyncio
async def test_concurrent_notifications_and_chat_journal_reviews_send_only_once(committed_database, monkeypatch):
    async with get_db_session() as db:
        config, approver, _, smtp = await _setup_mail_chat(db, monkeypatch)
        approver_id = approver.id

    async def request():
        async with get_db_session():
            return await service.send_outgoing(config, _outgoing(), idempotency_key="concurrent-review")

    receipts = await asyncio.gather(*(request() for _ in range(4)))
    assert len({receipt.delivery_id for receipt in receipts}) == 1
    delivery_id = receipts[0].delivery_id
    async with get_db_session() as db:
        choices = list(await db.scalars(select(Interaction).where(Interaction.kind == "mail_approval")))
        assert len(choices) == 1
        choice_id, room_id = choices[0].id, UUID(choices[0].room_id)

    async def chat():
        async with get_db_session():
            try:
                await answer_internal_interaction(approver_id, room_id, choice_id, option_id="approve")
            except ValueError:
                pass  # The journal may have expired the question first.

    async def journal():
        async with get_db_session():
            try:
                await service.approve_delivery(delivery_id, current_user_id=approver_id)
            except service.MailDeliveryStateError:
                pass  # The chat may already have submitted it.

    await asyncio.gather(chat(), journal())
    smtp.assert_called_once()
    async with get_db_session() as db:
        delivery = await db.get(service.MailOutboundDelivery, delivery_id)
        assert delivery.status == "sent"


@pytest.mark.asyncio
async def test_interrupted_prompt_delivery_is_recovered_from_its_persisted_choice(db, monkeypatch, mail_chat):
    from bridge.mail.approvals import retry_approval_notifications
    config, approver, _, smtp = mail_chat
    original = InternalMessenger.send_to_room
    monkeypatch.setattr(InternalMessenger, "send_to_room", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await service.send_outgoing(config, _outgoing(), idempotency_key="interrupted-review")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    assert choice is not None and choice.prompt_message_id is None
    choice_id = choice.id
    delivery = await db.scalar(select(service.MailOutboundDelivery).where(
        service.MailOutboundDelivery.idempotency_key == "interrupted-review",
    ))
    delivery.approval_notification_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    monkeypatch.setattr(InternalMessenger, "send_to_room", original)
    await retry_approval_notifications()
    await db.refresh(choice)
    assert choice.id == choice_id and choice.prompt_message_id is not None
    await answer_internal_interaction(approver.id, UUID(choice.room_id), choice.id, option_id="approve")
    smtp.assert_called_once()


@pytest.mark.asyncio
async def test_captured_answer_replay_never_retries_an_uncertain_smtp_submission(db, mail_chat):
    from app.messenger import interactions
    from uuid import uuid4
    config, approver, _, smtp = mail_chat
    smtp.side_effect = TimeoutError("Synthetic SMTP disconnect after submission")
    receipt = await service.send_outgoing(config, _outgoing(), idempotency_key="uncertain-review")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    await answer_internal_interaction(approver.id, UUID(choice.room_id), choice.id, option_id="approve")
    delivery = await db.get(service.MailOutboundDelivery, receipt.delivery_id)
    assert delivery.status == "uncertain"
    # Reproduce a crash after the domain committed its outcome but before choice completion.
    choice.status = "PROCESSING"
    choice.processing_token = uuid4()
    choice.processing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await interactions.retry_pending_interactions()
    assert choice.status == "RESOLVED"
    assert delivery.status == "uncertain"
    smtp.assert_called_once()


@pytest.mark.asyncio
async def test_responsible_approver_can_differ_from_the_agents_owner(db, mail_chat):
    config, approver, outsider, smtp = mail_chat
    agent = await db.get(Agent, config.agent_id)
    agent.user_id = outsider.id
    role = await db.scalar(select(Role).where(Role.code == "mail-reviewer-test"))
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL"))
    db.add(RolePrivilege(role_id=role.id, privilege_id=privilege.id))
    await db.commit()
    await service.send_outgoing(config, _outgoing(), idempotency_key="distinct-reviewer")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    assert choice is not None and choice.user_id == f"user:{approver.id}"
    await answer_internal_interaction(approver.id, UUID(choice.room_id), choice.id, option_id="reject")
    smtp.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["archived", "shared"])
async def test_mail_request_uses_a_visible_room_private_to_its_approver(db, mail_chat, unavailable):
    from app.messenger import create_internal_room
    from app.messenger.models import MessengerUser, RoomUser
    config, approver, outsider, smtp = mail_chat
    room = await create_internal_room(actor_user_id=approver.id, agent_id=config.agent_id)
    if unavailable == "archived":
        membership = await db.scalar(select(RoomUser).join(MessengerUser).where(
            RoomUser.room_id == room.id, MessengerUser.galaris_user_id == approver.id,
        ))
        membership.archived = True
    else:
        connection = await db.get(Connection, room.connection_id)
        identity = MessengerUser(tool_id=connection.tool_id, external_id=f"user:{outsider.id}",
                                 galaris_user_id=outsider.id, is_ai=False)
        db.add(identity)
        await db.flush()
        db.add(RoomUser(room_id=room.id, user_id=identity.id, role="member"))
    await db.commit()
    await service.send_outgoing(config, _outgoing(), idempotency_key="private-review")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "mail_approval"))
    assert choice is not None and choice.room_id != str(room.id)
    await answer_internal_interaction(approver.id, UUID(choice.room_id), choice.id, option_id="approve")
    smtp.assert_called_once()
