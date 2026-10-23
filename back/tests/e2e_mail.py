"""Synthetic runtime continuation; real Mail, approvals, outbox and Chat persistence."""

from uuid import uuid4

from sqlalchemy import select

from app.connection import facade as connections
from app.tools.authorization import prepared_authorization
from app.tools.facade import AuthorizationAction, AuthorizationRequired, AuthorizationClosed, register_authorization_waker
from app.tools.authorization_notifications import deliver_authorization_notifications
from bridge.mail import service
from bridge.mail.contracts import MailConnectionConfig, MailMessageDetail, MailMessageRef, MailMessageSummary, OutgoingMail
from core.database import get_db

_continuations: dict[str, tuple[MailConnectionConfig, OutgoingMail, str, AuthorizationAction]] = {}


async def _resume(agent_id: int, context_key: str) -> bool:
    continuation = _continuations.get(context_key)
    if continuation is None or continuation[0].agent_id != agent_id:
        return False
    config, outgoing, key, action = continuation
    try:
        with prepared_authorization(action):
            await service.send_outgoing(config, outgoing, idempotency_key=key)
    except AuthorizationRequired:
        return False
    except AuthorizationClosed as closed:
        if closed.status not in ("denied", "expired", "invalidated"):
            raise
    _continuations.pop(context_key, None)
    return True


register_authorization_waker("synthetic-mail-runtime", _resume)


def synthetic_inbound_message(client, ref, *, body_offset, body_limit):
    body = "Contenu synthétique du courriel reçu."
    return MailMessageDetail(ref=ref.encode(), from_address="sender@example.org",
        to_addresses=[str(client.config.email_address)], subject=f"Courriel entrant synthétique — {client.config.agent_label}",
        body=body, body_format="plain", body_start=0, body_end=len(body), body_total=len(body))


async def seed_inbound_mail(config: MailConnectionConfig) -> dict[str, str]:
    from bridge.mail.inbound import record_receipt, process_receipt

    subject = f"Courriel entrant synthétique — {config.agent_label}"
    summary = MailMessageSummary(ref=MailMessageRef(mailbox="INBOX", uid_validity=1, uid=10).encode(),
        from_address="sender@example.org", subject=subject,
        to_addresses=[str(config.email_address)])
    row = await record_receipt(config, summary, dispatch=True)
    await process_receipt(row.id)
    assert row.authorization_id is not None
    await deliver_authorization_notifications()
    return {"receipt_id": str(row.id), "authorization_id": str(row.authorization_id), "inbound_subject": subject}


async def seed_common_mail(config: MailConnectionConfig, outgoing: OutgoingMail, key: str) -> dict[str, str]:
    connection = await connections.get_connection(config.connection_id)
    assert connection is not None
    await connections.set_connection_function_state(connection.id, "mail_send", "ask")
    context_key = f"principal:synthetic-mail-runtime:{uuid4()}"
    action = AuthorizationAction(agent_id=config.agent_id, connection_id=connection.id, tool_id=connection.tool_id,
        runtime="internal", context_key=context_key, callback_key=str(uuid4()), name="mail_send",
        arguments={"to": list(outgoing.to), "subject": outgoing.subject, "body": outgoing.body}, configuration={})
    with prepared_authorization(action):
        try:
            await service.send_outgoing(config, outgoing, idempotency_key=key)
        except AuthorizationRequired as pending:
            identifier = pending.request_id
        else:
            raise AssertionError("The synthetic prepared Mail must await its human decision")
    delivery = await get_db().scalar(select(service.MailOutboundDelivery).where(service.MailOutboundDelivery.idempotency_key == key))
    assert delivery is not None
    _continuations[context_key] = config, outgoing, key, action
    await deliver_authorization_notifications()
    return {"delivery_id": str(delivery.id), "authorization_id": str(identifier)}
