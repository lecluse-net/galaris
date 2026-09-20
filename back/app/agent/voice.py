"""Canonical per-agent voice selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, unquote


VoiceMode = Literal["tts", "realtime"]


@dataclass(frozen=True, slots=True)
class VoiceSelection:
    """One value emitted by the agent Voice/TTS selector."""

    mode: VoiceMode
    model_id: int
    voice_code: str | None = None

    def serialize(self) -> str:
        if self.mode == "tts":
            return f"tts:{self.model_id}"
        assert self.voice_code is not None
        return f"realtime:{self.model_id}:{quote(self.voice_code, safe='')}"


def parse_voice_selection(value: str | None) -> VoiceSelection | None:
    """Parse the canonical stored selection, rejecting every other format."""
    raw = str(value or "").strip()
    if not raw:
        return None

    if raw.startswith("tts:"):
        identifier = raw.removeprefix("tts:")
        if identifier.isdigit() and int(identifier) > 0:
            return VoiceSelection(mode="tts", model_id=int(identifier))
        raise ValueError("invalid TTS voice selection")

    if raw.startswith("realtime:"):
        model, separator, encoded_voice = raw.removeprefix("realtime:").partition(":")
        voice_code = unquote(encoded_voice).strip() if separator else ""
        if model.isdigit() and int(model) > 0 and voice_code:
            return VoiceSelection(
                mode="realtime",
                model_id=int(model),
                voice_code=voice_code,
            )
        raise ValueError("invalid realtime voice selection")

    raise ValueError("invalid voice selection")


def normalize_voice_selection(value: str | None) -> str | None:
    """Return one canonical persisted representation."""
    selection = parse_voice_selection(value)
    return selection.serialize() if selection is not None else None
