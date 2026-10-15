"""Governed-memory selection around the canonical app.llm embedding client."""

from __future__ import annotations

import httpx
from app.llm import (
    ConfiguredEmbeddingModel as EmbeddingModel,
    EmbeddingError,
    EmbeddingNotConfiguredError,
    require_configured_embedding_model,
)


INDEX_EMBEDDING_TIMEOUT_SECONDS = 60.0
QUERY_EMBEDDING_TIMEOUT_SECONDS = 5.0


class MemoryEmbeddingError(EmbeddingError):
    """Embedding configuration or invocation failed."""


class MemoryEmbeddingNotConfiguredError(MemoryEmbeddingError):
    """No usable embedding model is selected."""


class MemoryEmbeddingProviderUnavailableError(MemoryEmbeddingError):
    """Retryable provider-wide failure; the document itself is not poisoned."""


async def resolve_embedding_model() -> EmbeddingModel:
    """Resolve the operator-selected vector model from the shared LLM catalog."""

    try:
        return await require_configured_embedding_model()
    except EmbeddingNotConfiguredError as exc:
        raise MemoryEmbeddingNotConfiguredError(str(exc)) from exc


async def embed_many(
    texts: list[str],
    *,
    model: EmbeddingModel,
    timeout_seconds: float = INDEX_EMBEDDING_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """Embed non-empty texts while preserving their request order."""

    try:
        return await model.embed(texts, timeout=timeout_seconds)
    except EmbeddingError as exc:
        cause = exc.__cause__
        if isinstance(cause, httpx.TransportError) or (
            isinstance(cause, httpx.HTTPStatusError)
            and (
                cause.response.status_code in {401, 403, 408, 429}
                or cause.response.status_code >= 500
            )
        ):
            raise MemoryEmbeddingProviderUnavailableError(str(exc)) from exc
        raise MemoryEmbeddingError(str(exc)) from exc


async def embed_query(
    query: str,
    *,
    model: EmbeddingModel,
    timeout_seconds: float = QUERY_EMBEDDING_TIMEOUT_SECONDS,
) -> list[float]:
    embeddings = await embed_many(
        [query],
        model=model,
        timeout_seconds=timeout_seconds,
    )
    return embeddings[0]


__all__ = [
    "EmbeddingModel",
    "MemoryEmbeddingError",
    "MemoryEmbeddingNotConfiguredError",
    "embed_many",
    "embed_query",
    "resolve_embedding_model",
]
