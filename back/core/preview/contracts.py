"""Contracts for optional server-side preview conversions."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreviewFile:
    path: Path
    name: str
    media_type: str


@dataclass(frozen=True)
class PreviewConverter:
    """A converter owns its temporary output and cleans it up on context exit.

    It must preserve the source and bound its resource usage. ``accepts`` receives
    the source media type and filename, in that order.
    """

    name: str
    version: str
    accepts: Callable[[str, str], bool]
    convert: Callable[[PreviewFile], AbstractAsyncContextManager[PreviewFile]]
    priority: int = 0
