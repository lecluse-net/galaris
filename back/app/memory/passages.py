"""Revision-scoped documentary passages and query-centred lexical excerpts."""

from dataclasses import dataclass
from collections import Counter
import math
import re
from uuid import UUID

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


@dataclass(frozen=True)
class Passage:
    text: str
    block_start: int | None = None
    block_end: int | None = None
    section_path: tuple[str, ...] = ()


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
