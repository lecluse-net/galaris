"""Media ports bound by the application composition root for background analysis."""

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol


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
