"""Recognize literal business identifiers and a small vocabulary of requested fields."""

from dataclasses import dataclass
import re

from .relevance import fold


_OPERATORS = re.compile(r'["«»“”]|\bOR\b|(?:^|\s)-', re.IGNORECASE)
_IDENTIFIER = re.compile(r"(?<![\w/-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![\w/-]|\.[0-9])")
_FIELDS = (
    ((("when", "due"), ("deadline",), ("quand faut il regler",), ("quand faut il payer",)),
     ("echeance", "echeances", "date limite de paiement", "date limite",
      "due date", "payment deadline", "a regler avant", "a payer avant", "payable avant", "payment due", "pay by")),
    ((("how much",), ("combien dois je payer",), ("combien faut il payer",)),
     ("montant", "montants", "total", "totaux", "amount", "amounts", "grand total", "amount due",
      "net a payer", "total ttc", "montant total")),
)


@dataclass(frozen=True, slots=True)
class ReferenceQuestion:
    references: tuple[str, ...]
    fields: tuple[str, ...]

    def matches_reference(self, text: str) -> bool:
        return any(reference in self.references for reference in _IDENTIFIER.findall(fold(text)))

    def has_evidence(self, title: str, passages: tuple[str, ...]) -> bool:
        return (any(self.matches_reference(text) for text in (title, *passages))
                and any(_contains_field(text, self.fields) for text in passages))


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[^\W_]+", fold(text))) + " "


def _contains_field(text: str, aliases: tuple[str, ...]) -> bool:
    words = _words(text)
    return any(f" {alias} " in words for alias in aliases)


def parse_reference_question(query: str) -> ReferenceQuestion | None:
    """Leave raw search operators to the lexical parser."""
    if not 1 <= len(query) <= 8_000 or _OPERATORS.search(query):
        return None
    references = tuple(dict.fromkeys(code for code in _IDENTIFIER.findall(fold(query))
                                    if len(code) <= 48 and any(char.isdigit() for char in code)))
    if not 1 <= len(references) <= 8:
        return None
    words = _words(query)
    aliases = tuple(alias for cues, fields in _FIELDS
                    if any(f" {field} " in words for field in fields)
                    or any(all(f" {part} " in words for part in cue) for cue in cues)
                    for alias in fields)
    return ReferenceQuestion(references, tuple(dict.fromkeys(aliases))) if aliases else None
