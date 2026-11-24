"""Recognize requests whose subject is the current human, using lexical cues only."""

import re
from typing import Literal

from .relevance import fold


PersonalRecordKind = Literal["health", "record"]
_POSSESSIVE = r"\b(?:mon|ma|mes|my)\s+(?:(?:tout(?:e)?s?|dernier(?:e)?s?|latest|most recent|recent(?:e)?s?|last|previous|propre(?:s)?|own)\s+)*"
_HEALTH_TERMS = (r"(?:prises? (?:de )?sang|bilans? sanguins?|analyses? (?:de sang|sanguines?|medicales?)|"
                 r"dossiers? medicaux|dossier medical|resultats? (?:sanguins?|medicaux)|"
                 r"blood (?:test|work)s?|medical (?:reports?|records?|results?)|lab (?:reports?|results?))\b")
_RECORD_TERMS = (r"(?:factures?|devis|invoices?|quotes?|bulletins? de paie|payslips?|"
                 r"releves? bancaires?|bank statements?|avis d['’]imposition|tax returns?)\b")
_HEALTH = re.compile(_POSSESSIVE + _HEALTH_TERMS)
_RECORD = re.compile(_POSSESSIVE + _RECORD_TERMS)
_RELATED_TERMS = {"health": re.compile(r"\b" + _HEALTH_TERMS), "record": re.compile(r"\b" + _RECORD_TERMS)}


def personal_record_kind(query: str) -> PersonalRecordKind | None:
    """Identify first-person requests; the caller resolves the speaker separately."""
    text = fold(query)
    if _HEALTH.search(text):
        return "health"
    return "record" if _RECORD.search(text) else None


def personal_record_for_turn(query: str, *, agent_id: int, turn: object | None) -> PersonalRecordKind | None:
    """Keep first-person scope when a tool reformulates the current human request."""
    explicit = personal_record_kind(query)
    if explicit is not None or getattr(turn, "agent_id", None) != agent_id:
        return explicit
    objective = getattr(turn, "objective", None)
    context = personal_record_kind(objective) if isinstance(objective, str) else None
    return context if context is not None and _RELATED_TERMS[context].search(fold(query)) else None
