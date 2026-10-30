"""Offline country lookup for a free-form application location."""

from collections.abc import Mapping
from functools import lru_cache
import re
from typing import cast
import unicodedata

from babel import Locale


def _key(value: str) -> str:
    return " ".join("".join(char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)).split())


@lru_cache(maxsize=1)
def _country_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {"uk": "GB", "usa": "US"}
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
    """Use an explicit country component, never a city, language or timezone."""
    parts = re.split(r"[,，;；()/\n]", localization[:2000])
    for part in reversed(parts):
        if country := _country_aliases().get(_key(part)):
            return country
    return ""
