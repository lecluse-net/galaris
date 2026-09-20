"""Contextual authorization assertions for outbound Mail reviews."""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.authorize import AssertionContext, BaseAssertion

from .models import MailOutboundDelivery


class MailApproverAssertion(BaseAssertion):
    """Allow a review only to the USER snapshotted as official approver."""

    async def assert_route(
        self,
        route_name: str,
        params: dict[str, Any],
        context: AssertionContext,
    ) -> bool:
        del route_name
        if context.user is None or context.db is None:
            return False
        try:
            delivery_id = UUID(str(params.get("delivery_id", "")))
        except ValueError:
            return False
        approver_user_id = await context.db.scalar(
            select(MailOutboundDelivery.approver_user_id).where(
                MailOutboundDelivery.id == delivery_id
            )
        )
        return approver_user_id == context.user.id


__all__ = ["MailApproverAssertion"]
