"""Pure adaptation of Claude partial-message events to Galaris trace blocks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


@dataclass
class ClaudeStreamTrace:
    """Collect complete public thinking blocks without emitting token fragments."""

    _thinking: dict[int, str] = field(default_factory=dict[int, str])

    @staticmethod
    def _message(content: str) -> dict[str, object]:
        return {
            "type": "tool",
            "tool_name": "thinking",
            "content": content,
            "success": True,
        }

    def consume(self, raw_event: object) -> list[dict[str, object]]:
        event = _mapping(raw_event)
        event_type = event.get("type")
        index = event.get("index")
        if not isinstance(index, int):
            return []
        if event_type == "content_block_delta":
            delta = _mapping(event.get("delta"))
            if delta.get("type") == "thinking_delta":
                text = delta.get("thinking")
                if isinstance(text, str) and text:
                    self._thinking[index] = self._thinking.get(index, "") + text
            return []
        if event_type != "content_block_stop":
            return []
        content = self._thinking.pop(index, "").strip()
        return [self._message(content)] if content else []

    def finish(self) -> list[dict[str, object]]:
        messages = [
            self._message(content.strip())
            for _, content in sorted(self._thinking.items())
            if content.strip()
        ]
        self._thinking.clear()
        return messages


__all__ = ["ClaudeStreamTrace"]
