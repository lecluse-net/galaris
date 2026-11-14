"""Read contracts for domain journals displaying the common action decision."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import load_only

from core.database import get_db
from core.util import get_encryption_service

from .authorization_models import ActionAuthorization


@dataclass(frozen=True)
class AuthorizationReview:
    id: UUID
    agent_id: int
    connection_id: int | None
    approver_user_id: int
    status: str
    decided_at: datetime | None
    decision_source: str | None
    created_at: datetime


def pending_authorization_ids() -> Select[tuple[UUID]]:
    """Composable filter for journals; transport state remains domain-owned."""
    return select(ActionAuthorization.id).where(
        ActionAuthorization.status == "pending",
        ActionAuthorization.expires_at > datetime.now(timezone.utc),
    )


def _review(row: ActionAuthorization) -> AuthorizationReview:
    status = row.status
    if status in ("pending", "approved") and row.expires_at <= datetime.now(timezone.utc):
        status = "expired"
    return AuthorizationReview(
        row.id, row.agent_id, row.connection_id, row.approver_user_id,
        status, row.decided_at, row.decision_source, row.created_at,
    )


async def authorization_reviews(
    identifiers: Collection[UUID],
) -> dict[UUID, AuthorizationReview]:
    if len(identifiers) > 500:
        raise ValueError("Read at most 500 authorization decisions")
    if not identifiers:
        return {}
    rows = await get_db().scalars(
        select(ActionAuthorization)
        .where(ActionAuthorization.id.in_(identifiers))
        .options(load_only(
            ActionAuthorization.id, ActionAuthorization.agent_id, ActionAuthorization.connection_id,
            ActionAuthorization.approver_user_id, ActionAuthorization.status, ActionAuthorization.expires_at,
            ActionAuthorization.decided_at, ActionAuthorization.decision_source, ActionAuthorization.created_at,
        ))
        .execution_options(populate_existing=True)
    )
    return {row.id: _review(row) for row in rows}


async def prepared_authorization_links(
    *,
    capability_names: Collection[str],
    resource_key: str,
    after_id: UUID | None = None,
    limit: int = 200,
) -> tuple[list[tuple[AuthorizationReview, UUID]], UUID | None]:
    """Bounded upgrade read: expose only a prepared resource identity, never its contents."""
    if not 1 <= limit <= 500:
        raise ValueError("Read between 1 and 500 prepared authorizations")
    query = select(ActionAuthorization).where(ActionAuthorization.capability_name.in_(capability_names))
    if after_id is not None:
        query = query.where(ActionAuthorization.id > after_id)
    rows = list(await get_db().scalars(query.order_by(ActionAuthorization.id).limit(limit)))
    result: list[tuple[AuthorizationReview, UUID]] = []
    for row in rows:
        for encrypted in (row.encrypted_arguments, row.encrypted_receipt):
            if encrypted is None:
                continue
            payload: object = json.loads(get_encryption_service().decrypt(encrypted))
            if not isinstance(payload, dict):
                continue
            mapping = cast(dict[str, object], payload)
            prepared = mapping.get("prepared", mapping)
            if not isinstance(prepared, dict):
                continue
            resource = cast(dict[str, object], prepared).get(resource_key)
            if not isinstance(resource, str):
                continue
            try:
                identity = UUID(resource)
            except ValueError:
                continue
            result.append((_review(row), identity))
            break
    return result, rows[-1].id if len(rows) == limit else None
