"""Normalize service-specific source and destination references for file transfers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class SourceReference:
    remote: str
    target: str = ""


@dataclass(frozen=True)
class DestinationReference:
    filename: str
    target: str = ""


class FileServiceReferenceError(ValueError):
    """A service path is missing a required target or file reference."""

    def __init__(self, service: str, reference: object, requirement: str) -> None:
        self.service = service
        self.reference = "" if reference is None else str(reference)
        self.requirement = requirement
        super().__init__(
            f"{service} reference requires {requirement}: {self.reference!r}"
        )


def _is_http_url(value: str) -> bool:
    return urlsplit(value).scheme.lower() in {"http", "https"}


def _clean_reference(value: object, *, required: bool = True) -> str:
    clean = ("" if value is None else str(value)).strip()
    if not clean and required:
        raise FileServiceReferenceError("file", value, "a non-empty path")
    return clean if _is_http_url(clean) else clean.replace("\\", "/")


def reference_filename(reference: object, fallback: str = "transfer.bin") -> str:
    """Derive a safe leaf filename from a service path or HTTP URL."""

    clean = _clean_reference(reference, required=False)
    if _is_http_url(clean):
        clean = unquote(urlsplit(clean).path)
    if clean.startswith("messenger:"):
        clean = clean.removeprefix("messenger:")
    name = PurePosixPath(clean.rstrip("/")).name
    return fallback if name in {"", ".", ".."} else name


def normalize_source_reference(service: str, reference: object) -> SourceReference:
    """Split a download reference into the transport's ``remote`` and ``target`` fields."""

    clean = _clean_reference(reference)
    normalized_service = (service or "").strip().lower()
    if normalized_service == "affine" and not _is_http_url(clean):
        target, separator, remote = clean.strip("/").partition("/")
        if not separator or not target or not remote:
            raise FileServiceReferenceError("AFFiNE", reference, "workspace/file-key")
        return SourceReference(remote=remote, target=target)
    if normalized_service == "messenger":
        clean = clean.removeprefix("messenger:").strip("/")
        target, separator, remote = clean.partition("/")
        if not separator or not target or not remote:
            raise FileServiceReferenceError("messenger", reference, "room/file-or-attachment")
        return SourceReference(remote=remote, target=target)
    return SourceReference(remote=clean)


def _split_grav_destination(
    reference: str,
    fallback_filename: str,
) -> DestinationReference:
    trailing_slash = reference.endswith("/")
    clean = reference.strip("/")
    if not clean:
        return DestinationReference(filename=fallback_filename)
    if trailing_slash:
        return DestinationReference(filename=fallback_filename, target=clean)
    page, separator, name = clean.rpartition("/")
    if separator and "." in name:
        return DestinationReference(filename=name, target=page)
    if separator:
        return DestinationReference(filename=fallback_filename, target=clean)
    if "." in clean:
        return DestinationReference(filename=clean)
    return DestinationReference(filename=fallback_filename, target=clean)


def normalize_destination_reference(
    service: str,
    reference: object,
    *,
    fallback_filename: str,
) -> DestinationReference:
    """Split an upload destination into the transport's ``filename`` and ``target`` fields."""

    normalized_service = (service or "").strip().lower()
    fallback = reference_filename(fallback_filename)
    clean = _clean_reference(reference, required=False)
    if normalized_service == "image":
        return DestinationReference(filename=fallback, target=clean)
    if normalized_service in {"affine", "messenger"}:
        if normalized_service == "messenger":
            clean = clean.removeprefix("messenger:")
        clean = clean.strip("/")
        if not clean:
            requirement = (
                "workspace[/filename]"
                if normalized_service == "affine"
                else "room[/filename]"
            )
            raise FileServiceReferenceError(normalized_service, reference, requirement)
        target, separator, filename = clean.partition("/")
        return DestinationReference(
            filename=reference_filename(filename, fallback) if separator else fallback,
            target=target,
        )
    if normalized_service == "grav":
        return _split_grav_destination(clean, fallback)

    trailing_slash = clean.endswith("/")
    clean = clean.strip("/")
    if not clean:
        return DestinationReference(filename=fallback)
    if trailing_slash:
        return DestinationReference(filename=fallback, target=clean)
    target, separator, filename = clean.rpartition("/")
    if separator:
        return DestinationReference(filename=filename or fallback, target=target)
    return DestinationReference(filename=clean)
