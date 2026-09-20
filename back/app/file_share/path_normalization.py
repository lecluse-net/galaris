"""Canonical relative-path handling for file providers.

MCP tools exchange stable paths relative to the selected provider root. Concrete transports may
accept additional aliases (an absolute path inside that root, ``~/...``, or provider-specific prefixes)
but always normalize them back to the same relative representation.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Sequence
from typing import Any


_URI_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")


class FilePathError(ValueError):
    """A path cannot be represented safely inside the provider root."""

    def __init__(self, value: object, reason: str) -> None:
        self.value = "" if value is None else str(value)
        self.reason = reason
        super().__init__(f"Invalid file path ({reason}): {self.value!r}")


def _parts(value: str) -> list[str]:
    return [part for part in value.split("/") if part not in {"", "."}]


def normalize_file_reference(
    value: object,
    *,
    root: str = "",
    aliases: Sequence[str] = (),
    allow_root: bool = False,
) -> str:
    """Return one canonical relative path bounded by ``root``.

    ``root`` is the absolute path visible to the runtime. ``aliases`` are relative spellings of
    that same root, ordered or unordered; the longest matching alias wins. A bare ``/`` is accepted
    only for root-aware operations such as ``file_list``.
    """

    raw = ("" if value is None else str(value)).strip().replace("\\", "/")
    if "\x00" in raw:
        raise FilePathError(value, "null byte")
    if not raw:
        if allow_root:
            return "."
        raise FilePathError(value, "empty")

    if raw == "~":
        raw = "."
    elif raw.startswith("~/"):
        raw = raw[2:]

    absolute = raw.startswith("/")
    if not absolute and (_URI_PREFIX.match(raw) or _WINDOWS_DRIVE.match(raw)):
        raise FilePathError(value, "not a provider-relative path")

    parts = _parts(raw)
    if ".." in parts:
        raise FilePathError(value, "path traversal")

    if absolute:
        if not parts and allow_root:
            return "."
        root_parts = _parts(root.strip().replace("\\", "/"))
        if not root_parts or parts[: len(root_parts)] != root_parts:
            raise FilePathError(value, "outside provider root")
        parts = parts[len(root_parts) :]
    else:
        alias_parts = sorted(
            (_parts(alias.strip().replace("\\", "/")) for alias in aliases),
            key=len,
            reverse=True,
        )
        for prefix in alias_parts:
            if prefix and parts[: len(prefix)] == prefix:
                parts = parts[len(prefix) :]
                break

    if not parts:
        if allow_root:
            return "."
        raise FilePathError(value, "filename missing")
    return "/".join(parts)


def join_file_references(
    reference: object,
    target: object = "",
    *,
    root: str = "",
    aliases: Sequence[str] = (),
    allow_root: bool = False,
) -> str:
    """Normalize and join an optional provider directory with a reference."""

    pieces: list[str] = []
    raw_target = ("" if target is None else str(target)).strip()
    if raw_target:
        normalized_target = normalize_file_reference(
            raw_target,
            root=root,
            aliases=aliases,
            allow_root=True,
        )
        if normalized_target != ".":
            pieces.append(normalized_target)
    normalized_reference = normalize_file_reference(
        reference,
        root=root,
        aliases=aliases,
        allow_root=allow_root,
    )
    if normalized_reference != ".":
        pieces.append(normalized_reference)
    if not pieces:
        if allow_root:
            return "."
        raise FilePathError(reference, "filename missing")
    return "/".join(pieces)


async def normalize_transport_reference(
    transport: Any,
    value: object,
    *,
    allow_root: bool = False,
) -> str:
    """Normalize a path through its concrete provider transport.

    The relative-only fallback keeps test doubles and third-party runtime transports compatible
    while requiring concrete Galaris transports to expose their runtime-specific aliases.
    """

    raw = "" if value is None else str(value)
    normalizer = getattr(transport, "normalize_resource_path", None)
    if callable(normalizer):
        result = normalizer(raw, allow_root=allow_root)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, str):
            raise TypeError("File path normalizers must return a string")
        return result
    return normalize_file_reference(raw, allow_root=allow_root)
