"""Exact JSON validation and extraction for Data documents."""
import json
import math
from typing import Any, cast

MAX_BYTES = 2_000_000

def parse_json(content: str, *, historical: bool = False) -> Any:
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Dataset content exceeds 2,000,000 bytes")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in items:
            if name in result and not historical:
                raise ValueError("Dataset JSON contains duplicate object keys")
            result[name] = value
        return result

    def constant(_value: str) -> Any:
        raise ValueError("Dataset JSON requires finite numbers")

    try:
        value: Any = json.loads(content, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, UnicodeError):
        raise ValueError("Dataset requires valid UTF-8 JSON") from None
    stack: list[tuple[Any, int]] = [(value, 0)]
    count = 0
    while stack:
        current, depth = stack.pop()
        count += 1
        if depth > 32 or count > 20_000:
            raise ValueError("Dataset exceeds the depth or item limit")
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("Dataset JSON requires finite numbers")
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in cast(dict[str, Any], current).values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in cast(list[Any], current))
    return value


def encode(value: Any) -> str:
    try:
        content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Dataset requires finite JSON values") from None
    parse_json(content)
    return content


def validate(content: str) -> None:
    parse_json(content)


def extract(content: str) -> str:
    return json.dumps(parse_json(content), ensure_ascii=False, sort_keys=True)
