"""Transport-neutral real-time audio-call orchestration.

Galaris segments incoming PCM, transcribes speech, streams the configured agent,
synthesizes its response, and supports barge-in. Platform signaling and media
details live in their bridge.
"""

from collections.abc import Awaitable, Callable

from .facade import (
    VoiceSynthesisFailed,
    VoiceSynthesisUnavailable,
    VoiceTranscriptionFailed,
    VoiceTranscriptionUnavailable,
    agent_voice_call_available,
    agent_voice_synthesis_available,
    available_kinds,
    get_call_provider,
    register_call_provider,
    reconcile_call_listeners,
    start_call_listeners as start_voice_call_listeners,
    stop_call_listeners as stop_voice_call_listeners,
    synthesize_agent_message,
    transcribe_voice_audio,
    call_listeners_running as voice_call_listeners_running,
)
from .interface import CallProvider, CallTransport
from .models import (
    AudioFrame,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    VoiceConversationSession,
    VoiceConversationStatus,
    VoiceTurnStatus,
)
from .audio_devices import PulseAudioBridge, PulseAudioConfig, PulseAudioDevices
from .session import VoiceSession
from .call_manager import VoiceCallInfo, voice_call_manager
from .mcp import AGENT_VOICE_TOOLS
from .inspection_service import inspect_turn as inspect_voice_turn
from .transcription_events import (
    VoiceTranscriptionEvent,
    VoiceTranscriptionStatus,
    publish_voice_transcription,
    register_voice_transcription_listener,
    unregister_voice_transcription_listener,
)


async def _refresh_channels(name: str, _value: str | None) -> None:
    from core.params import Params

    if name == Params.MESSENGER_ENABLED_CHANNELS:
        await reconcile_call_listeners()


def register_runtime_settings() -> None:
    """Voice owns its reaction to channel configuration, independent of messaging."""
    from core.params import params_service

    params_service.register_change_listener(_refresh_channels)

__all__ = [
    "register_runtime_settings",
    "AudioFrame",
    "DEFAULT_CHANNELS",
    "DEFAULT_SAMPLE_RATE",
    "VoiceConversationSession",
    "VoiceConversationStatus",
    "VoiceTurnStatus",
    "CallProvider",
    "CallTransport",
    "AGENT_VOICE_TOOLS",
    "VoiceCallInfo",
    "PulseAudioBridge",
    "PulseAudioConfig",
    "PulseAudioDevices",
    "VoiceSession",
    "VoiceSynthesisFailed",
    "VoiceSynthesisUnavailable",
    "VoiceTranscriptionFailed",
    "VoiceTranscriptionEvent",
    "VoiceTranscriptionStatus",
    "VoiceTranscriptionUnavailable",
    "agent_voice_call_available",
    "agent_voice_synthesis_available",
    "voice_call_manager",
    "has_active_voice_calls",
    "register_voice_activity_listener",
    "unregister_voice_activity_listener",
    "register_voice_call_ended_listener",
    "register_voice_transcription_listener",
    "unregister_voice_call_ended_listener",
    "unregister_voice_transcription_listener",
    "start_voice_call_listeners",
    "stop_voice_call_listeners",
    "synthesize_agent_message",
    "transcribe_voice_audio",
    "publish_voice_transcription",
    "voice_call_listeners_running",
    "register_call_provider",
    "reconcile_call_listeners",
    "get_call_provider",
    "inspect_voice_turn",
    "available_kinds",
]


def has_active_voice_calls() -> bool:
    """Public, transport-neutral foreground-activity signal."""

    return voice_call_manager.has_active_calls()


def register_voice_activity_listener(listener: Callable[[bool], None]) -> None:
    """Register a synchronous listener without exposing manager internals."""

    voice_call_manager.register_activity_listener(listener)


def unregister_voice_activity_listener(listener: Callable[[bool], None]) -> None:
    voice_call_manager.unregister_activity_listener(listener)


def register_voice_call_ended_listener(
    listener: Callable[[VoiceCallInfo], Awaitable[None]],
) -> None:
    """Register an adapter notified after a call leaves the active registry."""

    voice_call_manager.register_call_ended_listener(listener)


def unregister_voice_call_ended_listener(
    listener: Callable[[VoiceCallInfo], Awaitable[None]],
) -> None:
    voice_call_manager.unregister_call_ended_listener(listener)

from .events import register_events

register_events()
