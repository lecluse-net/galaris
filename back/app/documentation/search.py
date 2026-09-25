"""Bounded hybrid retrieval over the current shipped corpus only."""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Float, cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db

from .contracts import Corpus, Passage
from .models import DocumentationPassage as Row


Embed = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class SearchHit:
    uri: str
    title: str
    heading: str
    language: str
    domain: str
    kind: str
    status: str
    checksum: str
    offset: int
    max_chars: int
    excerpt: str
    score: float


@dataclass(frozen=True)
class SearchResult:
    corpus_revision: str
    build_version: str
    mode: str
    degradation_reason: str | None
    indexed_passages: int
    total_passages: int
    hits: tuple[SearchHit, ...]


async def synchronize(corpus: Corpus) -> None:
    """Idempotent inserts; never give old database rows authority over the manifest."""
    fingerprints = [p.fingerprint for p in corpus.passages]
    existing = set((await get_db().scalars(select(Row.fingerprint).where(Row.fingerprint.in_(fingerprints)))).all())
    missing = [p for p in corpus.passages if p.fingerprint not in existing]
    for offset in range(0, len(missing), 100):
        values = [{"fingerprint": p.fingerprint, "title": f"{p.page.title}\n{p.heading}\n{p.page.path}", "content": p.text}
                  for p in missing[offset:offset + 100]]
        await get_db().execute(insert(Row).values(values).on_conflict_do_nothing(index_elements=[Row.fingerprint]))


async def index_embeddings(corpus: Corpus, *, model_key: str, embed: Embed, batch_size: int = 32) -> int:
    await synchronize(corpus)
    fingerprints = [p.fingerprint for p in corpus.passages]
    rows = list((await get_db().scalars(select(Row).where(
        Row.fingerprint.in_(fingerprints),
        or_(Row.model_key.is_(None), Row.model_key != model_key, Row.embedding.is_(None)),
    ).order_by(Row.id).limit(batch_size))).all())
    if not rows:
        return 0
    vectors = await embed([f"{row.title}\n\n{row.content}" for row in rows])
    if len(vectors) != len(rows) or not vectors or not vectors[0]:
        raise ValueError("Invalid documentation embedding batch.")
    dimensions = len(vectors[0])
    for row, vector in zip(rows, vectors, strict=True):
        if len(vector) != dimensions or not all(math.isfinite(value) for value in vector):
            raise ValueError("Invalid documentation embedding dimensions or values.")
        row.embedding, row.model_key, row.dimensions = vector, model_key, dimensions
    await get_db().flush()
    return len(rows)


async def prune_retired(corpus: Corpus) -> None:
    # Keep a grace period for rolling upgrades and quick rollbacks.
    await get_db().execute(delete(Row).where(
        Row.fingerprint.not_in([p.fingerprint for p in corpus.passages]),
        Row.created_at < datetime.now(timezone.utc) - timedelta(days=7),
    ))


async def index_status(corpus: Corpus, *, model_key: str | None) -> dict[str, int | bool]:
    keys = [p.fingerprint for p in corpus.passages]
    indexed = int(await get_db().scalar(select(func.count()).select_from(Row).where(Row.fingerprint.in_(keys))) or 0)
    embedded = 0
    if model_key:
        embedded = int(await get_db().scalar(select(func.count()).select_from(Row).where(
            Row.fingerprint.in_(keys), Row.model_key == model_key, Row.embedding.is_not(None),
        )) or 0)
    return {"total_passages": len(keys), "indexed_passages": indexed, "embedded_passages": embedded,
            "vector_model_configured": model_key is not None}


async def search(
    corpus: Corpus,
    query: str,
    *,
    language: str = "",
    domain: str = "",
    kind: str = "",
    path_prefix: str = "",
    limit: int = 10,
    model_key: str | None = None,
    query_vector: list[float] | None = None,
    degradation_reason: str | None = None,
) -> SearchResult:
    query = query.strip()
    if not query or len(query) > 1000:
        raise ValueError("A documentation query must contain 1 to 1000 characters.")
    if not 1 <= limit <= 50:
        raise ValueError("Documentation search limit must be between 1 and 50.")
    if language not in {"", "fr", "en", "und"} or kind not in {"", "documentation", "decision", "plan"}:
        raise ValueError("Unsupported documentation language or source kind.")
    await synchronize(corpus)
    passages = {p.fingerprint: p for p in corpus.passages if
        (not language or p.page.language in {language, "und"})
        and (not domain or p.page.domain == domain)
        and (not kind or p.page.kind == kind)
        and p.page.path.startswith(path_prefix)}
    keys = list(passages)
    configuration = "french" if language == "fr" else "english" if language == "en" else "simple"
    tsquery = func.websearch_to_tsquery(configuration, query)
    lexical = list((await get_db().scalars(select(Row.fingerprint).where(
        Row.fingerprint.in_(keys), Row.search_vector.op("@@")(tsquery),
    ).order_by(func.ts_rank_cd(Row.search_vector, tsquery).desc(), Row.fingerprint).limit(100))).all())
    if not lexical:
        terms = re.findall(r"[\w]+", query, re.UNICODE)[:32]
        if terms:
            tsquery = func.websearch_to_tsquery(configuration, " OR ".join(terms))
            lexical = list((await get_db().scalars(select(Row.fingerprint).where(
                Row.fingerprint.in_(keys), Row.search_vector.op("@@")(tsquery),
            ).order_by(func.ts_rank_cd(Row.search_vector, tsquery).desc(), Row.fingerprint).limit(100))).all())
    exact = sorted((key for key, p in passages.items() if query.casefold() in
                    f"{p.page.title}\n{p.heading}\n{p.text}".casefold()),
                   key=lambda key: (passages[key].page.kind != "documentation", passages[key].page.path, passages[key].start))[:100]
    semantic: list[str] = []
    coverage = 0
    if model_key and query_vector:
        matching = (Row.fingerprint.in_(keys), Row.model_key == model_key,
                    Row.dimensions == len(query_vector), Row.embedding.is_not(None))
        coverage = int(await get_db().scalar(select(func.count()).select_from(Row).where(*matching)) or 0)
        if coverage:
            distance = cast(Row.embedding.op("<=>")(query_vector), Float())
            semantic = list((await get_db().scalars(select(Row.fingerprint).where(*matching)
                .order_by(distance, Row.fingerprint).limit(100))).all())
        if coverage < len(keys):
            degradation_reason = "semantic_index_incomplete"
    elif degradation_reason is None:
        degradation_reason = "no_vector_model"
    scores: dict[str, float] = {}
    for ranking, weight in ((lexical, 1.0), (exact, 1.5), (semantic, 1.0)):
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + weight / (60 + rank)
    # Prospective material must not displace current user guidance by default.
    if not kind:
        for key in scores:
            if passages[key].page.kind == "plan":
                scores[key] *= 0.5
            elif passages[key].page.kind == "decision":
                scores[key] *= 0.85
    ordered = sorted(scores, key=lambda key: (-scores[key], passages[key].page.path, passages[key].start))
    hits: list[SearchHit] = []
    translations: dict[str, str] = {}
    page_counts: dict[str, int] = {}
    for key in ordered:
        p = passages[key]
        # Equivalent EN/FR sources have the same relative path; retain the best hit.
        translation_key = re.sub(r"^docs/(fr|en)/", "docs/", p.page.path)
        selected_language = translations.get(translation_key)
        if (selected_language is not None and selected_language != p.page.language) or page_counts.get(p.page.path, 0) >= 2:
            continue
        translations[translation_key] = p.page.language
        page_counts[p.page.path] = page_counts.get(p.page.path, 0) + 1
        hits.append(_hit(p, scores[key], query))
        if len(hits) >= limit:
            break
    return SearchResult(corpus.revision, corpus.build_version, "hybrid" if semantic else "lexical",
                        degradation_reason, coverage, len(keys), tuple(hits))


def _hit(p: Passage, score: float, query: str) -> SearchHit:
    position = p.text.casefold().find(query.casefold())
    start = max(0, position - 120)
    return SearchHit(p.page.uri, p.page.title, p.heading, p.page.language, p.page.domain,
                     p.page.kind, p.page.status, p.page.checksum, p.start, p.end - p.start,
                     p.text[start:start + 700], score)
