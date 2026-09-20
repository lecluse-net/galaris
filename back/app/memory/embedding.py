"""Governed-memory selection around the canonical app.llm embedding client."""

from __future__ import annotations

from app.llm import model_usages

import hashlib
import json
import httpx
from dataclasses import dataclass, field

from app.llm import LLM, llm_provider_service, llm_service
from app.llm import embedding_service as llm_embedding
from app.llm.provider_facade import openai_protocol_base_url
from app.llm.resource_discovery import provider_connection


INDEX_EMBEDDING_TIMEOUT_SECONDS = 60.0
QUERY_EMBEDDING_TIMEOUT_SECONDS = 5.0
class MemoryEmbeddingError(llm_embedding.EmbeddingError):
    """Embedding configuration or invocation failed."""


class MemoryEmbeddingNotConfiguredError(MemoryEmbeddingError):
    """No usable embedding model is selected."""


class MemoryEmbeddingProviderUnavailableError(MemoryEmbeddingError):
    """Retryable provider-wide failure; the document itself is not poisoned."""


@dataclass(frozen=True)
class EmbeddingModel:
    """Resolved provider details and a stable, non-secret index version."""

    key: str
    code: str
    model_name: str
    base_url: str
    api_key: str | None = field(repr=False)


def _clean_base_url(llm: LLM) -> str:
    normalized = openai_protocol_base_url(
        provider_connection(llm.provider, None)
    ).strip()
    if not normalized:
        raise MemoryEmbeddingNotConfiguredError(
            "The selected embedding provider has no base URL."
        )
    return normalized


def _model_key(llm: LLM, *, base_url: str) -> str:
    """Fingerprint endpoint semantics without ever incorporating credentials."""

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
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def resolve_embedding_model() -> EmbeddingModel:
    """Resolve the operator-selected vector model from the shared LLM catalog."""

    llm = await llm_service.get_profile_llm(model_usages.VECTOR)
    if llm is None:
        raise MemoryEmbeddingNotConfiguredError(
            "No embedding model is configured."
        )
    if not llm.provider.is_active:
        raise MemoryEmbeddingNotConfiguredError(
            "The selected embedding provider is inactive."
        )
    base_url = _clean_base_url(llm)
    return EmbeddingModel(
        key=_model_key(llm, base_url=base_url),
        code=llm.code,
        model_name=llm.llm_name,
        base_url=base_url,
        api_key=llm_provider_service.decrypt_api_key(llm.provider.api_key),
    )


async def embed_many(
    texts: list[str],
    *,
    model: EmbeddingModel,
    timeout_seconds: float = INDEX_EMBEDDING_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """Embed non-empty texts while preserving their request order."""

    try:
        return await llm_embedding.embed_many(
            texts,
            endpoint=llm_embedding.EmbeddingEndpoint(
                model_name=model.model_name,
                base_url=model.base_url,
                api_key=model.api_key,
            ),
            timeout_seconds=timeout_seconds,
        )
    except llm_embedding.EmbeddingError as exc:
        cause = exc.__cause__
        if isinstance(cause, httpx.TransportError) or (
            isinstance(cause, httpx.HTTPStatusError)
            and (cause.response.status_code in {401, 403, 408, 429} or cause.response.status_code >= 500)
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
