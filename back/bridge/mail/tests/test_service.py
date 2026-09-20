from unittest.mock import AsyncMock, call

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.tools.models import Tool
from core.user.models import User
from bridge.mail import service
from bridge.mail.contracts import MailConnectionConfig, MailEndpointConfig, OutgoingMail


async def _persist_connection(db: AsyncSession) -> tuple[int, int]:
    title = Title(label="Agent", gender="N")
    tool = Tool(code="mail-idempotency-test", label="Mail")
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Mail",
        last_name="Agent",
        code="mail-idempotency-agent",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    return connection.id, agent.id


def _config(connection_id: int, *, agent_id: int) -> MailConnectionConfig:
    endpoint = MailEndpointConfig(
        host="mail.example.org",
        port=993,
        security="tls",
        username="agent@example.org",
        password=SecretStr("secret"),
    )
    return MailConnectionConfig(
        connection_id=connection_id,
        agent_id=agent_id,
        email_address="agent@example.org",
        imap=endpoint,
        smtp=endpoint.model_copy(update={"port": 465}),
        connect_timeout_s=10,
        operation_timeout_s=30,
        max_attachment_bytes=1_000_000,
        max_total_attachment_bytes=2_000_000,
        agent_label="Mail Agent",
    )


def _outgoing(subject: str = "Bonjour") -> OutgoingMail:
    return OutgoingMail(
        to=("alice@example.org",),
        cc=(),
        bcc=(),
        subject=subject,
        body="Message",
        html_body=None,
        attachments=(),
    )


@pytest.mark.asyncio
async def test_delivery_claim_reuses_key_and_rejects_a_different_payload(
    db: AsyncSession,
) -> None:
    connection_id, agent_id = await _persist_connection(db)
    config = _config(connection_id, agent_id=agent_id)

    first = await service._claim_delivery(  # pyright: ignore[reportPrivateUsage]
        config,
        idempotency_key="task:42:mail:1",
        fingerprint="a" * 64,
        outgoing=_outgoing(),
        delivery_kind="send",
    )
    replay = await service._claim_delivery(  # pyright: ignore[reportPrivateUsage]
        config,
        idempotency_key="task:42:mail:1",
        fingerprint="a" * 64,
        outgoing=_outgoing(),
        delivery_kind="send",
    )

    assert replay.id == first.id
    assert replay.rfc_message_id == first.rfc_message_id
    with pytest.raises(ValueError, match="different message"):
        await service._claim_delivery(  # pyright: ignore[reportPrivateUsage]
            config,
            idempotency_key="task:42:mail:1",
            fingerprint="b" * 64,
            outgoing=_outgoing("Different"),
            delivery_kind="send",
        )


@pytest.mark.asyncio
async def test_delivery_waits_for_the_responsible_user_before_smtp(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id, agent_id = await _persist_connection(db)
    approver = User(
        email="mail-approver@example.test",
        hashed_password="x",
        display_name="Mail Approver",
        is_active=True,
    )
    db.add(approver)
    await db.flush()
    config = _config(connection_id, agent_id=agent_id).model_copy(
        update={"approval_required": True, "approver_user_id": approver.id}
    )
    smtp_send = AsyncMock()
    monkeypatch.setattr(service.SmtpClient, "send", smtp_send)
    observe = AsyncMock(return_value=None)
    monkeypatch.setattr("app.messenger.observe_contact", observe)

    receipt = await service.send_outgoing(
        config,
        _outgoing(),
        idempotency_key="task:42:mail:approval",
    )

    assert receipt.status == "pending_approval"
    assert smtp_send.await_count == 0
    delivery = await db.get(service.MailOutboundDelivery, receipt.delivery_id)
    assert delivery is not None
    assert delivery.raw_message is not None
    assert delivery.to_addresses == ["alice@example.org"]
    assert delivery.subject == "Bonjour"
    assert delivery.approver_user_id == approver.id
    page = await service.list_deliveries(
        current_user_id=approver.id,
        scope="pending",
        agent_id=agent_id,
        search_text="alice@example.org",
        offset=0,
        limit=50,
    )
    assert page.total == 1
    assert page.items[0].can_review is True
    assert page.items[0].agent_label == "Mail Agent"

    with pytest.raises(service.MailApprovalForbiddenError):
        await service.approve_delivery(
            receipt.delivery_id,
            current_user_id=approver.id + 1,
        )

    monkeypatch.setattr(
        service,
        "resolve_connection",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        service.SmtpClient,
        "send",
        lambda _self, _message, *, sender, recipients: (len(recipients), 0),
    )
    approved = await service.approve_delivery(
        receipt.delivery_id,
        current_user_id=approver.id,
    )

    assert approved.status == "sent"
    assert delivery.reviewed_by_user_id == approver.id
    assert delivery.reviewed_at is not None
    assert delivery.sent_at is not None
    assert observe.await_count == 1


@pytest.mark.asyncio
async def test_rejected_delivery_is_terminal_and_never_reaches_smtp(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id, agent_id = await _persist_connection(db)
    approver = User(
        email="mail-rejector@example.test",
        hashed_password="x",
        is_active=True,
    )
    db.add(approver)
    await db.flush()
    config = _config(connection_id, agent_id=agent_id).model_copy(
        update={"approval_required": True, "approver_user_id": approver.id}
    )
    smtp_send = AsyncMock()
    monkeypatch.setattr(service.SmtpClient, "send", smtp_send)
    receipt = await service.send_outgoing(
        config,
        _outgoing(),
        idempotency_key="task:42:mail:rejected",
    )

    detail = await service.reject_delivery(
        receipt.delivery_id,
        current_user_id=approver.id,
        reason="Recipient must be confirmed",
    )

    assert detail.status == "rejected"
    assert detail.rejection_reason == "Recipient must be confirmed"
    assert smtp_send.await_count == 0
    with pytest.raises(service.MailDeliveryStateError):
        await service.approve_delivery(
            receipt.delivery_id,
            current_user_id=approver.id,
        )


@pytest.mark.asyncio
async def test_sent_mail_projects_each_distinct_recipient_and_replay_heals_memory(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id, agent_id = await _persist_connection(db)
    config = _config(connection_id, agent_id=agent_id)
    observe = AsyncMock(return_value=None)
    monkeypatch.setattr("app.messenger.observe_contact", observe)
    monkeypatch.setattr(
        service.SmtpClient,
        "send",
        lambda _self, _message, *, sender, recipients: (len(recipients), 0),
    )
    outgoing = OutgoingMail(
        to=("Alice@Example.ORG",),
        cc=("alice@example.org", "bob@example.org"),
        bcc=("hidden@example.org",),
        subject="Bonjour",
        body="Message",
        html_body=None,
        attachments=(),
    )

    receipt = await service.send_outgoing(
        config,
        outgoing,
        idempotency_key="task:42:mail:contacts",
    )

    assert receipt.status == "sent"
    assert observe.await_args_list == [
        call(
            owner_agent_id=agent_id,
            messaging_id="mail",
            user_id="alice@example.org",
        ),
        call(
            owner_agent_id=agent_id,
            messaging_id="mail",
            user_id="bob@example.org",
        ),
        call(
            owner_agent_id=agent_id,
            messaging_id="mail",
            user_id="hidden@example.org",
        ),
    ]

    observe.reset_mock()
    replay = await service.send_outgoing(
        config,
        outgoing,
        idempotency_key="task:42:mail:contacts",
    )

    assert replay.delivery_id == receipt.delivery_id
    assert replay.status == "sent"
    assert observe.await_count == 3
