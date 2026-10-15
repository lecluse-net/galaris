"""Small public semantic-ranking facade over the configured vector model."""

from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass, field
from collections.abc import Sequence

from . import embedding_service, llm_provider_service, llm_service, model_usages
from .provider_facade import openai_protocol_base_url
from .resource_discovery import provider_connection


_EMBEDDING_BATCH_SIZE = 64
_SEMANTIC_RANKING_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ConfiguredEmbeddingModel:
    """Public embedding handle with a credential-free cache identity."""

    key: str
    code: str
    model_name: str
    base_url: str
    api_key: str | None = field(default=None, repr=False)

    @property
    def endpoint(self) -> embedding_service.EmbeddingEndpoint:
        return embedding_service.EmbeddingEndpoint(
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def embed(self, texts: list[str], *, timeout: float = 5.0) -> list[list[float]]:
        return await embedding_service.embed_many(
            texts, endpoint=self.endpoint, timeout_seconds=timeout
        )


class EmbeddingNotConfiguredError(embedding_service.EmbeddingError):
    """The configured vector model has no usable provider endpoint."""


async def require_configured_embedding_model() -> ConfiguredEmbeddingModel:
    """Resolve vector configuration once, preserving existing index identities."""
    llm = await llm_service.get_profile_llm(model_usages.VECTOR)
    if llm is None:
        raise EmbeddingNotConfiguredError("No embedding model is configured.")
    if not llm.provider.is_active:
        raise EmbeddingNotConfiguredError("The selected embedding provider is inactive.")
    base_url = openai_protocol_base_url(provider_connection(llm.provider, None)).strip()
    if not base_url:
        raise EmbeddingNotConfiguredError("The selected embedding provider has no base URL.")
    payload = json.dumps(
        {
            "contract": 1,
            "provider_id": llm.llm_provider_id,
            "provider_type": llm.provider.provider_type,
            "base_url": base_url,
            "model_code": llm.code,
            "model_name": llm.llm_name,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ConfiguredEmbeddingModel(
        key=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        code=llm.code,
        model_name=llm.llm_name,
        base_url=base_url,
        api_key=llm_provider_service.decrypt_api_key(llm.provider.api_key),
    )


async def configured_embedding_model() -> ConfiguredEmbeddingModel | None:
    try:
        return await require_configured_embedding_model()
    except EmbeddingNotConfiguredError:
        return None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


async def rank_texts_by_semantic_similarity(
    query: str,
    texts: Sequence[str],
) -> tuple[int, ...] | None:
    """Return every text index from most to least relevant, or ``None`` without vectors."""

    normalized_query = query.strip()
    normalized_texts = [text.strip() or "[empty]" for text in texts]
    if not normalized_query or not normalized_texts:
        return None
    model = await configured_embedding_model()
    if model is None:
        return None
    query_embedding = (
        await model.embed([normalized_query], timeout=_SEMANTIC_RANKING_TIMEOUT_SECONDS)
    )[0]
    text_embeddings: list[list[float]] = []
    for offset in range(0, len(normalized_texts), _EMBEDDING_BATCH_SIZE):
        text_embeddings.extend(
            await model.embed(
                normalized_texts[offset : offset + _EMBEDDING_BATCH_SIZE],
                timeout=_SEMANTIC_RANKING_TIMEOUT_SECONDS,
            )
        )
    return tuple(
        sorted(
            range(len(normalized_texts)),
            key=lambda index: (
                -_cosine(query_embedding, text_embeddings[index]),
                index,
            ),
        )
    )


__all__ = [
    "rank_texts_by_semantic_similarity",
    "ConfiguredEmbeddingModel",
    "configured_embedding_model",
    "require_configured_embedding_model",
    "EmbeddingNotConfiguredError",
]
