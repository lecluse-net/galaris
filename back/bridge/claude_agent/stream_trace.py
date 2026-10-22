"""Pure adaptation of Claude partial-message events to Galaris trace blocks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast
import json


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


@dataclass
class ClaudeStreamTrace:
    """Collect complete public thinking blocks without emitting token fragments."""

    _thinking: dict[int, str] = field(default_factory=dict[int, str])
    _tools: dict[str, tuple[str, dict[str, object]]] = field(default_factory=dict[str, tuple[str, dict[str, object]]])
    _completed_tools: set[str] = field(default_factory=set[str])

    def record_tool_call(self, identifier: str, name: str, arguments: dict[str, object]) -> None:
        self._tools[identifier] = (name, arguments)

    def complete_tool_result(self, identifier: str, content: object, *, failed: bool = False,
                             result: dict[str, object] | None = None, elapsed: float = 0.0) -> dict[str, object] | None:
        if identifier in self._completed_tools or identifier not in self._tools:
            return None
        self._completed_tools.add(identifier)
        name, arguments = self._tools[identifier]
        failed = failed or _mapping(result).get("isError") is True
        if isinstance(content, list):
            text = "\n".join(str(block.get("text") or "") for raw in cast(list[object], content)
                             if (block := _mapping(raw)).get("type") == "text")
        else:
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        return {"type": "tool", "tool_name": name, "tool_call_external_id": identifier,
                "tool_arguments": arguments, "tool_result": result if result is not None else {"output": text[:8_000]},
                "content": text[:8_000], "success": not failed, "execution_time": elapsed, "cost": 0.0}

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
