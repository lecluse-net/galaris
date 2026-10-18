"""Bounded, private update evidence, independent of the API and telemetry exporters."""

import json
import os
from pathlib import Path
import re
import sys
import traceback
from collections.abc import Mapping, Sequence
from typing import cast
from datetime import datetime, timezone
from uuid import uuid4

from core import settings


DIAGNOSTIC_ROOT = Path("/data/update-diagnostics")
_SECRET = re.compile(
    r'''(?i)(["']?(?:api[_-]?key|authorization|cookie|password|passwd|credential|'''
    r'''(?:access[_-]?|refresh[_-]?)?token|secret|private[_-]?key)["']?\s*[:=]\s*)'''
    r'''(?:"[^"]*"|'[^']*'|[^\s,;]+)'''
)


def diagnostic_text(value: str) -> str:
    """Redact credentials before truncation, including values echoed without labels."""
    for name, secret in os.environ.items():
        if secret and re.search(r"(?i)password|secret|token|private.*key", name):
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)",
                   "[redacted private key]", value, flags=re.S)
    value = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+", "[redacted URL]", value)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [redacted]", value)
    value = _SECRET.sub(r"\1[redacted]", value)
    value = re.sub(r"[A-Za-z0-9_+/=-]{32,}", "[redacted opaque value]", value)
    return "".join(character for character in value if character in "\n\t" or ord(character) >= 32)[-8000:]


def _safe_value(value: object, depth: int = 0) -> object:
    if depth >= 8:
        return "[diagnostic depth limit]"
    if isinstance(value, str):
        return diagnostic_text(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {diagnostic_text(str(key)): ("[redacted]" if re.search(
            r"(?i)password|passwd|secret|token|credential|private.*key", str(key)
        ) else _safe_value(item, depth + 1)) for key, item in list(mapping.items())[:32]}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_safe_value(item, depth + 1) for item in sequence[:32]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return diagnostic_text(str(value))


def record_update_failure(error: BaseException, *, connection_id: int | None = None,
                          details: object = None) -> Path | None:
    """Keep both the primary cause and cleanup failures; never capture locals/source."""
    causes: list[dict[str, object]] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(causes) < 8:
        seen.add(id(current))
        causes.append({
            "type": type(current).__name__, "message": diagnostic_text(str(current)),
            "locations": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                          for frame in traceback.extract_tb(current.__traceback__)[-16:]],
        })
        current = current.__cause__ or current.__context__
    payload = {"connection_id": connection_id, "version": settings.APP_VERSION,
               "environment": settings.APP_ENV, "causes": causes, "details": _safe_value(details)}
    try:
        if DIAGNOSTIC_ROOT.is_symlink():
            raise OSError("Symlinked diagnostic directory")
        DIAGNOSTIC_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        DIAGNOSTIC_ROOT.chmod(0o700)
        name = datetime.now(timezone.utc).strftime("update-%Y%m%dT%H%M%S-%f-") + uuid4().hex + ".json"
        path = DIAGNOSTIC_ROOT / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(payload, output, ensure_ascii=True)
            output.flush()
            os.fsync(output.fileno())
        previous = sorted((item for item in DIAGNOSTIC_ROOT.glob("update-*.json") if item != path), reverse=True)
        for stale in previous[99:]:
            stale.unlink(missing_ok=True)
        return path
    except OSError as storage_error:
        # A broken disk must not hide the original cause or turn failure into success.
        sys.stderr.write(f"Update diagnostic storage failed ({type(storage_error).__name__}); diagnostic follows:\n")
        sys.stderr.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return None
