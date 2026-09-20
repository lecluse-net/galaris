"""Voice provider facade and dependency-inverting registry."""

from __future__ import annotations

from loguru import logger

from .interface import CallProvider

_providers: dict[str, CallProvider] = {}
_started_provider_kinds: set[str] = set()


class VoiceTranscriptionUnavailable(RuntimeError):
    """Raised when no speech-to-text resource can serve a voice request."""


class VoiceTranscriptionFailed(RuntimeError):
    """Raised when a configured speech-to-text provider rejects a voice request."""


class VoiceSynthesisUnavailable(RuntimeError):
    """Raised when no configured TTS resource can read a message."""


class VoiceSynthesisFailed(RuntimeError):
    """Raised when a configured TTS provider cannot synthesize a message."""


def _enabled(kind: str) -> bool:
    from app.messenger.facade import get_factory, is_kind_enabled

    return get_factory(kind) is None or is_kind_enabled(kind)


def register_call_provider(provider: CallProvider) -> None:
    """Register a bridge-owned call provider such as Nextcloud Talk."""
    if not provider.kind:
        raise ValueError("A call provider must declare a non-empty kind")
    _providers[provider.kind] = provider


def get_call_provider(kind: str) -> CallProvider | None:
    return _providers.get(kind) if _enabled(kind) else None


def available_kinds() -> list[str]:
    return [kind for kind in _providers if _enabled(kind)]


async def transcribe_voice_audio(
    content: bytes,
    *,
    filename: str,
    mime_type: str,
    language: str,
    agent_id: int,
) -> str:
    """Transcribe transient voice input without persisting it as a message file."""

    from app.llm import transcription_service

    try:
        return await transcription_service.transcribe_audio(
            content,
            filename=filename,
            mime_type=mime_type,
            language=language,
            agent_id=agent_id,
        )
    except transcription_service.TranscriptionNotConfigured as exc:
        raise VoiceTranscriptionUnavailable(
            "voice transcription is not configured"
        ) from exc
    except transcription_service.TranscriptionFailed as exc:
        if "returned no text" in str(exc).lower():
            return ""
        raise VoiceTranscriptionFailed("voice transcription failed") from exc


async def agent_voice_synthesis_available(agent_id: int) -> bool:
    """Return whether an agent has an active, MP3-capable TTS selection."""

    from app.llm import tts_service

    return await tts_service.speech_available_for_agent(agent_id)


async def agent_voice_call_available(agent_id: int) -> bool:
    """Return whether an agent can sustain a bidirectional audio call."""

    from app.agent import get_agent_record, parse_voice_selection
    from app.llm import transcription_service, tts_service
    from .realtime_engine import realtime_voice_available_for_agent

    agent = await get_agent_record(agent_id)
    if agent is None:
        return False
    try:
        selection = parse_voice_selection(getattr(agent, "voice", None))
    except ValueError:
        return False
    if selection is None:
        return False
    if selection.mode == "realtime":
        return await realtime_voice_available_for_agent(agent_id)
    if not await tts_service.speech_available_for_agent(agent_id):
        return False
    return await transcription_service.transcription_available_for_agent(agent_id)


async def synthesize_agent_message(
    agent_id: int,
    message: str,
    *,
    language: str = "",
) -> bytes:
    """Synthesize one transient message with the agent's configured TTS voice."""

    from app.llm import tts_service
    from .engine import prepare_spoken_text

    try:
        spoken_message = prepare_spoken_text(message)
        if not spoken_message:
            raise ValueError("the message has no speakable text")
        speech = await tts_service.generate_for_agent(
            agent_id,
            spoken_message,
            tts_service.TTSOptions(language=language),
        )
    except tts_service.TTSNotConfigured as exc:
        raise VoiceSynthesisUnavailable("voice synthesis is not configured") from exc
    except (tts_service.TTSProviderUnsupported, RuntimeError, ValueError) as exc:
        raise VoiceSynthesisFailed("voice synthesis failed") from exc
    return speech.content


async def start_call_listeners() -> None:
    """Start incoming-call listeners for every enabled platform."""

    await reconcile_call_listeners()


async def reconcile_call_listeners() -> None:
    """Apply global messaging activation to voice listeners and active calls."""

    from .call_manager import voice_call_manager

    enabled = set(available_kinds())
    for kind, provider in reversed(tuple(_providers.items())):
        if kind in enabled:
            continue
        try:
            await provider.stop_listeners()
        except Exception:
            logger.exception("Voice provider listener failed to stop kind={}", kind)
        _started_provider_kinds.discard(kind)
        stopped = await voice_call_manager.stop_transport_calls(kind)
        if stopped:
            logger.info("Voice bridge disabled kind={} stopped_calls={}", kind, stopped)

    for kind in enabled:
        provider = _providers[kind]
        if kind in _started_provider_kinds and provider.listeners_running():
            continue
        try:
            await provider.start_listeners()
            _started_provider_kinds.add(kind)
        except Exception:
            _started_provider_kinds.discard(kind)
            logger.exception("Voice provider listener failed to start kind={}", kind)


async def stop_call_listeners() -> None:
    """Stop incoming listeners and every live media session."""
    for provider in reversed(tuple(_providers.values())):
        try:
            await provider.stop_listeners()
        except Exception:
            logger.exception("Voice provider listener failed to stop kind={}", provider.kind)
    _started_provider_kinds.clear()
    from .call_manager import voice_call_manager

    stopped = await voice_call_manager.stop_all_calls()
    if stopped:
        logger.info("Voice shutdown: stopped {} active call(s)", stopped)


def call_listeners_running() -> bool:
    """Return whether every enabled provider reports a live root listener."""

    return all(
        provider.listeners_running()
        for kind, provider in _providers.items()
        if _enabled(kind)
    )
