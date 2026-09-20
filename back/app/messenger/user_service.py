"""Idempotent persistence and reconciliation of remote Messenger identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm.attributes import set_committed_value

from core.database import get_db

from app.tools import ToolModel

from . import directory
from ._observations import ObservedMessengerUser
from .models import (
    RoomUser,
    MessengerUser,
)


_IDENTITY_RECONCILIATION_BATCH_SIZE = 500


@dataclass(frozen=True)
class MessengerAgentIdentityReconciliationResult:
    """Bounded summary of persisted Nextcloud-to-agent identity repairs."""

    users_scanned: int = 0
    links_created: int = 0
    links_corrected: int = 0
    links_cleared: int = 0

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


async def resolve_messenger_user(
    *,
    tool_id: int,
    external_id: str,
    display_name: str = "",
    agent_id: int | None = None,
    galaris_user_id: int | None = None,
    is_ai: bool = False,
) -> UUID:
    """Resolve, restore and refresh one remote identity without duplication."""

    normalized_external_id = external_id[:512].strip()
    if not normalized_external_id:
        raise ValueError("A Messenger user requires an external identifier.")
    requested_display_name = display_name[:500].strip()
    normalized_display_name = requested_display_name or normalized_external_id
    effective_is_ai = is_ai or agent_id is not None
    inserted_id = await get_db().scalar(
        pg_insert(MessengerUser)
        .values(
            id=uuid4(),
            tool_id=tool_id,
            agent_id=agent_id,
            galaris_user_id=galaris_user_id,
            external_id=normalized_external_id,
            display_name=normalized_display_name,
            is_ai=effective_is_ai,
        )
        .on_conflict_do_nothing(constraint="uq_messenger_user_tool_external")
        .returning(MessengerUser.id)
    )
    if inserted_id is not None:
        return inserted_id

    existing = await get_db().scalar(
        select(MessengerUser)
        .where(
            MessengerUser.tool_id == tool_id,
            MessengerUser.external_id == normalized_external_id,
        )
        .execution_options(include_historized=True)
    )
    if existing is None:
        raise RuntimeError("The Messenger user disappeared while being resolved.")
    # Partial observations (notably live-call membership) often expose only an
    # external identifier. They must not downgrade a name learned earlier from the
    # provider directory to that opaque identifier.
    if not requested_display_name:
        normalized_display_name = existing.display_name or normalized_external_id
    values: dict[str, object] = {
        "display_name": normalized_display_name,
        "is_ai": bool(existing.is_ai or effective_is_ai),
        "deleted_at": None,
        "deleted_by": None,
    }
    if agent_id is not None:
        values["agent_id"] = agent_id
        values["is_ai"] = True
    if galaris_user_id is not None:
        values["galaris_user_id"] = galaris_user_id
    await get_db().execute(
        update(MessengerUser).where(MessengerUser.id == existing.id).values(**values)
    )
    return existing.id


async def resolve_observed_user(*, tool_id: int, user: ObservedMessengerUser) -> UUID:
    """Resolve one transport identity through local directory state and persist it."""

    resolved = await directory.resolve_user(tool_id, user.id)
    agent_id = user.agent_id if user.agent_id is not None else resolved.agent_id
    return await resolve_messenger_user(
        tool_id=tool_id,
        external_id=user.id,
        display_name=user.display_name,
        agent_id=agent_id,
        is_ai=user.is_ai or agent_id is not None,
    )


async def enrich_messenger_users(users: list[MessengerUser]) -> None:
    """Project configured agent links onto stored remote identities without mutating a GET."""

    unresolved_by_tool: dict[int, list[MessengerUser]] = {}
    for user in users:
        if user.agent_id is None:
            unresolved_by_tool.setdefault(user.tool_id, []).append(user)
    for tool_id, unresolved in unresolved_by_tool.items():
        resolved = await directory.resolve_agent_ids(
            tool_id,
            (user.external_id for user in unresolved),
        )
        for user in unresolved:
            agent_id = resolved.get(user.external_id)
            if agent_id is None:
                continue
            set_committed_value(user, "agent_id", agent_id)
            set_committed_value(user, "is_ai", True)


async def reconcile_nextcloud_agent_identities(
) -> MessengerAgentIdentityReconciliationResult:
    """Persist exact, unambiguous agent links for existing Nextcloud identities."""

    tools = list(
        (
            await get_db().scalars(
                select(ToolModel).where(ToolModel.messenger_config.is_not(None))
            )
        ).all()
    )
    tool_ids = [
        tool.id
        for tool in tools
        if str((tool.messenger_config or {}).get("service") or "")
        == "nextcloud_talk"
    ]
    if not tool_ids:
        return MessengerAgentIdentityReconciliationResult()

    users_scanned = 0
    links_created = 0
    links_corrected = 0
    links_cleared = 0
    cursor: UUID | None = None
    while True:
        query = select(MessengerUser).where(MessengerUser.tool_id.in_(tool_ids))
        if cursor is not None:
            query = query.where(MessengerUser.id > cursor)
        query = (
            query
            .order_by(MessengerUser.id)
            .limit(_IDENTITY_RECONCILIATION_BATCH_SIZE)
            .execution_options(include_historized=True)
        )
        users = list((await get_db().scalars(query)).all())
        if not users:
            break

        users_by_tool: dict[int, list[MessengerUser]] = {}
        for user in users:
            users_by_tool.setdefault(user.tool_id, []).append(user)
        for tool_id, tool_users in users_by_tool.items():
            resolved = await directory.resolve_agent_ids(
                tool_id,
                (user.external_id for user in tool_users),
            )
            for user in tool_users:
                desired_agent_id = resolved.get(user.external_id)
                current_agent_id = user.agent_id
                if current_agent_id == desired_agent_id:
                    continue
                if desired_agent_id is None:
                    user.agent_id = None
                    links_cleared += 1
                    continue
                user.agent_id = desired_agent_id
                user.is_ai = True
                if current_agent_id is None:
                    links_created += 1
                else:
                    links_corrected += 1

        users_scanned += len(users)
        cursor = users[-1].id
        await get_db().flush()

    return MessengerAgentIdentityReconciliationResult(
        users_scanned=users_scanned,
        links_created=links_created,
        links_corrected=links_corrected,
        links_cleared=links_cleared,
    )


async def synchronize_users(
    *,
    tool_id: int,
    users: list[ObservedMessengerUser],
    connection_id: int | None = None,
    authoritative: bool = False,
) -> list[MessengerUser]:
    """Persist a remote user result and optionally reconcile a complete directory snapshot."""

    del connection_id
    unique: dict[str, ObservedMessengerUser] = {}
    for user in users:
        external_id = user.id[:512].strip()
        if external_id:
            unique[external_id] = user

    current_ids: list[UUID] = []
    ordered_external_ids: list[str] = []
    for external_id, user in unique.items():
        current_ids.append(
            await resolve_observed_user(
                tool_id=tool_id,
                user=user,
            )
        )
        ordered_external_ids.append(external_id)

    if authoritative:
        stale = update(MessengerUser).where(
            MessengerUser.tool_id == tool_id,
            MessengerUser.deleted_at.is_(None),
        )
        if current_ids:
            stale = stale.where(MessengerUser.id.not_in(current_ids))
        await get_db().execute(stale.values(deleted_at=func.now(), deleted_by=None))

    rows = list(
        (
            await get_db().scalars(
                select(MessengerUser).where(MessengerUser.id.in_(current_ids))
            )
        ).all()
    )
    by_external_id = {row.external_id: row for row in rows}
    return [
        by_external_id[external_id]
        for external_id in ordered_external_ids
        if external_id in by_external_id
    ]


async def reconcile_room_users(
    *,
    room_id: UUID,
    user_ids: list[UUID],
    authoritative: bool,
) -> None:
    """Upsert current memberships and remove stale associations for a complete snapshot."""

    unique_ids = list(dict.fromkeys(user_ids))
    for user_id in unique_ids:
        await get_db().execute(
            pg_insert(RoomUser)
            .values(room_id=room_id, user_id=user_id)
            .on_conflict_do_nothing()
        )
    if authoritative:
        stale = delete(RoomUser).where(RoomUser.room_id == room_id)
        if unique_ids:
            stale = stale.where(RoomUser.user_id.not_in(unique_ids))
        await get_db().execute(stale)


__all__ = [
    "MessengerAgentIdentityReconciliationResult",
    "enrich_messenger_users",
    "reconcile_nextcloud_agent_identities",
    "reconcile_room_users",
    "resolve_messenger_user",
    "resolve_observed_user",
    "synchronize_users",
]
