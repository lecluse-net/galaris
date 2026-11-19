"""Combine local mirrors and signed remote releases for the existing installer."""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from loguru import logger

from core import settings

from . import remote_catalog
from .bundles import MAX_UPLOAD_BYTES, Bundle, BundleError, read_bundle

MAX_CANDIDATES = 64


def _candidates() -> Iterator[Path]:
    try:
        directory = settings.PLUGIN_CATALOG_DIRECTORY.iterdir()
        count = 0
        for path in directory:
            if path.suffix != ".zip" or path.is_symlink() or not path.is_file():
                continue
            count += 1
            if count > MAX_CANDIDATES:
                raise ValueError("Plugin catalogue has too many entries")
            yield path
    except FileNotFoundError:
        return


def _bundles() -> Iterator[tuple[Bundle, bytes]]:
    for path in _candidates():
        try:
            with path.open("rb") as stream:
                content = stream.read(MAX_UPLOAD_BYTES + 1)
            yield read_bundle(content), content
        except (BundleError, FileNotFoundError):
            continue


def _remote() -> tuple[str, remote_catalog.CatalogueIndex] | None:
    try:
        return remote_catalog.snapshot()
    except (OSError, ValueError, InvalidSignature, httpx.InvalidURL) as exc:
        logger.warning("Remote plugin catalogue unavailable ({})", type(exc).__name__)
        return None


def list_catalogue() -> list[Bundle]:
    remote = _remote()
    revoked: set[str] = set(remote[1].revoked) if remote else set()
    seen: dict[tuple[str, str], Bundle] = {}
    for bundle, _content in _bundles():
        if bundle.digest in revoked:
            continue
        key = bundle.manifest.code, bundle.manifest.version
        if key in seen and seen[key].digest != bundle.digest:
            raise ValueError("Two archive digests share a catalogue identity")
        seen[key] = bundle
    if remote and remote[1].current(datetime.now(timezone.utc)):
        for release in remote[1].releases:
            if release.digest not in revoked:
                seen.setdefault((release.manifest.code, release.manifest.version), release.preview())
    return [seen[key] for key in sorted(seen)]


def catalogue_archive(digest: str) -> bytes | None:
    remote = _remote()
    if remote and digest in remote[1].revoked:
        return None
    local = next((content for bundle, content in _bundles() if bundle.digest == digest), None)
    if local is not None:
        return local
    if remote and remote[1].current(datetime.now(timezone.utc)):
        base, index = remote
        for release in index.releases:
            if release.digest == digest:
                try:
                    content = remote_catalog.archive(base, release)
                except httpx.HTTPError as exc:
                    raise ValueError("Remote plugin archive is unavailable") from exc
                latest = _remote()
                if (latest and latest[0] == base and latest[1].current(datetime.now(timezone.utc))
                        and digest not in latest[1].revoked and release in latest[1].releases):
                    return content
    return None
