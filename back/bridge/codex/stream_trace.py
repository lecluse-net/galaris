"""Pure state machine adapting Codex App Server text items to Galaris traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
import json
from typing import cast


_COMMENTARY_PHASES = frozenset({"commentary", "analysis"})
_FINAL_PHASES = frozenset({"final", "final_answer"})


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _tool_payload(value: object) -> dict[str, object]:
    payload: dict[str, object] = dict(_mapping(value))
    if not isinstance(value, Mapping):
        payload = {"value": value}
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    return payload if len(encoded) <= 8_000 else {"truncated": True, "preview": encoded[:4_000]}


@dataclass
class _TextItem:
    text: str = ""
    phase: str = ""
    completed: bool = False
    stream_id: str = ""


@dataclass
class CodexStreamTrace:
    """Collect public Codex summaries while keeping the final answer separate."""

    _agent_items: dict[str, _TextItem] = field(default_factory=dict[str, _TextItem])
    _agent_order: list[str] = field(default_factory=list[str])
    _reasoning_items: dict[tuple[str, int], _TextItem] = field(
        default_factory=dict[tuple[str, int], _TextItem]
    )
    _reasoning_order: list[tuple[str, int]] = field(
        default_factory=list[tuple[str, int]]
    )
    _emitted_thinking: dict[str, str] = field(
        default_factory=dict[str, str]
    )
    _active_thinking_streams: dict[str, str] = field(
        default_factory=dict[str, str]
    )
    _thinking_revisions: dict[str, int] = field(default_factory=dict[str, int])
    _anonymous_agent_sequence: int = 0
    _anonymous_reasoning_sequence: int = 0
    _active_anonymous_agent_id: str | None = None
    _active_anonymous_reasoning_id: str | None = None
    _streamed_final_items: set[str] = field(default_factory=set[str])
    _completed_tools: set[str] = field(default_factory=set[str])

    def complete_tool_item(self, item: Mapping[str, object]) -> dict[str, object] | None:
        """Project completed SDK tool items, using their invocation identity once."""
        kind = item.get("type")
        if kind not in {"mcpToolCall", "dynamicToolCall", "commandExecution", "fileChange", "webSearch"}:
            return None
        identifier = str(item.get("id") or "")
        if not identifier or identifier in self._completed_tools:
            return None
        status = item.get("status")
        if status == "inProgress":
            return None
        self._completed_tools.add(identifier)
        success = status not in {"failed", "declined", "interrupted"} and item.get("success") is not False
        arguments: object
        result: object
        content: object
        if kind == "commandExecution":
            name = "command_execution"
            arguments = {"command": item.get("command"), "cwd": item.get("cwd")}
            result = {"exit_code": item.get("exitCode"), "output": item.get("aggregatedOutput")}
            content = item.get("aggregatedOutput")
            success = success and item.get("exitCode") in (None, 0)
        elif kind == "fileChange":
            name = "apply_patch"
            arguments = {"changes": item.get("changes")}
            result = {"status": status, "changes": item.get("changes")}
            content = json.dumps(item.get("changes"), ensure_ascii=False)
        elif kind == "webSearch":
            name = "web_search"
            arguments = {"query": item.get("query"), "action": item.get("action")}
            result = dict(item)
            content = item.get("query")
        else:
            name = str(item.get("tool") or "tool")
            arguments = item.get("arguments")
            result = item.get("result") if kind == "mcpToolCall" else {"content": item.get("contentItems")}
            outcome = _mapping(result)
            blocks = outcome.get("content")
            texts = [str(block.get("text") or "") for raw in cast(Sequence[object], blocks)
                     if isinstance(raw, Mapping) and (block := cast(Mapping[str, object], raw)).get("type") in {"text", "inputText"}
                     ] if isinstance(blocks, list) else []
            content = "\n".join(texts)
            success = success and not item.get("error") and outcome.get("isError") is not True
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {"raw": arguments}
        error = item.get("error")
        if error:
            result = {"result": result, "error": error}
        duration = item.get("durationMs")
        return {"type": "tool", "tool_name": name, "tool_call_external_id": identifier,
                "tool_arguments": _tool_payload(arguments),
                "tool_result": _tool_payload(result),
                "content": str(content or json.dumps(result, ensure_ascii=False, default=str))[:8_000],
                "success": success, "execution_time": duration / 1_000 if isinstance(duration, (int, float)) else 0.0}

    @staticmethod
    def _normalized_phase(phase: str | None) -> str:
        return (phase or "").strip().lower().replace("-", "_")

    @staticmethod
    def _thinking_message(content: str, *, stream_id: str) -> dict[str, object]:
        return {
            "type": "tool",
            "tool_name": "thinking",
            "content": content,
            "success": True,
            "stream_id": stream_id,
        }

    @staticmethod
    def _append_completed_text(current: str, completed: str) -> tuple[str, bool]:
        """Reconcile a completion without ever discarding an observed fragment."""

        normalized = completed.strip()
        if not normalized:
            return current, False
        if not current:
            return normalized, False
        if normalized == current or current.startswith(normalized):
            return current, False
        if normalized.startswith(current):
            return current + normalized[len(current):], False
        if current.endswith(normalized):
            return current, False
        return f"{current}\n\n{normalized}", True

    def _resolve_agent_id(self, item_id: str) -> str:
        explicit = item_id.strip()
        if explicit:
            anonymous = self._active_anonymous_agent_id
            if (
                anonymous is not None
                and anonymous != explicit
                and anonymous in self._agent_items
                and explicit not in self._agent_items
            ):
                self._agent_items[explicit] = self._agent_items.pop(anonymous)
                self._agent_order[self._agent_order.index(anonymous)] = explicit
                self._active_anonymous_agent_id = None
            return explicit
        active = self._active_anonymous_agent_id
        if active is not None:
            return active
        self._anonymous_agent_sequence += 1
        active = f"anonymous-agent-{self._anonymous_agent_sequence}"
        self._active_anonymous_agent_id = active
        return active

    def _resolve_reasoning_id(self, item_id: str) -> str:
        explicit = item_id.strip()
        if explicit:
            anonymous = self._active_anonymous_reasoning_id
            if (
                anonymous is not None
                and anonymous != explicit
                and any(key[0] == anonymous for key in self._reasoning_items)
                and not any(key[0] == explicit for key in self._reasoning_items)
            ):
                renamed: list[tuple[str, int]] = []
                for key in self._reasoning_order:
                    if key[0] != anonymous:
                        renamed.append(key)
                        continue
                    replacement = (explicit, key[1])
                    self._reasoning_items[replacement] = self._reasoning_items.pop(key)
                    renamed.append(replacement)
                self._reasoning_order = renamed
                self._active_anonymous_reasoning_id = None
            return explicit
        active = self._active_anonymous_reasoning_id
        if active is not None:
            return active
        self._anonymous_reasoning_sequence += 1
        active = f"anonymous-reasoning-{self._anonymous_reasoning_sequence}"
        self._active_anonymous_reasoning_id = active
        return active

    def _agent_item(self, item_id: str) -> _TextItem:
        item_id = self._resolve_agent_id(item_id)
        if item_id not in self._agent_items:
            self._agent_items[item_id] = _TextItem(
                stream_id=f"codex:agent:{item_id}",
            )
            self._agent_order.append(item_id)
        return self._agent_items[item_id]

    def _reasoning_item(self, item_id: str, summary_index: int) -> _TextItem:
        key = (self._resolve_reasoning_id(item_id), summary_index)
        if key not in self._reasoning_items:
            self._reasoning_items[key] = _TextItem(
                stream_id=f"codex:reasoning:{key[0]}:{summary_index}",
            )
            self._reasoning_order.append(key)
        return self._reasoning_items[key]

    def record_agent_delta(
        self,
        item_id: str,
        delta: str,
        *,
        phase: str | None = None,
    ) -> tuple[str, dict[str, object] | None]:
        """Expose public commentary immediately while keeping final text separate."""

        if not delta:
            return "", None
        item_id = self._resolve_agent_id(item_id)
        item = self._agent_item(item_id)
        item.text += delta
        normalized_phase = self._normalized_phase(phase)
        if normalized_phase:
            item.phase = normalized_phase
        if item.phase in _FINAL_PHASES:
            self._streamed_final_items.add(item_id)
            return delta, None
        if item.phase in _COMMENTARY_PHASES:
            return "", self._emit_thinking(item.stream_id, item.text)
        return "", None

    def complete_agent_item(
        self,
        item_id: str,
        text: str,
        *,
        phase: str | None = None,
    ) -> list[dict[str, object]]:
        """Complete one public agent message and emit commentary as thinking."""

        item_id = self._resolve_agent_id(item_id)
        item = self._agent_item(item_id)
        item.text, divergent = self._append_completed_text(item.text, text)
        normalized_phase = self._normalized_phase(phase)
        if normalized_phase:
            item.phase = normalized_phase
        item.completed = True
        if self._active_anonymous_agent_id == item_id:
            self._active_anonymous_agent_id = None
        if item.phase in _COMMENTARY_PHASES:
            message = self._emit_thinking(
                item.stream_id,
                item.text,
                force_new_block=divergent,
            )
            return [message] if message is not None else []
        return []

    def record_reasoning_delta(
        self,
        item_id: str,
        summary_index: int,
        delta: str,
    ) -> dict[str, object] | None:
        """Immediately expose a public reasoning-summary delta, never private thought."""

        if not delta:
            return None
        item = self._reasoning_item(item_id, summary_index)
        item.text += delta
        return self._emit_thinking(item.stream_id, item.text)

    def complete_reasoning_item(
        self,
        item_id: str,
        summaries: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
        item_id = self._resolve_reasoning_id(item_id)
        divergent_segments: set[int] = set()
        for summary_index, text in enumerate(summaries):
            item = self._reasoning_item(item_id, summary_index)
            item.text, divergent = self._append_completed_text(item.text, text)
            if divergent:
                divergent_segments.add(summary_index)
            item.completed = True

        messages: list[dict[str, object]] = []
        for reasoning_id, summary_index in self._reasoning_order:
            if reasoning_id != item_id:
                continue
            item = self._reasoning_items[(reasoning_id, summary_index)]
            item.completed = True
            message = self._emit_thinking(
                item.stream_id,
                item.text,
                force_new_block=summary_index in divergent_segments,
            )
            if message is not None:
                messages.append(message)
        if self._active_anonymous_reasoning_id == item_id:
            self._active_anonymous_reasoning_id = None
        return messages

    def _emit_thinking(
        self,
        stream_id: str,
        text: str,
        *,
        force_new_block: bool = False,
    ) -> dict[str, object] | None:
        emitted = self._emitted_thinking.get(stream_id, "")
        if not text or text == emitted:
            return None
        output_stream_id = self._active_thinking_streams.get(stream_id, stream_id)
        if force_new_block and emitted:
            revision = self._thinking_revisions.get(stream_id, 0) + 1
            self._thinking_revisions[stream_id] = revision
            output_stream_id = f"{stream_id}:revision:{revision}"
            self._active_thinking_streams[stream_id] = output_stream_id
        self._emitted_thinking[stream_id] = text
        content = text[len(emitted):] if emitted and text.startswith(emitted) else text
        if force_new_block:
            content = content.removeprefix("\n\n")
        return (
            self._thinking_message(content, stream_id=output_stream_id)
            if content
            else None
        )

    def finish(self) -> tuple[list[dict[str, object]], str, bool]:
        """Flush deferred summaries and resolve the single final assistant answer."""

        thinking: list[dict[str, object]] = []
        for item_id, summary_index in self._reasoning_order:
            item = self._reasoning_items[(item_id, summary_index)]
            message = self._emit_thinking(
                item.stream_id,
                item.text,
            )
            if message is not None:
                thinking.append(message)

        explicit_final_ids = [
            item_id
            for item_id in self._agent_order
            if self._agent_items[item_id].phase in _FINAL_PHASES
            and self._agent_items[item_id].text.strip()
        ]
        deferred_ids = [
            item_id
            for item_id in self._agent_order
            if not self._agent_items[item_id].phase
            and self._agent_items[item_id].text.strip()
        ]
        final_id = explicit_final_ids[-1] if explicit_final_ids else (
            deferred_ids[-1] if deferred_ids else None
        )

        for item_id in self._agent_order:
            item = self._agent_items[item_id]
            if item_id == final_id:
                continue
            message = self._emit_thinking(item.stream_id, item.text)
            if message is not None:
                thinking.append(message)

        final_text = self._agent_items[final_id].text.strip() if final_id else ""
        return (
            thinking,
            final_text,
            final_id in self._streamed_final_items if final_id else False,
        )


__all__ = ["CodexStreamTrace"]
