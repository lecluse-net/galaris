"""WhatsApp Cloud connection and webhook schemas."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def normalize_phone(value: str) -> str:
    """Normalize a WhatsApp identifier to digits without logging or guessing a country."""
    return re.sub(r"\D", "", value or "")


def parse_phone_set(raw: str) -> set[str]:
    phones: set[str] = set()
    for item in raw.replace(";", ",").replace("\n", ",").split(","):
        normalized = normalize_phone(item)
        if normalized:
            phones.add(normalized)
    return phones


class WhatsAppConnectionConfig(BaseModel):
    access_token: str = Field(min_length=1)
    phone_number_id: str = Field(min_length=1)
    business_account_id: str = ""
    allowed_phone_numbers: str = ""
    template_name: str = ""
    template_language: str = "en_US"

    model_config = ConfigDict(extra="ignore")

    @property
    def allowed_phones(self) -> set[str]:
        return parse_phone_set(self.allowed_phone_numbers)


class WhatsAppChange(BaseModel):
    field: str = ""
    value: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class WhatsAppEntry(BaseModel):
    id: str = ""
    changes: list[WhatsAppChange] = Field(default_factory=lambda: [])

    model_config = ConfigDict(extra="ignore")


class WhatsAppWebhook(BaseModel):
    object: str = ""
    entry: list[WhatsAppEntry] = Field(default_factory=lambda: [])

    model_config = ConfigDict(extra="ignore")
