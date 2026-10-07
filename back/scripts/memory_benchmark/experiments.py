"""Predeclared experimental query plans, using only message/history/clock inputs.

These rules are benchmark prototypes, not changes to the production memory engine.
No answers, scenario labels or catalogue names enter this module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


VARIANTS = ("baseline", "relevance_first", "history", "entities", "time", "combined", "previous")
_PROPER = re.compile(r"\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:[-’'][A-Za-zÀ-ÖØ-öø-ÿ]+)?(?:\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+){0,3}")
_NON_ENTITY = frozenset("""
avant autre before c can cela comment concerning concernant correction could dans de do does donne et find for hier how il in
je le la les même new nous on pour quel quelle quels quelles qu qui rappelle remind
reprenons retrouve the tiens tu un une what where who yesterday you
""".split())
_SWITCH = ("autre sujet", "on change de", "new topic", "change files")


def fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def entity_phrases(message: str, history: tuple[str, ...], *, limit: int = 2) -> tuple[str, ...]:
    values: list[str] = []
    for text in (message, *reversed(history[-2:])):
        for match in _PROPER.finditer(text):
            phrase = match.group(0).strip()
            words = phrase.split()
            while words and fold(words[0]) in _NON_ENTITY:
                words.pop(0)
            phrase = " ".join(words)
            if phrase and fold(phrase) not in {fold(v) for v in values}:
                values.append(phrase)
    return tuple(values[:limit])


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def dates(self) -> tuple[str, ...]:
        days = (self.end.date() - self.start.date()).days
        return tuple((self.start + timedelta(days=i)).date().isoformat() for i in range(days))


def relative_window(message: str, timestamp: str, timezone: str) -> Window | None:
    now = datetime.fromisoformat(timestamp).astimezone(ZoneInfo(timezone))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    text = fold(message)
    if re.search(r"\bhier\b|\byesterday\b", text):
        return Window(midnight - timedelta(days=1), midnight)
    if "semaine derniere" in text or "last week" in text:
        end = midnight - timedelta(days=midnight.weekday())
        return Window(end - timedelta(days=7), end)
    if "apres-demain" in text or "day after tomorrow" in text:
        start = midnight + timedelta(days=2)
        return Window(start, start + timedelta(days=1))
    return None


@dataclass(frozen=True)
class Plan:
    lexical: str
    entities: tuple[str, ...]
    window: Window | None
    relevant_first: bool


def plan(variant: str, *, message: str, history: tuple[str, ...], timestamp: str,
         timezone: str, baseline_query: str) -> Plan:
    if variant not in VARIANTS:
        raise ValueError("Unknown experiment variant")
    switched = any(marker in fold(message) for marker in _SWITCH)
    useful_history = () if switched else history[-2:]
    lexical = baseline_query
    if variant in ("history", "combined") and useful_history:
        lexical = " ".join((baseline_query, *useful_history))[:600]
    entities = entity_phrases(message, useful_history) if variant in ("entities", "combined") else ()
    window = relative_window(message, timestamp, timezone) if variant in ("time", "combined") else None
    return Plan(lexical, entities, window, variant not in ("baseline", "previous"))
