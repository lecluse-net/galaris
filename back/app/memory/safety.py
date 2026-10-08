"""Central secret filtering shared by every memory write path."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast


_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(api[_ -]?key|password|passwd|token|secret)\b(\s*[:=]\s*)(<redacted>|[^\s,;<>\"']+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SAFE_PLACEHOLDERS = {"[redacted]", "<redacted>", "***", "xxxxx", "example"}
_SECRET_FIELD_RE = re.compile(
    r"(?i)^(?:api[_ -]?key|password|passwd|token|secret)$"
)


class MemorySafetyError(ValueError):
    """A credential rejection with a fixed, model-safe diagnostic."""


def _is_secret_label(text: str, start: int) -> bool:
    """Recognize a field label at a line, HTML or configuration boundary."""

    cursor = start - 1
    while cursor >= 0 and text[cursor] not in "\r\n" and text[cursor].isspace():
        cursor -= 1
    return cursor < 0 or not (text[cursor].isalnum() or text[cursor] == "_")


def redact_secrets(text: str) -> str | None:
    """Return redacted text, or ``None`` for non-salvageable key material."""

    if _PRIVATE_KEY_RE.search(text):
        return None

    def redact_assignment(match: re.Match[str]) -> str:
        # 'secret' is also an ordinary noun in prose. A colon is a field
        # separator only at a label boundary; '=' remains an assignment anywhere.
        if (
            match.group(1).casefold() == "secret"
            and ":" in match.group(2)
            and not _is_secret_label(text, match.start())
        ):
            return match.group(0)
        value = match.group(3)
        if value.casefold() in _SAFE_PLACEHOLDERS:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}[redacted]"

    redacted = _ASSIGNMENT_SECRET_RE.sub(redact_assignment, text)
    return _BEARER_RE.sub("Bearer [redacted]", redacted)


def assert_safe_text(text: str) -> None:
    """Reject durable direct writes that contain credential-like material."""

    filtered = redact_secrets(text)
    if filtered is None or filtered != text:
        raise MemorySafetyError(
            "Memory content contains credential-like material; redact it before storing."
        )


def assert_safe_value(value: object) -> None:
    """Recursively reject secrets hidden in metadata or supporting fields."""

    if isinstance(value, str):
        assert_safe_text(value)
        return
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        for raw_key, child in mapping.items():
            key = str(raw_key).strip()
            if _SECRET_FIELD_RE.fullmatch(key):
                normalized = str(child or "").strip().casefold()
                if normalized and normalized not in _SAFE_PLACEHOLDERS:
                    raise MemorySafetyError(
                        "Memory metadata contains credential-like material; "
                        "redact it before storing."
                    )
            assert_safe_value(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        for child in sequence:
            assert_safe_value(child)


__all__ = ["MemorySafetyError", "assert_safe_text", "assert_safe_value", "redact_secrets"]
