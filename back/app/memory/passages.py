"""Revision-scoped documentary passages and query-centred lexical excerpts."""

from dataclasses import dataclass
from collections import Counter
import math
import re
from uuid import UUID
from typing import Literal

from core.util import html_blocks, visible_text
from . import relevance


def query_identity(query: str) -> UUID | None:
    value = query.strip()
    for prefix in ("memory://", "document://"):
        value = value.removeprefix(prefix)
    try:
        return UUID(value)
    except ValueError:
        return None


_RESOURCE_REFERENCE_RE = re.compile(
    r"(?<![\w:/])(?:memory|document)://([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?![\w/-])",
    re.IGNORECASE,
)
_SELF_COORDINATE_RE = re.compile(
    r"\b(?:mon|ma|mes|my)\s+(?:(?:propre|personnelle?|personal|own)\s+)?"
    r"(?:e[ -]?mails?|mails?|courriels?|telephones?|phones?|numero\s+de\s+telephone|"
    r"numero(?!\s+(?:de|du|d['’])\b)|(?:phone\s+)?numbers?(?!\s+of\b)|"
    r"adresses?|address(?:es)?(?!\s+book\b)|coordonnees|contact\s+(?:details|information))\b"
)


def query_resource_references(query: str) -> tuple[str, ...]:
    """Preserve whole canonical URI tokens when bounding a context query."""
    references: dict[UUID, str] = {}
    for match in _RESOURCE_REFERENCE_RE.finditer(query):
        references.setdefault(UUID(match[1]), match[0])
        if len(references) == 16:
            break
    return tuple(references.values())


def query_reference_ids(query: str) -> tuple[UUID, ...]:
    """Recognize bounded exact references even inside a natural-language request."""
    identity = query_identity(query)
    if identity is not None:
        return (identity,)
    return tuple(UUID(value.split("://", 1)[1]) for value in query_resource_references(query))


def query_is_contact_self_reference(query: str) -> bool:
    """An explicit possessive coordinate request refers to the scoped sender."""
    return _SELF_COORDINATE_RE.search(relevance.fold(query)) is not None


_CONTACT_LOOKUP_WORDS = relevance.STOPWORDS | frozenset("""
my connais connaissez connaissance sais savez rappelles rappeler donne donnez dis
know knows remember have give tell please address email mail phone number telephone
numero postale postal personnelle personnel personal propre own contact details information
""".split())


def query_is_direct_contact_lookup(query: str) -> bool:
    """Only a simple scoped coordinate question can bypass semantic inference.

    A named third party, relation, condition or additional subject keeps the
    complete hybrid path. This shortcut neither infers nor changes an identity.
    """
    normalized = relevance.fold(query)
    if not _SELF_COORDINATE_RE.search(normalized):
        return False
    remainder = _SELF_COORDINATE_RE.sub(" ", normalized)
    return all(word in _CONTACT_LOOKUP_WORDS for word in re.findall(r"[^\W_]+", remainder))


@dataclass(frozen=True)
class Passage:
    text: str
    block_start: int | None = None
    block_end: int | None = None
    section_path: tuple[str, ...] = ()
    content_source: Literal["document", "memory"] = "document"
    source_revision: int | None = None


def _table_windows(block: str, text: str, max_words: int) -> list[str]:
    """Repeat a table's column labels and keep ordinary rows together."""
    rows = [row for row in text.splitlines() if row.strip()]
    header = rows.pop(0) if rows and re.search(r"<th(?:\s|>)", block) else ""
    if not rows or len(header.split()) >= max_words // 2:
        return []
    prefix = [header] if header else []
    pending = list(prefix)
    words = len(header.split())
    windows: list[str] = []
    for row in rows:
        tokens = row.split()
        if words + len(tokens) > max_words and len(pending) > len(prefix):
            windows.append("\n".join(pending))
            pending, words = list(prefix), len(header.split())
        if words + len(tokens) > max_words:
            capacity = max(1, max_words - len(header.split()))
            for offset in range(0, len(tokens), capacity):
                windows.append("\n".join([*prefix, " ".join(tokens[offset:offset + capacity])]))
            continue
        pending.append(row)
        words += len(tokens)
    if len(pending) > len(prefix):
        windows.append("\n".join(pending))
    return windows


def document_passages(html: str, *, max_words: int = 360) -> list[Passage]:
    """Keep whole blocks when possible; split oversized blocks with overlap.

    Bounds are zero-based, end-exclusive top-level HTML blocks, matching
    file_read's offset unit. Multiple slices of a large block share its bounds.
    """
    passages: list[Passage] = []
    headings: list[tuple[int, str]] = []
    pending: list[str] = []
    start = end = words = 0

    def flush() -> None:
        nonlocal pending, words
        if pending:
            passages.append(Passage("\n".join(pending), start, end, tuple(value for _, value in headings)))
        pending, words = [], 0

    for index, block in enumerate(html_blocks(html)):
        text = visible_text(block).strip()
        if not text:
            continue
        heading = re.match(r"<h([1-6])(?:\s|>)", block)
        if heading:
            flush()
            level = int(heading[1])
            headings = [(depth, value) for depth, value in headings if depth < level]
            headings.append((level, text))
        tokens = text.split()
        if words + len(tokens) > max_words:
            flush()
        if len(tokens) > max_words:
            if re.match(r"<table(?:\s|>)", block):
                windows = _table_windows(block, text, max_words)
                if windows:
                    passages.extend(Passage(window, index, index + 1,
                        tuple(value for _, value in headings)) for window in windows)
                    continue
            overlap = min(60, max_words // 6)
            for offset in range(0, len(tokens), max_words - overlap):
                passages.append(Passage(" ".join(tokens[offset:offset + max_words]), index, index + 1,
                                        tuple(value for _, value in headings)))
                if offset + max_words >= len(tokens):
                    break
            continue
        if not pending:
            start = index
        end = index + 1
        pending.append(text)
        words += len(tokens)
    flush()
    return passages


def lexical_excerpt(text: str, query: str, *, limit: int = 800) -> str:
    """Show the densest query window, preserving original text and identifiers."""
    if len(text) <= limit:
        return text
    terms = set(relevance.terms(query))
    words = list(re.finditer(r"[^\W_]+", text))
    frequencies = Counter(relevance.stem(match[0]) for match in words)
    weights = {term: 1 / (1 + math.log1p(frequencies[term])) for term in terms}
    matches = [match for match in words if relevance.stem(match[0]) in terms]
    if not matches:
        return text[:limit - 1].rstrip() + "…"
    # Bound scoring work for very repetitive documents.
    starts = sorted({max(0, match.start() - limit // 4) for match in matches[:2000]})
    best_start = max(starts, key=lambda start: (
        sum(weights[term] for term in terms & set(relevance.terms(text[start:start + limit]))), -start,
    ))
    excerpt = text[best_start:best_start + limit - 2].strip()
    return ("…" if best_start else "") + excerpt + ("…" if best_start + limit - 2 < len(text) else "")
