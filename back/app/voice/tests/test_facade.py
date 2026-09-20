from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.voice import facade
from core.params.runtime_settings import runtime_settings


@pytest.mark.asyncio
async def test_channel_parameter_change_reconciles_voice_once(monkeypatch):
    import app.voice as voice
    from core.params import params_service

    monkeypatch.setattr(params_service, "_change_listeners", [])
    reconcile = AsyncMock()
    monkeypatch.setattr(voice, "reconcile_call_listeners", reconcile)
    voice.register_runtime_settings()
    voice.register_runtime_settings()
    for listener in params_service._change_listeners:
        await listener("MESSENGER_ENABLED_CHANNELS", '["matrix"]')
        await listener("TASK_ROOT_MAX_TOKENS", "1000")
    reconcile.assert_awaited_once()


def test_call_listeners_running_aggregates_registered_providers(
    monkeypatch,
) -> None:
    providers = {
        "matrix": SimpleNamespace(listeners_running=lambda: True),
        "nextcloud_talk": SimpleNamespace(listeners_running=lambda: True),
    }
    monkeypatch.setattr(facade, "_providers", providers)

    assert facade.call_listeners_running() is True

    providers["nextcloud_talk"] = SimpleNamespace(listeners_running=lambda: False)

    assert facade.call_listeners_running() is False


@pytest.mark.asyncio
async def test_reconcile_stops_disabled_provider_and_starts_enabled_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.voice.call_manager import voice_call_manager

    matrix = SimpleNamespace(
        kind="matrix",
        start_listeners=AsyncMock(),
        stop_listeners=AsyncMock(),
        listeners_running=lambda: False,
    )
    nextcloud = SimpleNamespace(
        kind="nextcloud_talk",
        start_listeners=AsyncMock(),
        stop_listeners=AsyncMock(),
        listeners_running=lambda: True,
    )
    stop_calls = AsyncMock(return_value=1)
    monkeypatch.setattr(
        facade,
        "_providers",
        {"matrix": matrix, "nextcloud_talk": nextcloud},
    )
    monkeypatch.setattr(facade, "_started_provider_kinds", {"nextcloud_talk"})
    monkeypatch.setattr(voice_call_manager, "stop_transport_calls", stop_calls)
    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_ENABLED_CHANNELS",
        '["matrix"]',
    )

    await facade.reconcile_call_listeners()

    matrix.start_listeners.assert_awaited_once()
    nextcloud.stop_listeners.assert_awaited_once()
    stop_calls.assert_awaited_once_with("nextcloud_talk")
    assert facade._started_provider_kinds == {  # pyright: ignore[reportPrivateUsage]
        "matrix"
    }


@pytest.mark.asyncio
async def test_transcribe_voice_audio_uses_agent_transcription_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import transcription_service

    transcribe = AsyncMock(return_value="Bonjour")
    monkeypatch.setattr(transcription_service, "transcribe_audio", transcribe)

    result = await facade.transcribe_voice_audio(
        b"audio",
        filename="dictation.webm",
        mime_type="audio/webm",
        language="fr-FR",
        agent_id=9,
    )

    assert result == "Bonjour"
    transcribe.assert_awaited_once_with(
        b"audio",
        filename="dictation.webm",
        mime_type="audio/webm",
        language="fr-FR",
        agent_id=9,
    )


@pytest.mark.asyncio
async def test_transcribe_voice_audio_reports_missing_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import transcription_service

    monkeypatch.setattr(
        transcription_service,
        "transcribe_audio",
        AsyncMock(side_effect=transcription_service.TranscriptionNotConfigured()),
    )

    with pytest.raises(facade.VoiceTranscriptionUnavailable):
        await facade.transcribe_voice_audio(
            b"audio",
            filename="dictation.webm",
            mime_type="audio/webm",
            language="fr",
            agent_id=9,
        )


@pytest.mark.asyncio
async def test_voice_call_requires_tts_and_stt_for_a_tts_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent as agent_facade
    from app.llm import transcription_service, tts_service

    monkeypatch.setattr(
        agent_facade,
        "get_agent_record",
        AsyncMock(return_value=SimpleNamespace(voice="tts:12")),
    )
    speech_available = AsyncMock(return_value=True)
    transcription_available = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(
        tts_service,
        "speech_available_for_agent",
        speech_available,
    )
    monkeypatch.setattr(
        transcription_service,
        "transcription_available_for_agent",
        transcription_available,
    )

    assert await facade.agent_voice_call_available(9) is False
    assert await facade.agent_voice_call_available(9) is True
    assert speech_available.await_count == 2
    assert transcription_available.await_count == 2


@pytest.mark.asyncio
async def test_voice_call_accepts_a_native_realtime_audio_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent as agent_facade
    from app.llm import transcription_service, tts_service
    from app.voice import realtime_engine

    monkeypatch.setattr(
        agent_facade,
        "get_agent_record",
        AsyncMock(return_value=SimpleNamespace(voice="realtime:12:marin")),
    )
    realtime_available = AsyncMock(return_value=True)
    speech_available = AsyncMock()
    transcription_available = AsyncMock()
    monkeypatch.setattr(
        realtime_engine,
        "realtime_voice_available_for_agent",
        realtime_available,
    )
    monkeypatch.setattr(
        tts_service,
        "speech_available_for_agent",
        speech_available,
    )
    monkeypatch.setattr(
        transcription_service,
        "transcription_available_for_agent",
        transcription_available,
    )

    assert await facade.agent_voice_call_available(9) is True
    realtime_available.assert_awaited_once_with(9)
    speech_available.assert_not_awaited()
    transcription_available.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesize_agent_message_reuses_spoken_text_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm import tts_service

    generate = AsyncMock(return_value=SimpleNamespace(content=b"ID3-audio"))
    monkeypatch.setattr(tts_service, "generate_for_agent", generate)

    result = await facade.synthesize_agent_message(
        9,
        "**Bien sûr** 😀 — [ouvrez ce lien](https://example.test)",
        language="fr-FR",
    )

    assert result == b"ID3-audio"
    generate.assert_awaited_once_with(
        9,
        "Bien sûr — ouvrez ce lien",
        tts_service.TTSOptions(language="fr-FR"),
    )
