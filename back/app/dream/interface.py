"""Media ports bound by the application composition root for background analysis."""

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol
from typing import Any
from uuid import UUID
from sqlalchemy import Select


class FileCataloguePort(Protocol):
    async def source_for_item(self, item_id: UUID, agent_id: int) -> dict[str, Any] | None: ...
    async def apply_manual(self, source: dict[str, Any], description: str) -> bool: ...
    async def thumbnail_pending(self, handled: Select[tuple[str]]) -> int: ...
    async def thumbnail_source(self, handled: Select[tuple[str]]) -> dict[str, Any] | None: ...
    async def thumbnail_generate(self, source: dict[str, Any], *, force: bool = False) -> bool: ...
    async def fingerprints(self) -> list[dict[str, Any]]: ...
    async def fingerprint(self, source: dict[str, Any]) -> str | None: ...
    async def identify(self, identity: str, version: str, sha256: str) -> bool: ...
    async def discovery_pending(self, claimed: list[dict[str, str]]) -> int: ...
    async def discovery_subjects(self, unavailable: list[dict[str, str]]) -> list[dict[str, str]]: ...
    async def discover(self, subject: dict[str, str], *, attempt: int, max_attempts: int) -> int: ...
    async def candidates(self) -> list[dict[str, Any]]: ...
    async def claimed(self, identity: str) -> None: ...
    async def materialize(self, source: dict[str, Any], path: Path) -> dict[str, Any] | None: ...
    async def apply(self, identity: str, version: str, description: str) -> bool: ...


_file_catalogue: FileCataloguePort | None = None


def register_file_catalogue(port: FileCataloguePort) -> None:
    global _file_catalogue
    _file_catalogue = port


def file_catalogue_port() -> FileCataloguePort | None:
    return _file_catalogue


class DreamAudioChunk(Protocol):
    @property
    def path(self) -> Path: ...


class DreamImageReader(Protocol):
    async def __call__(
        self, data: bytes, mime: str | None = None, instruction: str = "", *,
        agent_id: int | None = None,
    ) -> str: ...


AudioNormalizer = Callable[[Path, Path], Awaitable[Sequence[DreamAudioChunk]]]
_image_reader: DreamImageReader | None = None
_audio_normalizer: AudioNormalizer | None = None


def register_attachment_media(*, image_reader: DreamImageReader, audio_normalizer: AudioNormalizer) -> None:
    global _image_reader, _audio_normalizer
    _image_reader, _audio_normalizer = image_reader, audio_normalizer


async def describe_image(data: bytes, mime: str, *, instruction: str, agent_id: int | None) -> str:
    if _image_reader is None:
        raise RuntimeError("Dream image reader has not been registered")
    return await _image_reader(data, mime, instruction=instruction, agent_id=agent_id)


async def normalize_for_transcription_chunks(source: Path, destination: Path) -> Sequence[DreamAudioChunk]:
    if _audio_normalizer is None:
        raise RuntimeError("Dream audio normalizer has not been registered")
    return await _audio_normalizer(source, destination)
