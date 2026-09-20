"""Manage voice sessions running as background tasks."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from core.i18n import t
from loguru import logger

from .interface import CallTransport
from .session import VoiceSession


@dataclass(frozen=True, slots=True)
class VoiceCallInfo:
    call_id: str
    agent_id: int
    connection_id: int
    room_id: str
    transport_kind: str
    started_at: float
    conversation_room_id: UUID | None = None


@dataclass(slots=True)
class _ActiveVoiceCall:
    info: VoiceCallInfo
    task: asyncio.Task[None]
    stop_requested: asyncio.Event
    transport: CallTransport


class VoiceCallManager:
    """Track voice calls active in the backend process."""

    def __init__(self) -> None:
        self._active: dict[str, _ActiveVoiceCall] = {}
        self._activity_listeners: set[Callable[[bool], None]] = set()
        self._call_ended_listeners: set[
            Callable[[VoiceCallInfo], Awaitable[None]]
        ] = set()

    def has_active_calls(self) -> bool:
        """Return whether this backend process currently owns a live voice call."""

        return any(not active.task.done() for active in self._active.values())

    def register_activity_listener(self, listener: Callable[[bool], None]) -> None:
        """Subscribe a non-blocking callback to voice active/idle transitions."""

        self._activity_listeners.add(listener)

    def unregister_activity_listener(self, listener: Callable[[bool], None]) -> None:
        self._activity_listeners.discard(listener)

    def register_call_ended_listener(
        self,
        listener: Callable[[VoiceCallInfo], Awaitable[None]],
    ) -> None:
        """Subscribe an async adapter to terminal call transitions."""

        self._call_ended_listeners.add(listener)

    def unregister_call_ended_listener(
        self,
        listener: Callable[[VoiceCallInfo], Awaitable[None]],
    ) -> None:
        self._call_ended_listeners.discard(listener)

    def _notify_activity(self) -> None:
        active = self.has_active_calls()
        for listener in tuple(self._activity_listeners):
            try:
                listener(active)
            except Exception:
                logger.exception("Voice activity listener failed")

    async def _notify_call_ended(self, info: VoiceCallInfo) -> None:
        for listener in tuple(self._call_ended_listeners):
            try:
                await listener(info)
            except Exception:
                logger.exception(
                    "Voice call-ended listener failed call_id={}",
                    info.call_id,
                )

    @staticmethod
    def call_id_for(agent_id: int, connection_id: int, room_id: str) -> str:
        fingerprint = hashlib.sha256(
            f"{agent_id}\0{connection_id}\0{room_id}".encode()
        ).hexdigest()[:24]
        return f"voice-{agent_id}-{connection_id}-{fingerprint}"

    def start_agent_call(
        self,
        *,
        agent_id: int,
        connection_id: int,
        room_id: str,
        transport: CallTransport,
        language: str | None = None,
        remote_user_ids: tuple[str, ...] = (),
        conversation_room_id: UUID | None = None,
    ) -> tuple[VoiceCallInfo, bool]:
        """Start a direct transport-to-agent voice call in the background."""
        room_id = room_id.strip()
        if not room_id:
            raise ValueError(t("voice.manager_room_required", language))
        if len(room_id) > 512:
            raise ValueError(t("voice.manager_room_too_long", language))
        call_id = self.call_id_for(agent_id, connection_id, room_id)

        existing = self._active.get(call_id)
        if existing and not existing.task.done():
            return existing.info, False
        if existing:
            self._active.pop(call_id, None)

        info = VoiceCallInfo(
            call_id=call_id,
            agent_id=agent_id,
            connection_id=connection_id,
            room_id=room_id,
            transport_kind=transport.kind,
            started_at=time.time(),
            conversation_room_id=conversation_room_id,
        )
        session = VoiceSession(
            transport,
            room_id,
            connection_id=connection_id,
            remote_user_ids=remote_user_ids,
            conversation_room_id=conversation_room_id,
        )
        stop_requested = asyncio.Event()
        task = asyncio.create_task(
            self._run_agent(info, session, language, stop_requested),
            name=f"voice_call:{call_id}",
        )
        self._active[call_id] = _ActiveVoiceCall(
            info=info,
            task=task,
            stop_requested=stop_requested,
            transport=transport,
        )
        self._notify_activity()
        task.add_done_callback(lambda done, cid=call_id: self._on_done(cid, done))
        logger.info(
            "Voice call: start requested call_id={} agent={} transport={} room={}",
            call_id,
            agent_id,
            transport.kind,
            room_id,
        )
        return info, True

    async def stop_call(self, call_id: str) -> bool:
        active = self._active.get(call_id)
        if not active or active.task.done():
            self._active.pop(call_id, None)
            return False
        active.task.cancel()
        await asyncio.gather(active.task, return_exceptions=True)
        return True

    async def request_stop_call(self, call_id: str) -> bool:
        """Ask one live call to finish its current response, then hang up."""

        active = self._active.get(call_id)
        if not active or active.task.done():
            self._active.pop(call_id, None)
            return False
        active.stop_requested.set()
        return True

    async def request_stop_calls(
        self,
        *,
        agent_id: int,
        room_id: str | None = None,
        connection_id: int | None = None,
    ) -> int:
        """Request a graceful hangup for matching live calls."""

        targets = [
            active
            for active in self._active.values()
            if active.info.agent_id == agent_id
            and (room_id is None or active.info.room_id == room_id)
            and (
                connection_id is None
                or active.info.connection_id == connection_id
            )
            and not active.task.done()
        ]
        for active in targets:
            active.stop_requested.set()
        return len(targets)

    async def stop_calls(
        self,
        *,
        agent_id: int,
        room_id: str | None = None,
        connection_id: int | None = None,
    ) -> int:
        targets = [
            call_id
            for call_id, active in self._active.items()
            if active.info.agent_id == agent_id
            and (room_id is None or active.info.room_id == room_id)
            and (
                connection_id is None
                or active.info.connection_id == connection_id
            )
            and not active.task.done()
        ]
        count = 0
        for call_id in targets:
            if await self.stop_call(call_id):
                count += 1
        return count

    async def stop_all_calls(self) -> int:
        """Cancel every active call during application shutdown or reload."""
        targets = [
            call_id
            for call_id, active in self._active.items()
            if not active.task.done()
        ]
        count = 0
        for call_id in targets:
            if await self.stop_call(call_id):
                count += 1
        return count

    async def stop_transport_calls(self, transport_kind: str) -> int:
        """Cancel every active call owned by one messaging transport."""

        targets = [
            call_id
            for call_id, active in self._active.items()
            if active.info.transport_kind == transport_kind
            and not active.task.done()
        ]
        count = 0
        for call_id in targets:
            if await self.stop_call(call_id):
                count += 1
        return count

    def active_calls(self, *, agent_id: int | None = None) -> list[VoiceCallInfo]:
        return [
            active.info
            for active in self._active.values()
            if not active.task.done()
            and (agent_id is None or active.info.agent_id == agent_id)
        ]

    def active_transport(self, call_id: str) -> CallTransport | None:
        """Return the transport for a live call owned by this process."""

        active = self._active.get(call_id)
        if active is None or active.task.done():
            return None
        return active.transport

    async def _run_agent(
        self,
        info: VoiceCallInfo,
        session: VoiceSession,
        language: str | None,
        stop_requested: asyncio.Event,
    ) -> None:
        try:
            await session.run_agent(
                agent_id=info.agent_id,
                language=language or "fr",
                stop_requested=stop_requested,
            )
        except asyncio.CancelledError:
            logger.info("Voice call: cancelled call_id={}", info.call_id)
            raise
        except Exception:
            logger.exception("Voice call: failed call_id={}", info.call_id)
        finally:
            self._active.pop(info.call_id, None)
            self._notify_activity()
            await self._notify_call_ended(info)

    def _on_done(self, call_id: str, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("Voice call: task ended with error call_id={} error={}", call_id, exc)


voice_call_manager = VoiceCallManager()
