from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bridge.mail.assertions import MailApproverAssertion
from core.authorize import AssertionContext
from core.user.models import User


@pytest.mark.asyncio
async def test_only_the_official_user_passes_the_mail_approver_assertion() -> None:
    delivery_id = uuid4()
    approver = User(
        id=7,
        email="approver@example.test",
        hashed_password="x",
        is_active=True,
    )
    db = AsyncMock()
    db.scalar.return_value = approver.id
    assertion = MailApproverAssertion()

    assert await assertion.assert_route(
        "approve_outbound_mail",
        {"delivery_id": str(delivery_id)},
        AssertionContext(user=approver, db=db),
    )

    other_user = User(
        id=8,
        email="other@example.test",
        hashed_password="x",
        is_active=True,
    )
    assert not await assertion.assert_route(
        "approve_outbound_mail",
        {"delivery_id": str(delivery_id)},
        AssertionContext(user=other_user, db=db),
    )


@pytest.mark.asyncio
async def test_mail_approver_assertion_rejects_an_invalid_delivery_id() -> None:
    approver = User(
        id=7,
        email="approver@example.test",
        hashed_password="x",
        is_active=True,
    )

    assert not await MailApproverAssertion().assert_route(
        "approve_outbound_mail",
        {"delivery_id": "not-a-uuid"},
        AssertionContext(user=approver, db=AsyncMock()),
    )
