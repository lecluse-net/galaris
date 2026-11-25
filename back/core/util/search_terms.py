"""Shared French and English lexical evidence for retrieval and turn context."""

import re
import unicodedata
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


def fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def without_speaker_prefixes(value: str) -> str:
    """Strip the line-leading speaker labels used in conversation objectives."""
    return " ".join(re.sub(r"(?m)^\s*\[[^\]\n]{1,100}\]\s*", "", value).split())


def inflect(word: str) -> str:
    if word.isalpha():
        if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
            word = word[:-1]
        if word.endswith("er") and len(word) > 5:
            word = word[:-2]
        if len(word) > 4:
            word = word.rstrip("e")
    return word


def terms(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(inflect(m[0]) for m in re.finditer(r"[^\W_]+", fold(value))
                               if len(m[0]) > 1 and m[0] not in STOPWORDS))


def common_terms(texts: Iterable[str]) -> frozenset[str]:
    """Identify boilerplate shared by most candidates in the bounded result page."""
    counts: Counter[str] = Counter()
    size = 0
    for text in texts:
        counts.update(terms(text))
        size += 1
    return frozenset(word for word, count in counts.items() if count >= 3 and count * 2 > size)


def has_turn_evidence(query_terms: frozenset[str], title: str, excerpt: str, common: frozenset[str]) -> bool:
    """Require corroborating terms, or a focused title match for a short request."""
    if not query_terms:
        return False
    in_title = query_terms.intersection(terms(title))
    matches = in_title.union(query_terms.intersection(terms(excerpt)))
    if matches < query_terms and matches <= common:
        return False
    required = min(len(query_terms), 2 + len(query_terms) // 10, 4)
    return (len(matches) >= required
            or (bool(in_title) and len(query_terms) <= 4))
