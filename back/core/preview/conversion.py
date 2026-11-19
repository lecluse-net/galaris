"""Conversion extension point, independent of viewers and thumbnail rendering."""

from collections.abc import AsyncGenerator, Callable, Iterable
from contextlib import asynccontextmanager

from .contracts import PreviewConverter, PreviewFile

_converters: dict[str, PreviewConverter] = {}
_plugin_converters: dict[str, PreviewConverter] = {}


def register_preview_converter(converter: PreviewConverter) -> None:
    """Register once at bootstrap; highest priority wins, then name order."""
    if converter.name in _converters or converter.name in _plugin_converters:
        raise ValueError(f"Duplicate preview converter: {converter.name}")
    _converters[converter.name] = converter


def prepare_plugin_converters(converters: Iterable[PreviewConverter]) -> Callable[[], None]:
    candidate: dict[str, PreviewConverter] = {}
    for converter in converters:
        if converter.name in _converters or converter.name in candidate:
            raise ValueError("Duplicate preview converter")
        candidate[converter.name] = converter

    def promote() -> None:
        global _plugin_converters
        _plugin_converters = candidate

    return promote


@asynccontextmanager
async def prepare_preview(source: PreviewFile) -> AsyncGenerator[PreviewFile]:
    """Prepare an already authorized, local source for the context's lifetime.

    Without a matching converter, return the source unchanged. Conversion errors
    propagate to the caller; no conversion chain or implicit fallback is applied.
    """
    converter = next(
        (
            value
            for value in sorted((*_converters.values(), *_plugin_converters.values()), key=lambda item: (-item.priority, item.name))
            if value.accepts(source.media_type, source.name)
        ),
        None,
    )
    if converter is None:
        yield source
    else:
        async with converter.convert(source) as prepared:
            yield prepared
