"""Account-scoped help acknowledgements; no reset or replacement operation."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db
from .models import UserHelpDismissal


async def list_dismissed(user_id: int) -> list[str]:
    result = await get_db().scalars(
        select(UserHelpDismissal.help_key)
        .where(UserHelpDismissal.user_id == user_id)
        .order_by(UserHelpDismissal.help_key)
    )
    return list(result)


async def dismiss(user_id: int, help_key: str) -> None:
    db = get_db()
    await db.execute(
        insert(UserHelpDismissal)
        .values(user_id=user_id, help_key=help_key)
        .on_conflict_do_nothing(index_elements=["user_id", "help_key"])
    )
    await db.commit()
