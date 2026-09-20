"""Shared LLM cost calculations for executors and the Hermes proxy."""

from __future__ import annotations


def token_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    input_rate: float,
    output_rate: float,
    cached_input_rate: float | None = None,
    input_includes_cache: bool = False,
) -> float:
    """Calculate cost from rates expressed per million tokens.

    Some protocols include cache tokens in prompt tokens, while SDK usage may expose
    them separately. The explicit flag prevents double-counting across those conventions.
    """
    cache_rate = input_rate if cached_input_rate is None else cached_input_rate
    cache_read = max(0, int(cache_read_tokens))
    cache_write = max(0, int(cache_write_tokens))
    billed_input = max(0, int(input_tokens))
    if input_includes_cache:
        billed_input = max(0, billed_input - cache_read - cache_write)

    return (
        billed_input * float(input_rate)
        + cache_read * float(cache_rate)
        + cache_write * float(input_rate)
        + max(0, int(output_tokens)) * float(output_rate)
    ) / 1_000_000.0
