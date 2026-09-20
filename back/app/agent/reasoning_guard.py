"""Driver-neutral guard against degenerate repeated model output."""

from __future__ import annotations

import hashlib
import re

from .contracts import AIMessage, ReasoningDegenerationError


MAX_REASONING_PATTERN_REPETITIONS = 30
_MAX_PATTERN_TOKENS = 64
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)


class ReasoningPatternGuard:
    """Detect one consecutive token pattern repeated beyond the accepted limit.

    The token window is deliberately bounded. Exact semantic blocks are tracked
    separately so a long repeated reasoning block is still detected without keeping
    its content or exposing it in the resulting error.
    """

    def __init__(self) -> None:
        self._tokens: list[str] = []
        self._last_block_signature: str | None = None
        self._repeated_block_count = 0
        self._snapshot_lengths: dict[str, int] = {}

    def observe(self, message: AIMessage) -> None:
        """Observe generated prose, resetting the streak on actual runtime activity."""

        is_thinking = message.type == "tool" and message.tool_name == "thinking"
        if message.type == "tool" and not is_thinking:
            self.reset()
            return
        if message.type not in {"text", "tool"} or not message.content:
            self.reset()
            return

        content = message.content
        if message.stream_mode == "snapshot" and message.stream_id:
            observed = self._snapshot_lengths.get(message.stream_id, 0)
            self._snapshot_lengths[message.stream_id] = max(observed, len(content))
            content = content[observed:]
        normalized = " ".join(content.casefold().split())
        tokens = _TOKEN_PATTERN.findall(normalized)
        if not tokens:
            return

        signature = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if signature == self._last_block_signature:
            self._repeated_block_count += 1
        else:
            self._last_block_signature = signature
            self._repeated_block_count = 1
        if (
            self._repeated_block_count > MAX_REASONING_PATTERN_REPETITIONS
            and self._contains_letters(tokens)
        ):
            self._raise_degeneration()

        for token in tokens:
            self._tokens.append(token)
            overflow = len(self._tokens) - (
                (MAX_REASONING_PATTERN_REPETITIONS + 1) * _MAX_PATTERN_TOKENS
            )
            if overflow > 0:
                del self._tokens[:overflow]
            self._check_repeated_suffix()

    def reset(self) -> None:
        """Forget prose observed before a concrete non-reasoning event."""

        self._tokens.clear()
        self._last_block_signature = None
        self._repeated_block_count = 0

    def _check_repeated_suffix(self) -> None:
        repetition_count = MAX_REASONING_PATTERN_REPETITIONS + 1
        max_pattern_size = min(
            _MAX_PATTERN_TOKENS,
            len(self._tokens) // repetition_count,
        )
        for pattern_size in range(1, max_pattern_size + 1):
            pattern = self._tokens[-pattern_size:]
            if not self._contains_letters(pattern):
                continue
            repeated_size = pattern_size * repetition_count
            repeated_start = len(self._tokens) - repeated_size
            if all(
                self._tokens[index] == self._tokens[index + pattern_size]
                for index in range(
                    repeated_start,
                    len(self._tokens) - pattern_size,
                )
            ):
                self._raise_degeneration()

    @staticmethod
    def _contains_letters(tokens: list[str]) -> bool:
        return any(any(character.isalpha() for character in token) for token in tokens)

    @staticmethod
    def _raise_degeneration() -> None:
        raise ReasoningDegenerationError(
            "Stopped the agent run because the same reasoning pattern was repeated "
            f"more than {MAX_REASONING_PATTERN_REPETITIONS} consecutive times."
        )


__all__ = [
    "MAX_REASONING_PATTERN_REPETITIONS",
    "ReasoningDegenerationError",
    "ReasoningPatternGuard",
]
