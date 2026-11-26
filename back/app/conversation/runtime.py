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
        self._dirty_block: AIMessage | None = None
        self._positions: dict[str, int] = {}

    def current_event(self) -> ConversationRuntimeEvent:
        return ConversationRuntimeEvent(
            round_id=self.round_id, topic_id=self.topic_id, attempt=self.attempt,
            sequence=self._sequence, kind="snapshot", result=public_ai_result(self.result).model_copy(deep=True),
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
            block = self.result.add_message(message.model_copy(deep=True), stream_positions=self._positions)
            self._sequence += 1
            if self._publication is not None and not self._publication.done():
                # Plain fragments of one identified block have no independent
                # accounting or tool updates. A replacement of that block spans
                # the whole gap; mixed/legacy bursts still use the full snapshot.
                simple = (
                    block is not None and bool(message.stream_id)
                    and (message.type == "text" or (message.type == "tool" and message.tool_name == "thinking"))
                    and message.stream_mode == "delta" and message.usage is None
                    and not message.cost and not message.execution_time
                )
                if not self._dirty:
                    self._dirty_block = block if simple else None
                elif not simple or self._dirty_block is not block:
                    self._dirty_block = None
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
            block = self._dirty_block
            self._dirty_block = None
            if block is None:
                event = self.current_event()
            else:
                event = ConversationRuntimeEvent(
                    round_id=self.round_id, topic_id=self.topic_id, attempt=self.attempt,
                    sequence=self._sequence, base_sequence=event.sequence, kind="message",
                    message=public_ai_message(block).model_copy(update={"stream_mode": "snapshot"}),
                    success=block.success,
                )

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
        # Drivers with identified blocks can reconcile the trace in two passes.
        # Legacy traces can also match anonymous blocks by content below.
        positions = {item.stream_id: i for i, item in enumerate(result.messages) if item.stream_id}
        if len(positions) == len(result.messages) and len(self._positions) == len(self.result.messages):
            omitted: dict[int, list[AIMessage]] = {}
            anchor = -1
            for message in self.result.messages:
                index = positions.get(message.stream_id) if message.stream_id else None
                if index is None:
                    if message.type != "text":
                        omitted.setdefault(anchor, []).append(message.model_copy(deep=True))
                else:
                    anchor = index
                    match = result.messages[index]
                    if match.type == message.type and message.content.startswith(match.content):
                        match.content = message.content
            if omitted:
                merged = omitted.get(-1, [])
                for index, message in enumerate(result.messages):
                    merged.append(message)
                    merged.extend(omitted.get(index, ()))
                result.messages = merged
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
        self, *, success: bool, result: AIResult | None = None, reconciled: bool = False,
    ) -> None:
        async with self._lock:
            if self._finished:
                return
            self._finished = True
            if _active_streams.get(self.room_id) is self:
                del _active_streams[self.room_id]
            if self._publication is not None:
                await self._publication
            # The scheduler persists the reconciled snapshot before it releases
            # the lease. Reuse that trace when publishing the same terminal state.
            if result is None or reconciled:
                public = public_ai_result(self.result if result is None else result).model_copy(deep=True)
            else:
                public = public_ai_result(self.snapshot(result))
            public.success = success
            await self._publish("finished", result=public, success=success)
