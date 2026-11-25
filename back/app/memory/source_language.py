"""Select topical passages when a question specifies the language of its source."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from .relevance import entity_groups, fold, matched_entities, resource_query_terms, terms
from .storage_evidence import StorageLookup, storage_lookup


_RESOURCE = r"(?:notes?|documents?|rapports?|reports?|notices?|manuals?|guides?|instructions?|consignes?|articles?|versions?)"
_LANG = r"(?:english|french|anglais(?:e?s?)?|fran[cç]ais(?:e?s?)?)"
_QUALIFIER = re.compile(r"\b(?:(english|french)\s+" + _RESOURCE + "|" + _RESOURCE
                        + r"\s+(?:(?:(?:rédigé|écrit)\w*\s+)?en\s+|written in\s+|in\s+)?(" + _LANG + r"))\b(?!-)", re.I)
_READ = re.compile(r"\b(?:find|retrieve|locate|read|show|open|look up|what|which|where|according to|"
                   r"retrouve[rz]?|cherch(?:e|er|ez)|lis|ouvre|montre|selon|d['’]apres|que dit|qu['’]indique|quel\w*|ou)\b")
_OTHER_INTENT = re.compile(r"\b(?:writ\w*|draft|creat\w*|translat\w*|redig\w*|ecri\w*|tradu\w*|"
                           r"sauf|except|plutot|instead|sans|without|not|pas)\b")
_FILLER = frozenset(terms("selon après d'après according about described décrites écrit written please locate open read look up ouvrir ouvre lis lire dit indique"))
_MARKERS = {
    "en": frozenset("the this these their its our your are is was were does has will must from for with in of to on and by".split()),
    "fr": frozenset("le la les des du aux une cette notre leur sont est doit depuis dans pour avec sur par et au".split()),
}


def _language_runs(text: str, requested: str, tag: str) -> Iterator[str]:
    start: int | None = None
    end = 0
    current = ""
    for segment in re.finditer(r"\S[\s\S]*?(?:(?<=[.!?])(?=\s)|(?=\n)|$)", text):
        words = set(re.findall(r"[^\W\d_]+", fold(segment[0])))
        difference = len(words & _MARKERS["en"]) - len(words & _MARKERS["fr"])
        if abs(difference) >= 2:
            current = "en" if difference > 0 else "fr"
        elif words.isdisjoint(_MARKERS["en"]) and words.isdisjoint(_MARKERS["fr"]):
            current = current or tag
        else:
            hint = current or tag
            current = hint if (difference > 0 and hint == "en" or difference < 0 and hint == "fr") else ""
        if current == requested:
            if start is None:
                start = segment.start()
            end = segment.end()
        elif start is not None:
            yield text[start:end]
            start = None
    if start is not None:
        yield text[start:end]


@dataclass(frozen=True, slots=True)
class SourceLanguage:
    language: str
    topic: frozenset[str]
    names: tuple[tuple[str, ...], ...]
    storage: StorageLookup | None = None

    @property
    def prefix_query(self) -> str:
        # An unchanged proper name or cognate can bridge languages. Every extra
        # index candidate must still pass the passage check before emission.
        if self.names:
            tokens = self.names[0]
            joiner = " & "
        else:
            tokens = tuple(sorted(self.topic))
            joiner = " | "
        if not 1 <= len(tokens) <= 4 or not all(word.isalpha() and len(word) >= 4 for word in tokens):
            return ""
        return joiner.join(f"{word}:*" for word in tokens)

    def passage(self, title: str, text: str, *, declared: object = None, semantic: bool = False,
                require_storage: bool = False) -> str:
        """Return original wording from one language run, including adjacent values."""
        tag = declared.casefold().replace("_", "-").split("-")[0] if isinstance(declared, str) else ""
        best, best_score = "", 0
        for passage in _language_runs(text[:8000], self.language, tag):
            if require_storage and self.storage is not None:
                passage = self.storage.passage(title, passage)
                if not passage:
                    continue
            # A title can identify the project. Other requested content must be
            # present in the selected language run or grounded by semantic recall.
            if self.names and not matched_entities(title + " " + passage, self.names):
                continue
            overlap = len(self.topic.intersection(terms(passage)))
            if require_storage and self.storage is not None or self.topic and self.topic == frozenset(terms(title)):
                overlap = max(1, overlap)
            if self.topic and not overlap and not semantic:
                continue
            score = 1 + overlap
            if score > best_score:
                best, best_score = passage, score
        return best


def source_language_query(query: str) -> SourceLanguage | None:
    matches = list(_QUALIFIER.finditer(query))
    if len(matches) != 1:
        return None
    match = matches[0]
    remainder = query[:match.start()] + " " + query[match.end():]
    folded = fold(remainder)
    if (not _READ.search(fold(query)) or _OTHER_INTENT.search(folded) or re.search(r"\b" + _LANG + r"\b", folded)
            or re.search(r"\b(?:and|or|et|ou|sinon|otherwise|if|si)\b|[;!?]\s+\w", remainder.casefold())):
        return None
    language = fold(match[1] or match[2])
    content = frozenset(terms(resource_query_terms(remainder))) - _FILLER
    names = tuple(group for group in entity_groups(remainder, limit=6) if content.issuperset(group))
    name_words = {word for group in names for word in group}
    topic = content - name_words
    return (SourceLanguage("en" if language.startswith(("anglais", "english")) else "fr",
                           topic, names, storage_lookup(remainder)) if names or topic else None)
