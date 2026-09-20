"""Isolated, resource-bounded PDF text worker; no application bootstrap or DB access."""

from __future__ import annotations

import io
import resource
import sys
from itertools import islice

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARS = 20_000
MAX_PAGES = 100


def extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    remaining = MAX_TEXT_CHARS
    for page in islice(reader.pages, MAX_PAGES):
        part = (page.extract_text() or "")[:remaining]
        if part.strip():
            parts.append(part)
            remaining -= len(part) + 2
        if remaining <= 0:
            break
    return "\n\n".join(parts)[:MAX_TEXT_CHARS]


def main() -> None:
    # Even a single malicious page must not exhaust the API process.
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("PDF exceeds extraction input limit")
    sys.stdout.buffer.write(extract_pdf_text(data).encode("utf-8"))


if __name__ == "__main__":
    main()
