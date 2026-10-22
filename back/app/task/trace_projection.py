"""Bounded tool details for authorized Task activity readers."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

_SECRET_KEYS = frozenset({"api_key", "apikey", "authorization", "cookie", "password", "passwd",
                          "private_key", "secret", "token", "access_token", "refresh_token"})
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _safe_value(value: object, depth: int = 0) -> object:
    if depth >= 8:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(cast(Mapping[object, object], value).items()):
            if index >= 64:
                result["_truncated"] = True
                break
            key = str(raw_key)[:256]
            normalized = key.lower().replace("-", "_")
            result[key] = "[REDACTED]" if (
                normalized in _SECRET_KEYS or normalized.endswith(("_token", "_secret", "_password", "_api_key"))
            ) else _safe_value(item, depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = cast(Sequence[object], value)
        return [_safe_value(item, depth + 1) for item in items[:64]] + (["[truncated]"] if len(items) > 64 else [])
    if isinstance(value, bytes):
        return {"binary_bytes": len(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _BEARER.sub("Bearer [REDACTED]", str(value))[:8_000]


def project_tool_payload(value: dict[str, Any] | None, *, limit: int = 4_000) -> dict[str, Any] | None:
    """Keep useful arguments/outcomes without exposing credentials or unbounded JSON."""
    if value is None:
        return None
    safe = cast(dict[str, Any], _safe_value(value))
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= limit:
        return safe
    # Reserve room for JSON string escaping and the explicit truncation envelope.
    preview = encoded.encode("utf-8")[: (limit - 128) // 2].decode("utf-8", errors="ignore")
    return {"truncated": True, "preview": preview}
