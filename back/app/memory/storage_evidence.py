"""Passages assigning a storage location to the object named by a question."""

import re
from dataclasses import dataclass

from .relevance import fold, terms


_EN_ACTION = r"(?:stor(?:e|ed)|keep|kept|fil(?:e|ed)|archiv(?:e|ed)|collect(?:ed)?|hous(?:e|ed))"
_FR_ACTION = r"(?:stock|rang|class|archiv|conserv|rassembl)(?:e|es|ee|ees|ent|ons|ez|er)"
_OBJECT = r"(?P<object>[\w'’ -]{1,100}?)"
_REQUESTS = tuple(re.compile(r"\b" + pattern + "$") for pattern in (
    r"where (?:is|are) " + _OBJECT + " " + _EN_ACTION,
    r"where (?:do|should|can) (?:we|i|you) " + _EN_ACTION + " " + _OBJECT,
    r"ou (?:sont|est) " + _FR_ACTION + " " + _OBJECT,
    r"ou (?:sont|est) " + _OBJECT + " " + _FR_ACTION,
    r"ou " + _FR_ACTION + r"(?:-t)?-on " + _OBJECT,
    r"(?:rangement|stockage|archivage|classement) (?:de |des |du |d['’])" + _OBJECT,
    r"(?:filing|archiving|storage of) " + _OBJECT,
))
_DEST = r"(?:in(?:to)?|inside|under|on|at|behind|dans|sous|sur|derriere|au|aux|chez)\s+\S+"
_PLACEMENT = tuple(re.compile(pattern) for pattern in (
    # Passive assignments and simple locations ("the samples are in the tray").
    _OBJECT + r"\s+(?:are|is|sont|est)\s+(?:(?:" + _EN_ACTION + "|" + _FR_ACTION + r")\s+)?" + _DEST,
    # Active instructions ("keep the samples in the tray").
    r"^\s*(?:(?:we|i|nous|on)\s+)?(?:" + _EN_ACTION + "|" + _FR_ACTION + r")\s+" + _OBJECT + r"\s+" + _DEST,
))
_UNASSERTED = re.compile(
    r"\b(?:if|whether|unless|maybe|perhaps|might|could|not|never|formerly|previously|without|no longer|"
    r"si|peut-etre|pourrait|pas|plus|jamais|anciennement|autrefois|sans)\b|[«»“”\"]"
)
_LOCATION_FIELD = re.compile(r"^(?:emplacement|lieu de stockage|storage location|location)\s*[:=]\s*\S+")
_CLAUSE_BREAK = re.compile(r"\s*(?:,|:)\s*|\s+(?:and|but|et|mais)\s+", re.I)
_NOMINAL_PREFIX = re.compile(
    r"(?:(?:find|show|open|read|locate|retrieve|retrouve|cherche|ouvre|lis|montre)(?:-moi)?\s+)?"
    r"(?:(?:the|a|an|le|la|les|une?|about|on|for|sur|concernant|pour)\s+)*"
)


@dataclass(frozen=True, slots=True)
class StorageLookup:
    subject: frozenset[str]

    def passage(self, title: str, body: str) -> str:
        heading_matches = self.subject == frozenset(terms(title))
        # Periods in paths, filenames and version numbers are part of the answer.
        for fragment in re.split(r"(?<=[.!?])\s+|[;\n]+", body[:8000]):
            sentence = fragment.strip()
            folded = fold(sentence)
            if sentence.endswith("?") or _UNASSERTED.search(folded):
                continue
            if heading_matches and _LOCATION_FIELD.match(folded):
                return sentence
            # A project introduction or an adjacent clause cannot supply the
            # object of a different assignment.
            delimiters = list(_CLAUSE_BREAK.finditer(sentence))
            starts = [0, *(m.end() for m in delimiters)]
            ends = [*(m.start() for m in delimiters), len(sentence)]
            found_assignment = False
            answer_start = None
            for index, (start, end) in enumerate(zip(starts, ends, strict=True)):
                clause = fold(sentence[start:end])
                objects = [terms(m["object"]) for pattern in _PLACEMENT if (m := pattern.search(clause))]
                if not objects:
                    continue
                if answer_start is not None:
                    return sentence[answer_start:ends[index - 1]].strip()
                if any(self.subject == frozenset(words) for words in objects):
                    answer_start = start if found_assignment else 0
                found_assignment = True
            if answer_start is not None:
                return sentence[answer_start:].strip()
        return ""


def storage_lookup(query: str, *, direct: bool = False) -> StorageLookup | None:
    # Source-language parsing can leave a dangling "according to" after a
    # passive question. Strip attribution only at the end of the request.
    text = re.sub(r"\s+(?:according to|selon|d['’]apres|(?:decrites?|described) (?:dans|in))(?: (?:la|le|the))?$",
                  "", fold(query).strip(" ?.!,\n"))
    if (re.search(r"\b(?:et|and|or|but|mais|without|sans|instead|plutot|not|pas)\b|[;!?].*\w", text)
            or re.search(r"\bou\b", query.casefold())):
        return None
    if direct and not text.startswith(("where ", "ou ")):
        return None
    for pattern in _REQUESTS:
        if match := (pattern.match(text) if direct else pattern.search(text)):
            if not match[0].startswith(("ou ", "where ")) and not _NOMINAL_PREFIX.fullmatch(
                re.sub(r"\s+", " ", text[:match.start()])
            ):
                continue
            subject = frozenset(terms(match["object"]))
            if 1 <= len(subject) <= 6:
                return StorageLookup(subject)
    return None
