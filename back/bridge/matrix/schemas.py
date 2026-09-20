"""Validated Matrix connection settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


def parse_matrix_id_set(raw: str) -> frozenset[str]:
    """Parse comma, semicolon, newline, or whitespace-separated Matrix IDs."""

    values: set[str] = set()
    for item in raw.replace(";", ",").replace("\n", ",").split(","):
        values.update(token for token in item.split() if token)
    return frozenset(values)


class MatrixConnectionConfig(BaseModel):
    """Per-agent Matrix identity and access policy."""

    user_id: str = Field(min_length=1)
    access_token: str = ""
    password: str = ""
    allowed_user_ids: str = ""
    allowed_room_ids: str = ""
    require_group_mention: bool = False
    auto_join_invites: bool = False
    model_config = ConfigDict(extra="ignore")

    @property
    def users(self) -> frozenset[str]:
        return parse_matrix_id_set(self.allowed_user_ids)

    @property
    def rooms(self) -> frozenset[str]:
        return parse_matrix_id_set(self.allowed_room_ids)
