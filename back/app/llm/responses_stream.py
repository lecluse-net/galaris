"""Complete function argument deltas for Responses SDK consumers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.util import as_dict


@dataclass
class _FunctionArguments:
    arguments: dict[str, str] = field(default_factory=lambda: {})
    inserted_events: int = 0

    def complete(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("type")
        item = as_dict(event.get("item"))
        identifier = str(event.get("item_id") or item.get("id") or "")
        if event_type == "response.output_item.added" and item.get("type") == "function_call":
            self.arguments[identifier] = str(item.get("arguments") or "")
        elif event_type == "response.function_call_arguments.delta":
            if identifier in self.arguments:
                self.arguments[identifier] += str(event.get("delta") or "")
        elif event_type == "response.function_call_arguments.done" or (
            event_type == "response.output_item.done" and item.get("type") == "function_call"
        ):
            final = event.get("arguments") if event_type == "response.function_call_arguments.done" else item.get("arguments")
            if identifier not in self.arguments or not isinstance(final, str):
                return None
            emitted = self.arguments[identifier]
            if not final.startswith(emitted):
                # Appending contradictory bytes would produce different tool inputs
                # from the authoritative provider result. Fail before tool execution.
                raise RuntimeError("Responses function arguments disagree with their streamed prefix.")
            self.arguments[identifier] = final
            if suffix := final[len(emitted):]:
                return {
                    "type": "response.function_call_arguments.delta",
                    "item_id": identifier,
                    "output_index": event.get("output_index", 0),
                    "delta": suffix,
                }
        elif event_type in {"response.completed", "response.incomplete", "response.failed", "error"}:
            self.arguments.clear()
        return None

    def frame(self, lines: list[str]) -> list[str]:
        data = "\n".join(line[5:].lstrip(" ") for line in lines if line.startswith("data:"))
        try:
            decoded: object = json.loads(data)
        except json.JSONDecodeError:
            return lines
        if not isinstance(decoded, dict):
            return lines
        event = as_dict(decoded)
        extra = self.complete(event)
        sequence = event.get("sequence_number")
        prefix: list[str] = []
        if extra is not None:
            extra["sequence_number"] = (sequence if isinstance(sequence, int) else 0) + self.inserted_events
            prefix = [f'event: {extra["type"]}', "data: " + json.dumps(extra), ""]
            self.inserted_events += 1
        if self.inserted_events and isinstance(sequence, int):
            # Keep event numbers ordered when an extra delta precedes a done frame.
            event["sequence_number"] = sequence + self.inserted_events
            lines = [line for line in lines if not line.startswith("data:")]
            lines.insert(len(lines) - 1 if lines and lines[-1] == "" else len(lines),
                         "data: " + json.dumps(event))
        return [*prefix, *lines]


async def complete_function_argument_deltas(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Relay SSE frames, filling only the missing suffix from completed calls.

    Some providers send arguments only in done events. Pydantic AI builds its
    function calls from added/delta events, ignoring these final snapshots.
    Buffer one SSE frame so an injected delta precedes the original event header.
    Existing complete deltas, call identities and unrelated frames are preserved.
    """
    state = _FunctionArguments()
    frame: list[str] = []
    async for line in lines:
        frame.append(line)
        if line == "":
            for normalized in state.frame(frame):
                yield normalized
            frame = []
    if frame:
        for normalized in state.frame(frame):
            yield normalized
