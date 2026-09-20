from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm import transcription_service


@pytest.mark.asyncio
async def test_transcription_availability_accepts_openai_compatible_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(provider_type="openai_compatible")
    monkeypatch.setattr(
        transcription_service,
        "_selected_resource",
        AsyncMock(return_value=(SimpleNamespace(), connection)),
    )
    monkeypatch.setattr(
        transcription_service,
        "transcription_provider_for",
        MagicMock(return_value=None),
    )

    assert await transcription_service.transcription_available_for_agent(9) is True


@pytest.mark.asyncio
async def test_transcription_availability_rejects_a_missing_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        transcription_service,
        "_selected_resource",
        AsyncMock(
            side_effect=transcription_service.TranscriptionNotConfigured(
                "not configured"
            )
        ),
    )

    assert await transcription_service.transcription_available_for_agent(9) is False
