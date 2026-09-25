"""Small public semantic-ranking facade over the configured vector model."""

from __future__ import annotations

import math
import hashlib
from dataclasses import dataclass
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
    endpoint: embedding_service.EmbeddingEndpoint

    async def embed(self, texts: list[str], *, timeout: float = 5.0) -> list[list[float]]:
        return await embedding_service.embed_many(texts, endpoint=self.endpoint, timeout_seconds=timeout)


async def configured_embedding_model() -> ConfiguredEmbeddingModel | None:
    llm = await llm_service.get_profile_llm(model_usages.VECTOR)
    if llm is None or not llm.provider.is_active:
        return None
    base_url = openai_protocol_base_url(provider_connection(llm.provider, None)).strip()
    if not base_url:
        return None
    key = hashlib.sha256(f"v1\0{llm.llm_provider_id}\0{base_url}\0{llm.code}\0{llm.llm_name}".encode()).hexdigest()
    return ConfiguredEmbeddingModel(key, embedding_service.EmbeddingEndpoint(
        model_name=llm.llm_name, base_url=base_url,
        api_key=llm_provider_service.decrypt_api_key(llm.provider.api_key),
    ))


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
    llm = await llm_service.get_profile_llm(model_usages.VECTOR)
    if llm is None or not llm.provider.is_active:
        return None
    base_url = openai_protocol_base_url(
        provider_connection(llm.provider, None)
    ).strip()
    if not base_url:
        return None
    endpoint = embedding_service.EmbeddingEndpoint(
        model_name=llm.llm_name,
        base_url=base_url,
        api_key=llm_provider_service.decrypt_api_key(llm.provider.api_key),
    )
    query_embedding = (
        await embedding_service.embed_many(
            [normalized_query],
            endpoint=endpoint,
            timeout_seconds=_SEMANTIC_RANKING_TIMEOUT_SECONDS,
        )
    )[0]
    text_embeddings: list[list[float]] = []
    for offset in range(0, len(normalized_texts), _EMBEDDING_BATCH_SIZE):
        text_embeddings.extend(
            await embedding_service.embed_many(
                normalized_texts[offset : offset + _EMBEDDING_BATCH_SIZE],
                endpoint=endpoint,
                timeout_seconds=_SEMANTIC_RANKING_TIMEOUT_SECONDS,
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


__all__ = ["rank_texts_by_semantic_similarity", "ConfiguredEmbeddingModel", "configured_embedding_model"]
