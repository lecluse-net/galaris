"""Bounded, model-safe runtime diagnostics."""

import re


def redact_logs(lines: list[str]) -> list[str]:
    result: list[str] = []
    budget = 200_000
    for raw in lines:
        line = raw[:2000]
        line = re.sub(r'''(?i)(password|token|secret|api[_-]?key|authorization)["']?\s*[=:]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)''', r"\1=[redacted]", line)
        line = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", line)
        line = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[redacted]", line)
        line = re.sub(r"https?://\S+|(?<!\w)/(?:[^\s/]+/)*[^\s]+|[A-Za-z]:\\\S+", "[redacted location]", line)
        line = line[:budget]
        result.append(line)
        budget -= len(line)
        if budget <= 0:
            break
    return result
