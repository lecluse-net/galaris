"""Canonical OpenAI-compatible embedding protocol."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import httpx

from core.util import as_dict, as_list


MAX_EMBEDDING_DIMENSIONS = 16_000


class EmbeddingError(RuntimeError):
    """Embedding protocol invocation failed."""


@dataclass(frozen=True)
class EmbeddingEndpoint:
    model_name: str
    base_url: str
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class EmbeddingResult:
    embeddings: list[list[float]]
    model: str
    usage: dict[str, Any] | None


def _parse_response(data: dict[str, Any]) -> list[list[float]]:
    raw_items = data.get("data")
    if isinstance(raw_items, list):
        indexed: list[tuple[int, list[float]]] = []
        for fallback_index, raw_item in enumerate(as_list(raw_items)):
            item = as_dict(raw_item)
            raw_embedding = item.get("embedding")
            if not isinstance(raw_embedding, list):
                raise EmbeddingError(
                    "The embedding response contains an item without a vector."
                )
            try:
                index = int(item.get("index", fallback_index))
            except (TypeError, ValueError) as exc:
                raise EmbeddingError(
                    "The embedding response contains an invalid item index."
                ) from exc
            indexed.append(
                (index, [float(value) for value in as_list(raw_embedding)])
            )
        indexed.sort(key=lambda entry: entry[0])
        if [index for index, _embedding in indexed] != list(range(len(indexed))):
            raise EmbeddingError(
                "The embedding response contains invalid item indexes."
            )
        return [embedding for _index, embedding in indexed]
    raw_embedding = data.get("embedding")
    if isinstance(raw_embedding, list):
        return [[float(value) for value in as_list(raw_embedding)]]
    raise EmbeddingError("The embedding response contains no vectors.")


def _validate(embeddings: list[list[float]], *, expected_count: int) -> None:
    if len(embeddings) != expected_count:
        raise EmbeddingError(
            "The embedding response count does not match the request."
        )
    dimensions = len(embeddings[0]) if embeddings else 0
    if dimensions <= 0 or dimensions > MAX_EMBEDDING_DIMENSIONS:
        raise EmbeddingError(
            f"The embedding dimension {dimensions} is unsupported."
        )
    for embedding in embeddings:
        if len(embedding) != dimensions:
            raise EmbeddingError(
                "The embedding response uses inconsistent dimensions."
            )
        if not all(math.isfinite(value) for value in embedding):
            raise EmbeddingError(
                "The embedding response contains non-finite values."
            )


async def embed_many(
    texts: list[str],
    *,
    endpoint: EmbeddingEndpoint,
    timeout_seconds: float,
) -> list[list[float]]:
    result = await embed_many_with_usage(texts, endpoint=endpoint, timeout_seconds=timeout_seconds)
    return result.embeddings


async def embed_many_with_usage(
    texts: list[str], *, endpoint: EmbeddingEndpoint, timeout_seconds: float,
    dimensions: int | None = None,
) -> EmbeddingResult:
    normalized = [text.strip() for text in texts]
    if not normalized or any(not text for text in normalized):
        raise EmbeddingError("Embedding inputs must be non-empty.")
    headers = {"Content-Type": "application/json"}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    body: dict[str, Any] = {"model": endpoint.model_name, "input": normalized}
    if dimensions is not None:
        body["dimensions"] = dimensions
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{endpoint.base_url.rstrip('/')}/embeddings",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise EmbeddingError(
            f"The embedding provider rejected the request ({exc.response.status_code})."
        ) from exc
    except httpx.HTTPError as exc:
        raise EmbeddingError(
            "The embedding provider could not be reached."
        ) from exc
    except (TypeError, ValueError) as exc:
        raise EmbeddingError(
            "The embedding provider returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise EmbeddingError(
            "The embedding provider returned an invalid payload."
        )
    embeddings = _parse_response(as_dict(payload))
    _validate(embeddings, expected_count=len(normalized))
    if dimensions is not None and any(len(vector) != dimensions for vector in embeddings):
        raise EmbeddingError("The embedding provider returned unexpected dimensions.")
    data = as_dict(payload)
    return EmbeddingResult(
        embeddings=embeddings, model=str(data.get("model") or endpoint.model_name),
        usage=as_dict(data["usage"]) if isinstance(data.get("usage"), dict) else None,
    )


__all__ = ["EmbeddingEndpoint", "EmbeddingError", "EmbeddingResult", "embed_many", "embed_many_with_usage"]
