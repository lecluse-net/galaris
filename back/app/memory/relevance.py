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
    tokens = dict.fromkeys(_inflect(m[0].casefold()) for m in re.finditer(r"[^\W_]+", value)
                           if len(m[0]) > 1 and fold(m[0]) not in STOPWORDS)
    return " | ".join(f"{word}:*" for word in list(tokens)[:16])


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
    return tuple(dict.fromkeys(stem(m[0]) for m in re.finditer(r"[^\W_]+", value)
                               if len(m[0]) > 1 and fold(m[0]) not in STOPWORDS))


def term_weights(query: str, texts: Iterable[str]) -> dict[str, float]:
    documents = [set(terms(text)) for text in texts]
    counts: Counter[str] = Counter(word for document in documents for word in document)
    return {word: 1.0 + math.log((len(documents) + 1) / (counts[word] + 1)) for word in terms(query)}


def coverage(text: str, weights: dict[str, float]) -> float:
    present = matched_terms(text, weights)
    total = sum(weights.values())
    return sum(weight for word, weight in weights.items() if word in present) / total if total else 0.0
