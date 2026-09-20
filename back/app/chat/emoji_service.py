"""Per-user frequently used emoji projection."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_db

from .models import ChatEmojiUsage


FREQUENT_EMOJI_LIMIT = 25
_MAX_EMOJI_LENGTH = 64
_EMOJI_SINGLE_CODEPOINTS = {
    0x00A9,
    0x00AE,
    0x203C,
    0x2049,
    0x20E3,
    0x2122,
    0x2139,
    0x3030,
    0x303D,
    0x3297,
    0x3299,
}


def _contains_emoji_codepoint(value: str) -> bool:
    for character in value:
        codepoint = ord(character)
        if (
            codepoint in _EMOJI_SINGLE_CODEPOINTS
            or 0x2190 <= codepoint <= 0x23FF
            or 0x25A0 <= codepoint <= 0x27BF
            or 0x2B00 <= codepoint <= 0x2BFF
            or 0x1F000 <= codepoint <= 0x1FAFF
        ):
            return True
    return False


def _normalize_emoji(value: str) -> str:
    emoji = value.strip()
    if (
        not emoji
        or emoji != value
        or len(emoji) > _MAX_EMOJI_LENGTH
        or any(character.isspace() for character in emoji)
        or not _contains_emoji_codepoint(emoji)
    ):
        raise ValueError("Invalid emoji.")
    return emoji


async def list_frequent_emojis(user_id: int) -> tuple[str, ...]:
    rows = await get_db().scalars(
        select(ChatEmojiUsage.emoji)
        .where(ChatEmojiUsage.user_id == user_id)
        .order_by(
            ChatEmojiUsage.usage_count.desc(),
            ChatEmojiUsage.last_used_at.desc(),
            ChatEmojiUsage.emoji.asc(),
        )
        .limit(FREQUENT_EMOJI_LIMIT)
    )
    return tuple(rows.all())


async def record_emoji_use(user_id: int, value: str) -> tuple[str, ...]:
    emoji = _normalize_emoji(value)
    statement = (
        pg_insert(ChatEmojiUsage)
        .values(user_id=user_id, emoji=emoji, usage_count=1)
        .on_conflict_do_update(
            constraint="uq_chat_emoji_usage_user_emoji",
            set_={
                "usage_count": ChatEmojiUsage.usage_count + 1,
                "last_used_at": func.now(),
            },
        )
    )
    await get_db().execute(statement)
    await get_db().commit()
    return await list_frequent_emojis(user_id)


__all__ = [
    "FREQUENT_EMOJI_LIMIT",
    "list_frequent_emojis",
    "record_emoji_use",
]
