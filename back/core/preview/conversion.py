"""Conversion extension point, independent of viewers and thumbnail rendering."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from .contracts import PreviewConverter, PreviewFile

_converters: dict[str, PreviewConverter] = {}


def register_preview_converter(converter: PreviewConverter) -> None:
    """Register once at bootstrap; highest priority wins, then name order."""
    if converter.name in _converters:
        raise ValueError(f"Duplicate preview converter: {converter.name}")
    _converters[converter.name] = converter


@asynccontextmanager
async def prepare_preview(source: PreviewFile) -> AsyncGenerator[PreviewFile]:
    """Prepare an already authorized, local source for the context's lifetime.

    Without a matching converter, return the source unchanged. Conversion errors
    propagate to the caller; no conversion chain or implicit fallback is applied.
    """
    converter = next(
        (
            value
            for value in sorted(_converters.values(), key=lambda item: (-item.priority, item.name))
            if value.accepts(source.media_type, source.name)
        ),
        None,
    )
    if converter is None:
        yield source
    else:
        async with converter.convert(source) as prepared:
            yield prepared
