"""Freeze authorized input images and verify them before provider disclosure."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from pydantic import BaseModel, Field

from app.file_share import ResourceContext, materialize_resource
from app.llm.facade import VideoFrame, VideoFrameRole
from core.util import complete_io

MAX_FRAME_BYTES = 5_000_000


class VideoFrameError(ValueError):
    """A requested video frame is missing, invalid, or no longer matches admission."""


class FrameInput(BaseModel):
    role: VideoFrameRole
    uri: str = Field(min_length=1, max_length=2048)


class FrozenFrame(FrameInput):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _read_frame(path: Path, role: VideoFrameRole) -> VideoFrame:
    try:
        with Image.open(path, formats=["JPEG", "PNG"]) as image:
            width, height = image.size
            if max(width, height) > 6000 or getattr(image, "is_animated", False):
                raise VideoFrameError("Video frame references must be still images up to 6000 pixels per side.")
            media_type = "image/png" if image.format == "PNG" else "image/jpeg"
            image.load()
    except (OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise VideoFrameError("Video frame references must contain a valid JPEG or PNG image.") from exc
    return VideoFrame(role, media_type, width, height, path.read_bytes())


async def _materialize_frame(ctx: ResourceContext, source: FrameInput) -> tuple[str, VideoFrame]:
    with TemporaryDirectory(prefix="galaris-video-frame-") as directory:
        path = Path(directory) / "frame"
        try:
            resource = await materialize_resource(ctx, source.uri, path, max_bytes=MAX_FRAME_BYTES)
        except (ValueError, RuntimeError, FileNotFoundError, IsADirectoryError) as exc:
            raise VideoFrameError("A video frame URI must resolve to a readable file of at most 5 MB.") from exc
        return resource.uri, await complete_io(_read_frame, path, source.role)


async def freeze_frames(ctx: ResourceContext, sources: tuple[FrameInput, ...]) -> tuple[FrozenFrame, ...]:
    frozen: list[FrozenFrame] = []
    for source in sources:
        uri, frame = await _materialize_frame(ctx, source)
        frozen.append(FrozenFrame(role=source.role, uri=uri, sha256=sha256(frame.content).hexdigest()))
    return tuple(frozen)


async def load_frozen_frames(ctx: ResourceContext, sources: tuple[FrozenFrame, ...]) -> tuple[VideoFrame, ...]:
    verified: list[VideoFrame] = []
    for source in sources:
        uri, frame = await _materialize_frame(ctx, source)
        if uri != source.uri or sha256(frame.content).hexdigest() != source.sha256:
            raise VideoFrameError("A video frame changed after admission. Submit a new invocation to use the updated file.")
        verified.append(frame)
    return tuple(verified)
