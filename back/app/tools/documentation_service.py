"""Composition of product knowledge, live grants and the configured embedding model."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import asdict
from time import monotonic
from typing import Any

from loguru import logger

from app.documentation import facade as documentation
from app.llm import EmbeddingError, configured_embedding_model

from .admin_access import require_documentation_access


_INDEX_BATCH_SIZE = 8
_INDEX_TIMEOUT_SECONDS = 60.0
# Process-local cooldown for this maintenance job only; never gate interactive calls.
_index_retry_at = 0.0
_index_retry_delay = 0.0


async def documentation_catalog(agent_id: int) -> dict[str, Any]:
    await require_documentation_access(agent_id)
    corpus = await asyncio.to_thread(documentation.load_corpus)
    model = await configured_embedding_model()
    return {
        "uri": "galaris://documentation/", "corpus_revision": corpus.revision,
        "build_version": corpus.build_version, "pages": len(corpus.pages),
        "passages": len(corpus.passages), "languages": dict(Counter(p.language for p in corpus.pages)),
        "domains": dict(Counter(p.domain for p in corpus.pages)),
        "source_kinds": dict(Counter(p.kind for p in corpus.pages)),
        "index": await documentation.index_status(corpus, model_key=model.key if model else None),
        "entrypoints": [p.uri for p in corpus.pages if p.path in {
            "docs/fr/README.md", "docs/en/README.md", "docs/fr/features.md", "docs/en/features.md",
            "docs/fr/user/navigation.md", "docs/en/user/navigation.md",
            "docs/fr/architecture/generated/navigation.md", "docs/en/architecture/generated/navigation.md",
        }],
        "read_access": "documentation_catalog", "offset_unit": "character",
        "guidance": "Search first, then file_read the returned URI and offset. Plans describe intent, not delivered behavior. "
                    "Documentation does not establish the user's permissions or the installation's configuration.",
    }


async def documentation_search(agent_id: int, query: str, *, language: str = "", domain: str = "",
                               kind: str = "", path_prefix: str = "", limit: int = 10) -> dict[str, Any]:
    from app.connection import facade as connections

    await require_documentation_access(agent_id)
    if not await connections.has_active_tool_function(agent_id, "galaris_admin", "documentation_search"):
        raise PermissionError("The documentation_search function is disabled.")
    if not query.strip() or len(query) > 1000 or not 1 <= limit <= 50:
        raise ValueError("Use a query of 1–1000 characters and a limit of 1–50 results.")
    if language not in {"", "fr", "en", "und"} or kind not in {"", "documentation", "decision", "plan"}:
        raise ValueError("Unsupported documentation language or source kind.")
    corpus = await asyncio.to_thread(documentation.load_corpus)
    model_key: str | None = None
    vector: list[float] | None = None
    reason: str | None = None
    try:
        model = await configured_embedding_model()
        if model is not None:
            model_key = model.key
            vector = (await model.embed([query]))[0]
    except Exception:
        # Provider diagnostics and credentials must not enter the model's tool result.
        reason = "semantic_provider_unavailable"
    result = await documentation.search(corpus, query, language=language, domain=domain, kind=kind,
                                        path_prefix=path_prefix, limit=limit, model_key=model_key,
                                        query_vector=vector, degradation_reason=reason)
    await require_documentation_access(agent_id)
    return asdict(result)


async def refresh_documentation_index() -> None:
    """Scheduler root: bounded, restartable batches, with no inference on the request path."""
    from app.connection import facade as connections
    from sqlalchemy import func, select
    from core.database import get_db

    global _index_retry_at, _index_retry_delay
    if monotonic() < _index_retry_at:
        return

    # The scheduler owns this callback's session and transaction.
    if not await connections.has_any_active_tool_connection("galaris_admin"):
        return
    model = await configured_embedding_model()
    if model is None:
        return
    corpus = await asyncio.to_thread(documentation.load_corpus)

    # Publish new lexical rows before waiting on the provider. Otherwise concurrent
    # searches can block on synchronize's unique-key inserts throughout the HTTP call.
    await documentation.synchronize(corpus)
    await get_db().commit()
    # Keep cross-worker exclusion limited to background indexing. This deliberately
    # retains one DB connection, but no passage write locks during the network wait.
    if not await get_db().scalar(select(func.pg_try_advisory_xact_lock(func.hashtextextended("galaris-documentation-index", 0)))):
        return

    async def embed(texts: list[str]) -> list[list[float]]:
        # Bound wall-clock time as well as the HTTP client's individual I/O waits.
        async with asyncio.timeout(_INDEX_TIMEOUT_SECONDS):
            return await model.embed(texts, timeout=_INDEX_TIMEOUT_SECONDS)

    try:
        await documentation.index_embeddings(corpus, model_key=model.key, embed=embed,
                                            batch_size=_INDEX_BATCH_SIZE)
    except (EmbeddingError, TimeoutError) as exc:
        await get_db().rollback()
        _index_retry_delay = min(600.0, _index_retry_delay * 2 or 60.0)
        _index_retry_at = monotonic() + _index_retry_delay
        logger.warning(
            "Documentation embeddings deferred: {}; retry in {:.0f}s; lexical search remains available",
            type(exc.__cause__ or exc).__name__, _index_retry_delay,
        )
        return
    await documentation.prune_retired(corpus)
    _index_retry_at = _index_retry_delay = 0.0
