"""Real durable MIME and approval persistence; only the SMTP boundary is replaced."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.connection import facade as connections
from app.agent.authorization import set_yolo
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
async def test_common_approval_binds_frozen_mime_and_sends_once(committed_database, monkeypatch):
    async with get_db_session():
        from core.database import get_db
        config, approver, _, smtp = await _setup_mail_chat(get_db(), monkeypatch)
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
        with prepared_authorization(action):
            replay = await service.send_outgoing(config, _outgoing(), idempotency_key="common-review")
        assert replay.status == "sent"
        assert smtp.call_count == 1
        from core.database import get_db
        delivery = await get_db().get(MailDelivery, receipt.delivery_id)
        assert bytes(delivery.raw_message) == original_mime
        row = await get_db().get(ActionAuthorization, caught.value.request_id)
        assert row.status == "completed" and row.decision_source == "human"


@pytest.mark.asyncio
async def test_yolo_does_not_answer_for_a_distinct_mail_approver(committed_database, monkeypatch):
    async with get_db_session() as db:
        config, manager, reviewer, smtp = await _setup_mail_chat(db, monkeypatch)
        await set_yolo(config.agent_id, enabled=True, acknowledged=True)
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
        assert await answer_action(row.id, user_id=reviewer.id, approved=False)
    async with get_db_session():
        with prepared_authorization(replace(action, callback_key=action.callback_key)):
            with pytest.raises(AuthorizationClosed, match="denied"):
                await service.send_outgoing(config, _outgoing(), idempotency_key="distinct-reviewer")
        smtp.assert_not_called()
