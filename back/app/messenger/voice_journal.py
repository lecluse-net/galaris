"""Canonical Messenger persistence for live audio conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select, update

from core.database import get_db

from ._observations import (
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from .facade import get_messenger
from .models import ConversationType, Message, MessengerUser, Room, RoomUser
from .room_service import resolve_messenger_room
from .user_service import reconcile_room_users, resolve_observed_user


VoiceMessageRole = Literal["input", "output"]


@dataclass(frozen=True)
class AudioSpeakerIdentity:
    """Stable, provider-independent identity of one audio-room member."""

    external_id: str
    display_name: str
    agent_id: int | None
    is_ai: bool


@dataclass(frozen=True)
class AudioRoomSpeakers:
    """The local agent and remote participants attached to an audio room."""

    agent: AudioSpeakerIdentity | None
    participants: tuple[AudioSpeakerIdentity, ...]


def _audio_room_external_id(transport_kind: str, call_external_id: str) -> str:
    return f"{transport_kind}:call:{call_external_id}"[:512]


async def open_audio_room(
    *,
    connection_id: int,
    transport_kind: str,
    source_room_id: str,
    call_external_id: str,
    agent_id: int,
    participant_external_ids: tuple[str, ...],
    agent_display_name: str = "",
) -> UUID:
    """Create one distinct local audio room and synchronize its known members."""

    messenger = await get_messenger(connection_id)
    external_id = _audio_room_external_id(transport_kind, call_external_id)
    room_id = await resolve_messenger_room(
        connection_id=connection_id,
        external_id=external_id,
        label=f"{transport_kind} audio — {source_room_id}"[:500],
        kind="direct" if len(participant_external_ids) == 1 else "group",
        conversation_type=ConversationType.AUDIO,
    )
    user_ids: list[UUID] = []
    if messenger.self_id:
        user_ids.append(
            await resolve_observed_user(
                tool_id=messenger.tool_id,
                user=ObservedMessengerUser(
                    id=messenger.self_id,
                    display_name=agent_display_name,
                    agent_id=agent_id,
                    is_ai=True,
                    connection_id=connection_id,
                    tool_id=messenger.tool_id,
                ),
            )
        )
    for external_user_id in dict.fromkeys(participant_external_ids):
        normalized = external_user_id.strip()
        if not normalized or normalized == messenger.self_id:
            continue
        user_ids.append(
            await resolve_observed_user(
                tool_id=messenger.tool_id,
                user=ObservedMessengerUser(
                    id=normalized,
                    connection_id=connection_id,
                    tool_id=messenger.tool_id,
                ),
            )
        )
    await reconcile_room_users(
        room_id=room_id,
        user_ids=user_ids,
        authoritative=True,
    )
    return room_id


def _speaker_identity(user: MessengerUser) -> AudioSpeakerIdentity:
    return AudioSpeakerIdentity(
        external_id=user.external_id,
        display_name=user.display_name or user.external_id,
        agent_id=user.agent_id,
        is_ai=user.is_ai,
    )


async def get_audio_room_speakers(
    *,
    room_id: UUID,
    agent_id: int,
) -> AudioRoomSpeakers:
    """Return canonical names for prompt rendering and call monitoring."""

    _room, agent, _single_remote = await _room_identities(
        room_id=room_id,
        agent_id=agent_id,
    )
    members = list(
        (
            await get_db().scalars(
                select(MessengerUser)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(RoomUser.room_id == room_id)
                .execution_options(include_historized=True)
            )
        ).all()
    )
    participants = tuple(
        _speaker_identity(member)
        for member in members
        if member.id != getattr(agent, "id", None)
    )
    return AudioRoomSpeakers(
        agent=_speaker_identity(agent) if agent is not None else None,
        participants=participants,
    )


async def _room_identities(
    *,
    room_id: UUID,
    agent_id: int,
) -> tuple[Room, MessengerUser | None, MessengerUser | None]:
    room = await get_db().scalar(
        select(Room)
        .where(Room.id == room_id)
        .execution_options(include_historized=True)
    )
    if room is None:
        raise LookupError(f"Messenger audio room {room_id} not found.")
    members = list(
        (
            await get_db().scalars(
                select(MessengerUser)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(RoomUser.room_id == room_id)
                .execution_options(include_historized=True)
            )
        ).all()
    )
    agent = next((member for member in members if member.agent_id == agent_id), None)
    remote = [member for member in members if member.id != getattr(agent, "id", None)]
    return room, agent, remote[0] if len(remote) == 1 else None


def _observation_user(
    user: MessengerUser | None,
    *,
    connection_id: int,
) -> ObservedMessengerUser | None:
    if user is None:
        return None
    return ObservedMessengerUser(
        id=user.external_id,
        display_name=user.display_name,
        agent_id=user.agent_id,
        is_ai=user.is_ai,
        connection_id=connection_id,
        tool_id=user.tool_id,
    )


async def record_audio_message(
    *,
    connection_id: int,
    messenger_room_id: UUID,
    agent_id: int,
    external_identifier: str,
    role: VoiceMessageRole,
    text: str,
    occurred_at: datetime | None = None,
    contact_memory_item_id: UUID | None = None,
) -> Message:
    """Persist one voice utterance and return its local Messenger model."""

    from . import journal

    room, agent, remote = await _room_identities(
        room_id=messenger_room_id,
        agent_id=agent_id,
    )
    messenger = await get_messenger(connection_id)
    sender = remote if role == "input" else agent
    recipient = agent if role == "input" else remote
    observation = ObservedMessengerMessage(
        id=external_identifier[:512],
        platform=messenger.kind,
        tool_id=messenger.tool_id,
        sender=_observation_user(sender, connection_id=connection_id),
        recipient=_observation_user(recipient, connection_id=connection_id),
        room=ObservedMessengerRoom(
            id=room.external_id,
            local_id=room.id,
            label=room.label,
            kind="direct" if room.kind == "direct" else "group",
            conversation_type=cast(
                Literal["audio", "text"],
                room.conversation_type,
            ),
            connection_id=connection_id,
            tool_id=messenger.tool_id,
        ),
        text=text,
        time=int((occurred_at or datetime.now(timezone.utc)).timestamp()),
    )
    if role == "input":
        await journal.persist_inbound(
            observation,
            connection_id=connection_id,
            platform=messenger.kind,
        )
        direction = "inbound"
    else:
        await journal.persist_outbound(
            observation,
            connection_id=connection_id,
            platform=messenger.kind,
            status="delivered",
        )
        direction = "outbound"
    stored = await journal.stored_message(
        connection_id=connection_id,
        remote_message_id=observation.id,
        direction=direction,
    )
    if stored is None:
        raise RuntimeError("The audio message was not found after persistence.")
    if contact_memory_item_id is not None:
        await get_db().execute(
            update(Message)
            .where(Message.id == stored.id)
            .values(contact_memory_item_id=contact_memory_item_id)
        )
        stored.contact_memory_item_id = contact_memory_item_id
    from .events import message_journaled

    await message_journaled.send_async(stored)
    return stored


__all__ = [
    "AudioRoomSpeakers",
    "AudioSpeakerIdentity",
    "get_audio_room_speakers",
    "open_audio_room",
    "record_audio_message",
]
