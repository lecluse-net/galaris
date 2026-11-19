"""Bounded temporary conversion of a synthetic note."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from app.plugin.contracts import PluginRuntimeContext
from core.preview import PreviewConverter, PreviewFile


@asynccontextmanager
async def convert_sample_note(source: PreviewFile) -> AsyncGenerator[PreviewFile]:
    def read_bounded() -> bytes:
        with source.path.open("rb") as stream:
            value = stream.read(16_385)
        if len(value) > 16_384:
            raise ValueError("Sample note is too large")
        value.decode("utf-8")
        return value

    content = await asyncio.to_thread(read_bounded)
    with TemporaryDirectory(prefix="sample-preview-") as directory:
        target = Path(directory) / "preview.txt"
        await asyncio.to_thread(target.write_bytes, content)
        yield PreviewFile(target, "preview.txt", "text/plain")


def plugin_converter(_context: PluginRuntimeContext) -> PreviewConverter:
    return PreviewConverter(
        name="sample.preview", version="1", accepts=lambda _, name: name.endswith(".sample-note"),
        convert=convert_sample_note,
    )
