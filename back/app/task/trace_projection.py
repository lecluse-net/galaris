"""Bounded tool details for authorized Task activity readers."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

_SECRET_KEYS = frozenset({"api_key", "apikey", "authorization", "cookie", "password", "passwd",
                          "private_key", "secret", "token", "access_token", "refresh_token"})
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _safe_value(value: object, depth: int = 0, *, bounded: bool = True) -> object:
    if bounded and depth >= 8:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(cast(Mapping[object, object], value).items()):
            if bounded and index >= 64:
                result["_truncated"] = True
                break
            key = str(raw_key)[:256] if bounded else str(raw_key)
            normalized = key.lower().replace("-", "_")
            result[key] = "[REDACTED]" if (
                normalized in _SECRET_KEYS or normalized.endswith(("_token", "_secret", "_password", "_api_key"))
            ) else _safe_value(item, depth + 1, bounded=bounded)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = cast(Sequence[object], value)
        selected = items[:64] if bounded else items
        return [_safe_value(item, depth + 1, bounded=bounded) for item in selected] + (
            ["[truncated]"] if bounded and len(items) > 64 else [])
    if isinstance(value, bytes):
        return {"binary_bytes": len(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = _BEARER.sub("Bearer [REDACTED]", str(value))
    return text[:8_000] if bounded else text


def project_tool_payload(value: dict[str, Any] | None, *, limit: int | None = 4_000) -> dict[str, Any] | None:
    """Redact credentials; limit=None preserves the complete canonical payload."""
    if value is None:
        return None
    safe = cast(dict[str, Any], _safe_value(value, bounded=limit is not None))
    if limit is None:
        return safe
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= limit:
        return safe
    # Reserve room for JSON string escaping and the explicit truncation envelope.
    preview = encoded.encode("utf-8")[: (limit - 128) // 2].decode("utf-8", errors="ignore")
    return {"truncated": True, "preview": preview}
