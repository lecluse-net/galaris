"""Audio-call transport interface implemented once per platform.

Transports join calls and expose inbound and outbound PCM streams. Their handle is opaque;
session orchestration lives in ``app.voice.session``.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from .models import AudioFrame


class CallTransport(ABC):
    """Real-time audio-call transport without AI processing."""

    kind: str = ""

    @abstractmethod
    async def join(self, room_id: str) -> Any:
        """Join a room call and return an opaque media-session handle."""
        ...

    @abstractmethod
    async def leave(self, handle: Any) -> None:
        """Leave the call and release media resources."""
        ...

    async def terminate(self, handle: Any) -> None:
        """End the provider call after an explicit local hangup request.

        Transports without a distinct provider-wide termination operation fall
        back to leaving their own media session.
        """

        await self.leave(handle)

    @abstractmethod
    def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
        """Yield inbound PCM audio frames from the remote participant."""
        ...

    @abstractmethod
    async def send_audio(self, handle: Any, frames: AsyncIterator[AudioFrame]) -> None:
        """Consume a PCM stream and send it to the remote participant."""
        ...

    async def interrupt_output(self, handle: Any) -> None:
        """Discard audio queued for playback after a human barge-in.

        Transports with no internal playback buffer may keep this default no-op.
        The application-level generation guard still discards stale future frames.
        """
        del handle

    async def wait_output_ready(self, handle: Any) -> None:
        """Wait until newly connected listeners can receive the first audio.

        Most transports can send immediately. MCU-based transports may need a
        short subscription grace period after advertising their publisher, or
        the beginning of the first utterance is sent before remote listeners
        have attached.
        """
        del handle

    async def wait_input_ready(self, handle: Any) -> None:
        """Wait until the remote audio track is actually delivering PCM.

        The default is immediate for transports whose ``join`` contract already
        guarantees bidirectional media. MCU transports override this so the
        initial greeting never invites the caller to speak into a subscriber
        connection that is not receiving audio yet.
        """
        del handle

    async def wait_output_drained(self, handle: Any) -> None:
        """Wait until already submitted audio has actually finished playing.

        Transports without an additional playback buffer may keep this no-op.
        Buffered transports override it so a graceful hangup does not clip the
        agent's final sentence.
        """
        del handle

    async def wait_ended(self, handle: Any) -> None:
        """Wait for the remote call to end when the transport can detect it.

        The default never completes. Transports that observe participant departure may override
        it so ``VoiceSession`` hangs up automatically.
        """
        await asyncio.Event().wait()

    def remote_user_ids(self, handle: Any) -> tuple[str, ...]:
        """Return exact human platform identities when the transport can prove them."""

        del handle
        return ()

    def call_external_id(self, handle: Any) -> str:
        """Return the provider identifier for this concrete call, when available."""

        del handle
        return ""


class CallProvider(ABC):
    """Platform adapter that resolves accounts and creates call transports.

    A provider belongs to a bridge (Nextcloud Talk, Matrix, SIP, ...). The voice
    domain only consumes this interface and never imports a concrete platform.
    """

    kind: str = ""

    @abstractmethod
    async def resolve_connection_id(
        self,
        *,
        agent_id: int,
        room_id: str,
        connection_id: int | None = None,
        language: str = "en",
    ) -> int:
        """Resolve an active platform connection that can access the room."""
        ...

    @abstractmethod
    async def create_transport(
        self,
        connection_id: int,
        *,
        outgoing: bool,
    ) -> CallTransport:
        """Build a transport for an outgoing call or an incoming answer."""
        ...

    async def start_listeners(self) -> None:
        """Start bridge-specific incoming call listeners, when supported."""

    async def stop_listeners(self) -> None:
        """Stop bridge-specific incoming call listeners, when supported."""

    def listeners_running(self) -> bool:
        """Return whether this provider's root listeners are alive."""
        return True
