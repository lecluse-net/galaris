"""Shared AI-provider capability taxonomy and inference helpers."""

from __future__ import annotations

from typing import Literal

from .handlers import LLMModelInfo


AICapability = Literal[
    "chat",
    "vision",
    "image_generation",
    "embedding",
    "transcription",
    "speech",
    "realtime_conversation",
    "audio_understanding",
    "video_understanding",
    "sound_generation",
    "music_generation",
    "video_generation",
]
AIResourceType = Literal["model", "voice", "preset", "service"]

AI_CAPABILITIES: tuple[AICapability, ...] = (
    "chat",
    "vision",
    "image_generation",
    "embedding",
    "transcription",
    "speech",
    "realtime_conversation",
    "audio_understanding",
    "video_understanding",
    "sound_generation",
    "music_generation",
    "video_generation",
)

_CAPABILITY_HINTS: dict[AICapability, tuple[str, ...]] = {
    "embedding": ("embedding", "embed-", "/embed", "bge-", "e5-"),
    "transcription": (
        "whisper",
        "transcrib",
        "speech-to-text",
        "scribe",
        "asr",
        "/stt",
        "-stt",
        "stt-",
    ),
    "speech": ("text-to-speech", "/tts", "-tts", "tts-", "speech", "voice"),
    "realtime_conversation": ("gpt-realtime", "realtime-preview"),
    "image_generation": (
        "dall-e",
        "gpt-image",
        "imagen",
        "nano-banana",
        "flash-image",
        "flux",
        "stable-diffusion",
        "seedream",
    ),
    "chat": (),
    "vision": (),
}


def default_modalities(capability: AICapability) -> dict[str, bool]:
    """Return safe directional modality defaults for one service capability."""
    flags = {
        "input_text": False,
        "input_image": False,
        "input_file": False,
        "input_video": False,
        "input_audio": False,
        "output_text": False,
        "output_image": False,
        "output_file": False,
        "output_video": False,
        "output_audio": False,
    }
    if capability == "chat":
        flags.update(input_text=True, output_text=True)
    elif capability == "vision":
        flags.update(input_text=True, input_image=True, output_text=True)
    elif capability == "image_generation":
        flags.update(input_text=True, output_image=True)
    elif capability == "embedding":
        flags.update(input_text=True)
    elif capability == "transcription":
        flags.update(input_audio=True, output_text=True)
    elif capability == "speech":
        flags.update(input_text=True, output_audio=True)
    elif capability in {"sound_generation", "music_generation"}:
        flags.update(input_text=True, output_audio=True)
    elif capability == "video_generation":
        flags.update(input_text=True, output_video=True)
    elif capability == "audio_understanding":
        flags.update(input_text=True, input_audio=True, output_text=True)
    elif capability == "video_understanding":
        flags.update(input_text=True, input_video=True, output_text=True)
    elif capability == "realtime_conversation":
        flags.update(
            input_text=True,
            input_audio=True,
            output_text=True,
            output_audio=True,
        )
    return flags


def infer_capabilities(model: LLMModelInfo) -> list[AICapability]:
    """Infer service capabilities from provider metadata and stable model hints."""
    declared: list[AICapability] = [
        value
        for value in model.service_capabilities
        if value in AI_CAPABILITIES
    ]
    if declared:
        # Catalog enrichment can add native inputs to a provider's chat entry.
        # Keep specialized services (transcription, speech, etc.) as declared.
        flags = model.modalities or {}
        if "chat" in declared and flags.get("output_text"):
            native_inputs: tuple[tuple[str, AICapability], ...] = (
                ("input_image", "vision"),
                ("input_audio", "audio_understanding"),
                ("input_video", "video_understanding"),
            )
            for field, capability in native_inputs:
                if flags.get(field):
                    declared.append(capability)
        return list(dict.fromkeys(declared))

    result: list[AICapability] = []
    flags = model.modalities or {}
    if flags.get("input_image") and flags.get("output_text"):
        result.append("vision")
    if flags.get("output_image"):
        result.append("image_generation")
    if flags.get("input_audio") and flags.get("output_text"):
        result.append("transcription")
    if flags.get("output_audio"):
        result.append("speech")

    lowered = f"{model.id} {model.name or ''}".lower()
    for capability, hints in _CAPABILITY_HINTS.items():
        if hints and any(hint in lowered for hint in hints):
            result.append(capability)

    # Legacy rows sometimes marked Whisper as audio output. A transcription model is not TTS
    # unless its own identifier also carries a speech/voice/TTS signal.
    if (
        "transcription" in result
        and "speech" in result
        and not any(hint in lowered for hint in _CAPABILITY_HINTS["speech"])
    ):
        result.remove("speech")

    specialized = {
        "embedding",
        "transcription",
        "speech",
        "image_generation",
        "realtime_conversation",
    }
    if not specialized.intersection(result) and (
        flags.get("output_text", True) or not flags
    ):
        result.append("chat")
    return list(dict.fromkeys(result)) or ["chat"]


def applies_to_capability(model: LLMModelInfo, capability: AICapability) -> bool:
    """Return whether a normalized resource belongs in a capability catalog."""
    return capability in infer_capabilities(model)


def with_capability(
    model: LLMModelInfo,
    capability: AICapability,
    *,
    resource_type: AIResourceType | None = None,
) -> LLMModelInfo:
    """Attach a discovered capability and fill missing directional modalities."""
    capabilities = infer_capabilities(model)
    if capability not in capabilities:
        capabilities.append(capability)
    model.service_capabilities = [str(value) for value in capabilities]
    model.resource_type = resource_type or model.resource_type
    defaults = default_modalities(capability)
    # Absence means unknown, not an explicit provider refusal. Keep unknown
    # fields absent until catalog enrichment and API response serialization.
    modalities = dict(model.modalities or {})
    for key, enabled in defaults.items():
        if enabled:
            modalities.setdefault(key, True)
    model.modalities = modalities
    return model
