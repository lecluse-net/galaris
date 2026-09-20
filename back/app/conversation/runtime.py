"""One AIResult, composed of identified AIMessages, shared by text and voice."""

from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from app.agent import AIMessage, AIResult

from .contracts import ConversationRuntimeEvent, public_ai_message, public_ai_result


_active_streams: dict[UUID, ConversationRuntimeStream] = {}


def room_runtime_snapshot(room_id: UUID) -> ConversationRuntimeEvent | None:
    """Read current progress; callers must authorize access to the room."""
    stream = _active_streams.get(room_id)
    return stream.current_event() if stream is not None else None


class ConversationRuntimeStream:
    """Accumulate message deltas and publish an ordered, terminally closed stream."""

    def __init__(
        self, *, room_id: UUID, round_id: UUID,
        topic_id: UUID | None = None, attempt: int = 1,
    ) -> None:
        self.room_id = room_id
        self.round_id = round_id
        self.topic_id = topic_id
        self.attempt = attempt
        self.result = AIResult(prompt="")
        self._sequence = -1
        self._finished = False
        self._lock = asyncio.Lock()
        self._publication: asyncio.Task[None] | None = None
        self._dirty = False

    def current_event(self) -> ConversationRuntimeEvent:
        return ConversationRuntimeEvent(
            round_id=self.round_id, topic_id=self.topic_id, attempt=self.attempt,
            sequence=self._sequence, kind="snapshot", result=public_ai_result(self.snapshot()),
        )

    async def _publish(
        self, kind: Literal["started", "message", "reset", "finished"], *, message: AIMessage | None = None,
        result: AIResult | None = None, success: bool = True,
    ) -> None:
        from .facade import publish_runtime_event

        self._sequence += 1
        await publish_runtime_event(
            self.room_id,
            ConversationRuntimeEvent(
                round_id=self.round_id, topic_id=self.topic_id,
                attempt=self.attempt, sequence=self._sequence,
                kind=kind, message=message, result=result, success=success,
            ),
        )

    async def start(self) -> None:
        async with self._lock:
            if self._sequence < 0 and not self._finished:
                _active_streams[self.room_id] = self
                await self._publish("started")

    async def append(self, message: AIMessage) -> None:
        async with self._lock:
            if self._finished:
                return
            self.result.add_message(message.model_copy(deep=True))
            self._sequence += 1
            if self._publication is not None and not self._publication.done():
                # A slow listener needs only the latest cumulative state, never an
                # unbounded queue of fragments. Generation remains independent.
                self._dirty = True
            else:
                event = ConversationRuntimeEvent(
                    round_id=self.round_id, topic_id=self.topic_id, attempt=self.attempt,
                    sequence=self._sequence, kind="message",
                    message=public_ai_message(message), success=message.success,
                )
                self._publication = asyncio.create_task(self._drain(event))
        await asyncio.sleep(0)

    async def _drain(self, event: ConversationRuntimeEvent) -> None:
        from .facade import publish_runtime_event

        while True:
            await publish_runtime_event(self.room_id, event)
            if not self._dirty:
                return
            self._dirty = False
            event = self.current_event()

    async def reset(self) -> None:
        async with self._lock:
            if self._finished:
                return
            if self._publication is not None:
                await self._publication
            self.result.messages = [
                message.model_copy(update={"type": "tool", "tool_name": "thinking"})
                if message.type == "text" else message
                for message in self.result.messages
            ]
            self.result.result = ""
            await self._publish("reset")

    def snapshot(self, terminal: AIResult | None = None) -> AIResult:
        """Retain observed trace messages when a terminal producer omits them."""
        if terminal is None:
            return self.result.model_copy(deep=True)
        result = terminal.model_copy(deep=True)
        if not result.messages:
            result.messages = self.result.model_copy(deep=True).messages
            return result
        insertion = 0
        for message in self.result.messages:
            match = next((item for item in result.messages if (
                message.stream_id == item.stream_id
                if message.stream_id and item.stream_id
                else item.type == message.type and item.tool_name == message.tool_name
                and message.content in item.content
            )), None)
            if match is not None:
                if match.type == message.type and message.content.startswith(match.content):
                    match.content = message.content
                insertion = result.messages.index(match) + 1
            elif message.type != "text":
                result.messages.insert(insertion, message.model_copy(deep=True))
                insertion += 1
        return result

    async def finish(
        self, *, success: bool, result: AIResult | None = None,
    ) -> None:
        async with self._lock:
            if self._finished:
                return
            self._finished = True
            if _active_streams.get(self.room_id) is self:
                del _active_streams[self.room_id]
            if self._publication is not None:
                await self._publication
            terminal = self.snapshot(result)
            terminal.success = success
            await self._publish("finished", result=public_ai_result(terminal), success=success)
