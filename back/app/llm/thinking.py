"""Project SDK reasoning without changing its native history or opaque metadata."""

from typing import cast

from pydantic_ai.messages import ThinkingPart


def thinking_content(part: ThinkingPart) -> str:
    """Prefer available raw reasoning; a summary must not hide a generating loop."""
    raw = (part.provider_details or {}).get("raw_content")
    if isinstance(raw, list):
        blocks = [value for value in cast(list[object], raw) if isinstance(value, str)]
        if any(blocks):
            return "\n\n".join(blocks)
    return part.content
