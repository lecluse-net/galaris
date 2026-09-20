"""Provider-neutral contracts for specialist media services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .provider_facade import ProviderConnection

MediaOperation = Literal[
    "audio_read", "video_read", "sound_generate", "music_generate", "video_generate"
]


class MediaRequestRejected(ValueError):
    """The provider definitively refused admission; no generation was accepted."""


class MediaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: MediaOperation
    model: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1, max_length=10_000)
    lyrics: str | None = Field(default=None, max_length=5000)
    title: str = Field(default="", max_length=100)
    style: str = Field(default="", max_length=1000)
    instrumental: bool = False
    duration: int | None = Field(default=None, ge=1, le=600)
    loop: bool = False
    resolution: str | None = Field(default=None, max_length=20)
    aspect_ratio: str | None = Field(default=None, max_length=20)


@dataclass(frozen=True)
class MediaArtifact:
    external_id: str
    media_type: str
    content: bytes = field(default=b"", repr=False)
    url: str = field(default="", repr=False)


@dataclass(frozen=True)
class MediaResult:
    state: Literal["running", "success", "error", "unknown"]
    external_id: str = ""
    artifacts: tuple[MediaArtifact, ...] = ()
    text: str = ""
    cost: float | None = None
    error: str = ""


class MediaProvider(Protocol):
    def supports(self, operation: MediaOperation, model: str) -> bool: ...

    def validate(self, request: MediaRequest) -> None: ...

    async def analyze(
        self, connection: ProviderConnection, request: MediaRequest,
        source: Path, media_type: str,
    ) -> MediaResult: ...

    async def submit(
        self, connection: ProviderConnection, request: MediaRequest,
        *, callback_url: str,
    ) -> MediaResult: ...

    async def poll(
        self, connection: ProviderConnection, request: MediaRequest, external_id: str,
    ) -> MediaResult: ...


_providers: dict[str, MediaProvider] = {}


def register_media_provider(code: str, provider: MediaProvider) -> None:
    _providers[code] = provider


def media_provider_for(connection: ProviderConnection) -> MediaProvider | None:
    return _providers.get(connection.catalog_code or connection.provider_type)
