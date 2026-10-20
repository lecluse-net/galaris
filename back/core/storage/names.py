"""Display names are metadata, never paths or file identities."""

import unicodedata
from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from core.database import get_db
from .models import StoredFile


async def registered_file_names(identities: Iterable[UUID]) -> dict[UUID, str]:
    """Read canonical names in a batch; callers authorize the referring resources."""
    ids = set(identities)
    if not ids:
        return {}
    return {identity: name for identity, name in await get_db().execute(
        select(StoredFile.id, StoredFile.name).where(StoredFile.id.in_(ids)))}


async def rename_stored_file(identity: UUID, name: str) -> None:
    """Rename one file after the calling domain has authorized the operation."""
    stored = await get_db().get(StoredFile, identity)
    if stored is None:
        raise FileNotFoundError(str(identity))
    stored.name = validate_file_name(name)


def validate_file_name(value: str) -> str:
    name = unicodedata.normalize("NFC", value).strip()
    if (not name or len(name) > 500 or name in {".", ".."}
        or any(char in name for char in ("/", "\\"))
        or any(unicodedata.category(char) == "Cc" for char in name)):
        raise ValueError("A file name must contain 1–500 characters without path separators or control characters")
    return name


class FileRename(BaseModel):
    name: str = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return validate_file_name(value)
