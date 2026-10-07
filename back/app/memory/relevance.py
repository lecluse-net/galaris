"""Query evidence independent of graph popularity and provider score scales."""

from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache
from collections import Counter
from collections.abc import Iterable


STOPWORDS = frozenset("""
a au aux avec ce ces cet cette dans de des du elle elles en est et eux il ils je la le les leur leurs
ma mais me mes mon ne nos notre nous on ou par pas pour qu que quel quelle quels quelles qui quoi
sa se ses son sont sur ta te tes toi ton tu un une vos votre vous y d l s t c n j m
ai as avons avez ont etre avoir ete etait sont serait fait faire faut peut peux pouvez dois doit
comment pourquoi quand lors alors aussi tres plus moins bien merci bonjour maintenant encore
the a an and are as at be been by can could do does for from has have how i in is it its of on or
our that their there these this to was we were what when where which who why will with would you your
rappelle rappelez remind remember tell
""".split())

_ENTITY_STOPWORDS = STOPWORDS | frozenset("""
avant autre before concerning concernant could donne find il je le la new on please
regarding remind reprenons retrouve tiens yesterday hier unknown inconnu
""".split())


def fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def _inflect(word: str) -> str:
    if word.isalpha():
        if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
            word = word[:-1]
        if word.endswith("er") and len(word) > 5:
            word = word[:-2]
        if len(word) > 4:
            word = word.rstrip("e")
    return word


def stem(value: str) -> str:
    """Conservative inflection matching; never rewrite identifiers or numbers."""
    return _inflect(fold(value))


def prefix_query(value: str) -> str:
    tokens = dict.fromkeys(_inflect(m[0]) for m in re.finditer(r"[^\W_]+", fold(value))
                           if len(m[0]) > 1 and m[0] not in STOPWORDS)
    return " | ".join(f"{word}:*" for word in list(tokens)[:16])


def entity_groups(value: str, *, limit: int = 2) -> tuple[tuple[str, ...], ...]:
    """Bounded explicit capitalized phrases, not an identity/alias oracle."""
    groups: list[tuple[str, ...]] = []
    pending: list[str] = []
    previous_end = 0
    value = unicodedata.normalize("NFC", value)
    for match in re.finditer(r"[^\W_]+", value):
        word = match[0]
        token = stem(word)
        capitalized = word[0].isupper() and word.isalpha() and fold(word) not in _ENTITY_STOPWORDS
        adjacent = value[previous_end:match.start()].isspace()
        if pending and (not capitalized or not adjacent or len(pending) == 4):
            group = tuple(pending)
            if group not in groups:
                groups.append(group)
            pending = []
        if capitalized:
            pending.append(token)
        previous_end = match.end()
    if pending and tuple(pending) not in groups:
        groups.append(tuple(pending))
    return tuple(groups[:limit])


_RELATION_QUERY_RE = re.compile(
    r"\b(?:collegue|collaborateur|collaboratrice|cousin|cousine|tante|oncle|"
    r"ami|amie|voisin|voisine|colleague|coworker|co-worker|cousin|aunt|uncle|friend|neighbour|neighbor)\b"
    r"|\b(?:personne|person)\b.{0,60}\b(?:travaille|working|works|collabore)\b",
)
_RELATION_BEFORE_NAME_RE = re.compile(
    r"\b(?:collegue|collaborateur|collaboratrice|cousin|cousine|tante|oncle|"
    r"ami|amie|voisin|voisine|colleague|coworker|co-worker|aunt|uncle|friend|neighbour|neighbor)"
    r"\s+(?:de|du|of)\s+$"
    r"|\b(?:personne|person)\b.{0,60}\b(?:travaille|collabore|working|works)"
    r"\s+(?:avec|with)\s+$",
)
_RELATION_AFTER_NAME_RE = re.compile(
    r"['’]s\s+(?:colleague|coworker|co-worker|cousin|aunt|uncle|friend|neighbour|neighbor)\b",
)
_RELATION_EVIDENCE_RE = re.compile(
    r"\b(?:travaille(?:nt)?|collabore(?:nt)?)\s+avec\b|\b(?:works?|collaborates?)\s+with\b"
    r"|\b(?:est|is)\s+(?:la\s+|le\s+|l['’]|une?\s+|the\s+|an?\s+|[\w]+['’]s\s+)"
    r"(?:collegue|cousin|cousine|tante|oncle|ami|amie|voisin|voisine|colleague|cousin|aunt|uncle|friend|neighbor|neighbour)\b",
)
_ASSERTED_RELATION_GAP_RE = re.compile(
    r"(?:travaille(?:nt)?\s+avec|collabore(?:nt)?\s+avec|works?\s+with|collaborates?\s+with)"
    r"|(?:est|is)\s+(?:la\s+|le\s+|l['’]|une?\s+|the\s+|an?\s+)"
    r"(?:collegue|cousin|cousine|tante|oncle|ami|amie|voisin|voisine|colleague|aunt|uncle|friend|neighbor|neighbour)\s+(?:de|of)",
)
_UNCERTAIN_RELATION_RE = re.compile(
    r"\b(?:pas|plus|jamais|aucun|not|never|no|ancien|ancienne|former|peut|pourrait|might|maybe|"
    r"will|would|may|could|devrait|voudrait|hypothese|suppose|pense|thinks|claims|si|if)\b"
    r"|[\"«»?]",
)
_RELATION_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("colleague", re.compile(r"\b(?:collegue|collaborateur|collaboratrice|colleague|coworker|co-worker|travaille(?:nt)?|working|works?|collabore(?:nt)?|collaborates?)\b")),
    ("cousin", re.compile(r"\b(?:cousin|cousine)\b")),
    ("aunt", re.compile(r"\b(?:tante|aunt)\b")),
    ("uncle", re.compile(r"\b(?:oncle|uncle)\b")),
    ("friend", re.compile(r"\b(?:ami|amie|friend)\b")),
    ("neighbor", re.compile(r"\b(?:voisin|voisine|neighbour|neighbor)\b")),
)


def indirect_relation(value: str) -> bool:
    """Recognize a relation to a name, rather than a named person's own role."""
    normalized = fold(value[:4000])
    if not _RELATION_QUERY_RE.search(normalized):
        return False
    names = entity_groups(value[:4000])
    lexemes = tuple(re.finditer(r"[^\W_]+", normalized))
    inflections = tuple(_inflect(token[0]) for token in lexemes)
    for name in names:
        for start in range(len(inflections) - len(name) + 1):
            if inflections[start:start + len(name)] != name:
                continue
            left = lexemes[start].start()
            right = lexemes[start + len(name) - 1].end()
            if (_RELATION_BEFORE_NAME_RE.search(normalized[max(0, left - 120):left])
                    or _RELATION_AFTER_NAME_RE.match(normalized[right:right + 80])):
                return True
    return False


def relation_targets(
    text: str, anchors: tuple[tuple[str, ...], ...], *, query: str,
) -> tuple[tuple[str, ...], ...]:
    """Names on the two sides of an asserted relation, not event co-occurrences.

    Only short, unquoted positive statements with two full names qualify. No
    target is inferred from an ambiguous, hypothetical or negated relationship.
    Callers must supply evidence from readable candidates in the current scope.
    """
    targets: list[tuple[str, ...]] = []
    folded_query = fold(query)
    query_kinds = {kind for kind, pattern in _RELATION_KINDS if pattern.search(folded_query)}
    for sentence in re.split(r"[.!;\n]", text[:4000]):
        if len(sentence) > 400:
            continue
        normalized = fold(sentence)
        relation = _RELATION_EVIDENCE_RE.search(normalized)
        if relation is None or _UNCERTAIN_RELATION_RE.search(normalized):
            continue
        evidence_kinds = {kind for kind, pattern in _RELATION_KINDS if pattern.search(relation[0])}
        if not query_kinds.intersection(evidence_kinds):
            continue
        names = entity_groups(sentence, limit=8)
        if len(names) != 2 or any(len(name) < 2 for name in names):
            continue
        # Match an entire affirmative clause, not a predicate found anywhere
        # inside a quote, reported hypothesis or contracted negation.
        lexemes = tuple(re.finditer(r"[^\W_]+", normalized))
        inflections = tuple(_inflect(token[0]) for token in lexemes)
        spans: list[tuple[int, int]] = []
        for name in names:
            starts = [index for index in range(len(inflections) - len(name) + 1)
                      if inflections[index:index + len(name)] == name]
            if len(starts) != 1:
                break
            start = starts[0]
            spans.append((lexemes[start].start(), lexemes[start + len(name) - 1].end()))
        if len(spans) != 2:
            continue
        left, right = spans
        if normalized[:left[0]].strip() or not _ASSERTED_RELATION_GAP_RE.fullmatch(normalized[left[1]:right[0]].strip()):
            continue
        tail = normalized[right[1]:].strip()
        if tail and not tail.startswith(("sur ", "on ")):
            continue
        present = {name for name in names if name in anchors}
        if len(present) != 1:
            continue
        if evidence_kinds.intersection({"aunt", "uncle"}) and names[0] in present:
            # X being Y's aunt/uncle does not make Y the aunt/uncle of X.
            continue
        target = next(name for name in names if name not in present)
        if target not in targets:
            targets.append(target)
    return tuple(targets[:8])


def fact_tokens(text: str) -> tuple[str, ...]:
    """Conservative visible-fact signature retaining accents and numeric signs.

    Unlike query terms, this does not stem words or remove stopwords. Matching
    excerpts receive a soft redundancy penalty, never a merge or exclusion.
    """
    if len(text) > 4000:
        # Do not equate long resources by a shared prefix or tokenize them in
        # full merely to classify redundancy in a bounded recall.
        return ()
    return tuple(match[0] for match in re.finditer(
        r"[+-]?\d+(?:[.,:/-]\d+)*|[^\W_]+|[?\"«»“”]",
        unicodedata.normalize("NFC", text.casefold()),
    ))


def entity_prefix_query(value: str) -> str:
    return " | ".join("(" + " <-> ".join(f"{word}:*" for word in group) + ")"
                      for group in entity_groups(value))


def matched_entities(text: str, groups: tuple[tuple[str, ...], ...]) -> frozenset[int]:
    if not groups:
        return frozenset()
    tokens = tuple(_inflect(match[0]) for match in re.finditer(r"[^\W_]+", fold(text))
                   if match[0] not in STOPWORDS)
    return frozenset(index for index, group in enumerate(groups)
                     if any(tokens[start:start + len(group)] == group
                            for start in range(len(tokens) - len(group) + 1)))


@lru_cache(maxsize=4096)
def _one_edit(left: str, right: str) -> bool:
    if min(len(left), len(right)) < 6 or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) <= 1
    shorter, longer = sorted((left, right), key=len)
    for index, character in enumerate(shorter):
        if character != longer[index]:
            return shorter[index:] == longer[index + 1:]
    return True


def matched_terms(text: str, query_terms: Iterable[str]) -> set[str]:
    present = set(terms(text))
    return {word for word in query_terms if word in present or
            (word.isalpha() and any(candidate.isalpha() and _one_edit(word, candidate) for candidate in present))}


def terms(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_inflect(m[0]) for m in re.finditer(r"[^\W_]+", fold(value))
                               if len(m[0]) > 1 and m[0] not in STOPWORDS))


def term_weights(query: str, texts: Iterable[str]) -> dict[str, float]:
    documents = [set(terms(text)) for text in texts]
    counts: Counter[str] = Counter(word for document in documents for word in document)
    entities = {word for group in entity_groups(query) for word in group}
    return {word: (1.0 + math.log((len(documents) + 1) / (counts[word] + 1)))
            * (2.0 if word in entities else 1.0) for word in terms(query)}


def coverage(text: str, weights: dict[str, float]) -> float:
    present = matched_terms(text, weights)
    total = sum(weights.values())
    return sum(weight for word, weight in weights.items() if word in present) / total if total else 0.0
