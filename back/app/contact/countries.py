"""Resolve an explicit country in the application's free-form location, offline."""

from __future__ import annotations

from functools import lru_cache
from collections.abc import Mapping
import re
import unicodedata
from typing import cast

from babel import Locale

from app.memory import ContactCoordinates
from core.params import runtime_settings


def _key(value: str) -> str:
    return " ".join("".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    ).split())


@lru_cache(maxsize=1)
def _country_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for language in ("en", "fr", "zh"):
        territories = cast(Mapping[str, object], Locale(language).territories)
        for code, name in territories.items():
            if len(code) != 2 or code in {"EU", "EZ", "UN", "ZZ", "QO"}:
                continue
            if isinstance(name, str):
                aliases[_key(name)] = code
            aliases[code.casefold()] = code
    return aliases


def country_from_localization(localization: str) -> str:
    """Match a country name/code or a separate component; never guess from a city."""
    aliases = _country_aliases()
    parts = re.split(r"[,，;；()/\n]", localization[:2000])
    for part in reversed(parts):
        if country := aliases.get(_key(part)):
            return country
    return ""


def default_country() -> str:
    return country_from_localization(runtime_settings.LOCALIZATION)


def apply_country_defaults(coordinates: ContactCoordinates | None) -> ContactCoordinates | None:
    if coordinates is None:
        return None
    country = default_country()
    return ContactCoordinates(
        phone_numbers=[phone.model_copy(update={"country": country})
            if "country" not in phone.model_fields_set else phone for phone in coordinates.phone_numbers],
        postal_addresses=[address.model_copy(update={"country": country})
            if "country" not in address.model_fields_set else address for address in coordinates.postal_addresses],
    )
