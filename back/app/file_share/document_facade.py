"""Authorized preparation cache in a process-owned temporary workspace."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time
from uuid import UUID

from core.document import PreparedDocument, prepare_document, preparation_version
from core.storage import file_path, register_live_file_workspace
from core.util import as_dict, complete_io
from .document_rag_cache import document_rag_cache
from .resource_contracts import ResourceContext, ResourceDescriptor
from .resource_service import materialize_resource, resource_info

CACHE_DAYS = 7
CACHE_BYTES = 2 * 1024**3
CACHE_ENTRIES = 256
_cache = TemporaryDirectory(prefix="galaris-document-preparation-")


@dataclass
class _Entry:
    directory: Path
    agent_id: int
    uri: str
    file_id: UUID | None
    sha256: str | None = None
    document: PreparedDocument | None = None
    building: asyncio.Task[PreparedDocument] | None = None
    invalidated: bool = False


_entries: dict[str, _Entry] = {}


def _revision(info: ResourceDescriptor) -> str:
    return json.dumps([info.name, info.media_type, info.size, info.modified_at, info.revision, info.checksum, info.etag], sort_keys=True)


@asynccontextmanager
async def prepared_resource(ctx: ResourceContext, uri: str) -> AsyncGenerator[tuple[PreparedDocument, Path]]:
    # Canonical authorization always precedes cache lookup, even for immutable files.
    try:
        before = await resource_info(ctx, uri)
        binding = await document_rag_cache(ctx, uri)
    except (FileNotFoundError, PermissionError):
        await purge_prepared_uri(ctx.agent_id, uri)
        raise
    # Without a managed immutable identity, always download and hash current bytes.
    if binding is None:
        async with _download(ctx, uri, before) as (source, name, mime, digest):
            key = _key(ctx, uri, before, digest)
            entry = _entry(key, ctx, before.uri, None, digest)
            async def build_remote() -> PreparedDocument:
                return await prepare_document(source, name, mime, entry.directory)
            async with _prepared(entry, build_remote) as document:
                await _recheck(ctx, uri, before)
                yield document, entry.directory
        return
    stamp = await complete_io(_stamp, file_path(binding.file_id))
    key = _key(ctx, uri, before, [str(binding.file_id), binding.source_sha256, stamp])
    entry = _entries.get(key)
    if (entry is None or entry.invalidated or not entry.directory.is_dir()
        or (entry.sha256 is not None and entry.sha256 != binding.source_sha256)):
        entry = await register_live_file_workspace(binding.file_id, binding.source_sha256,
            lambda: _entry(key, ctx, before.uri, binding.file_id, binding.source_sha256, replace=True))

    async def build_managed() -> PreparedDocument:
        async with _download(ctx, uri, before) as (source, name, mime, _digest_value):
            if await complete_io(_stamp, file_path(binding.file_id)) != stamp:
                raise ValueError('Document changed while downloading')
            return await prepare_document(source, name, mime, entry.directory)

    async with _prepared(entry, build_managed) as document:
        await _recheck(ctx, uri, before)
        if await complete_io(_stamp, file_path(binding.file_id)) != stamp:
            raise ValueError('Document changed during preparation')
        yield document, entry.directory


def _key(ctx: ResourceContext, uri: str, info: ResourceDescriptor, identity: object) -> str:
    return hashlib.sha256(json.dumps([ctx.agent_id, uri, _revision(info), identity,
                                     preparation_version(info.name)]).encode()).hexdigest()


def _entry(key: str, ctx: ResourceContext, uri: str, file_id: UUID | None, sha256: str, *, replace: bool = False) -> _Entry:
    entry = _entries.get(key)
    if entry is None or replace or entry.invalidated or not entry.directory.is_dir():
        directory = Path(_cache.name) / str(ctx.agent_id) / key
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        entry = _Entry(directory, ctx.agent_id, uri, file_id, sha256)
        _entries[key] = entry
    return entry


def _stamp(path: Path) -> tuple[int, int, int, int, int]:
    if path.is_symlink():
        raise ValueError('Invalid managed file')
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@asynccontextmanager
async def _download(ctx: ResourceContext, uri: str, before: ResourceDescriptor) -> AsyncGenerator[tuple[Path, str, str, str]]:
    with TemporaryDirectory(prefix='document-source-') as temporary:
        source = Path(temporary) / 'input'
        materialized = await materialize_resource(ctx, uri, source, max_bytes=512 * 1024 * 1024)
        await _recheck(ctx, uri, before)
        digest = await complete_io(_digest, source)
        yield source, materialized.name, materialized.media_type, digest


async def _recheck(ctx: ResourceContext, uri: str, before: ResourceDescriptor) -> None:
    if _revision(before) != _revision(await resource_info(ctx, uri)):
        raise ValueError('Document access or version changed while preparing')


@asynccontextmanager
async def _prepared(entry: _Entry, build: Callable[[], Awaitable[PreparedDocument]]) -> AsyncGenerator[PreparedDocument]:
    if entry.invalidated:
        raise FileNotFoundError('Document source was deleted')
    with (entry.directory / '.lock').open('a') as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(.05)
        try:
            if entry.invalidated:
                raise FileNotFoundError('Document source was deleted')
            # Quota cleanup may win the race between opening and locking a
            # workspace. Never recreate it using an unlinked lock descriptor.
            if (not entry.directory.is_dir() or (entry.directory / '.lock').stat().st_ino
                != os.fstat(lock.fileno()).st_ino):
                raise FileNotFoundError('Preparation cache was evicted; retry the source URI')
            await complete_io(_purge, entry.directory.parent, entry.directory)
            if entry.document is None:
                entry.document = await complete_io(_load_prepared, entry.directory, entry.sha256)
            if entry.document is None:
                async def preparing() -> PreparedDocument:
                    return await build()
                entry.building = asyncio.create_task(preparing())
                try:
                    entry.document = await entry.building
                except asyncio.CancelledError:
                    if entry.invalidated:
                        raise FileNotFoundError('Document source was deleted during preparation') from None
                    raise
            entry.sha256 = entry.document.sha256
            if entry.invalidated:
                raise FileNotFoundError('Document source was deleted during preparation')
            await complete_io(_purge, entry.directory.parent, entry.directory)
            # utime cannot recreate a path removed by source deletion.
            await complete_io(os.utime, entry.directory, None)
            yield entry.document
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            if entry.invalidated or entry.document is None:
                await _discard([entry])
            # Keep text only for this reader's lifetime; the bounded manifest is
            # cheap to reload and must not become an unbounded process RAM cache.
            entry.document = None
            entry.building = None
            for key, cached in list(_entries.items()):
                if (cached.agent_id == entry.agent_id and not cached.directory.exists()
                    and (cached.building is None or cached.building.done())):
                    _entries.pop(key, None)


async def _discard(entries: Sequence[_Entry]) -> None:
    building: list[asyncio.Task[PreparedDocument]] = []
    for entry in entries:
        entry.invalidated = True
        if entry.building is not None and not entry.building.done():
            entry.building.cancel()
            building.append(entry.building)
    if building:
        await asyncio.gather(*building, return_exceptions=True)
    for entry in entries:
        key = entry.directory.name
        if _entries.get(key) is entry:
            await complete_io(_remove, entry.directory)
            if _entries.get(key) is entry:
                _entries.pop(key, None)


def _remove(directory: Path) -> None:
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass


async def purge_prepared_files(file_ids: Sequence[UUID]) -> None:
    identities = set(file_ids)
    await _discard([entry for entry in _entries.values() if entry.file_id in identities])


async def purge_prepared_uri(agent_id: int, uri: str) -> None:
    await _discard([entry for entry in _entries.values() if entry.agent_id == agent_id and entry.uri == uri])


def _load_prepared(directory: Path, sha256: str | None) -> PreparedDocument | None:
    try:
        manifest = as_dict(json.loads((directory / 'manifest.json').read_text(encoding='utf-8')))
        if manifest.get('complete') is not True or as_dict(manifest.get('identity')).get('sha256') != sha256:
            return None
        document = PreparedDocument.model_validate(manifest.get('result'))
        if document.sha256 != sha256 or as_dict(manifest.get('identity')).get('version') != preparation_version(document.name):
            return None
        for page in document.pages:
            document.image_path(page, directory)
        return document
    except (OSError, ValueError, TypeError):
        return None


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
    count = len(entries)
    for entry, size, modified in sorted(entries, key=lambda value: value[2]):
        if entry == current or (total <= CACHE_BYTES and count <= CACHE_ENTRIES and time.time() - modified <= CACHE_DAYS * 86400):
            continue
        with (entry / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            shutil.rmtree(entry)
            total -= size
            count -= 1
    if total > CACHE_BYTES or count > CACHE_ENTRIES:
        raise ValueError("Document preparation cache quota exhausted")
