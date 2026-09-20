"""Effective native input support for the internal SDK/proxy transport."""

from .provider_models import LLM
from .provider_facade import ProviderMediaInputPolicy, media_input_policy_for
from .resource_discovery import provider_connection


def normalized_media_type(media_type: str, name: str = "") -> str:
    import mimetypes

    mime = media_type.split(";", 1)[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {"image/jpg": "image/jpeg", "audio/x-wav": "audio/wav", "audio/wave": "audio/wav",
            "audio/x-flac": "audio/flac", "audio/x-aiff": "audio/aiff",
            "audio/mp3": "audio/mpeg", "audio/x-m4a": "audio/mp4"}.get(mime, mime)


def native_media_policy(llm: LLM) -> ProviderMediaInputPolicy:
    provider = getattr(llm, "provider", None)
    return (media_input_policy_for(provider_connection(provider, None))
            if provider is not None else ProviderMediaInputPolicy())


def supports_native_input(llm: LLM, media_type: str, name: str = "") -> bool:
    """Do not advertise a model modality that our selected transport cannot serialize."""
    mime = normalized_media_type(media_type, name)
    if mime in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return bool(getattr(llm, "input_image", False))
    if mime.startswith("audio/"):
        return bool(getattr(llm, "input_audio", False)) and mime in native_media_policy(llm).audio_types
    if mime.startswith("video/"):
        return bool(getattr(llm, "input_video", False)) and mime in native_media_policy(llm).video_types
    return mime == "application/pdf" and bool(getattr(llm, "input_file", False))


def native_media_requires_chat(llm: LLM) -> bool:
    """Installed Responses SDK cannot serialize binary audio/video; use the same model in Chat."""
    policy = native_media_policy(llm)
    return bool((getattr(llm, "input_audio", False) and policy.audio_types)
                or (getattr(llm, "input_video", False) and policy.video_types))


def native_audio_format(media_type: str) -> str:
    return {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/aiff": "aiff",
            "audio/aac": "aac", "audio/ogg": "ogg", "audio/flac": "flac",
            "audio/mp4": "m4a"}[normalized_media_type(media_type)]
