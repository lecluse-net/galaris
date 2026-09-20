from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.dbadmin import (
    DATA_SOURCE,
    PRIVILEGE_LIST_NAME,
    _enable_native_chat_channel,
    _introduces_native_chat,
    _native_chat_channel_is_enabled,
    _introduces_durable_unread_state,
)
from core.authorize import Privilege, PrivilegeList
from core.dbadmin import SchemaTransitionSet, reconcile_dataset
from core.params import Param, Params


def test_native_chat_activation_is_tied_to_its_schema_introduction() -> None:
    assert _introduces_native_chat(
        SchemaTransitionSet(added_tables=frozenset({"chat_emoji_usages"}))
    )
    assert not _introduces_native_chat(SchemaTransitionSet())


def test_unread_baseline_is_tied_to_the_new_cursor_columns() -> None:
    assert _introduces_durable_unread_state(
        SchemaTransitionSet(
            added_columns=frozenset(
                {"messenger_room_users.read_through_position"}
            )
        )
    )
    assert not _introduces_durable_unread_state(SchemaTransitionSet())


@pytest.mark.asyncio
async def test_dbadmin_enables_native_chat_without_overwriting_other_channels(
    db: AsyncSession,
) -> None:
    param = await db.get(Param, Params.MESSENGER_ENABLED_CHANNELS)
    if param is None:
        param = Param(
            name=Params.MESSENGER_ENABLED_CHANNELS,
            value='["matrix","telegram"]',
        )
        db.add(param)
    else:
        param.value = '["matrix","telegram"]'
    await db.flush()

    transitions = SchemaTransitionSet(
        added_tables=frozenset({"chat_emoji_usages"})
    )
    assert not await _native_chat_channel_is_enabled(db, transitions)

    await _enable_native_chat_channel(db, transitions)
    await _enable_native_chat_channel(db, transitions)
    await db.flush()

    assert param.value == '["internal","matrix","telegram"]'
    assert await _native_chat_channel_is_enabled(db, transitions)


@pytest.mark.asyncio
async def test_dbadmin_groups_chat_privileges_without_overwriting(
    db: AsyncSession,
) -> None:
    list_dataset, group_dataset = DATA_SOURCE.compile()
    await reconcile_dataset(db, list_dataset)
    await reconcile_dataset(db, group_dataset)
    await db.flush()

    privilege_list = await db.scalar(
        select(PrivilegeList).where(
            PrivilegeList.display_name == PRIVILEGE_LIST_NAME
        )
    )
    assert privilege_list is not None
    rows = (
        await db.execute(
            select(Privilege.code, Privilege.privilege_list_id)
            .where(Privilege.code.like("CHAT_%"))
            .order_by(Privilege.code)
        )
    ).all()
    assert [code for code, _list_id in rows] == [
        "CHAT_ACCESS",
        "CHAT_CALL",
        "CHAT_IMPERSONATE",
        "CHAT_MANAGE",
        "CHAT_SEND",
    ]
    assert {list_id for _code, list_id in rows} == {privilege_list.id}

    other_list = PrivilegeList(display_name="Administrator choice")
    db.add(other_list)
    await db.flush()
    privilege = await db.scalar(
        select(Privilege).where(Privilege.code == "CHAT_ACCESS")
    )
    assert privilege is not None
    privilege.privilege_list_id = other_list.id
    await db.flush()

    await reconcile_dataset(db, group_dataset)
    await db.flush()
    assert privilege.privilege_list_id == other_list.id
