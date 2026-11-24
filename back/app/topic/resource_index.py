"""Conservative reuse of existing thematic dossiers for indexed files."""

import re
from uuid import UUID

from sqlalchemy import select

from core.database import get_db

from .models import Topic


def _words(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


async def match_indexed_topic(text: str) -> UUID | None:
    normalized = f" {_words(text)} "
    matches: list[UUID] = []
    rows = await get_db().execute(select(Topic.id, Topic.title).where(Topic.deleted_at.is_(None)))
    for identity, title in rows:
        phrase = _words(title)
        if len(phrase) >= 5 and f" {phrase} " in normalized:
            matches.append(identity)
    return matches[0] if len(matches) == 1 else None
