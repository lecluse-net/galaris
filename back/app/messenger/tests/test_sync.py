from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.messenger import journal
from app.messenger._observations import (
    ObservedMessengerFile as Attachment,
    ObservedMessengerMessage as Message,
    ObservedMessengerRoom as Room,
    ObservedMessengerUser as User,
)
from app.messenger.models import (
    File as FileModel,
    Attachment as AttachmentModel,
    Message as MessageModel,
    Room as RoomModel,
    RoomUser,
    MessengerUser,
)
from app.messenger.room_service import synchronize_rooms
from app.messenger.user_service import synchronize_users
from app.tools.models import Tool


async def _connection(db: AsyncSession) -> Connection:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Title {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Bridge",
        last_name="Sync",
        code=f"bridge-sync-{suffix}",
        agent_driver="internal",
    )
    tool = Tool(
        code=f"messenger-sync-{suffix}",
        label="Messenger sync test",
        description="",
        connection_schema={},
    )
    db.add_all([agent, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    return connection


async def _all_users(db: AsyncSession, tool_id: int) -> list[MessengerUser]:
    db.expire_all()
    return list(
        (
            await db.scalars(
                select(MessengerUser)
                .where(MessengerUser.tool_id == tool_id)
                .execution_options(include_historized=True)
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_filtered_user_sync_never_historizes_out_of_scope_users(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    users = [User(id="alice"), User(id="bob")]

    await synchronize_users(tool_id=connection.tool_id, users=users)
    await synchronize_users(
        tool_id=connection.tool_id,
        users=[User(id="alice")],
        authoritative=False,
    )

    rows = await _all_users(db, connection.tool_id)
    assert {row.external_id for row in rows if row.deleted_at is None} == {
        "alice",
        "bob",
    }


@pytest.mark.asyncio
async def test_complete_user_sync_historizes_and_later_restores_missing_user(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    tool_id = connection.tool_id
    await synchronize_users(
        tool_id=tool_id,
        users=[User(id="alice"), User(id="bob")],
        authoritative=True,
    )

    await synchronize_users(
        tool_id=tool_id,
        users=[User(id="alice")],
        authoritative=True,
    )
    rows = await _all_users(db, tool_id)
    bob = next(row for row in rows if row.external_id == "bob")
    assert bob.deleted_at is not None
    assert bob.deleted_by is None

    restored = await synchronize_users(
        tool_id=tool_id,
        users=[User(id="bob", display_name="Bob restored")],
        authoritative=False,
    )
    assert len(restored) == 1
    assert restored[0].id == bob.id
    rows = await _all_users(db, tool_id)
    bob = next(row for row in rows if row.external_id == "bob")
    assert bob.deleted_at is None
    assert bob.display_name == "Bob restored"


@pytest.mark.asyncio
async def test_room_membership_is_reconciled_only_from_a_complete_member_list(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    connection_id = connection.id
    tool_id = connection.tool_id
    room = Room(
        id="room-1",
        users=[User(id="alice"), User(id="bob")],
        users_complete=True,
    )
    stored = await synchronize_rooms(
        connection_id=connection_id,
        tool_id=tool_id,
        rooms=[room],
    )
    room_uuid = stored[0].id
    assert (
        await db.scalar(
            select(func.count(RoomUser.user_id)).where(
                RoomUser.room_id == room_uuid
            )
        )
    ) == 2

    partial = room.model_copy(
        update={"users": [User(id="alice")], "users_complete": False}
    )
    stored = await synchronize_rooms(
        connection_id=connection_id,
        tool_id=tool_id,
        rooms=[partial],
    )
    assert (
        await db.scalar(
            select(func.count(RoomUser.user_id)).where(
                RoomUser.room_id == room_uuid
            )
        )
    ) == 2

    complete = partial.model_copy(update={"users_complete": True})
    stored = await synchronize_rooms(
        connection_id=connection_id,
        tool_id=tool_id,
        rooms=[complete],
    )
    assert (
        await db.scalar(
            select(func.count(RoomUser.user_id)).where(
                RoomUser.room_id == room_uuid
            )
        )
    ) == 1
    db.expire_all()
    assert (
        await db.scalar(select(func.count(RoomUser.room_id)))
    ) == 1
    assert (
        await db.scalar(
            select(func.count(MessengerUser.id)).where(
                MessengerUser.tool_id == tool_id
            )
        )
    ) == 2


@pytest.mark.asyncio
async def test_limited_message_import_is_idempotent_and_never_historizes_absences(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    connection_id = connection.id
    tool_id = connection.tool_id
    messages = [
        Message(
            id="message-1",
            platform="telegram",
            sender=User(id="alice", display_name="Alice"),
            recipient=User(id="bot", is_ai=True),
            room=Room(id="room-1"),
            text="bonjour",
            attachments=[
                Attachment(
                    id="provider-file-1",
                    name="preuve.pdf",
                    mime="application/pdf",
                    size=1234,
                    kind="document",
                    text="must never be persisted",
                )
            ],
            time=100,
        ),
        Message(
            id="message-2",
            platform="telegram",
            sender=User(id="alice", display_name="Alice"),
            recipient=User(id="bot", is_ai=True),
            room=Room(id="room-1"),
            text="encore",
            attachments=[
                Attachment(
                    id="provider-file-1",
                    name="preuve.pdf",
                    mime="application/pdf",
                    size=1234,
                    kind="document",
                    text="must never be persisted",
                )
            ],
            time=101,
        ),
    ]

    first = await journal.synchronize_messages(
        connection_id=connection_id,
        tool_id=tool_id,
        self_id="bot",
        messages=messages,
    )
    second = await journal.synchronize_messages(
        connection_id=connection_id,
        tool_id=tool_id,
        self_id="bot",
        messages=messages[-1:],
    )

    assert all(message.id is not None for message in first)
    assert all(message.files[0].id is not None for message in first)
    assert first[0].files[0].id == first[1].files[0].id
    assert second[0].id == first[1].id
    assert all(message.counts_as_unread is False for message in first)
    db.expire_all()
    assert (
        await db.scalar(
            select(func.count(MessageModel.id)).where(
                MessageModel.connection_id == connection_id
            )
        )
    ) == 2
    assert (
        await db.scalar(
            select(func.count(MessageModel.id)).where(
                MessageModel.deleted_at.is_not(None)
            )
        )
    ) == 0
    room = await db.scalar(
        select(RoomModel).where(RoomModel.connection_id == connection_id)
    )
    assert room is not None
    files = list((await db.scalars(select(FileModel))).all())
    assert len(files) == 1
    assert files[0].external_identifier == "provider-file-1"
    assert (
        await db.scalar(select(func.count(AttachmentModel.message_id)))
    ) == 2
