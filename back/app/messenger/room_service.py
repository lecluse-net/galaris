"""Persistence helpers for canonical Messenger rooms."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_db

from ._observations import ObservedMessengerRoom
from .models import (
    ConversationType,
    Room,
)
from .user_service import reconcile_room_users, resolve_observed_user


async def resolve_messenger_room(
    *,
    connection_id: int,
    external_id: str,
    label: str | None = None,
    kind: str = "group",
    conversation_type: ConversationType = ConversationType.TEXT,
) -> UUID:
    """Resolve or create one room without duplicating its transport scope."""

    normalized_external_id = external_id[:512]
    if not normalized_external_id:
        raise ValueError("A Messenger room requires an external identifier.")
    normalized_label = (label or normalized_external_id)[:500]
    inserted_id = await get_db().scalar(
        pg_insert(Room)
        .values(
            id=uuid4(),
            connection_id=connection_id,
            external_id=normalized_external_id,
            label=normalized_label,
            kind="direct" if kind == "direct" else "group",
            conversation_type=conversation_type.value,
        )
        .on_conflict_do_nothing(
            constraint="uq_messenger_room_connection_external"
        )
        .returning(Room.id)
    )
    if inserted_id is not None:
        return inserted_id

    existing = (
        await get_db().execute(
            select(Room.id, Room.deleted_at)
            .where(
                Room.connection_id == connection_id,
                Room.external_id == normalized_external_id,
            )
            .execution_options(include_historized=True)
        )
    ).one_or_none()
    if existing is None:
        raise RuntimeError("The Messenger room disappeared while it was being resolved.")
    room_id, _deleted_at = existing
    await get_db().execute(
        update(Room)
        .where(Room.id == room_id)
        .values(
            label=normalized_label,
            kind="direct" if kind == "direct" else "group",
            conversation_type=conversation_type.value,
            deleted_at=None,
            deleted_by=None,
        )
    )
    return room_id


async def _room_models(room_ids: list[UUID]) -> list[Room]:
    rooms = list(
        (
            await get_db().scalars(
                select(Room).where(Room.id.in_(room_ids))
            )
        ).all()
    )
    by_id = {room.id: room for room in rooms}
    return [by_id[room_id] for room_id in room_ids if room_id in by_id]


async def synchronize_rooms(
    *,
    connection_id: int,
    tool_id: int,
    rooms: list[ObservedMessengerRoom],
    authoritative: bool = False,
) -> list[Room]:
    """Persist remote rooms, users and memberships, then return local rows."""

    unique = {room.id[:512].strip(): room for room in rooms if room.id.strip()}
    current_ids: list[UUID] = []
    for external_id, room in unique.items():
        room_id = await resolve_messenger_room(
            connection_id=connection_id,
            external_id=external_id,
            label=room.label,
            kind=room.kind,
            conversation_type=ConversationType(room.conversation_type),
        )
        current_ids.append(room_id)
        member_ids: list[UUID] = []
        for user in room.users:
            if not user.id.strip():
                continue
            member_ids.append(
                await resolve_observed_user(
                    tool_id=tool_id,
                    user=user,
                )
            )
        await reconcile_room_users(
            room_id=room_id,
            user_ids=member_ids,
            authoritative=room.users_complete,
        )

    if authoritative:
        stale = update(Room).where(
            Room.connection_id == connection_id,
            Room.deleted_at.is_(None),
        )
        if current_ids:
            stale = stale.where(Room.id.not_in(current_ids))
        await get_db().execute(stale.values(deleted_at=func.now(), deleted_by=None))

    return await _room_models(current_ids)


__all__ = [
    "resolve_messenger_room",
    "synchronize_rooms",
]
