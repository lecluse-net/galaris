"""Resource-independent sharing contracts."""

from typing import Literal

from pydantic import BaseModel, Field

PrincipalKind = Literal["agent", "user", "team"]
ShareKind = Literal["document", "dataset", "process"]


class Collaborator(BaseModel):
    kind: PrincipalKind
    id: int = Field(gt=0)
    label: str
    can_write: bool = False
    group_ids: list[int] = Field(default_factory=list[int])
    avatar_url: str | None = None
    has_avatar: bool = False


class SharingState(BaseModel):
    lock_version: int
    can_manage: bool
    grants: list[Collaborator]
    options: list[Collaborator]
    level: Literal["private", "groups", "public"]
    can_write: bool
    owner: Collaborator | None
    owner_groups: list[Collaborator]


class GrantUpdate(BaseModel):
    kind: PrincipalKind
    id: int = Field(gt=0)
    can_write: bool = False


class SharingUpdate(BaseModel):
    level: Literal["private", "groups", "public"]
    can_write: bool = False
    grants: list[GrantUpdate]
    expected_lock_version: int = Field(ge=1)


class SingleGrantUpdate(BaseModel):
    kind: PrincipalKind
    id: int = Field(gt=0)
    can_write: bool | None
    expected_lock_version: int = Field(ge=1)


class SharingConflictError(ValueError):
    pass
