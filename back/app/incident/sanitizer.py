"""Deterministic trace conversion, secret redaction, and fingerprinting."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel

from .contracts import FailureEvent


_TRACE_MAX_BYTES = 8 * 1024 * 1024
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
        "access_token",
        "refresh_token",
    }
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_ERROR_REFERENCE_RE = re.compile(
    r"(?i)(error reference|référence d[’']erreur)\s*:\s*[0-9a-f-]{8,64}"
)


def _is_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SECRET_KEYS or normalized.endswith("_token") or normalized.endswith("_secret")


def _json_safe(value: object, *, path: str, redacted: list[str]) -> Any:
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="json"), path=path, redacted=redacted)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value), path=path, redacted=redacted)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in cast(dict[object, object], value).items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if _is_secret_key(key):
                result[key] = "[REDACTED]"
                redacted.append(child_path)
            else:
                result[key] = _json_safe(item, path=child_path, redacted=redacted)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(cast(Iterable[object], value))
        return [
            _json_safe(item, path=f"{path}[{index}]", redacted=redacted)
            for index, item in enumerate(items)
        ]
    if isinstance(value, bytes):
        return {
            "kind": "binary",
            "size": len(value),
            "sha256": sha256(value).hexdigest(),
        }
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).replace("\x00", "")
    cleaned = _BEARER_RE.sub("Bearer [REDACTED]", text)
    if cleaned != text:
        redacted.append(path)
    return cleaned


def sanitize_trace(trace: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str], str, int]:
    """Return a JSON-safe trace with explicit redaction and truncation metadata."""

    redacted: list[str] = []
    payload = cast(dict[str, Any], _json_safe(trace, path="$", redacted=redacted))
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    truncated: list[str] = []
    if len(encoded) > _TRACE_MAX_BYTES:
        preview_bytes = _TRACE_MAX_BYTES // 2
        preview = encoded[:preview_bytes].decode("utf-8", errors="replace")
        suffix = encoded[-preview_bytes:].decode("utf-8", errors="replace")
        payload = {
            "trace_truncated": True,
            "original_byte_size": len(encoded),
            "prefix": preview,
            "suffix": suffix,
        }
        truncated.append("$")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return payload, sorted(set(redacted)), truncated, sha256(encoded).hexdigest(), len(encoded)


def categorize_failure(event: FailureEvent) -> str:
    if event.category:
        return event.category
    text = f"{event.error_type} {event.error_code or ''} {event.error_message}".lower()
    rules = (
        ("rate_limit", ("rate limit", "too many requests", "429")),
        ("authentication", ("unauthorized", "authentication", "invalid api key", "401")),
        ("permission", ("forbidden", "permission", "403")),
        ("timeout", ("timeout", "timed out", "deadline")),
        ("validation", ("validation", "invalid argument", "schema", "retry prompt")),
        ("model_output", ("unexpectedmodelbehavior", "max retries", "content_filter", "finish_reason=length")),
        ("protocol", ("protocol", "malformed", "decode", "parse")),
        ("unavailable", ("unavailable", "connection", "502", "503", "504")),
    )
    for category, needles in rules:
        if any(needle in text for needle in needles):
            return category
    return "tool_runtime" if event.kind == "tool" else "unknown"


def fingerprint_failure(event: FailureEvent, category: str) -> str:
    normalized_message = _ERROR_REFERENCE_RE.sub(
        r"\1: <reference>", event.error_message.lower()
    )
    normalized_message = _UUID_RE.sub("<uuid>", normalized_message)
    normalized_message = _HEX_RE.sub("<hex>", normalized_message)
    normalized_message = _LONG_NUMBER_RE.sub("<number>", normalized_message)
    normalized_message = " ".join(normalized_message.split())[:2_000]
    material = {
        "version": 2,
        "kind": event.kind,
        "category": category,
        "phase": event.phase,
        "error_type": event.error_type,
        "error_code": event.error_code or "",
        "message": normalized_message,
        "driver": event.driver_code or "",
        "provider": event.provider_code or "",
        "model": event.model_code or "",
        "tool": event.tool_name or "",
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = ["categorize_failure", "fingerprint_failure", "sanitize_trace"]
