"""Driver-neutral guard against degenerate repeated model output."""

from __future__ import annotations

import hashlib
import re

from .contracts import AIMessage, ReasoningDegenerationError


MAX_REASONING_PATTERN_REPETITIONS = 30
_MAX_PATTERN_TOKENS = 64
_MAX_WORD_CHARS = 1024
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
        self._stream_id: str | None = None
        self._pending_word = ""
        self._oversized_word = False

    def observe(self, message: AIMessage) -> None:
        """Observe generated prose, resetting the streak on actual runtime activity."""

        is_thinking = message.type == "tool" and message.tool_name == "thinking"
        if message.type == "tool" and not is_thinking:
            self.reset()
            return
        if message.type not in {"text", "tool"}:
            self.reset()
            return

        content = message.content
        if message.stream_mode == "snapshot" and message.stream_id:
            observed = self._snapshot_lengths.get(message.stream_id, 0)
            self._snapshot_lengths[message.stream_id] = max(observed, len(content))
            content = content[observed:]
        if not content:
            if message.stream_complete and message.stream_id == self._stream_id:
                self._finish_word()
            return
        if message.stream_id != self._stream_id:
            self._finish_word()
            self._stream_id = message.stream_id
        normalized = content.casefold()
        tokens = _TOKEN_PATTERN.findall(normalized)

        # Anonymous messages are complete semantic blocks. A transport fragment is
        # never a block: repeated subword deltas can be one perfectly valid word.
        if message.stream_id is None and tokens:
            signature = hashlib.sha256(" ".join(normalized.split()).encode("utf-8")).hexdigest()
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

        for match in re.finditer(r"\w+|\W", normalized):
            token = match.group()
            if token[0].isalnum() or token[0] == "_":
                if not self._oversized_word:
                    self._pending_word += token
                    if len(self._pending_word) > _MAX_WORD_CHARS:
                        # Keep memory bounded without inventing word boundaries.
                        self._pending_word = ""
                        self._oversized_word = True
                        self._tokens.clear()
            else:
                self._finish_word()
                if not token.isspace():
                    self._observe_token(token)
        if message.stream_id is None or message.stream_complete:
            self._finish_word()

    def _finish_word(self) -> None:
        word = self._pending_word
        self._pending_word = ""
        self._oversized_word = False
        if word:
            self._observe_token(word)

    def _observe_token(self, token: str) -> None:
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
        self._pending_word = ""
        self._oversized_word = False
        self._stream_id = None

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
