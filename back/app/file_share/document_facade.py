"""Authorized, content-versioned preparation cache; never a second file provider."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import asyncio
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time

from core import settings
from core.document import PreparedDocument, prepare_document
from .resource_contracts import ResourceContext, ResourceDescriptor
from .resource_service import materialize_resource, resource_info

CACHE_DAYS = 7
CACHE_BYTES = 2 * 1024**3


def _revision(info: ResourceDescriptor) -> str:
    return json.dumps([info.name, info.media_type, info.size, info.modified_at, info.revision, info.checksum, info.etag], sort_keys=True)


@asynccontextmanager
async def prepared_resource(ctx: ResourceContext, uri: str) -> AsyncGenerator[tuple[PreparedDocument, Path]]:
    # Always authorize and fetch source bytes before a cache lookup. Even providers
    # without reliable etags therefore cannot serve stale data or grant by checksum.
    before = await resource_info(ctx, uri)
    with TemporaryDirectory(prefix="document-source-") as temporary:
        source = Path(temporary) / "input"
        materialized = await materialize_resource(ctx, uri, source, max_bytes=512 * 1024 * 1024)
        after = await resource_info(ctx, uri)
        if _revision(before) != _revision(after):
            raise ValueError("Document changed while downloading")
        digest = await asyncio.to_thread(_digest, source)
        identity = json.dumps([ctx.agent_id, uri, digest, materialized.name, materialized.media_type, 3])
        key = hashlib.sha256(identity.encode()).hexdigest()
        root = Path(settings.GALARIS_DOCUMENT_ROOT) / "cache" / str(ctx.agent_id)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = root / key
        directory.mkdir(exist_ok=True, mode=0o700)
        with (directory / ".lock").open("a") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.1)
            try:
                await asyncio.to_thread(_purge, root, directory)
                prepared = await prepare_document(source, materialized.name, materialized.media_type, directory)
                await asyncio.to_thread(_purge, root, directory)
                # Recheck access after the converter and at every new read.
                if _revision(after) != _revision(await resource_info(ctx, uri)):
                    raise ValueError("Document access or version changed while preparing")
                directory.touch()
                yield prepared, directory
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _purge(root: Path, current: Path) -> None:
    entries: list[tuple[Path, int, float]] = []
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        size = sum(p.stat().st_size for p in entry.rglob("*") if p.is_file() and not p.is_symlink())
        entries.append((entry, size, entry.stat().st_mtime))
    total = sum(size for _, size, _ in entries)
    for entry, size, modified in sorted(entries, key=lambda value: value[2]):
        if entry == current or (total <= CACHE_BYTES and time.time() - modified <= CACHE_DAYS * 86400):
            continue
        with (entry / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            shutil.rmtree(entry)
            total -= size
    if total > CACHE_BYTES:
        raise ValueError("Document preparation cache quota exhausted")
