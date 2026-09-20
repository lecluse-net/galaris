"""Validated Telegram connection settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


def parse_id_set(raw: str) -> set[int]:
    """Parse a comma/space separated set of signed Telegram identifiers."""
    values: set[int] = set()
    for item in raw.replace(";", ",").replace("\n", ",").split(","):
        for token in item.split():
            try:
                values.add(int(token))
            except ValueError as exc:
                raise ValueError(f"Invalid Telegram identifier: {token}") from exc
    return values


class TelegramConnectionConfig(BaseModel):
    bot_token: str = Field(min_length=1)
    allowed_user_ids: str = ""
    allowed_chat_ids: str = ""
    require_group_mention: bool = True
    model_config = ConfigDict(extra="ignore")

    @property
    def users(self) -> set[int]:
        return parse_id_set(self.allowed_user_ids)

    @property
    def chats(self) -> set[int]:
        return parse_id_set(self.allowed_chat_ids)
