"""Recursively sanitize data received from an external process engine."""

from __future__ import annotations

import json
from typing import Any, cast

SECRET_KEYS = {
    "token", "secret", "api_key", "apikey", "password", "authorization",
    "x-n8n-api-key", "cookie", "set-cookie", "bearer", "credential", "credentials",
    "private_key", "access_token", "refresh_token", "callback_token",
}
TRUNCATED = "...(truncated)"


def _secret_key(key: str, extra: set[str]) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in {item.replace("-", "_") for item in SECRET_KEYS | extra}


def sanitize(
    value: Any,
    *,
    max_bytes: int = 65_536,
    max_depth: int = 10,
    deny_keys: set[str] | None = None,
) -> Any:
    """Return a bounded JSON structure with secrets removed."""
    extra = deny_keys or set()

    def walk(node: Any, depth: int) -> Any:
        if depth >= max_depth:
            return TRUNCATED
        if isinstance(node, bytes):
            return "***binary omitted***"
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for raw_key, child in cast(dict[Any, Any], node).items():
                key = str(raw_key)
                result[key] = "***" if _secret_key(key, extra) else walk(child, depth + 1)
            return result
        if isinstance(node, (list, tuple)):
            return [walk(child, depth + 1) for child in cast(list[Any] | tuple[Any, ...], node)]
        if isinstance(node, str):
            encoded = node.encode("utf-8")
            if len(encoded) <= max_bytes:
                return node
            return encoded[:max_bytes].decode("utf-8", errors="ignore") + TRUNCATED
        if node is None or isinstance(node, (bool, int, float)):
            return node
        return str(node)

    cleaned = walk(value, 0)
    encoded = json.dumps(cleaned, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= max_bytes:
        return cleaned
    if isinstance(cleaned, str):
        return cleaned[:max_bytes] + TRUNCATED
    return {"_truncated": True, "preview": encoded[:max_bytes].decode("utf-8", errors="ignore") + TRUNCATED}
