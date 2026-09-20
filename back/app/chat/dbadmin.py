"""Permanent RBAC presentation data for Chat."""

from __future__ import annotations

import json
from typing import cast

from sqlalchemy import Table, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import Privilege, PrivilegeList, RolePrivilege
from core.dbadmin import (
    DbAdminAction,
    DbAdminDataSource,
    DbAdminDataset,
    DbAdminPhase,
    DbAdminRegistry,
    SchemaTransitionSet,
)
from core.params import Param, Params

from .privileges import (
    CHAT_ACCESS,
    CHAT_CALL,
    CHAT_IMPERSONATE,
    CHAT_MANAGE,
    CHAT_SEND,
)


PRIVILEGE_LIST_NAME = "Chat"
_PRIVILEGE_CODES = (
    "CHAT_ACCESS",
    "CHAT_CALL",
    "CHAT_IMPERSONATE",
    "CHAT_MANAGE",
    "CHAT_SEND",
)
_LEGACY_PRIVILEGE_CODES = {
    "INTERNAL_MESSENGER_ACCESS": "CHAT_ACCESS",
    "INTERNAL_MESSENGER_CALL": "CHAT_CALL",
    "INTERNAL_MESSENGER_MANAGE": "CHAT_MANAGE",
    "INTERNAL_MESSENGER_SEND": "CHAT_SEND",
}
_NATIVE_CHAT_TABLE = "chat_emoji_usages"
_NATIVE_CHAT_KIND = "internal"
_UNREAD_COLUMNS = frozenset(
    {
        "messenger_messages.journal_position",
        "messenger_messages.sender_messenger_user_id",
        "messenger_messages.counts_as_unread",
        "messenger_room_users.read_through_position",
    }
)


def _introduces_native_chat(transitions: SchemaTransitionSet) -> bool:
    return transitions.table_added(_NATIVE_CHAT_TABLE)


def _introduces_durable_unread_state(transitions: SchemaTransitionSet) -> bool:
    return bool(_UNREAD_COLUMNS.intersection(transitions.added_columns))


async def _baseline_durable_unread_state(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    """Backfill authors and baseline all pre-existing room history as read."""

    await session.execute(
        text(
            """
            UPDATE messenger_messages AS message
               SET sender_messenger_user_id = sender.id
              FROM messenger_users AS sender
             WHERE message.sender_messenger_user_id IS NULL
               AND message.tool_id = sender.tool_id
               AND NULLIF(message.metadata ->> 'sender_id', '') = sender.external_id
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE messenger_room_users AS membership
               SET read_through_position = latest.position
              FROM (
                    SELECT messenger_room_id AS room_id,
                           MAX(journal_position) AS position
                      FROM messenger_messages
                     WHERE messenger_room_id IS NOT NULL
                     GROUP BY messenger_room_id
                   ) AS latest
             WHERE membership.room_id = latest.room_id
               AND (
                    membership.read_through_position IS NULL
                    OR membership.read_through_position < latest.position
               )
            """
        )
    )


async def _durable_unread_state_is_baselined(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    pending = await session.scalar(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM messenger_room_users AS membership
                  JOIN (
                        SELECT messenger_room_id AS room_id,
                               MAX(journal_position) AS position
                          FROM messenger_messages
                         WHERE messenger_room_id IS NOT NULL
                         GROUP BY messenger_room_id
                       ) AS latest ON latest.room_id = membership.room_id
                 WHERE membership.read_through_position IS NULL
                    OR membership.read_through_position < latest.position
            )
            """
        )
    )
    return pending is False


def _enabled_messenger_channels(value: str | None) -> list[str]:
    if value is None:
        raise ValueError("MESSENGER_ENABLED_CHANNELS has no value")
    try:
        decoded: object = json.loads(value)
    except ValueError as exc:
        raise ValueError("MESSENGER_ENABLED_CHANNELS is not valid JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("MESSENGER_ENABLED_CHANNELS must be a JSON string array")
    items = cast(list[object], decoded)
    if not all(isinstance(item, str) for item in items):
        raise ValueError("MESSENGER_ENABLED_CHANNELS must be a JSON string array")
    return [item for item in items if isinstance(item, str)]


async def _enable_native_chat_channel(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    param = await session.get(Param, Params.MESSENGER_ENABLED_CHANNELS)
    if param is None:
        raise RuntimeError("DbAdmin could not resolve MESSENGER_ENABLED_CHANNELS")
    channels = _enabled_messenger_channels(param.value)
    if _NATIVE_CHAT_KIND not in channels:
        param.value = json.dumps(
            [_NATIVE_CHAT_KIND, *channels],
            separators=(",", ":"),
        )


async def _native_chat_channel_is_enabled(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    param = await session.get(Param, Params.MESSENGER_ENABLED_CHANNELS)
    return bool(
        param is not None
        and _NATIVE_CHAT_KIND in _enabled_messenger_channels(param.value)
    )


def _privilege_table_already_exists(transitions: SchemaTransitionSet) -> bool:
    return "privileges" not in transitions.added_tables


async def _migrate_legacy_grants(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    descriptions = {
        "CHAT_ACCESS": CHAT_ACCESS,
        "CHAT_CALL": CHAT_CALL,
        "CHAT_MANAGE": CHAT_MANAGE,
        "CHAT_SEND": CHAT_SEND,
    }
    for legacy_code, chat_code in _LEGACY_PRIVILEGE_CODES.items():
        chat_id = await session.scalar(
            pg_insert(Privilege)
            .values(code=chat_code, display_name=descriptions[chat_code])
            .on_conflict_do_update(
                index_elements=[Privilege.code],
                set_={"display_name": descriptions[chat_code]},
            )
            .returning(Privilege.id)
        )
        legacy_id = await session.scalar(
            select(Privilege.id).where(Privilege.code == legacy_code)
        )
        if legacy_id is None or chat_id is None:
            continue
        role_ids = tuple(
            (await session.scalars(
                select(RolePrivilege.role_id).where(
                    RolePrivilege.privilege_id == legacy_id
                )
            )).all()
        )
        if role_ids:
            await session.execute(
                pg_insert(RolePrivilege)
                .values(
                    [
                        {"role_id": role_id, "privilege_id": chat_id}
                        for role_id in role_ids
                    ]
                )
                .on_conflict_do_nothing()
            )


async def _legacy_grants_are_migrated(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    for legacy_code, chat_code in _LEGACY_PRIVILEGE_CODES.items():
        legacy_id = await session.scalar(
            select(Privilege.id).where(Privilege.code == legacy_code)
        )
        if legacy_id is None:
            continue
        chat_id = await session.scalar(
            select(Privilege.id).where(Privilege.code == chat_code)
        )
        if chat_id is None:
            return False
        legacy_roles = set(
            (await session.scalars(
                select(RolePrivilege.role_id).where(
                    RolePrivilege.privilege_id == legacy_id
                )
            )).all()
        )
        chat_roles = set(
            (await session.scalars(
                select(RolePrivilege.role_id).where(
                    RolePrivilege.privilege_id == chat_id
                )
            )).all()
        )
        if not legacy_roles <= chat_roles:
            return False
    return True

# Keep imports tied to the declared constants so a rename cannot silently leave
# this presentation dataset pointing at privileges that no longer exist.
assert all(
    value
    for value in (
        CHAT_ACCESS,
        CHAT_CALL,
        CHAT_IMPERSONATE,
        CHAT_MANAGE,
        CHAT_SEND,
    )
)


async def _privilege_group_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    list_id = await session.scalar(
        select(PrivilegeList.id).where(
            PrivilegeList.display_name == PRIVILEGE_LIST_NAME
        )
    )
    if list_id is None:
        raise RuntimeError("DbAdmin could not resolve the Chat privilege list")
    return tuple(
        {"code": code, "privilege_list_id": int(list_id)}
        for code in _PRIVILEGE_CODES
    )


def _datasets() -> tuple[DbAdminDataset, ...]:
    return (
        DbAdminDataset(
            key="app.chat.privilege_list",
            table=cast(Table, PrivilegeList.__table__),
            natural_key=("display_name",),
            rows=({"display_name": PRIVILEGE_LIST_NAME},),
            update_columns=(),
            depends_on=("core.authorize.privileges",),
        ),
        DbAdminDataset(
            key="app.chat.privilege_group",
            table=cast(Table, Privilege.__table__),
            natural_key=("code",),
            rows=_privilege_group_rows,
            update_columns=("privilege_list_id",),
            # Once an administrator moves a privilege, its organization is theirs.
            update_only_null=True,
            depends_on=(
                "app.chat.privilege_list",
                "core.authorize.privileges",
            ),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="app.chat", factory=_datasets)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.chat.baseline_durable_unread_state",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1-backfill-authors-and-baseline-existing-room-history",
            predicate=_introduces_durable_unread_state,
            handler=_baseline_durable_unread_state,
            postcondition=_durable_unread_state_is_baselined,
        )
    )
    registry.register_action(
        DbAdminAction(
            key="app.chat.migrate_internal_messenger_privilege_grants",
            phase=DbAdminPhase.BEFORE_EXPAND,
            checksum="v1-copy-four-legacy-grants",
            predicate=_privilege_table_already_exists,
            handler=_migrate_legacy_grants,
            postcondition=_legacy_grants_are_migrated,
        )
    )
    registry.register_action(
        DbAdminAction(
            key="app.chat.enable_native_channel_by_default",
            phase=DbAdminPhase.AFTER_DATASET,
            checksum="enable-internal-when-native-chat-is-introduced",
            predicate=_introduces_native_chat,
            handler=_enable_native_chat_channel,
            postcondition=_native_chat_channel_is_enabled,
        )
    )
    registry.register_data_source(DATA_SOURCE)
