"""In-process fan-out for Matrix `/sync` events shared by messages and VoIP."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MatrixRoomEvent:
    connection_id: int
    room_id: str
    event_id: str
    sender: str
    type: str
    content: dict[str, Any]
    origin_server_ts: int
    raw: dict[str, Any]


class MatrixEventSubscription:
    def __init__(
        self,
        bus: "MatrixEventBus",
        connection_id: int,
        queue: "asyncio.Queue[MatrixRoomEvent]",
    ) -> None:
        self._bus = bus
        self.connection_id = connection_id
        self.queue = queue
        self._closed = False

    async def get(self) -> MatrixRoomEvent:
        return await self.queue.get()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._bus.unsubscribe(self.connection_id, self.queue)


class MatrixEventBus:
    """Broadcast events without starting a second competing Matrix `/sync`."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[MatrixRoomEvent]]] = defaultdict(set)
        self._recent: dict[int, deque[MatrixRoomEvent]] = defaultdict(
            lambda: deque(maxlen=256)
        )

    def subscribe(self, connection_id: int, *, replay: bool = True) -> MatrixEventSubscription:
        queue: asyncio.Queue[MatrixRoomEvent] = asyncio.Queue(maxsize=512)
        if replay:
            for event in self._recent[connection_id]:
                queue.put_nowait(event)
        self._subscribers[connection_id].add(queue)
        return MatrixEventSubscription(self, connection_id, queue)

    def unsubscribe(
        self,
        connection_id: int,
        queue: "asyncio.Queue[MatrixRoomEvent]",
    ) -> None:
        subscribers = self._subscribers.get(connection_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(connection_id, None)

    async def publish(self, event: MatrixRoomEvent) -> None:
        recent = self._recent[event.connection_id]
        if event.event_id and any(
            item.event_id == event.event_id for item in recent
        ):
            return
        recent.append(event)
        for queue in tuple(self._subscribers.get(event.connection_id, ())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def reset_for_tests(self) -> None:
        self._subscribers.clear()
        self._recent.clear()


matrix_event_bus = MatrixEventBus()
