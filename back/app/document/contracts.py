"""Public documentary values; storage engines and graph indexes are adapters."""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class DocumentAccess:
    can_read: bool
    can_write: bool

from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

@dataclass(frozen=True, slots=True)
class DatasetDocumentGrant:
    """One Dataset-owned grant mirrored for historical document readers."""

    agent_id: int | None
    user_id: int | None
    team_id: int | None
    can_write: bool


@dataclass(frozen=True, slots=True)
class DatasetDocumentProjection:
    """Metadata for an existing legacy alias; never Dataset content or history."""

    title: str
    revision: int
    lock_version: int
    content_hash: str
    size_bytes: int
    owner_agent_id: int | None
    owner_user_id: int | None
    global_access: int
    group_access: int
    read_only: bool
    keywords: tuple[str, ...]
    metadata: Mapping[str, object]
    grants: tuple[DatasetDocumentGrant, ...]


# None retires an existing projection; it never deletes migration evidence.
DatasetProjectionWriter = Callable[[UUID, DatasetDocumentProjection | None], Awaitable[None]]
