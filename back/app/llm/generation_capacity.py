"""Use published output capacity when a caller has not supplied a generation budget."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from core.util import as_dict, as_list

from .handlers import LLMModelInfo
from .provider_facade import ProviderConnection, model_catalog_metadata, model_metadata_for
from .request_parameters import RequestParameterPolicy, RequestProtocol


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    expires_at: float = 0
    metadata: LLMModelInfo | None = None


_cache: OrderedDict[str, _Entry] = OrderedDict()
_CACHE_SIZE = 256
_TTL = 300


async def _metadata(connection: ProviderConnection, model: str) -> LLMModelInfo | None:
    # Hash credentials/configuration; never retain raw secrets in the cache key.
    key = hashlib.sha256(json.dumps([
        connection.id, connection.catalog_code, connection.provider_type,
        connection.base_url, connection.api_key, connection.configuration, model,
    ], sort_keys=True).encode()).hexdigest()
    entry = _cache.get(key)
    if entry is None:
        entry = _Entry()
        _cache[key] = entry
        if len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    async with entry.lock:
        if entry.expires_at > time.monotonic():
            return entry.metadata
        metadata: LLMModelInfo | None = None
        for service in (model_metadata_for(connection), model_catalog_metadata()):
            if service is None:
                continue
            try:
                async with asyncio.timeout(3):
                    found = await service.get_model_metadata(connection, model)
            except Exception:
                # Discovery is optional; cancellation still propagates (BaseException).
                continue
            if found is not None:
                if metadata is None:
                    metadata = found
                else:
                    metadata = LLMModelInfo(
                        id=model, context_length=metadata.context_length or found.context_length,
                        max_output_tokens=metadata.max_output_tokens or found.max_output_tokens,
                    )
                if metadata.max_output_tokens and metadata.context_length:
                    break
        entry.metadata = metadata
        entry.expires_at = time.monotonic() + (_TTL if metadata and metadata.max_output_tokens else 30)
        return metadata


def _input_reserve(body: dict[str, Any]) -> int:
    """Conservative local estimate, not a tokenizer or billing measurement.

    Include history, tools and output schemas. Count UTF-8 rather than characters
    so CJK/code are not treated like English prose. Media bytes are not text tokens.
    """
    media = 0

    def bounded(value: Any) -> Any:
        nonlocal media
        if isinstance(value, dict):
            mapping = as_dict(value)
            kind = mapping.get("type")
            if isinstance(kind, str) and kind in {
                "image_url", "input_image", "input_audio", "video_url", "input_video",
                "file", "input_file",
            }:
                media += 4096
                return {"type": mapping["type"]}
            return {key: bounded(item) for key, item in mapping.items()}
        if isinstance(value, list):
            return [bounded(item) for item in as_list(value)]
        return value

    payload = bounded({key: body[key] for key in (
        "messages", "input", "instructions", "tools", "response_format", "text",
    ) if key in body})
    size = len(json.dumps(payload, ensure_ascii=False).encode())
    return (size + 2) // 3 + 256 + media


async def apply_generation_capacity(
    body: dict[str, Any], connection: ProviderConnection, model: str,
    policy: RequestParameterPolicy, protocol: RequestProtocol,
) -> dict[str, Any]:
    """Fill only an absent limit, before provider-owned parameter adaptation."""
    if protocol == "compact" or any(body.get(key) is not None for key in (
        "max_tokens", "max_completion_tokens", "max_output_tokens",
    )):
        return body
    supported = policy.chat if protocol == "chat" else policy.responses
    key = policy.chat_token_limit if protocol == "chat" else "max_output_tokens"
    if key not in supported and "max_tokens" not in supported:
        return body
    # The previous context is held remotely; a local subtraction would be fictitious.
    if body.get("previous_response_id") or body.get("conversation"):
        return body
    metadata = await _metadata(connection, model)
    if metadata is None:
        return body
    capacity = metadata.max_output_tokens
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity <= 0:
        return body
    context = metadata.context_length
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        available = context - _input_reserve(body)
        if available <= 0:
            return body  # Let the authoritative provider handle a full/unknown context.
        capacity = min(capacity, available)
    return {**body, key: capacity}
