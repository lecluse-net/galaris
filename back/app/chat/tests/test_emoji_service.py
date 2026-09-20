from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.emoji_service import list_frequent_emojis, record_emoji_use
from app.chat.models import ChatEmojiUsage
from core.user import UserModel as User


def _user(email: str) -> User:
    return User(
        email=email,
        display_name=email,
        hashed_password="unused",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_frequent_emojis_are_ranked_and_isolated_per_user(
    db: AsyncSession,
) -> None:
    first = _user("emoji-first@example.test")
    second = _user("emoji-second@example.test")
    db.add_all([first, second])
    await db.flush()

    await record_emoji_use(first.id, "😀")
    await record_emoji_use(first.id, "🚀")
    await record_emoji_use(first.id, "😀")
    await record_emoji_use(second.id, "🚀")

    assert await list_frequent_emojis(first.id) == ("😀", "🚀")
    assert await list_frequent_emojis(second.id) == ("🚀",)


@pytest.mark.asyncio
async def test_emoji_usage_rejects_arbitrary_text(db: AsyncSession) -> None:
    user = _user("emoji-invalid@example.test")
    db.add(user)
    await db.flush()

    with pytest.raises(ValueError, match="Invalid emoji"):
        await record_emoji_use(user.id, "not-an-emoji")


@pytest.mark.asyncio
async def test_frequent_emoji_list_is_limited_to_twenty_five(
    db: AsyncSession,
) -> None:
    user = _user("emoji-limit@example.test")
    db.add(user)
    await db.flush()
    emojis = [chr(0x1F600 + index) for index in range(30)]
    db.add_all(
        [
            ChatEmojiUsage(
                user_id=user.id,
                emoji=emoji,
                usage_count=index + 1,
            )
            for index, emoji in enumerate(emojis)
        ]
    )
    await db.flush()

    result = await list_frequent_emojis(user.id)

    assert len(result) == 25
    assert result == tuple(reversed(emojis[5:]))
