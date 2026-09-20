"""Authorization assertions for the managed document library."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent import management_scope_for
from core.authorize import AssertionContext, BaseAssertion

from .access import managed_item_agent_ids, human_document_access
from .models import MemoryItem


class ManagedDocumentAccessAssertion(BaseAssertion):
    """Limit document-library routes to documents visible to managed Agents."""

    async def assert_route(
        self,
        route_name: str,
        params: dict[str, Any],
        context: AssertionContext,
    ) -> bool:
        if context.user is None or context.db is None:
            return False
        scope = await management_scope_for(context.user, context.db)
        if route_name == "browse_managed_documents":
            return True
        raw_document_id = params.get("document_id")
        try:
            document_id = UUID(str(raw_document_id))
        except (TypeError, ValueError):
            return False
        item = await context.db.scalar(
            select(MemoryItem)
            .options(selectinload(MemoryItem.grants))
            .where(
                MemoryItem.id == document_id,
                MemoryItem.node_kind == "document",
            )
        )
        if item is None:
            return False
        readable, writable = await managed_item_agent_ids(item, scope.agent_ids)
        human = await human_document_access(item, scope.user_id)
        if route_name in {
            "move_managed_document",
            "change_document_owner",
            "set_managed_document_global_access",
            "set_managed_document_grant",
            "remove_managed_document_grant",
            "restore_managed_document_content_revision",
        }:
            return bool(writable) or human.can_write
        return bool(readable) or human.can_read


__all__ = ["ManagedDocumentAccessAssertion"]
